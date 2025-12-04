import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "github_crawler")
DB_USER = os.getenv("DB_USER", "postgres")
# Do NOT hardcode passwords here -- read from environment variables or secure secret storage.
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_PORT = int(os.getenv("DB_PORT", 5432))

# GitHub API Token (for higher rate limits: 5000/hour vs 60/hour)
# Support for multiple tokens (comma separated) for rotation
GITHUB_TOKENS_STR = os.getenv("GITHUB_TOKENS", "")
if GITHUB_TOKENS_STR:
    GITHUB_TOKENS = [t.strip() for t in GITHUB_TOKENS_STR.split(",") if t.strip()]
else:
    # Fallback to single token
    single_token = os.getenv("GITHUB_TOKEN", "")
    GITHUB_TOKENS = [single_token] if single_token else []

# Gitstar Ranking Configuration
GITSTAR_BASE_URL = "https://gitstar-ranking.com"
GITSTAR_REPOS_PER_PAGE = 50  # Gitstar shows ~50 repos per page

# Crawling Configuration
REQUEST_TIMEOUT = 30  # seconds (tăng từ 10 lên 30 để tránh timeout)
MAX_RETRIES = 5
BASE_RETRY_DELAY = 1  # seconds (will exponentially backoff)
MAX_RETRY_DELAY = 30  # seconds
RATE_LIMIT_SLEEP = 0.5  # seconds between requests to avoid blocking

# Circuit Breaker Configuration
CIRCUIT_BREAKER_FAIL_THRESHOLD = 5  # Number of consecutive failures to open circuit
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60  # Seconds to wait before trying again (Half-Open)
