"""
GitHub Crawler Module

This module crawls top GitHub repositories and saves repository metadata,
releases, and commits to a PostgreSQL database using the GitHub REST API.
"""

import requests
import time
import logging
from database import create_tables, upsert_repo_with_releases_and_commits
from config import GITHUB_TOKEN

logging.basicConfig(
    filename='crawler_5000_repo_with_github_token.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

HEADERS = {
    "Accept": "application/vnd.github.v3+json"
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

def fetch_top_repositories(limit=5000):
    """
    Fetch the most-starred repositories from GitHub.
    
    GitHub Search API limits results to 1000 per query. To retrieve more repositories,
    this function splits the search into multiple star-count ranges and aggregates results.
    Repositories are deduplicated by their GitHub ID.
    
    Args:
        limit (int): Maximum number of repositories to fetch. Default is 5000.
    
    Returns:
        list: List of repository dictionaries containing GitHub API response data.
              Each repository includes fields like id, name, full_name, html_url,
              stargazers_count, language, and created_at.
    
    Note:
        The function handles rate limits and network errors gracefully by logging
        errors and stopping pagination for problematic ranges.
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
            try:
                response = requests.get(url, headers=HEADERS, timeout=10)
            except requests.exceptions.RequestException as e:
                logging.error(f"Network error fetching repos: {e}")
                print(f"Network error: {e}")
                break
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                if not items:
                    break
                
                for item in items:
                    if item['id'] not in seen_ids:
                        repos.append(item)
                        seen_ids.add(item['id'])
                
                print(f"Fetched page {page} ({star_range}), total repos: {len(repos)}")
                page += 1
                
            elif response.status_code == 422:
                logging.error(f"Invalid query or pagination exceeded: {response.text}")
                print(f"Pagination limit reached for {star_range}")
                break
            elif response.status_code == 403:
                logging.error(f"Rate limit: {response.json()}")
                print("Rate limit exceeded!")
                break
            else:
                logging.error(f"Error fetching repos: {response.status_code} - {response.text}")
                print(f"Error fetching repos: {response.status_code}")
                break
            
    return repos[:limit]

def fetch_releases(owner, repo_name):
    """
    Fetch the latest releases for a GitHub repository.
    
    Args:
        owner (str): The GitHub username or organization name that owns the repository.
        repo_name (str): The name of the repository.
    
    Returns:
        list: List of release dictionaries from the GitHub API, or empty list on error.
              Each release includes fields like name, tag_name, published_at, and html_url.
    """
    url = f"https://api.github.com/repos/{owner}/{repo_name}/releases?per_page=5"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error fetching releases for {owner}/{repo_name}: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error fetching releases for {owner}/{repo_name}: {e}")
    return []

def fetch_commits(owner, repo_name):
    """
    Fetch the latest commits for a GitHub repository.
    
    Args:
        owner (str): The GitHub username or organization name that owns the repository.
        repo_name (str): The name of the repository.
    
    Returns:
        list: List of commit dictionaries from the GitHub API, or empty list on error.
              Each commit includes fields like sha, commit message, author, date, and html_url.
    """
    url = f"https://api.github.com/repos/{owner}/{repo_name}/commits?per_page=5"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error fetching commits for {owner}/{repo_name}: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error fetching commits for {owner}/{repo_name}: {e}")
    return []

def save_to_db(repo):
    """
    Save repository data, releases, and commits to the database.
    
    This function performs the following operations in a transaction:
    1. Insert repository metadata into the repositories table (or skip if exists)
    2. Fetch and insert the latest releases for the repository
    3. Fetch and insert the latest commits for the repository
    
    Args:
        repo (dict): Repository dictionary from GitHub API containing all metadata.
    
    Note:
        All operations are performed in a single transaction with rollback on error.
        Errors are logged and printed but don't stop the overall crawling process.
    """
    try:
        print(f"Processing repo: {repo['full_name']}")
        
        owner = repo['owner']['login']
        repo_name = repo['name']
        
        releases = fetch_releases(owner, repo_name)
        commits = fetch_commits(owner, repo_name)
        
        repo_data = {
            'github_id': repo['id'],
            'name': repo['name'],
            'full_name': repo['full_name'],
            'html_url': repo['html_url'],
            'stargazers_count': repo.get('stargazers_count'),
            'language': repo.get('language'),
            'created_at': repo.get('created_at')
        }
        
        releases_data = [
            {
                'name': rel.get('name'),
                'tag_name': rel.get('tag_name'),
                'published_at': rel.get('published_at'),
                'html_url': rel.get('html_url')
            }
            for rel in releases
        ]
        
        commits_data = [
            {
                'sha': c.get('sha'),
                'message': c.get('commit', {}).get('message'),
                'author_name': c.get('commit', {}).get('author', {}).get('name'),
                'date': c.get('commit', {}).get('author', {}).get('date'),
                'html_url': c.get('html_url')
            }
            for c in commits
        ]
        
        result = upsert_repo_with_releases_and_commits(
            repo_data,
            releases_data,
            commits_data
        )
        
        if result['success']:
            print(f"Successfully saved {repo['full_name']}")
        
    except Exception as e:
        logging.error(f"Error saving repo {repo['full_name']}: {e}")
        print(f"Error saving repo {repo['full_name']}: {e}")

def main():
    """
    Main entry point for the GitHub crawler.
    
    This function orchestrates the entire crawling process:
    1. Creates database tables if they don't exist
    2. Fetches top repositories from GitHub
    3. Saves each repository's data, releases, and commits to the database
    4. Reports total execution time
    
    Note:
        This implementation does not include sleep/delays between requests,
        which may trigger GitHub's rate limiting.
    """
    start_time = time.time()
    
    create_tables()
    
    repos = fetch_top_repositories(limit=5000)
    
    print(f"Found {len(repos)} repositories. Starting detailed crawl...")
    
    for i, repo in enumerate(repos):
        save_to_db(repo)
        print(f"[{i+1}/{len(repos)}] Saved data for {repo['full_name']}")
    
    end_time = time.time()
    total_time = end_time - start_time
    print(f"\nCrawling completed in {total_time:.2f} seconds ({total_time/60:.2f} minutes)")

if __name__ == "__main__":
    main()
