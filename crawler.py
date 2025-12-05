"""
GitHub Crawler Module

This module crawls top GitHub repositories and saves repository metadata,
releases, and commits to a PostgreSQL database using the GitHub REST API.

Features:
- Token Rotation: Supports multiple GitHub tokens for higher rate limits
- Circuit Breaker: Automatically pauses requests when API is unavailable
- Exponential Backoff: Retries failed requests with increasing delays
- Gitstar Integration: Bypasses GitHub Search API's 1000 result limit
"""

import requests
import time
import logging
import random
from database import create_tables, get_connection
from config import (
    GITHUB_TOKENS,
    GITSTAR_BASE_URL,
    REQUEST_TIMEOUT,
    RATE_LIMIT_SLEEP,
    MAX_RETRIES,
    BASE_RETRY_DELAY,
    MAX_RETRY_DELAY,
    CIRCUIT_BREAKER_FAIL_THRESHOLD,
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
)
from bs4 import BeautifulSoup

# Logging configuration
logging.basicConfig(
    filename="crawler_5000_repo_with_github_token.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class GitHubAPIClient:
    """
    A robust GitHub API client with token rotation, circuit breaker, and retry mechanisms.

    Attributes:
        tokens (list): List of GitHub API tokens for rotation
        current_token_index (int): Index of currently active token
        consecutive_failures (int): Count of consecutive failed requests
        is_circuit_open (bool): Whether circuit breaker is currently open
    """

    def __init__(self):
        self.tokens = GITHUB_TOKENS
        self.current_token_index = 0
        self.consecutive_failures = 0
        self.circuit_open_time = 0
        self.is_circuit_open = False

    def _get_headers(self):
        """Get request headers with current token authorization."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.tokens:
            token = self.tokens[self.current_token_index]
            headers["Authorization"] = f"token {token}"
        return headers

    def _rotate_token(self):
        """Rotate to the next available token. Returns True if rotation successful."""
        if not self.tokens or len(self.tokens) <= 1:
            return False
        self.current_token_index = (self.current_token_index + 1) % len(self.tokens)
        print(f"🔄 Rotating to token index {self.current_token_index}")
        return True

    def _check_circuit_breaker(self):
        """Check if circuit breaker allows requests. Returns True if allowed."""
        if self.is_circuit_open:
            if time.time() - self.circuit_open_time > CIRCUIT_BREAKER_RECOVERY_TIMEOUT:
                print("🔌 Circuit Breaker: Half-Open (Testing connection...)")
                self.is_circuit_open = False
                self.consecutive_failures = 0
                return True
            else:
                return False
        return True

    def _record_failure(self):
        """Record a failed request and potentially open the circuit breaker."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= CIRCUIT_BREAKER_FAIL_THRESHOLD:
            self.is_circuit_open = True
            self.circuit_open_time = time.time()
            print(
                f"🔌 Circuit Breaker: OPENED due to {self.consecutive_failures} consecutive failures."
            )

    def _record_success(self):
        """Record a successful request and reset failure counter."""
        self.consecutive_failures = 0
        self.is_circuit_open = False

    def make_request(self, url, params=None):
        """
        Make an HTTP GET request with retry logic, token rotation, and circuit breaker.

        Args:
            url (str): The URL to request
            params (dict): Optional query parameters

        Returns:
            Response object on success, None on failure
        """
        if not self._check_circuit_breaker():
            print("🔌 Circuit Breaker is OPEN. Skipping request.")
            return None

        retries = 0
        while retries <= MAX_RETRIES:
            try:
                headers = self._get_headers()
                response = requests.get(
                    url, headers=headers, params=params, timeout=REQUEST_TIMEOUT
                )

                # Handle Rate Limits (403/429)
                if response.status_code in [403, 429]:
                    remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
                    print(
                        f"⚠️ Rate limit hit (Status {response.status_code}). Remaining: {remaining}"
                    )

                    if self._rotate_token():
                        print("🔄 Retrying with new token...")
                        continue
                    else:
                        reset_time = response.headers.get("X-RateLimit-Reset")
                        if reset_time:
                            wait_time = int(reset_time) - time.time() + 1
                            if wait_time > 0:
                                print(
                                    f"⏳ Sleeping {wait_time:.0f}s for rate limit reset..."
                                )
                                time.sleep(min(wait_time, 60))
                                continue

                # Handle Server Errors (5xx)
                if 500 <= response.status_code < 600:
                    raise requests.exceptions.RequestException(
                        f"Server Error {response.status_code}"
                    )

                # Success
                if response.status_code == 200:
                    self._record_success()
                    return response

                # Other client errors (404, etc)
                self._record_success()
                return response

            except requests.exceptions.RequestException as e:
                print(f"❌ Network Error: {e}")
                self._record_failure()

                retries += 1
                if retries > MAX_RETRIES:
                    print(f"❌ Max retries exceeded for {url}")
                    break

                # Exponential Backoff + Jitter
                delay = min(MAX_RETRY_DELAY, (BASE_RETRY_DELAY * (2 ** (retries - 1))))
                jitter = random.uniform(0, 0.1 * delay)
                sleep_time = delay + jitter
                print(
                    f"⏳ Retrying in {sleep_time:.2f}s (Attempt {retries}/{MAX_RETRIES})..."
                )
                time.sleep(sleep_time)

        return None


# Initialize global client
github_client = GitHubAPIClient()


def log_completion(total_time, repos_count, total_releases, total_commits):
    """
    Log crawl completion statistics to the log file.

    Args:
        total_time (float): Total execution time in seconds
        repos_count (int): Number of repositories processed
        total_releases (int): Total releases fetched
        total_commits (int): Total commits fetched
    """
    with open("crawler_5000_repo_with_github_token.log", "a") as f:
        f.write(f"\n{'=' * 60}\n")
        f.write("CRAWL COMPLETED\n")
        f.write(
            f"Total Time: {total_time:.2f} seconds ({total_time / 60:.2f} minutes)\n"
        )
        f.write(f"Repositories Processed: {repos_count}\n")
        f.write(f"Total Releases: {total_releases}\n")
        f.write(f"Total Commits: {total_commits}\n")
        if repos_count > 0:
            f.write(f"Average Time per Repo: {total_time / repos_count:.2f} seconds\n")
            f.write(f"Average Releases per Repo: {total_releases / repos_count:.2f}\n")
            f.write(f"Average Commits per Repo: {total_commits / repos_count:.2f}\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'=' * 60}\n")


def fetch_repos_from_gitstar(limit=5000):
    """
    Fetch repository list from Gitstar-ranking.com to bypass GitHub Search API's 1000 result limit.

    Args:
        limit (int): Maximum number of repositories to fetch. Default is 5000.

    Returns:
        list: List of repository paths in 'owner/repo' format.

    Note:
        Gitstar-ranking.com ranks repositories by star count and allows pagination
        beyond GitHub's search limits.
    """
    repos = []
    seen_repos = set()
    page = 1

    print(f"Fetching top {limit} repositories from Gitstar-ranking...")

    while len(repos) < limit:
        url = f"{GITSTAR_BASE_URL}/repositories?page={page}"
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "GitHub-Crawler-Bot/1.0"},
                timeout=30,
            )
            if response.status_code != 200:
                logging.error(
                    f"Failed to fetch Gitstar page {page}: {response.status_code}"
                )
                print(f"Error fetching page {page}: {response.status_code}")
                break

            soup = BeautifulSoup(response.text, "html.parser")
            repo_links = soup.select("a[href*='/']")

            if not repo_links:
                print(f"No more repos found at page {page}")
                break

            for link in repo_links:
                href = link.get("href", "").strip()
                if href.startswith("/") and href.count("/") == 2 and len(repos) < limit:
                    repo_path = href.strip("/")
                    if repo_path not in seen_repos and ":" not in repo_path:
                        repos.append(repo_path)
                        seen_repos.add(repo_path)

            print(f"Fetched page {page}, total repos: {len(repos)}")
            page += 1
            time.sleep(RATE_LIMIT_SLEEP)

        except requests.exceptions.RequestException as e:
            logging.error(f"Network error fetching Gitstar page {page}: {e}")
            print(f"Network error: {e}. Retrying in 5 seconds...")
            time.sleep(5)
            continue

    print(f"Finished fetching {len(repos)} repositories from Gitstar")
    return repos[:limit]


