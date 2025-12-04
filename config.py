"""
Configuration Module

Defines database connection parameters and application settings.
Configure these values according to your environment.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# -------------------------------
# Database Configuration
# -------------------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "github_crawler")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

# Batch Processing Configuration
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))

# -------------------------------
# Redis Configuration
# -------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_URL = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}")

# -------------------------------
# GitHub Tokens
# -------------------------------
raw_tokens = os.getenv("GITHUB_TOKENS", "")
GITHUB_TOKENS = [t.strip() for t in raw_tokens.split(",") if t.strip()]

# Backward compatibility - single token
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
if GITHUB_TOKEN and not GITHUB_TOKENS:
    GITHUB_TOKENS = [GITHUB_TOKEN]

if not GITHUB_TOKENS:
    raise ValueError(
        "No GitHub tokens provided. "
        "Please set GITHUB_TOKENS or GITHUB_TOKEN environment variable."
    )

# -------------------------------
# PostgreSQL URL (optional)
# -------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "")

# -------------------------------
# Final config object (optional)
# -------------------------------
config = {
    "database": {
        "host": DB_HOST,
        "port": DB_PORT,
        "name": DB_NAME,
        "user": DB_USER,
        "password": DB_PASS,
    },
    "batch": {
        "size": BATCH_SIZE,
    },
    "redis": {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "url": REDIS_URL,
    },
    "github": {
        "tokens": GITHUB_TOKENS,
    },
    "postgres": {
        "database_url": DATABASE_URL,
    },
}