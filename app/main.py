import sys
import logging
import cProfile
import pstats
from app.crawler.manager import main_with_threading, main_with_queue
from app.utils.metrics import start_metrics_server

# Configure logging
logging.basicConfig(
    filename='crawler.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def run_crawler():
    """Main execution logic wrapped for profiling"""
    # Start Prometheus Metrics Server
    start_metrics_server(8000)

    mode = sys.argv[1] if len(sys.argv) > 1 else "threading"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    
    if mode == "queue":
        main_with_queue(limit=limit, num_workers=workers)
    else:
        main_with_threading(limit=limit, max_workers=workers)

if __name__ == "__main__":
    # Initialize Profiler
    profiler = cProfile.Profile()
    
    print("🚀 Starting Crawler with Performance Profiling...")
    profiler.enable()
    
    try:
        run_crawler()
    finally:
        profiler.disable()
        
        # Save stats to file
        output_file = 'crawler_performance.prof'
        profiler.dump_stats(output_file)
        
        print(f"\n📊 Profiling completed! Stats saved to '{output_file}'")
        
        # Print top 20 time-consuming functions by cumulative time
        print("\n=== Top 20 Functions by Cumulative Time ===")
        stats = pstats.Stats(profiler).sort_stats('cumtime')
        stats.print_stats(20)
        print("\n" + "="*60)
        print("✅ CRAWLING FINISHED!")
        print("📊 Prometheus Metrics đang chạy tại: http://localhost:8000/metrics")
        print("👉 Nhấn [Enter] để thoát chương trình và tắt server...")
        print("="*60)
        try:
            input()
        except KeyboardInterrupt:
            pass