def get_repo_from_github_api(owner, repo_name):
    """
    Fetch repository details from GitHub API.

    Args:
        owner (str): Repository owner username
        repo_name (str): Repository name

    Returns:
        dict: Repository data from GitHub API, or None on error
    """
    url = f"https://api.github.com/repos/{owner}/{repo_name}"
    response = github_client.make_request(url)

    if response and response.status_code == 200:
        repo_data = response.json()
        print(f"✅ Fetched repo: {owner}/{repo_name}")
        logging.info(f"Fetched repo: {owner}/{repo_name}")
        return repo_data
    else:
        status_code = response.status_code if response else "No response"
        error_msg = f"Failed to fetch repo {owner}/{repo_name}: Status {status_code}"
        logging.error(error_msg)
        print(f"❌ {error_msg}")
        return None


def fetch_top_repositories(limit=5000):
    """
    Fetch the most-starred repositories from GitHub Search API.

    GitHub Search API limits results to 1000 per query. To retrieve more repositories,
    this function splits the search into multiple star-count ranges and aggregates results.

    Args:
        limit (int): Maximum number of repositories to fetch. Default is 5000.

    Returns:
        list: List of repository dictionaries from GitHub API.
    """
    repos = []
    seen_ids = set()

    star_ranges = [
        "stars:>=50000",
        "stars:10000..49999",
        "stars:5000..9999",
        "stars:2000..4999",
        "stars:1000..1999",
    ]

    print(f"Starting to crawl top {limit} repositories...")

    for star_range in star_ranges:
        if len(repos) >= limit:
            break

        page = 1
        per_page = 100

        while len(repos) < limit:
            url = f"https://api.github.com/search/repositories?q={star_range}&sort=stars&order=desc&per_page={per_page}&page={page}"
            response = github_client.make_request(url)

            if response and response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                if not items:
                    break

                for item in items:
                    if item["id"] not in seen_ids:
                        repos.append(item)
                        seen_ids.add(item["id"])

                print(f"Fetched page {page} ({star_range}), total repos: {len(repos)}")
                page += 1

            elif response and response.status_code == 422:
                logging.error(f"Invalid query or pagination exceeded: {response.text}")
                print(f"Pagination limit reached for {star_range}")
                break
            else:
                break

    return repos[:limit]


