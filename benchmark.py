import time
import argparse
import logging
from pythonjsonlogger import jsonlogger
from app.crawler.manager import main_with_threading
from app.metrics import REQUEST_COUNT, PROCESSING_TIME

# --- SETUP LOGGING (Giống hệt app/main.py để đo lường chính xác overhead) ---
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 1. File Handler thường
fileHandler = logging.FileHandler("crawler.log")
fileFormatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
fileHandler.setFormatter(fileFormatter)
logger.addHandler(fileHandler)

# 2. JSON Handler
jsonHandler = logging.FileHandler("metrics.json.log")
jsonFormatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(levelname)s %(message)s %(event)s",
    rename_fields={"levelname": "level", "asctime": "timestamp"},
)
jsonHandler.setFormatter(jsonFormatter)


class EventFilter(logging.Filter):
    def filter(self, record):
        return hasattr(record, "event") and record.event is not None


jsonHandler.addFilter(EventFilter())
logger.addHandler(jsonHandler)
# ---------------------------------------------------------------------------


def get_counter_value(metric):
    """Helper to get the current value of a Counter metric."""
    try:
        return list(metric.collect())[0].samples[0].value
    except IndexError:
        return 0


def get_histogram_count(metric):
    """Helper to get the count value of a Histogram metric."""
    try:
        for sample in list(metric.collect())[0].samples:
            if sample.name.endswith("_count"):
                return sample.value
        return 0
    except IndexError:
        return 0


def benchmark(max_workers, limit):
    print(f"Starting benchmark with max_workers={max_workers}, limit={limit}...")

    # Capture start metrics
    start_requests = get_counter_value(REQUEST_COUNT)
    start_items = get_histogram_count(PROCESSING_TIME)

    start_time = time.time()

    # Run the crawler (Đây chính là hàm chạy thật sự)
    try:
        main_with_threading(limit=limit, max_workers=max_workers)
    except Exception as e:
        print(f"Crawler stopped with error: {e}")

    end_time = time.time()
    duration = end_time - start_time

    # Capture end metrics
    end_requests = get_counter_value(REQUEST_COUNT)
    end_items = get_histogram_count(PROCESSING_TIME)

    total_requests = end_requests - start_requests
    total_items = end_items - start_items

    avg_rps = total_requests / duration if duration > 0 else 0

    print("\n" + "=" * 40)
    print("BENCHMARK RESULTS")
    print("=" * 40)
    print(f"Threads (max_workers) : {max_workers}")
    print(f"Limit (repositories)  : {limit}")
    print(f"Total Execution Time  : {duration:.2f} seconds")
    print(f"Total Requests        : {int(total_requests)}")
    print(f"Total Items Processed : {int(total_items)}")
    print(f"Average Requests/Sec  : {avg_rps:.2f}")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark GitHub Crawler Performance")
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of worker threads (recommended: 5-10 to avoid rate limits)",
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Number of repositories to process"
    )

    args = parser.parse_args()

    benchmark(args.workers, args.limit)
