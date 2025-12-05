"""
Database Module

Provides unified database operations with both sync (psycopg2) and async (Tortoise ORM) support.
Includes retry logic, transaction safety, and batch upsert operations for GitHub repository data.

Sync API:
- get_connection(): Get psycopg2 connection
- create_tables(): Create database tables using raw SQL
- upsert_repo_with_releases_and_commits(): Sync upsert operation

Async API (Tortoise ORM):
- async_upsert_repo_with_releases_and_commits(): Async upsert operation
- create_tables_async(): Create tables using Tortoise ORM
"""

import psycopg2
import asyncio
import time
import logging
from typing import Optional, Callable, TypeVar, List, Dict, Any
from tortoise.exceptions import (
    OperationalError,
    IntegrityError,
    TransactionManagementError,
    DBConnectionError,
)
from tortoise.transactions import in_transaction

from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT, BATCH_SIZE
from models import Repository, Release, Commit
from interfaces import GitHubReleaseCommit

T = TypeVar("T")

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s"
)

# ============================================================================
# SYNC DATABASE OPERATIONS (psycopg2)
# ============================================================================


def execute_with_retry(
    fn: Callable[[], T],
    retries: int = 3,
    delay_ms: int = 1000,
    operation_name: str = "Database operation",
) -> T:
    """
    Execute a database operation with automatic retry on transient failures.

    Args:
        fn: The function to execute (should be a database operation)
        retries: Maximum number of retry attempts. Default is 3.
        delay_ms: Delay in milliseconds between retries. Default is 1000.
        operation_name: Name of the operation for logging purposes.

    Returns:
        The result of the successful function execution.

    Raises:
        Exception: Re-raises the last exception if all retries are exhausted.

    Note:
        Retries are attempted for common database errors like connection issues,
        deadlocks, and transient failures.
    """
    attempt = 0
    last_error = None

    while attempt < retries:
        try:
            return fn()
        except (
            psycopg2.OperationalError,
            psycopg2.InterfaceError,
            psycopg2.errors.DeadlockDetected,
        ) as error:
            attempt += 1
            last_error = error

            if attempt >= retries:
                logging.error(
                    f"{operation_name} failed after {retries} retries: {error}"
                )
                raise

            logging.warning(
                f"{operation_name} failed (attempt {attempt}/{retries}): {error}. "
                f"Retrying in {delay_ms}ms..."
            )
            time.sleep(delay_ms / 1000.0)
        except Exception as error:
            logging.error(f"{operation_name} failed with non-retryable error: {error}")
            raise

    raise last_error or Exception(f"{operation_name} failed after maximum retries")


def get_connection():
    """
    Create and return a new PostgreSQL database connection.

    Returns:
        psycopg2.connection: Active database connection object.

    Raises:
        psycopg2.OperationalError: If connection cannot be established.

    Note:
        Connection parameters are loaded from the config module.
        Caller is responsible for closing the connection.
    """
    conn = psycopg2.connect(
        host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
    )
    return conn