def fetch_releases(owner, repo_name):
    """
    Fetch the latest releases for a GitHub repository.

    Args:
        owner (str): The GitHub username or organization name.
        repo_name (str): The name of the repository.

    Returns:
        list: List of release dictionaries, or empty list on error.
    """
    url = f"https://api.github.com/repos/{owner}/{repo_name}/releases?per_page=5"
    response = github_client.make_request(url)
    if response and response.status_code == 200:
        releases = response.json()
        print(f"✅ Fetched {len(releases)} releases for {owner}/{repo_name}")
        logging.info(f"Fetched {len(releases)} releases for {owner}/{repo_name}")
        return releases
    return []


def fetch_commits(owner, repo_name):
    """
    Fetch the latest commits for a GitHub repository.

    Args:
        owner (str): The GitHub username or organization name.
        repo_name (str): The name of the repository.

    Returns:
        list: List of commit dictionaries, or empty list on error.
    """
    url = f"https://api.github.com/repos/{owner}/{repo_name}/commits?per_page=5"
    response = github_client.make_request(url)
    if response and response.status_code == 200:
        commits = response.json()
        print(f"✅ Fetched {len(commits)} commits for {owner}/{repo_name}")
        logging.info(f"Fetched {len(commits)} commits for {owner}/{repo_name}")
        return commits
    return []


