import time
import logging
import asyncio
from app.database.connection import ServiceFactory
from app.crawler.fetcher import fetch_top_repositories
from app.crawler.processor import redis_manager, async_queue_worker


async def main_with_queue_async(limit: int = 5000, num_workers: int = 10, max_concurrent_db: int = 5):
    """
    Main crawler with Redis queue-based load leveling using ASYNC operations.
    This version uses asyncio and Tortoise ORM for optimal performance.
    
    Args:
        limit: Maximum number of repositories to fetch
        num_workers: Number of async workers to process the queue
        max_concurrent_db: Maximum concurrent database operations
    """
    start_time = time.time()

    print(f"\n{'=' * 70}")
    print(f"OPTIMIZED GITHUB CRAWLER - Queue-based Mode (ASYNC)")
    print(f"{'=' * 70}\n")

    # Initialize Tortoise ORM with ServiceFactory
    print("Initializing async database connection...")
    await ServiceFactory.init_orm(
        models_modules=["app.database.models"],
        generate_schemas=True
    )
    print("Database initialized successfully.\n")

    # Fetch repositories and push to queue
    repos = fetch_top_repositories(limit=limit)
    print(f"\nFound {len(repos)} repositories. Pushing to Redis queue...")

    for repo in repos:
        redis_manager.push_to_queue(repo)

    print(f"All repositories queued. Queue size: {redis_manager.get_queue_size()}")
    print(f"Starting {num_workers} async workers with max {max_concurrent_db} concurrent DB ops...\n")

    # Create semaphore to limit concurrent database operations
    semaphore = asyncio.Semaphore(max_concurrent_db)

    # Start async workers
    tasks = [
        async_queue_worker(worker_id=i+1, semaphore=semaphore)
        for i in range(num_workers)
    ]

    # Wait for all workers to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Count successes and failures
    total_processed = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logging.error(f"Worker {i+1} failed with exception: {result}")
        else:
            total_processed += result

    # Cleanup
    await ServiceFactory.shutdown()

    end_time = time.time()
    total_time = end_time - start_time

    print(f"\n{'=' * 70}")
    print(f"CRAWLING COMPLETED (ASYNC)")
    print(f"{'=' * 70}")
    print(f"Total repositories queued: {len(repos)}")
    print(f"Successfully processed: {total_processed}")
    print(f"Total time: {total_time:.2f} seconds ({total_time / 60:.2f} minutes)")
    if total_processed > 0:
        print(f"Average time per repo: {total_time / total_processed:.2f} seconds")
    print(f"{'=' * 70}\n")


def run_main_with_queue_async(limit: int = 5000, num_workers: int = 10, max_concurrent_db: int = 5):
    """
    Synchronous wrapper to run the async main_with_queue_async function.
    Use this from synchronous code (e.g., main.py).
    """
    asyncio.run(main_with_queue_async(
        limit=limit,
        num_workers=num_workers,
        max_concurrent_db=max_concurrent_db
    ))
