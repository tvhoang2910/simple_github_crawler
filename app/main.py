import sys
import logging
from app.crawler.manager import run_main_with_queue_async

# Configure logging
logging.basicConfig(
    filename='crawler.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    max_concurrent_db = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    
    # Run optimized async version with Tortoise ORM
    run_main_with_queue_async(
        limit=limit,
        num_workers=workers,
        max_concurrent_db=max_concurrent_db
    )
