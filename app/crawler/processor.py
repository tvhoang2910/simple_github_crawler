import logging
import asyncio
from typing import List, Dict, Any
from app.utils.redis_client import RedisManager
from app.crawler.fetcher import (
    fetch_releases,
    fetch_tags,
    fetch_commits,
    fetch_compare_commits,
)
from database import async_upsert_repo_with_releases_and_commits

# Global Redis manager
redis_manager = RedisManager()


# ============================================================================
# ASYNC PROCESSING FUNCTIONS (OPTIMIZED)
# ============================================================================


def prepare_releases_with_commits(
    releases_data: List[Dict[str, Any]],
    commits_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Transform releases and commits data to match the format expected by 
    async_upsert_repo_with_releases_and_commits.
    
    Returns list of GitHubReleaseCommit structures.
    """
    releases_with_commits = []
    
    if releases_data:
        # For each release, associate all commits
        for release in releases_data:
            release_obj = {
                "release": {
                    "tag_name": release.get("tag_name", "unknown"),
                    "body": release.get("name") or release.get("tag_name", ""),
                    "published_at": release.get("published_at"),
                },
                "commits": []
            }
            
            # Transform commits to match expected structure
            for commit in commits_data:
                commit_obj = {
                    "sha": commit.get("sha"),
                    "commit": {
                        "message": commit.get("message", ""),
                        "author": {
                            "name": commit.get("author_name", "Unknown"),
                            "date": commit.get("date"),
                        }
                    },
                    "html_url": commit.get("html_url", ""),
                }
                release_obj["commits"].append(commit_obj)
            
            releases_with_commits.append(release_obj)
    else:
        # No releases - create a default one for main branch
        if commits_data:
            default_release = {
                "release": {
                    "tag_name": "main",
                    "body": "Main branch commits",
                },
                "commits": []
            }
            
            for commit in commits_data:
                commit_obj = {
                    "sha": commit.get("sha"),
                    "commit": {
                        "message": commit.get("message", ""),
                        "author": {
                            "name": commit.get("author_name", "Unknown"),
                            "date": commit.get("date"),
                        }
                    },
                    "html_url": commit.get("html_url", ""),
                }
                default_release["commits"].append(commit_obj)
            
            releases_with_commits.append(default_release)
    
    return releases_with_commits


async def async_process_repository(repo: Dict[str, Any]) -> bool:
    """
    Async process a single repository with optimized logic:
    - Check cache to avoid re-processing
    - Fetch releases with fallback to tags
    - Use Compare API for incremental commits
    - Use async database operations with Tortoise ORM
    
    Returns True if successful, False otherwise.
    """
    try:
        full_name = repo["full_name"]
        owner = repo["owner"]["login"]
        repo_name = repo["name"]

        # Check if recently processed
        if redis_manager.is_repo_processed(full_name):
            logging.info(f"Skipping recently processed repo: {full_name}")
            return True

        print(f"[ASYNC] Processing repo: {full_name}")

        # Run sync API calls in executor
        loop = asyncio.get_event_loop()
        
        releases = await loop.run_in_executor(
            None, 
            fetch_releases, 
            owner, 
            repo_name
        )

        if not releases:
            logging.info(f"No releases found for {full_name}, trying tags...")
            tags = await loop.run_in_executor(
                None,
                fetch_tags,
                owner,
                repo_name
            )
            
            # Convert tags to release-like format
            releases = [
                {
                    "name": tag.get("name"),
                    "tag_name": tag.get("name"),
                    "published_at": None,
                    "html_url": tag.get("commit", {}).get("url"),
                }
                for tag in tags[:10]
            ]

        # Fetch commits
        if not releases:
            logging.info(f"No releases or tags for {full_name}, fetching recent commits...")
            commits = await loop.run_in_executor(
                None,
                fetch_commits,
                owner,
                repo_name,
                20
            )
        else:
            # Use Compare API for incremental commits
            commits = []
            last_cached_release = redis_manager.get_last_release(full_name)

            for i, release in enumerate(releases):
                tag_name = release.get("tag_name")

                if tag_name == last_cached_release:
                    break

                if i < len(releases) - 1:
                    base = releases[i + 1].get("tag_name")
                    head = tag_name
                    release_commits = await loop.run_in_executor(
                        None,
                        fetch_compare_commits,
                        owner,
                        repo_name,
                        base,
                        head
                    )
                else:
                    release_commits = await loop.run_in_executor(
                        None,
                        fetch_commits,
                        owner,
                        repo_name,
                        10
                    )

                commits.extend(release_commits)

            if releases:
                redis_manager.cache_last_release(full_name, releases[0].get("tag_name"))

        # Prepare data
        releases_data = [
            {
                "name": rel.get("name"),
                "tag_name": rel.get("tag_name"),
                "published_at": rel.get("published_at"),
                "html_url": rel.get("html_url"),
            }
            for rel in releases
        ]

        commits_data = [
            {
                "sha": c.get("sha"),
                "message": c.get("commit", {}).get("message")
                if isinstance(c.get("commit"), dict)
                else c.get("message"),
                "author_name": c.get("commit", {}).get("author", {}).get("name")
                if isinstance(c.get("commit"), dict)
                else c.get("author_name"),
                "date": c.get("commit", {}).get("author", {}).get("date")
                if isinstance(c.get("commit"), dict)
                else c.get("date"),
                "html_url": c.get("html_url"),
            }
            for c in commits
        ]

        # Transform and upsert using async Tortoise ORM
        releases_with_commits = prepare_releases_with_commits(releases_data, commits_data)

        result = await async_upsert_repo_with_releases_and_commits(
            owner=owner,
            repo_name=repo_name,
            releases_with_commits=releases_with_commits
        )

        if result.get("success"):
            redis_manager.cache_repo_processed(full_name)
            print(f"[ASYNC SUCCESS] Successfully processed {full_name}")
            return True
        else:
            print(f"[ASYNC FAILED] Failed to process {full_name}")
            return False

    except Exception as e:
        logging.error(f"[ASYNC] Error processing repository {repo.get('full_name', 'unknown')}: {e}")
        print(f"[ASYNC ERROR] Error processing {repo.get('full_name', 'unknown')}: {e}")
        return False


async def async_queue_worker(worker_id: int, semaphore: asyncio.Semaphore) -> int:
    """
    Async worker that processes repositories from Redis queue.
    Uses semaphore to limit concurrent database operations.
    
    Args:
        worker_id: Unique identifier for this worker
        semaphore: Asyncio semaphore to limit concurrency
        
    Returns:
        Number of repositories processed
    """
    print(f"[Worker-{worker_id}] Started")
    processed = 0

    while True:
        repo_data = redis_manager.pop_from_queue(timeout=2)

        if repo_data is None:
            queue_size = redis_manager.get_queue_size()
            if queue_size == 0:
                await asyncio.sleep(0.5)
                if redis_manager.get_queue_size() == 0:
                    break
            continue

        # Process with semaphore to limit concurrent DB operations
        async with semaphore:
            success = await async_process_repository(repo_data)
            if success:
                processed += 1

    print(f"[Worker-{worker_id}] Finished. Processed {processed} repositories.")
    return processed
