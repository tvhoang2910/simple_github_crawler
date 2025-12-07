import sys
import logging
from app.crawler.manager import main_with_threading, main_with_queue

# Configure logging
logging.basicConfig(
    filename='crawler.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "threading"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    
    if mode == "queue":
        main_with_queue(limit=limit, num_workers=workers)
    else:
        main_with_threading(limit=limit, max_workers=workers)
