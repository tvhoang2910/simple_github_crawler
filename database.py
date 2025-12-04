"""
Database Module

Provides database connection management, table creation, and optimized
batch operations for storing GitHub repository data with retry logic
and transaction safety.
"""

import psycopg2
import time
import logging
from typing import Optional, Callable, TypeVar, List, Dict, Any
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT

BATCH_SIZE = 100

T = TypeVar('T')

BATCH_SIZE = 100

T = TypeVar('T')


def execute_with_retry(
    fn: Callable[[], T],
    retries: int = 3,
    delay_ms: int = 1000,
    operation_name: str = "Database operation"
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
        except (psycopg2.OperationalError, psycopg2.InterfaceError, 
                psycopg2.errors.DeadlockDetected) as error:
            attempt += 1
            last_error = error
            
            if attempt >= retries:
                logging.error(f"{operation_name} failed after {retries} retries: {error}")
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
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
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
    commits_data: List[Dict[str, Any]]
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
            cur.execute("""
                INSERT INTO repositories (github_id, name, full_name, html_url, stargazers_count, language, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (github_id) DO NOTHING
                RETURNING id;
            """, (
                repo_data['github_id'],
                repo_data['name'],
                repo_data['full_name'],
                repo_data['html_url'],
                repo_data.get('stargazers_count'),
                repo_data.get('language'),
                repo_data.get('created_at')
            ))
            
            result = cur.fetchone()
            
            if not result:
                cur.execute(
                    "SELECT id FROM repositories WHERE github_id = %s",
                    (repo_data['github_id'],)
                )
                result = cur.fetchone()
            
            if not result:
                raise Exception(f"Failed to get repo_id for {repo_data['full_name']}")
            
            repo_id = result[0]
            
            if releases_data:
                release_values = [
                    (repo_id, rel.get('name'), rel.get('tag_name'), 
                     rel.get('published_at'), rel.get('html_url'))
                    for rel in releases_data
                ]
                
                for rel_val in release_values:
                    cur.execute("""
                        INSERT INTO releases (repo_id, release_name, tag_name, published_at, html_url)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, rel_val)
            
            if commits_data:
                for i in range(0, len(commits_data), BATCH_SIZE):
                    batch = commits_data[i:i + BATCH_SIZE]
                    
                    for commit in batch:
                        cur.execute("""
                            INSERT INTO commits (repo_id, sha, message, author_name, date, html_url)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                        """, (
                            repo_id,
                            commit.get('sha'),
                            commit.get('message'),
                            commit.get('author_name'),
                            commit.get('date'),
                            commit.get('html_url')
                        ))
            
            conn.commit()
            return {'success': True, 'repo_id': repo_id}
            
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
        operation_name=f"Upsert repo {repo_data.get('full_name', 'unknown')}"
    )


if __name__ == "__main__":
    create_tables()
