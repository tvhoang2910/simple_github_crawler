from prometheus_client import Counter, Histogram, Gauge, start_http_server

# Define Metrics
REQUEST_COUNT = Counter('github_crawler_requests_total', 'Total HTTP requests sent to GitHub API')
TOKEN_SWITCH_COUNT = Counter('github_crawler_token_switches_total', 'Total number of token rotations')
RETRY_COUNT = Counter('github_crawler_retries_total', 'Total number of retries due to rate limits or errors')
PROCESSING_TIME = Histogram('github_crawler_processing_seconds', 'Time taken to process a single repository')
QUEUE_SIZE = Gauge('github_crawler_queue_size', 'Current number of items in the processing queue')

def start_metrics_server(port=8000):
    """Start the Prometheus metrics server."""
    try:
        start_http_server(port)
        print(f"📊 Metrics server started on port {port}")
    except Exception as e:
        print(f"⚠️ Failed to start metrics server: {e}")
