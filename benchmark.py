import time
import argparse
import logging
import os
import json
from collections import Counter
import yappi  # Thay thế cProfile

# import cProfile (Removed)
# import pstats (Removed)
from pythonjsonlogger import jsonlogger

from app.crawler.manager import main_with_threading
from app.metrics import (
    REQUEST_COUNT,
    PROCESSING_TIME,
    start_metrics_server,
)


# =========================
# Logging cấu hình cho benchmark
# =========================
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Ghi log text tổng hợp
file_handler = logging.FileHandler("benchmark.log")
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Ghi log JSON cho các event có field `event`
json_handler = logging.FileHandler("metrics.json.log")
json_formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(levelname)s %(message)s %(event)s",
    rename_fields={"levelname": "level", "asctime": "timestamp"},
)
json_handler.setFormatter(json_formatter)


class EventFilter(logging.Filter):
    def filter(self, record):
        return hasattr(record, "event") and record.event is not None


json_handler.addFilter(EventFilter())
logger.addHandler(json_handler)

# Ghi ra console cho dễ theo dõi
console_handler = logging.StreamHandler()
console_handler.setFormatter(file_formatter)
logger.addHandler(console_handler)


# =========================
# Helper đọc metrics
# =========================
def get_counter_value(metric):
    """Lấy value hiện tại của Counter."""
    try:
        return list(metric.collect())[0].samples[0].value
    except (IndexError, ValueError):
        return 0


def get_histogram_count(metric):
    """Lấy `_count` của Histogram (tổng số item đã ghi nhận)."""
    try:
        for sample in list(metric.collect())[0].samples:
            if sample.name.endswith("_count"):
                return sample.value
        return 0
    except (IndexError, ValueError):
        return 0


# =========================
# Hàm benchmark chính
# =========================
def run_benchmark(max_workers: int, limit: int):
    print(f"Starting benchmark with max_workers={max_workers}, limit={limit}...")

    # 1. Start Prometheus server
    start_metrics_server(8000)

    # 2. Chụp metrics ban đầu
    start_requests = get_counter_value(REQUEST_COUNT)
    start_items = get_histogram_count(PROCESSING_TIME)

    # 3. Khởi tạo profiler (SỬ DỤNG YAPPI CHO ĐA LUỒNG)
    yappi.set_clock_type("wall")  # Đo thời gian thực
    yappi.start()

    wall_start = time.time()

    try:
        # 4. Chạy crawler thực sự
        main_with_threading(limit=limit, max_workers=max_workers)
    finally:
        wall_end = time.time()
        yappi.stop()

        # 5. Ghi file profile
        stats = yappi.get_func_stats()
        stats.save("output.prof", type="pstat")
        print("Profiling data saved to 'output.prof'")

    duration = wall_end - wall_start

    # 6. Chụp metrics sau khi chạy
    end_requests = get_counter_value(REQUEST_COUNT)
    end_items = get_histogram_count(PROCESSING_TIME)

    total_requests = end_requests - start_requests
    total_items = end_items - start_items

    avg_rps = total_requests / duration if duration > 0 else 0.0

    # 7. In summary ra console
    print("\n" + "=" * 50)
    print("BENCHMARK SUMMARY")
    print("=" * 50)
    print(f"Threads (max_workers)   : {max_workers}")
    print(f"Limit (repositories)    : {limit}")
    print(f"Total Execution Time    : {duration:.2f} seconds")
    print(f"Total Requests          : {int(total_requests)}")
    print(f"Total Items Processed   : {int(total_items)}")
    print(f"Average Requests / Sec  : {avg_rps:.2f}")
    print("=" * 50 + "\n")

    # 8. Chạy phân tích log tự động
    analyze_logs("metrics.json.log")

    # 9. Giữ process sống để Grafana scrape
    print("Benchmark finished. Keeping process alive for metrics scraping.")
    print("Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")


# =========================
# Hàm phân tích Log tự động
# =========================
def analyze_logs(log_file="metrics.json.log"):
    """Đọc file log JSON và in ra báo cáo thống kê."""
    print("\n" + "=" * 50)
    print("LOG ANALYSIS REPORT")
    print("=" * 50)

    if not os.path.exists(log_file):
        print(f"Log file '{log_file}' not found.")
        return

    event_counts = Counter()

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    event = record.get("event")
                    if event:
                        event_counts[event] += 1
                except json.JSONDecodeError:
                    continue

        # In bảng thống kê sự kiện
        print(f"{'Event Type':<30} | {'Count':<10}")
        print("-" * 43)
        if not event_counts:
            print("No events found in log.")
        else:
            for event, count in event_counts.most_common():
                print(f"{event:<30} | {count:<10}")

        print("-" * 43)

        # In các chỉ số quan trọng cụ thể
        print(f"[-] Switch Token      : {event_counts.get('Switch Token', 0)}")
        print(f"[-] Retry             : {event_counts.get('Retry', 0)}")
        print(f"[-] Duplicate Skipped : {event_counts.get('Duplicate Skipped', 0)}")
        print("=" * 50 + "\n")

    except Exception as e:
        print(f"Error analyzing logs: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified Benchmark Entry Point")
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of worker threads",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of repositories to process",
    )

    args = parser.parse_args()
    run_benchmark(args.workers, args.limit)
    analyze_logs()
