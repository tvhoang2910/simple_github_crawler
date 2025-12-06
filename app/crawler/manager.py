import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.database.connection import DatabaseConnectionPool, create_tables_sync
from app.crawler.fetcher import fetch_top_repositories
from app.crawler.processor import process_repository, redis_manager
from app.metrics import QUEUE_SIZE


def queue_worker():
    """
    Worker that processes repositories from Redis queue.
    Runs in a separate thread.
    """
    print("Queue worker started...")

    # Initialize database connection pool for this worker thread
    DatabaseConnectionPool.initialize(minconn=1, maxconn=2)

    while True:
        # Update queue size metric
        QUEUE_SIZE.set(redis_manager.get_queue_size())

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

    # Close connection pool for this worker
    DatabaseConnectionPool.close_all()


def main_with_threading(limit: int = 5000, max_workers: int = 10):
    """
    Main crawler with ThreadPoolExecutor for concurrent processing.
    """
    start_time = time.time()

    # Initialize connection pool
    DatabaseConnectionPool.initialize(minconn=max_workers, maxconn=max_workers * 2)

    # Create tables
    create_tables_sync()

    # Fetch repositories
    print(f"\n{'=' * 70}")
    print(f"OPTIMIZED GITHUB CRAWLER - Multi-threading Mode")
    print(f"{'=' * 70}\n")

    repos = fetch_top_repositories(limit=limit)
    print(f"\nFound {len(repos)} repositories. Starting concurrent processing...")
    print(f"Using {max_workers} worker threads\n")

    # Process repositories concurrently
    success_count = 0
    failure_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_repo = {
            executor.submit(process_repository, repo): repo for repo in repos
        }

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
                print(
                    f"Progress: [{total_processed}/{len(repos)}] | Success: {success_count} | Failed: {failure_count}"
                )

            except Exception as e:
                failure_count += 1
                logging.error(
                    f"Thread exception for {repo.get('full_name', 'unknown')}: {e}"
                )

    # Cleanup
    DatabaseConnectionPool.close_all()

    end_time = time.time()
    total_time = end_time - start_time

    print(f"\n{'=' * 70}")
    print(f"CRAWLING COMPLETED")
    print(f"{'=' * 70}")
    print(f"Total repositories: {len(repos)}")
    print(f"Successfully processed: {success_count}")
    print(f"Failed: {failure_count}")
    print(f"Total time: {total_time:.2f} seconds ({total_time / 60:.2f} minutes)")
    if len(repos) > 0:
        print(f"Average time per repo: {total_time / len(repos):.2f} seconds")
    else:
        print("Average time per repo: N/A (no repositories found)")
    print(f"{'=' * 70}\n")


def main_with_queue(limit: int = 5000, num_workers: int = 5):
    """
    Main crawler with Redis queue-based load leveling.
    """
    start_time = time.time()

    # Initialize connection pool
    DatabaseConnectionPool.initialize(minconn=num_workers, maxconn=num_workers * 2)

    # Create tables
    create_tables_sync()

    print(f"\n{'=' * 70}")
    print(f"OPTIMIZED GITHUB CRAWLER - Queue-based Mode")
    print(f"{'=' * 70}\n")

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

    print(f"\n{'=' * 70}")
    print(f"CRAWLING COMPLETED")
    print(f"{'=' * 70}")
    print(f"Total time: {total_time:.2f} seconds ({total_time / 60:.2f} minutes)")
    print(f"{'=' * 70}\n")


def process_single_repo(repo_data):
    """
    Process a single repository for testing purposes.
    Returns True if successful.
    """
    try:
        # Initialize database connection pool
        DatabaseConnectionPool.initialize(minconn=1, maxconn=2)

        # Clear Redis cache for this repo
        redis_manager.redis_client.delete(
            f"github_crawler:cache:processed:{repo_data['full_name']}"
        )

        # Process the repo
        success = process_repository(repo_data)

        # Close connection pool
        DatabaseConnectionPool.close()

        return success
    except Exception as e:
        print(f"Error in process_single_repo: {e}")
        return False
