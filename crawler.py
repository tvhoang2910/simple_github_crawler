"""
Optimized GitHub Crawler Module

This module implements performance optimizations including:
- Multi-threading with ThreadPoolExecutor for concurrent crawling
- Redis queue-based load leveling
- Connection pooling for database operations
- GitHub Compare API for incremental commit fetching
- Redis caching for crawl state management
- Fallback logic for repos without releases
"""

import requests
import time
import logging
import redis
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool

from config import (
    GITHUB_TOKENS, 
    REDIS_HOST, 
    REDIS_PORT,
    DB_HOST, 
    DB_NAME, 
    DB_USER, 
    DB_PASS, 
    DB_PORT
)

logging.basicConfig(
    filename='crawler_optimized.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ============================================================================
# GITHUB TOKEN ROTATION
# ============================================================================

class GitHubTokenRotator:
    """Manages rotation of GitHub tokens to maximize rate limits."""
    
    def __init__(self, tokens: List[str]):
        if not tokens:
            raise ValueError("At least one GitHub token is required")
        self.tokens = tokens
        self.current_index = 0
        self.token_stats = {token: {"requests": 0, "errors": 0} for token in tokens}
    
    def get_next_token(self) -> str:
        """Get the next token in rotation."""
        token = self.tokens[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.tokens)
        self.token_stats[token]["requests"] += 1
        return token
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers with rotated token."""
        token = self.get_next_token()
        return {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {token}",
            "User-Agent": "GitHubCrawler/1.0"
        }
    
    def mark_error(self, token: str):
        """Mark a token as having encountered an error."""
        if token in self.token_stats:
            self.token_stats[token]["errors"] += 1


# Global token rotator
token_rotator = GitHubTokenRotator(GITHUB_TOKENS)


# ============================================================================
# CONNECTION POOLING
# ============================================================================

class DatabaseConnectionPool:
    """Database connection pool manager."""
    
    _pool = None
    
    @classmethod
    def initialize(cls, minconn=5, maxconn=20):
        """Initialize the connection pool."""
        if cls._pool is None:
            try:
                cls._pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn,
                    maxconn,
                    host=DB_HOST,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASS,
                    port=DB_PORT
                )
                logging.info(f"Connection pool initialized with {minconn}-{maxconn} connections")
            except Exception as e:
                logging.error(f"Failed to initialize connection pool: {e}")
                raise
    
    @classmethod
    @contextmanager
    def get_connection(cls):
        """Get a connection from the pool (context manager)."""
        if cls._pool is None:
            cls.initialize()
        
        conn = cls._pool.getconn()
        try:
            yield conn
        finally:
            cls._pool.putconn(conn)
    
    @classmethod
    def close_all(cls):
        """Close all connections in the pool."""
        if cls._pool is not None:
            cls._pool.closeall()
            cls._pool = None
            logging.info("Connection pool closed")


# ============================================================================
# REDIS CACHE & QUEUE
# ============================================================================

class RedisManager:
    """Manages Redis operations for caching and queueing."""
    
    def __init__(self, host: str = REDIS_HOST, port: int = int(REDIS_PORT)):
        self.redis_client = redis.Redis(
            host=host,
            port=port,
            decode_responses=True,
            socket_connect_timeout=5
        )
        self.queue_name = "github_crawler:queue"
        self.cache_prefix = "github_crawler:cache:"
    
    def push_to_queue(self, repo_data: Dict[str, Any]):
        """Push repository data to processing queue."""
        try:
            self.redis_client.rpush(self.queue_name, json.dumps(repo_data))
        except Exception as e:
            logging.error(f"Failed to push to queue: {e}")
    
    def pop_from_queue(self, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """Pop repository data from processing queue."""
        try:
            result = self.redis_client.blpop(self.queue_name, timeout=timeout)
            if result:
                _, data = result
                return json.loads(data)
        except Exception as e:
            logging.error(f"Failed to pop from queue: {e}")
        return None
    
    def get_queue_size(self) -> int:
        """Get current queue size."""
        try:
            return self.redis_client.llen(self.queue_name)
        except Exception as e:
            logging.error(f"Failed to get queue size: {e}")
            return 0
    
    def cache_last_release(self, repo_full_name: str, tag_name: str):
        """Cache the last crawled release for a repository."""
        try:
            key = f"{self.cache_prefix}last_release:{repo_full_name}"
            self.redis_client.set(key, tag_name, ex=86400 * 7)  # 7 days TTL
        except Exception as e:
            logging.error(f"Failed to cache last release: {e}")
    
    def get_last_release(self, repo_full_name: str) -> Optional[str]:
        """Get the last crawled release for a repository."""
        try:
            key = f"{self.cache_prefix}last_release:{repo_full_name}"
            return self.redis_client.get(key)
        except Exception as e:
            logging.error(f"Failed to get last release: {e}")
            return None
    
    def cache_repo_processed(self, repo_full_name: str):
        """Mark repository as processed."""
        try:
            key = f"{self.cache_prefix}processed:{repo_full_name}"
            self.redis_client.set(key, "1", ex=86400)  # 1 day TTL
        except Exception as e:
            logging.error(f"Failed to cache processed repo: {e}")
    
    def is_repo_processed(self, repo_full_name: str) -> bool:
        """Check if repository was recently processed."""
        try:
            key = f"{self.cache_prefix}processed:{repo_full_name}"
            return self.redis_client.exists(key) > 0
        except Exception as e:
            logging.error(f"Failed to check processed repo: {e}")
            return False


# Global Redis manager
redis_manager = RedisManager()


# ============================================================================
# OPTIMIZED GITHUB API FUNCTIONS
# ============================================================================

def fetch_with_retry(url: str, max_retries: int = 3) -> Optional[Dict[str, Any]]:
    """Fetch data from GitHub API with retry logic and token rotation."""
    for attempt in range(max_retries):
        try:
            headers = token_rotator.get_headers()
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            
            elif response.status_code == 403:
                # Check for rate limit reset header
                reset_time = response.headers.get("x-ratelimit-reset")
                if reset_time:
                    wait_time = int(reset_time) - time.time()
                    if wait_time > 0:
                        logging.warning(f"Rate limit hit. Waiting {wait_time:.2f}s until reset.")
                        print(f"Rate limit hit. Waiting {wait_time:.2f}s...")
                        time.sleep(wait_time + 1) # Wait a bit extra
                        # Retry immediately after wait
                        continue
                
                logging.warning(f"Rate limit hit (no reset header) on attempt {attempt + 1}")
                time.sleep(2 ** attempt)  # Exponential backoff
                
            elif response.status_code == 422:
                # Unprocessable Entity - often happens with Compare API for large diffs
                logging.warning(f"422 Unprocessable Entity for {url} - skipping retry")
                return None
                
            elif response.status_code == 404:
                logging.info(f"Resource not found: {url}")
                return None
            else:
                logging.error(f"Error {response.status_code} for {url}: {response.text}")
                
        except Exception as e:
            logging.error(f"Request failed on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
    
    return None


def fetch_top_repositories(limit: int = 5000) -> List[Dict[str, Any]]:
    """
    Fetch the most-starred repositories from GitHub.
    Uses the same logic as the original crawler.
    """
    repos = []
    seen_ids = set()
    
    star_ranges = [
        "stars:>=50000",
        "stars:10000..49999",
        "stars:5000..9999",
        "stars:2000..4999",
        "stars:1000..1999"
    ]
    
    print(f"Starting to crawl top {limit} repositories...")
    
    for star_range in star_ranges:
        if len(repos) >= limit:
            break
            
        page = 1
        per_page = 100
        
        while len(repos) < limit:
            url = f"https://api.github.com/search/repositories?q={star_range}&sort=stars&order=desc&per_page={per_page}&page={page}"
            data = fetch_with_retry(url)
            
            if not data:
                break
            
            items = data.get("items", [])
            if not items:
                break
            
            for item in items:
                if item['id'] not in seen_ids:
                    repos.append(item)
                    seen_ids.add(item['id'])
            
            print(f"Fetched page {page} ({star_range}), total repos: {len(repos)}")
            page += 1
            
            # Check if we've hit pagination limit
            if page > 10:  # GitHub limits to 1000 results (10 pages * 100)
                break
    
    return repos[:limit]


def fetch_releases(owner: str, repo_name: str) -> List[Dict[str, Any]]:
    """Fetch releases for a repository."""
    url = f"https://api.github.com/repos/{owner}/{repo_name}/releases?per_page=10"
    data = fetch_with_retry(url)
    return data if data else []


def fetch_tags(owner: str, repo_name: str) -> List[Dict[str, Any]]:
    """Fetch tags as fallback when releases are not available."""
    url = f"https://api.github.com/repos/{owner}/{repo_name}/tags?per_page=10"
    data = fetch_with_retry(url)
    return data if data else []


def fetch_commits(owner: str, repo_name: str, per_page: int = 10) -> List[Dict[str, Any]]:
    """Fetch recent commits for a repository."""
    url = f"https://api.github.com/repos/{owner}/{repo_name}/commits?per_page={per_page}"
    data = fetch_with_retry(url)
    return data if data else []


def fetch_compare_commits(owner: str, repo_name: str, base: str, head: str) -> List[Dict[str, Any]]:
    """
    Use GitHub Compare API to fetch only commits between two tags/releases.
    This avoids duplicate commits across releases.
    """
    url = f"https://api.github.com/repos/{owner}/{repo_name}/compare/{base}...{head}"
    data = fetch_with_retry(url)
    
    if data and 'commits' in data:
        return data['commits']
    return []


# ============================================================================
# DATABASE OPERATIONS WITH CONNECTION POOLING
# ============================================================================

def create_tables():
    """Create database tables if they don't exist."""
    with DatabaseConnectionPool.get_connection() as conn:
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
                html_url VARCHAR(500),
                UNIQUE(repo_id, tag_name)
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS commits (
                id SERIAL PRIMARY KEY,
                repo_id INT REFERENCES repositories(id),
                sha VARCHAR(40) UNIQUE,
                message TEXT,
                author_name VARCHAR(255),
                date TIMESTAMP,
                html_url VARCHAR(500)
            );
        """)
        
        conn.commit()
        cur.close()
        print("Tables created successfully.")


def upsert_repo_with_data(
    repo_data: Dict[str, Any],
    releases_data: List[Dict[str, Any]],
    commits_data: List[Dict[str, Any]]
) -> bool:
    """
    Upsert repository with releases and commits using connection pool.
    Returns True if successful.
    """
    try:
        with DatabaseConnectionPool.get_connection() as conn:
            cur = conn.cursor()
            
            # Upsert repository
            cur.execute("""
                INSERT INTO repositories (github_id, name, full_name, html_url, stargazers_count, language, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (github_id) DO UPDATE SET
                    stargazers_count = EXCLUDED.stargazers_count
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
            repo_id = result[0] if result else None
            
            if not repo_id:
                cur.execute("SELECT id FROM repositories WHERE github_id = %s", (repo_data['github_id'],))
                result = cur.fetchone()
                repo_id = result[0] if result else None
            
            if not repo_id:
                raise Exception(f"Failed to get repo_id for {repo_data['full_name']}")
            
            # Batch insert releases
            if releases_data:
                for release in releases_data:
                    cur.execute("""
                        INSERT INTO releases (repo_id, release_name, tag_name, published_at, html_url)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (repo_id, tag_name) DO NOTHING
                    """, (
                        repo_id,
                        release.get('name'),
                        release.get('tag_name'),
                        release.get('published_at'),
                        release.get('html_url')
                    ))
            
            # Batch insert commits
            if commits_data:
                for commit in commits_data:
                    cur.execute("""
                        INSERT INTO commits (repo_id, sha, message, author_name, date, html_url)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (sha) DO NOTHING
                    """, (
                        repo_id,
                        commit.get('sha'),
                        commit.get('message'),
                        commit.get('author_name'),
                        commit.get('date'),
                        commit.get('html_url')
                    ))
            
            conn.commit()
            cur.close()
            return True
            
    except Exception as e:
        logging.error(f"Error upserting repo {repo_data.get('full_name', 'unknown')}: {e}")
        return False


# ============================================================================
# WORKER FUNCTIONS
# ============================================================================

def process_repository(repo: Dict[str, Any]) -> bool:
    """
    Process a single repository with optimized logic:
    - Check cache to avoid re-processing
    - Fetch releases with fallback to tags
    - Use Compare API for incremental commits
    - Cache the result
    """
    try:
        full_name = repo['full_name']
        owner = repo['owner']['login']
        repo_name = repo['name']
        
        # Check if recently processed
        if redis_manager.is_repo_processed(full_name):
            logging.info(f"Skipping recently processed repo: {full_name}")
            return True
        
        print(f"Processing repo: {full_name}")
        
        # Fetch releases with fallback to tags
        releases = fetch_releases(owner, repo_name)
        
        if not releases:
            logging.info(f"No releases found for {full_name}, trying tags...")
            tags = fetch_tags(owner, repo_name)
            
            # Convert tags to release-like format
            releases = [
                {
                    'name': tag.get('name'),
                    'tag_name': tag.get('name'),
                    'published_at': None,
                    'html_url': tag.get('commit', {}).get('url')
                }
                for tag in tags[:10]
            ]
        
        # If still no releases/tags, just fetch recent commits
        if not releases:
            logging.info(f"No releases or tags for {full_name}, fetching recent commits...")
            commits = fetch_commits(owner, repo_name, per_page=20)
        else:
            # Use Compare API for incremental commits between releases
            commits = []
            last_cached_release = redis_manager.get_last_release(full_name)
            
            for i, release in enumerate(releases):
                tag_name = release.get('tag_name')
                
                # Skip if we've already processed this release
                if tag_name == last_cached_release:
                    break
                
                # Get commits for this release
                if i < len(releases) - 1:
                    # Compare with previous release
                    base = releases[i + 1].get('tag_name')
                    head = tag_name
                    release_commits = fetch_compare_commits(owner, repo_name, base, head)
                else:
                    # For the oldest release, just get recent commits
                    release_commits = fetch_commits(owner, repo_name, per_page=10)
                
                commits.extend(release_commits)
            
            # Cache the latest release
            if releases:
                redis_manager.cache_last_release(full_name, releases[0].get('tag_name'))
        
        # Prepare data for database
        repo_data = {
            'github_id': repo['id'],
            'name': repo['name'],
            'full_name': full_name,
            'html_url': repo['html_url'],
            'stargazers_count': repo.get('stargazers_count'),
            'language': repo.get('language'),
            'created_at': repo.get('created_at')
        }
        
        releases_data = [
            {
                'name': rel.get('name'),
                'tag_name': rel.get('tag_name'),
                'published_at': rel.get('published_at'),
                'html_url': rel.get('html_url')
            }
            for rel in releases
        ]
        
        commits_data = [
            {
                'sha': c.get('sha'),
                'message': c.get('commit', {}).get('message') if isinstance(c.get('commit'), dict) else c.get('message'),
                'author_name': c.get('commit', {}).get('author', {}).get('name') if isinstance(c.get('commit'), dict) else c.get('author_name'),
                'date': c.get('commit', {}).get('author', {}).get('date') if isinstance(c.get('commit'), dict) else c.get('date'),
                'html_url': c.get('html_url')
            }
            for c in commits
        ]
        
        # Save to database
        success = upsert_repo_with_data(repo_data, releases_data, commits_data)
        
        if success:
            # Mark as processed in cache
            redis_manager.cache_repo_processed(full_name)
            print(f"✓ Successfully processed {full_name}")
            return True
        else:
            print(f"✗ Failed to process {full_name}")
            return False
            
    except Exception as e:
        logging.error(f"Error processing repo {repo.get('full_name', 'unknown')}: {e}")
        print(f"✗ Error processing {repo.get('full_name', 'unknown')}: {e}")
        return False


def queue_worker():
    """
    Worker that processes repositories from Redis queue.
    Runs in a separate thread.
    """
    print("Queue worker started...")
    
    while True:
        repo_data = redis_manager.pop_from_queue(timeout=5)
        
        if repo_data is None:
            # Check if queue is empty and should exit
            if redis_manager.get_queue_size() == 0:
                time.sleep(1)
                if redis_manager.get_queue_size() == 0:
                    break
            continue
        
        process_repository(repo_data)
    
    print("Queue worker finished.")


# ============================================================================
# MAIN ORCHESTRATION
# ============================================================================

def main_with_threading(limit: int = 5000, max_workers: int = 10):
    """
    Main crawler with ThreadPoolExecutor for concurrent processing.
    
    Args:
        limit: Number of repositories to crawl
        max_workers: Number of concurrent threads
    """
    start_time = time.time()
    
    # Initialize connection pool
    DatabaseConnectionPool.initialize(minconn=max_workers, maxconn=max_workers * 2)
    
    # Create tables
    create_tables()
    
    # Fetch repositories
    print(f"\n{'='*70}")
    print(f"OPTIMIZED GITHUB CRAWLER - Multi-threading Mode")
    print(f"{'='*70}\n")
    
    repos = fetch_top_repositories(limit=limit)
    print(f"\nFound {len(repos)} repositories. Starting concurrent processing...")
    print(f"Using {max_workers} worker threads\n")
    
    # Process repositories concurrently
    success_count = 0
    failure_count = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_repo = {executor.submit(process_repository, repo): repo for repo in repos}
        
        # Process completed tasks
        for i, future in enumerate(as_completed(future_to_repo)):
            repo = future_to_repo[future]
            try:
                result = future.result()
                if result:
                    success_count += 1
                else:
                    failure_count += 1
                
                # Progress update
                total_processed = i + 1
                print(f"Progress: [{total_processed}/{len(repos)}] | Success: {success_count} | Failed: {failure_count}")
                
            except Exception as e:
                failure_count += 1
                logging.error(f"Thread exception for {repo.get('full_name', 'unknown')}: {e}")
    
    # Cleanup
    DatabaseConnectionPool.close_all()
    
    end_time = time.time()
    total_time = end_time - start_time
    
    print(f"\n{'='*70}")
    print(f"CRAWLING COMPLETED")
    print(f"{'='*70}")
    print(f"Total repositories: {len(repos)}")
    print(f"Successfully processed: {success_count}")
    print(f"Failed: {failure_count}")
    print(f"Total time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    print(f"Average time per repo: {total_time/len(repos):.2f} seconds")
    print(f"{'='*70}\n")


def main_with_queue(limit: int = 5000, num_workers: int = 5):
    """
    Main crawler with Redis queue-based load leveling.
    
    Args:
        limit: Number of repositories to crawl
        num_workers: Number of worker threads
    """
    start_time = time.time()
    
    # Initialize connection pool
    DatabaseConnectionPool.initialize(minconn=num_workers, maxconn=num_workers * 2)
    
    # Create tables
    create_tables()
    
    print(f"\n{'='*70}")
    print(f"OPTIMIZED GITHUB CRAWLER - Queue-based Mode")
    print(f"{'='*70}\n")
    
    # Fetch repositories and push to queue
    repos = fetch_top_repositories(limit=limit)
    print(f"\nFound {len(repos)} repositories. Pushing to Redis queue...")
    
    for repo in repos:
        redis_manager.push_to_queue(repo)
    
    print(f"All repositories queued. Queue size: {redis_manager.get_queue_size()}")
    print(f"Starting {num_workers} worker threads...\n")
    
    # Start worker threads
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(queue_worker) for _ in range(num_workers)]
        
        # Wait for all workers to complete
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logging.error(f"Worker thread exception: {e}")
    
    # Cleanup
    DatabaseConnectionPool.close_all()
    
    end_time = time.time()
    total_time = end_time - start_time
    
    print(f"\n{'='*70}")
    print(f"CRAWLING COMPLETED")
    print(f"{'='*70}")
    print(f"Total time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    import sys
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "threading"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    
    if mode == "queue":
        main_with_queue(limit=limit, num_workers=workers)
    else:
        main_with_threading(limit=limit, max_workers=workers)