def create_tables():
    """
    Create database tables for repositories, releases, and commits if they don't exist.

    Creates three tables with proper relationships:
    - repositories: Stores GitHub repository metadata
    - releases: Stores release information linked to repositories
    - commits: Stores commit information linked to repositories

    Note:
        Uses IF NOT EXISTS to safely handle repeated calls.
        All operations are committed in a single transaction.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Bảng lưu thông tin Repository
    cur.execute("""
        CREATE TABLE IF NOT EXISTS repositories (
            id SERIAL PRIMARY KEY,
            github_id BIGINT UNIQUE,
            name VARCHAR(255),
            full_name VARCHAR(255),
            html_url VARCHAR(500),
            stargazers_count INT,
            language VARCHAR(100),
            created_at TIMESTAMP
        );
    """)

    # Bảng lưu thông tin Releases
    cur.execute("""
        CREATE TABLE IF NOT EXISTS releases (
            id SERIAL PRIMARY KEY,
            repo_id INT REFERENCES repositories(id),
            release_name VARCHAR(255),
            tag_name VARCHAR(100),
            published_at TIMESTAMP,
            html_url VARCHAR(500)
        );
    """)

    # Bảng lưu thông tin Commits
    cur.execute("""
        CREATE TABLE IF NOT EXISTS commits (
            id SERIAL PRIMARY KEY,
            repo_id INT REFERENCES repositories(id),
            sha VARCHAR(40),
            message TEXT,
            author_name VARCHAR(255),
            date TIMESTAMP,
            html_url VARCHAR(500)
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Tables created successfully.")


def upsert_repo_with_releases_and_commits(
    repo_data: Dict[str, Any],
    releases_data: List[Dict[str, Any]],
    commits_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Atomically upsert repository with its releases and commits in a single transaction.

    This function performs optimized batch operations:
    1. Upsert the repository (insert or skip if exists)
    2. Batch upsert releases linked to the repository
    3. Batch upsert commits in chunks to avoid memory issues

    Args:
        repo_data: Dictionary containing repository fields (github_id, name, full_name, etc.)
        releases_data: List of release dictionaries to upsert
        commits_data: List of commit dictionaries to upsert

    Returns:
        dict: Result dictionary with 'success' boolean and 'repo_id'.

    Note:
        All operations are wrapped in a transaction with automatic retry logic.
        If any step fails, the entire transaction is rolled back.
    """

    def transaction():
        conn = get_connection()
        cur = conn.cursor()

        try:
            cur.execute(
                """
                INSERT INTO repositories (github_id, name, full_name, html_url, stargazers_count, language, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (github_id) DO NOTHING
                RETURNING id;
            """,
                (
                    repo_data["github_id"],
                    repo_data["name"],
                    repo_data["full_name"],
                    repo_data["html_url"],
                    repo_data.get("stargazers_count"),
                    repo_data.get("language"),
                    repo_data.get("created_at"),
                ),
            )

            result = cur.fetchone()

            if not result:
                cur.execute(
                    "SELECT id FROM repositories WHERE github_id = %s",
                    (repo_data["github_id"],),
                )
                result = cur.fetchone()

            if not result:
                raise Exception(f"Failed to get repo_id for {repo_data['full_name']}")

            repo_id = result[0]

            if releases_data:
                release_values = [
                    (
                        repo_id,
                        rel.get("name"),
                        rel.get("tag_name"),
                        rel.get("published_at"),
                        rel.get("html_url"),
                    )
                    for rel in releases_data
                ]

                for rel_val in release_values:
                    cur.execute(
                        """
                        INSERT INTO releases (repo_id, release_name, tag_name, published_at, html_url)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """,
                        rel_val,
                    )

            if commits_data:
                for i in range(0, len(commits_data), BATCH_SIZE):
                    batch = commits_data[i : i + BATCH_SIZE]

                    for commit in batch:
                        cur.execute(
                            """
                            INSERT INTO commits (repo_id, sha, message, author_name, date, html_url)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                        """,
                            (
                                repo_id,
                                commit.get("sha"),
                                commit.get("message"),
                                commit.get("author_name"),
                                commit.get("date"),
                                commit.get("html_url"),
                            ),
                        )

            conn.commit()
            return {"success": True, "repo_id": repo_id}

        except Exception as e:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    return execute_with_retry(
        transaction,
        retries=3,
        delay_ms=1000,
        operation_name=f"Upsert repo {repo_data.get('full_name', 'unknown')}",
    )


# ============================================================================
# ASYNC DATABASE OPERATIONS (Tortoise ORM)
# ============================================================================


def should_retry_async(error: Exception) -> bool:
    """
    Determine if an async error should trigger a retry.

    Args:
        error: The exception that occurred

    Returns:
        bool: True if the operation should be retried
    """
    return isinstance(
        error, (OperationalError, DBConnectionError, TransactionManagementError)
    )


async def execute_with_retry_async(
    fn: Callable[[], T],
    retries: int = 3,
    delay_ms: int = 1000,
    operation_name: str = "Database operation",
) -> T:
    """
    Execute an async database operation with automatic retry on transient failures.

    Args:
        fn: The async function to execute (should be a database operation)
        retries: Maximum number of retry attempts. Default is 3.
        delay_ms: Delay in milliseconds between retries. Default is 1000.
        operation_name: Name of the operation for logging purposes.

    Returns:
        The result of the successful function execution.

    Raises:
        Exception: Re-raises the last exception if all retries are exhausted.
    """
    attempt = 0
    last_error = None

    while attempt < retries:
        try:
            return await fn()
        except Exception as error:
            attempt += 1
            last_error = error

            if attempt >= retries or not should_retry_async(error):
                logging.error(
                    f"{operation_name} failed after {attempt} attempts: {error}"
                )
                raise

            logging.warning(
                f"{operation_name} failed (attempt {attempt}/{retries}): {error}. "
                f"Retrying in {delay_ms}ms..."
            )
            await asyncio.sleep(delay_ms / 1000.0)

    raise last_error or Exception(f"{operation_name} failed after maximum retries")


async def async_upsert_repo_with_releases_and_commits(
    owner: str, repo_name: str, releases_with_commits: List[GitHubReleaseCommit]
) -> Dict[str, Any]:
    """
    Atomically upsert repository with its releases and commits in a single transaction (async).

    This function performs optimized batch operations similar to Prisma:
    1. Upsert the repository (create or get existing)
    2. Batch upsert releases linked to the repository
    3. Batch upsert commits linked to releases

    Args:
        owner: Repository owner (GitHub username or organization)
        repo_name: Repository name
        releases_with_commits: List of releases with their associated commits

    Returns:
        dict: Result dictionary with 'success' boolean and optional 'repo_id'.

    Raises:
        Exception: If the transaction fails after all retries

    Note:
        All operations are wrapped in a transaction with automatic retry logic.
        If any step fails, the entire transaction is rolled back.
    """

    async def transaction():
        async with in_transaction() as conn:
            # Upsert Repository
            repo, created = await Repository.get_or_create(
                name=repo_name, owner=owner, using_db=conn
            )

            if not releases_with_commits:
                return {"success": True, "repo_id": repo.id}

            # Prepare releases data for batch operations
            releases_data = [
                {
                    "tag_name": rc["release"]["tag_name"],
                    "body": rc["release"].get("body"),
                    "repo_id": repo.id,
                }
                for rc in releases_with_commits
            ]

            # Batch upsert releases
            release_objects = []
            for release_data in releases_data:
                release, created = await Release.get_or_create(
                    tag_name=release_data["tag_name"],
                    repo_id=release_data["repo_id"],
                    defaults={"body": release_data["body"]},
                    using_db=conn,
                )
                # Update body if release already exists
                if not created and release_data["body"] != release.body:
                    release.body = release_data["body"]
                    await release.save(using_db=conn)

                release_objects.append(release)

            # Get all releases for this repo to map commits
            releases = await Release.filter(repo_id=repo.id).using_db(conn).all()

            # Create a map of tagName to release for faster lookups
            release_map = {r.tag_name: r for r in releases}

            # Prepare commits data for batch operation
            all_commits = []
            for rc in releases_with_commits:
                release = release_map.get(rc["release"]["tag_name"])
                if release:
                    for commit_data in rc["commits"]:
                        all_commits.append(
                            {
                                "sha": commit_data["sha"],
                                "message": commit_data["commit"]["message"],
                                "release_id": release.id,
                                "repo_id": repo.id,
                                "author_name": commit_data.get("commit", {})
                                .get("author", {})
                                .get("name"),
                                "date": commit_data.get("commit", {})
                                .get("author", {})
                                .get("date"),
                                "html_url": commit_data.get("html_url"),
                            }
                        )

            # Process commits in batches
            for i in range(0, len(all_commits), BATCH_SIZE):
                batch_commits = all_commits[i : i + BATCH_SIZE]

                # Use individual get_or_create for reliability
                tasks = []
                for commit_data in batch_commits:
                    task = Commit.get_or_create(
                        sha=commit_data["sha"],
                        defaults={
                            "message": commit_data["message"],
                            "release_id": commit_data["release_id"],
                            "repo_id": commit_data["repo_id"],
                            "author_name": commit_data.get("author_name"),
                            "date": commit_data.get("date"),
                            "html_url": commit_data.get("html_url"),
                        },
                        using_db=conn,
                    )
                    tasks.append(task)

                # Execute batch concurrently
                await asyncio.gather(*tasks)

            return {"success": True, "repo_id": repo.id}

    return await execute_with_retry_async(
        transaction,
        retries=3,
        delay_ms=1000,
        operation_name=f"Async upsert repo {owner}/{repo_name}",
    )


async def create_tables_async():
    """
    Create database tables using Tortoise ORM schema generation.

    Note:
        This should be called after Tortoise.init() in ServiceFactory.
        Uses safe=True to avoid dropping existing tables.
    """
    from tortoise import Tortoise

    await Tortoise.generate_schemas(safe=True)
    logging.info("Tables created/verified successfully (async).")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # Create tables using sync method
    create_tables()
