"""
Database Operations with Tortoise ORM

Provides async database operations with retry logic, transactions,
and batch upsert operations for GitHub repository data.
"""

import asyncio
import logging
from typing import Callable, TypeVar, List, Dict, Any, Optional
from tortoise.exceptions import (
    OperationalError,
    IntegrityError,
    TransactionManagementError,
    DBConnectionError
)
from tortoise.transactions import in_transaction

from models import Repository, Release, Commit
from interfaces import GitHubReleaseCommit

# Configuration
BATCH_SIZE = 100

T = TypeVar('T')

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def should_retry(error: Exception) -> bool:
    """
    Determine if an error should trigger a retry.
    
    Args:
        error: The exception that occurred
        
    Returns:
        bool: True if the operation should be retried
    """
    return isinstance(error, (
        OperationalError,
        DBConnectionError,
        TransactionManagementError
    ))


async def execute_with_retry(
    fn: Callable[[], T],
    retries: int = 3,
    delay_ms: int = 1000,
    operation_name: str = "Database operation"
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
            
            if attempt >= retries or not should_retry(error):
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


async def upsert_repo_with_releases_and_commits(
    owner: str,
    repo_name: str,
    releases_with_commits: List[GitHubReleaseCommit]
) -> Dict[str, Any]:
    """
    Atomically upsert repository with its releases and commits in a single transaction.
    
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
                name=repo_name,
                owner=owner,
                using_db=conn
            )
            
            if not releases_with_commits:
                return {"success": True, "repo_id": repo.id}
            
            # Prepare releases data for batch operations
            releases_data = [
                {
                    "tag_name": rc["release"]["tag_name"],
                    "body": rc["release"].get("body"),
                    "repo_id": repo.id
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
                    using_db=conn
                )
                # Update body if release already exists
                if not created and release_data["body"] != release.body:
                    release.body = release_data["body"]
                    await release.save(using_db=conn)
                    
                release_objects.append(release)
            
            # Get all releases for this repo to map commits
            releases = await Release.filter(
                repo_id=repo.id
            ).using_db(conn).all()
            
            # Create a map of tagName to release for faster lookups
            release_map = {r.tag_name: r for r in releases}
            
            # Prepare commits data for batch operation
            all_commits = []
            for rc in releases_with_commits:
                release = release_map.get(rc["release"]["tag_name"])
                if release:
                    for commit_data in rc["commits"]:
                        all_commits.append({
                            "sha": commit_data["sha"],
                            "message": commit_data["commit"]["message"],
                            "release_id": release.id,
                            "repo_id": repo.id,
                            "author_name": commit_data.get("commit", {}).get("author", {}).get("name"),
                            "date": commit_data.get("commit", {}).get("author", {}).get("date"),
                            "html_url": commit_data.get("html_url")
                        })
            
            # Process commits in batches
            for i in range(0, len(all_commits), BATCH_SIZE):
                batch_commits = all_commits[i:i + BATCH_SIZE]
                
                # Use bulk_create with update_on_conflict for better performance
                # However, Tortoise ORM doesn't have native bulk upsert
                # So we'll do individual get_or_create for reliability
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
                            "html_url": commit_data.get("html_url")
                        },
                        using_db=conn
                    )
                    tasks.append(task)
                
                # Execute batch concurrently
                await asyncio.gather(*tasks)
            
            return {"success": True, "repo_id": repo.id}
    
    return await execute_with_retry(
        transaction,
        retries=3,
        delay_ms=1000,
        operation_name=f"Upsert repo {owner}/{repo_name}"
    )


async def create_tables():
    """
    Create database tables using Tortoise ORM schema generation.
    
    Note:
        This should be called after Tortoise.init() in ServiceFactory.
        Uses safe=True to avoid dropping existing tables.
    """
    from tortoise import Tortoise
    await Tortoise.generate_schemas(safe=True)
    logging.info("Tables created/verified successfully.")
