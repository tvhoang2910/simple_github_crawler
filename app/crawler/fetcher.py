import requests
import time
import logging
from typing import List, Dict, Any, Optional
from app.config import GITHUB_TOKENS
from app.utils.token_rotator import GitHubTokenRotator
from app.utils.metrics import REQUEST_COUNT, RETRY_COUNT

# Global token rotator
token_rotator = GitHubTokenRotator(GITHUB_TOKENS)

def fetch_with_retry(url: str, max_retries: int = 3) -> Optional[Dict[str, Any]]:
    """Fetch data from GitHub API with retry logic and token rotation."""
    for attempt in range(max_retries):
        try:
            headers = token_rotator.get_headers()
            
            # Increment Request Count
            REQUEST_COUNT.inc()
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            
            elif response.status_code == 403:
                # Increment Retry Count
                RETRY_COUNT.inc()
                
                # Check for rate limit reset header
                reset_time = response.headers.get("x-ratelimit-reset")
                if reset_time:
                    wait_time = int(reset_time) - time.time()
                    if wait_time > 0:
                        logging.warning(f"Rate limit hit. Waiting {wait_time:.2f}s until reset.")
                        print(f"Rate limit hit. Waiting {wait_time:.2f}s...")
                        time.sleep(wait_time + 1) # Wait a bit extra
                        # Retry immediately after wait
                        continue
                
                logging.warning(f"Rate limit hit (no reset header) on attempt {attempt + 1}")
                time.sleep(2 ** attempt)  # Exponential backoff
                
            elif response.status_code == 422:
                # Unprocessable Entity - often happens with Compare API for large diffs
                logging.warning(f"422 Unprocessable Entity for {url} - skipping retry")
                return None
                
            elif response.status_code == 404:
                logging.info(f"Resource not found: {url}")
                return None
            else:
                logging.error(f"Error {response.status_code} for {url}: {response.text}")
                
        except Exception as e:
            logging.error(f"Request failed on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
    
    return None


def fetch_top_repositories(limit: int = 5000) -> List[Dict[str, Any]]:
    """
    Fetch the most-starred repositories from GitHub.
    """
    repos = []
    seen_ids = set()
    
    star_ranges = [
        "stars:>=50000",
        "stars:10000..49999",
        "stars:5000..9999",
        "stars:2000..4999",
        "stars:1000..1999"
    ]
    
    print(f"Starting to crawl top {limit} repositories...")
    
    for star_range in star_ranges:
        if len(repos) >= limit:
            break
            
        page = 1
        per_page = 100
        
        while len(repos) < limit:
            url = f"https://api.github.com/search/repositories?q={star_range}&sort=stars&order=desc&per_page={per_page}&page={page}"
            data = fetch_with_retry(url)
            
            if not data:
                break
            
            items = data.get("items", [])
            if not items:
                break
            
            for item in items:
                if item['id'] not in seen_ids:
                    repos.append(item)
                    seen_ids.add(item['id'])
            
            print(f"Fetched page {page} ({star_range}), total repos: {len(repos)}")
            page += 1
            
            # Check if we've hit pagination limit
            if page > 10:  # GitHub limits to 1000 results (10 pages * 100)
                break
    
    return repos[:limit]


def fetch_releases(owner: str, repo_name: str) -> List[Dict[str, Any]]:
    """Fetch releases for a repository."""
    url = f"https://api.github.com/repos/{owner}/{repo_name}/releases?per_page=10"
    data = fetch_with_retry(url)
    return data if data else []


def fetch_tags(owner: str, repo_name: str) -> List[Dict[str, Any]]:
    """Fetch tags as fallback when releases are not available."""
    url = f"https://api.github.com/repos/{owner}/{repo_name}/tags?per_page=10"
    data = fetch_with_retry(url)
    return data if data else []


def fetch_commits(owner: str, repo_name: str, per_page: int = 10) -> List[Dict[str, Any]]:
    """Fetch recent commits for a repository."""
    url = f"https://api.github.com/repos/{owner}/{repo_name}/commits?per_page={per_page}"
    data = fetch_with_retry(url)
    return data if data else []


def fetch_compare_commits(owner: str, repo_name: str, base: str, head: str) -> List[Dict[str, Any]]:
    """
    Use GitHub Compare API to fetch only commits between two tags/releases.
    """
    url = f"https://api.github.com/repos/{owner}/{repo_name}/compare/{base}...{head}"
    data = fetch_with_retry(url)
    
    if data and 'commits' in data:
        return data['commits']
    return []
