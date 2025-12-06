import sys
import logging
from pythonjsonlogger import jsonlogger
import cProfile
import pstats
from app.crawler.manager import main_with_threading, main_with_queue
from app.metrics import start_metrics_server

# Configure structured logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Handler for general crawler logs (console + file)
fileHandler = logging.FileHandler("crawler.log")
fileFormatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
fileHandler.setFormatter(fileFormatter)
logger.addHandler(fileHandler)

# Handler for structured metrics/events logs (JSON)
jsonHandler = logging.FileHandler("metrics.json.log")
jsonFormatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(levelname)s %(message)s %(event)s",
    rename_fields={"levelname": "level", "asctime": "timestamp"},
)
jsonHandler.setFormatter(jsonFormatter)


# Only log records that have an 'event' field to the JSON log
class EventFilter(logging.Filter):
    def filter(self, record):
        return hasattr(record, "event") and record.event is not None


jsonHandler.addFilter(EventFilter())
logger.addHandler(jsonHandler)

# Also log to console for visibility (optional, but good for debugging)
consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(fileFormatter)
logger.addHandler(consoleHandler)

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "threading"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    # Initialize Profiler
    profiler = cProfile.Profile()
    profiler.enable()

    # Start Prometheus metrics server
    start_metrics_server(8000)

    try:
        if mode == "queue":
            main_with_queue(limit=limit, num_workers=workers)
        else:
            main_with_threading(limit=limit, max_workers=workers)
    finally:
        profiler.disable()
        # Save profiling stats
        stats = pstats.Stats(profiler)
        stats.sort_stats("tottime")
        stats.dump_stats("crawler_profile.prof")
        print("Profiling data saved to 'crawler_profile.prof'")

        # Keep the program running to serve metrics
        print("\nCrawler finished. Metrics server is still running on port 8000.")
        print("You can check the metrics at http://localhost:8000")
        try:
            input("Press Enter to exit and stop the metrics server...")
        except KeyboardInterrupt:
            pass