def save_to_db(repo):
    """
    Save repository data, releases, and commits to the database.

    Args:
        repo: Either a dict (from GitHub API) or string (owner/repo from Gitstar)

    Returns:
        tuple: (releases_count, commits_count) saved to database
    """
    conn = get_connection()
    cur = conn.cursor()

    releases_count = 0
    commits_count = 0

    try:
        # If repo is a string (from Gitstar), fetch from GitHub API
        if isinstance(repo, str):
            owner, repo_name = repo.split("/")
            repo = get_repo_from_github_api(owner, repo_name)
            if not repo:
                print(f"Failed to fetch {owner}/{repo_name} from GitHub API")
                return 0, 0

        print(f"Processing repo: {repo['full_name']}")

        # 1. Insert Repository
        cur.execute(
            """
            INSERT INTO repositories (github_id, name, full_name, html_url, stargazers_count, language, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (github_id) DO NOTHING
            RETURNING id;
            """,
            (
                repo["id"],
                repo["name"],
                repo["full_name"],
                repo["html_url"],
                repo["stargazers_count"],
                repo["language"],
                repo["created_at"],
            ),
        )

        repo_db_id = cur.fetchone()

        if not repo_db_id:
            cur.execute(
                "SELECT id FROM repositories WHERE github_id = %s", (repo["id"],)
            )
            repo_db_id = cur.fetchone()

        if repo_db_id:
            repo_id = repo_db_id[0]

            # 2. Fetch & Insert Releases
            releases = fetch_releases(repo["owner"]["login"], repo["name"])
            for rel in releases:
                cur.execute(
                    """
                    INSERT INTO releases (repo_id, release_name, tag_name, published_at, html_url)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        repo_id,
                        rel.get("name"),
                        rel.get("tag_name"),
                        rel.get("published_at"),
                        rel.get("html_url"),
                    ),
                )
                releases_count += 1

            if releases_count > 0:
                print(f"✅ Saved {releases_count} releases for {repo['full_name']}")
                logging.info(f"Saved {releases_count} releases for {repo['full_name']}")

            # 3. Fetch & Insert Commits
            commits = fetch_commits(repo["owner"]["login"], repo["name"])
            for c in commits:
                commit_info = c.get("commit", {})
                author_info = commit_info.get("author", {})
                cur.execute(
                    """
                    INSERT INTO commits (repo_id, sha, message, author_name, date, html_url)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        repo_id,
                        c.get("sha"),
                        commit_info.get("message"),
                        author_info.get("name"),
                        author_info.get("date"),
                        c.get("html_url"),
                    ),
                )
                commits_count += 1

            if commits_count > 0:
                print(f"✅ Saved {commits_count} commits for {repo['full_name']}")
                logging.info(f"Saved {commits_count} commits for {repo['full_name']}")

            conn.commit()

    except Exception as e:
        logging.error(f"Error saving repo: {e}")
        print(f"Error saving repo: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

    return releases_count, commits_count


def main():
    """
    Main entry point for the GitHub crawler.

    This function orchestrates the entire crawling process:
    1. Creates database tables if they don't exist
    2. Fetches repositories from Gitstar-ranking (bypasses GitHub's 1000 limit)
    3. Saves each repository's data, releases, and commits to the database
    4. Reports total execution time and statistics

    Features:
    - Graceful handling of KeyboardInterrupt
    - Detailed logging to file
    - Progress tracking with realtime output
    """
    start_time = time.time()

    try:
        create_tables()

        print(
            "Strategy: Using Gitstar-ranking.com as data source (bypass GitHub Search API limit of 1000)"
        )
        repos = fetch_repos_from_gitstar(limit=500)

        if not repos:
            print("No repositories found. Exiting.")
            return

        print(f"Found {len(repos)} repositories. Starting detailed crawl...")

        total_releases = 0
        total_commits = 0
        failed_repos = 0

        for i, repo in enumerate(repos):
            releases_count, commits_count = save_to_db(repo)
            total_releases += releases_count
            total_commits += commits_count
            if releases_count == 0 and commits_count == 0:
                failed_repos += 1
            print(
                f"[{i + 1}/{len(repos)}] Processed {repo} (Releases: {releases_count}, Commits: {commits_count})"
            )

            time.sleep(RATE_LIMIT_SLEEP)

        end_time = time.time()
        total_time = end_time - start_time
        print(
            f"\nCrawling completed in {total_time:.2f} seconds ({total_time / 60:.2f} minutes)"
        )
        print(f"Failed repos: {failed_repos}")

        log_completion(
            total_time, len(repos) - failed_repos, total_releases, total_commits
        )

    except KeyboardInterrupt:
        end_time = time.time()
        total_time = end_time - start_time
        print(f"\n⚠️ Crawling interrupted by user after {total_time:.2f} seconds")
        print(f"Processed repos so far: {i + 1 if 'i' in locals() else 0}")
        log_completion(
            total_time,
            i + 1 if "i" in locals() else 0,
            total_releases if "total_releases" in locals() else 0,
            total_commits if "total_commits" in locals() else 0,
        )


if __name__ == "__main__":
    main()
