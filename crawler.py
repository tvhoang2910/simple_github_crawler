import requests
import time
import logging
import random
from database import get_connection, create_tables
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

# Cấu hình logging
logging.basicConfig(
    filename="crawler_5000_repo_with_github_token.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def log_completion(total_time, repos_count, total_releases, total_commits):
    """Log thời gian hoàn thành crawl"""
    with open("crawler_5000_repo_with_github_token.log", "a") as f:
        f.write(f"\n{'=' * 60}\n")
        f.write("CRAWL COMPLETED\n")
        f.write(
            f"Total Time: {total_time:.2f} seconds ({total_time / 60:.2f} minutes)\n"
        )
        f.write(f"Repositories Processed: {repos_count}\n")
        f.write(f"Total Releases: {total_releases}\n")
        f.write(f"Total Commits: {total_commits}\n")
        f.write(f"Average Time per Repo: {total_time / repos_count:.2f} seconds\n")
        f.write(f"Average Releases per Repo: {total_releases / repos_count:.2f}\n")
        f.write(f"Average Commits per Repo: {total_commits / repos_count:.2f}\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'=' * 60}\n")


def fetch_repos_from_gitstar(limit=5000):
    """
    Lấy danh sách repository từ Gitstar-ranking.com để vượt qua giới hạn 1000 kết quả của GitHub Search API.

    Args:
        limit: Số repo cần lấy (tối đa 5000)

    Returns:
        List của repo objects với owner/repo name
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
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code != 200:
                logging.error(
                    f"Failed to fetch Gitstar page {page}: {response.status_code}"
                )
                print(f"Error fetching page {page}: {response.status_code}")
                break

            soup = BeautifulSoup(response.text, "html.parser")

            # Tìm tất cả link repo (thường là trong dạng /owner/repo)
            repo_links = soup.select("a[href*='/']")

            if not repo_links:
                print(f"No more repos found at page {page}")
                break

            for link in repo_links:
                href = link.get("href", "").strip()
                # Lọc link repo theo pattern: /owner/repo (2 slashes)
                if href.startswith("/") and href.count("/") == 2 and len(repos) < limit:
                    repo_path = href.strip("/")  # owner/repo
                    if (
                        repo_path not in seen_repos and ":" not in repo_path
                    ):  # Loại bỏ link không hợp lệ
                        repos.append(repo_path)
                        seen_repos.add(repo_path)

            print(f"Fetched page {page}, total repos: {len(repos)}")
            page += 1
            time.sleep(RATE_LIMIT_SLEEP)  # Tránh overload Gitstar

        except requests.exceptions.RequestException as e:
            logging.error(f"Network error fetching Gitstar page {page}: {e}")
            print(f"Network error: {e}")
            break

    print(f"Finished fetching {len(repos)} repositories from Gitstar")
    return repos[:limit]


def get_repo_from_github_api(owner, repo_name):
    """
    Lấy thông tin repo từ GitHub API sử dụng GitHubAPIClient
    """
    url = f"https://api.github.com/repos/{owner}/{repo_name}"
    response = github_client.make_request(url)

    if response and response.status_code == 200:
        return response.json()

    return None


def fetch_top_repositories(limit=5000):
    """
    Tìm kiếm các repository nhiều sao nhất trên GitHub.
    GitHub Search API giới hạn 1000 kết quả cho mỗi query.
    Để lấy 5000, chia query theo ranges of stars.
    """
    repos = []
    seen_ids = set()  # Để tránh duplicate

    # Chia thành 5 ranges để lấy ~1000 repos mỗi lần
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

                # Thêm repos chưa thấy
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
    url = f"https://api.github.com/repos/{owner}/{repo_name}/releases?per_page=5"
    response = github_client.make_request(url)
    if response and response.status_code == 200:
        return response.json()
    return []


def fetch_commits(owner, repo_name):
    url = f"https://api.github.com/repos/{owner}/{repo_name}/commits?per_page=5"
    response = github_client.make_request(url)
    if response and response.status_code == 200:
        return response.json()
    return []


def save_to_db(repo):
    """
    Lưu thông tin repo vào database.

    Args:
        repo: Có thể là dict (từ GitHub API) hoặc string (owner/repo từ Gitstar)
    """
    conn = get_connection()
    cur = conn.cursor()

    releases_count = 0
    commits_count = 0

    try:
        # Nếu repo là string (từ Gitstar), cần fetch từ GitHub API
        if isinstance(repo, str):
            owner, repo_name = repo.split("/")
            repo = get_repo_from_github_api(owner, repo_name)
            if not repo:
                print(f"Failed to fetch {owner}/{repo_name} from GitHub API")
                return 0, 0

        # 1. Insert Repository
        print(f"Processing repo: {repo['full_name']}")
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

        # Nếu repo đã tồn tại, lấy ID của nó
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

            conn.commit()

    except Exception as e:
        logging.error(f"Error saving repo: {e}")
        print(f"Error saving repo: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

    return releases_count, commits_count


class GitHubAPIClient:
    def __init__(self):
        self.tokens = GITHUB_TOKENS
        self.current_token_index = 0
        self.consecutive_failures = 0
        self.circuit_open_time = 0
        self.is_circuit_open = False

    def _get_headers(self):
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.tokens:
            token = self.tokens[self.current_token_index]
            headers["Authorization"] = f"token {token}"
        return headers

    def _rotate_token(self):
        if not self.tokens or len(self.tokens) <= 1:
            return False
        self.current_token_index = (self.current_token_index + 1) % len(self.tokens)
        print(f"🔄 Rotating to token index {self.current_token_index}")
        return True

    def _check_circuit_breaker(self):
        if self.is_circuit_open:
            if time.time() - self.circuit_open_time > CIRCUIT_BREAKER_RECOVERY_TIMEOUT:
                print("🔌 Circuit Breaker: Half-Open (Testing connection...)")
                self.is_circuit_open = False
                self.consecutive_failures = 0
                return True  # Allow request
            else:
                return False  # Circuit still open
        return True

    def _record_failure(self):
        self.consecutive_failures += 1
        if self.consecutive_failures >= CIRCUIT_BREAKER_FAIL_THRESHOLD:
            self.is_circuit_open = True
            self.circuit_open_time = time.time()
            print(
                f"🔌 Circuit Breaker: OPENED due to {self.consecutive_failures} consecutive failures."
            )

    def _record_success(self):
        self.consecutive_failures = 0
        self.is_circuit_open = False

    def make_request(self, url, params=None):
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

                    # Try rotating token first
                    if self._rotate_token():
                        print("🔄 Retrying with new token...")
                        continue  # Retry immediately with new token
                    else:
                        # No tokens or single token, must wait
                        reset_time = response.headers.get("X-RateLimit-Reset")
                        if reset_time:
                            wait_time = int(reset_time) - time.time() + 1
                            if wait_time > 0:
                                print(
                                    f"⏳ Sleeping {wait_time:.0f}s for rate limit reset..."
                                )
                                time.sleep(
                                    min(wait_time, 60)
                                )  # Cap sleep for safety? Or just sleep.
                                # If we sleep, we can retry.
                                continue

                # Handle Server Errors (5xx) -> Retry with Backoff
                if 500 <= response.status_code < 600:
                    raise requests.exceptions.RequestException(
                        f"Server Error {response.status_code}"
                    )

                # Success
                if response.status_code == 200:
                    self._record_success()
                    return response

                # Other client errors (404, etc) - Don't retry
                self._record_success()  # It's a successful connection, just a bad request
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


def main():
    start_time = time.time()

    # Tạo bảng nếu chưa có
    create_tables()

    # Lấy danh sách repo từ Gitstar-ranking (vượt qua giới hạn 1000 của GitHub Search API)
    print(
        "Strategy: Using Gitstar-ranking.com as data source (bypass GitHub Search API limit of 1000)"
    )
    repos = fetch_repos_from_gitstar(limit=5000)

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

        # Sleep để tránh rate limit
        time.sleep(RATE_LIMIT_SLEEP)

    end_time = time.time()
    total_time = end_time - start_time
    print(
        f"\nCrawling completed in {total_time:.2f} seconds ({total_time / 60:.2f} minutes)"
    )
    print(f"Failed repos: {failed_repos}")

    # Log thời gian hoàn thành
    log_completion(total_time, len(repos) - failed_repos, total_releases, total_commits)


if __name__ == "__main__":
    main()
