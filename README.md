# Simple GitHub Crawler

Optimized GitHub Crawler with multi-threading, Redis queue, and PostgreSQL storage.

## Structure

- `app/`: Main application package
  - `config.py`: Configuration settings
  - `main.py`: Entry point
  - `crawler/`: Crawler logic (fetcher, processor, manager)
  - `database/`: Database connection and models
  - `schemas/`: Data schemas/interfaces
  - `utils/`: Utilities (Redis, Token Rotation)

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables in `.env`:
   - `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`
   - `REDIS_HOST`, `REDIS_PORT`
   - `GITHUB_TOKENS` (comma-separated)

## Usage

Run the crawler in threading mode (default):
```bash
python -m app.main threading 100 10
# args: mode limit workers
```

Run with Redis queue:
```bash
python -m app.main queue 100 5
```
