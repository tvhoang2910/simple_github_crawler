import logging
from typing import List, Dict, Any
from app.database.connection import DatabaseConnectionPool
from app.utils.redis_client import RedisManager
from app.crawler.fetcher import (
    fetch_releases,
    fetch_tags,
    fetch_commits,
    fetch_compare_commits
)

# Global Redis manager
redis_manager = RedisManager()

def upsert_repo_with_data(
    repo_data: Dict[str, Any],
    releases_data: List[Dict[str, Any]],
    commits_data: List[Dict[str, Any]]
) -> bool:
    """
    Upsert repository with releases and commits using connection pool.
    Returns True if successful.
    """
    try:
        with DatabaseConnectionPool.get_connection() as conn:
            with conn.cursor() as cur:
                # Upsert repository
                cur.execute("""
                    INSERT INTO repositories (github_id, name, full_name, html_url, stargazers_count, language, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (github_id) DO UPDATE SET
                        stargazers_count = EXCLUDED.stargazers_count
                    RETURNING id;
                """, (
                    repo_data['github_id'],
                    repo_data['name'],
                    repo_data['full_name'],
                    repo_data['html_url'],
                    repo_data.get('stargazers_count'),
                    repo_data.get('language'),
                    repo_data.get('created_at')
                ))
                
                result = cur.fetchone()
                repo_id = result[0] if result else None
                
                if not repo_id:
                    cur.execute("SELECT id FROM repositories WHERE github_id = %s", (repo_data['github_id'],))
                    result = cur.fetchone()
                    repo_id = result[0] if result else None
                
                if not repo_id:
                    raise Exception(f"Failed to get repo_id for {repo_data['full_name']}")
                
                # Batch insert releases
                if releases_data:
                    for release in releases_data:
                        cur.execute("""
                            INSERT INTO releases (repo_id, release_name, tag_name, published_at, html_url)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (repo_id, tag_name) DO NOTHING
                        """, (
                            repo_id,
                            release.get('name'),
                            release.get('tag_name'),
                            release.get('published_at'),
                            release.get('html_url')
                        ))
                
                # Batch insert commits
                if commits_data:
                    for commit in commits_data:
                        cur.execute("""
                            INSERT INTO commits (repo_id, sha, message, author_name, date, html_url)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (sha) DO NOTHING
                        """, (
                            repo_id,
                            commit.get('sha'),
                            commit.get('message'),
                            commit.get('author_name'),
                            commit.get('date'),
                            commit.get('html_url')
                        ))
                
                conn.commit()
                return True
            
    except Exception as e:
        logging.error(f"Error upserting repo {repo_data.get('full_name', 'unknown')}: {e}")
        return False


def process_repository(repo: Dict[str, Any]) -> bool:
    """
    Process a single repository with optimized logic:
    - Check cache to avoid re-processing
    - Fetch releases with fallback to tags
    - Use Compare API for incremental commits
    - Cache the result
    """
    try:
        full_name = repo['full_name']
        owner = repo['owner']['login']
        repo_name = repo['name']
        
        # Check if recently processed
        if redis_manager.is_repo_processed(full_name):
            logging.info(f"Skipping recently processed repo: {full_name}")
            return True
        
        print(f"Processing repo: {full_name}")
        
        # Fetch releases with fallback to tags
        releases = fetch_releases(owner, repo_name)
        
        if not releases:
            logging.info(f"No releases found for {full_name}, trying tags...")
            tags = fetch_tags(owner, repo_name)
            
            # Convert tags to release-like format
            releases = [
                {
                    'name': tag.get('name'),
                    'tag_name': tag.get('name'),
                    'published_at': None,
                    'html_url': tag.get('commit', {}).get('url')
                }
                for tag in tags[:10]
            ]
        
        # If still no releases/tags, just fetch recent commits
        if not releases:
            logging.info(f"No releases or tags for {full_name}, fetching recent commits...")
            commits = fetch_commits(owner, repo_name, per_page=20)
        else:
            # Use Compare API for incremental commits between releases
            commits = []
            last_cached_release = redis_manager.get_last_release(full_name)
            
            for i, release in enumerate(releases):
                tag_name = release.get('tag_name')
                
                # Skip if we've already processed this release
                if tag_name == last_cached_release:
                    break
                
                # Get commits for this release
                if i < len(releases) - 1:
                    # Compare with previous release
                    base = releases[i + 1].get('tag_name')
                    head = tag_name
                    release_commits = fetch_compare_commits(owner, repo_name, base, head)
                else:
                    # For the oldest release, just get recent commits
                    release_commits = fetch_commits(owner, repo_name, per_page=10)
                
                commits.extend(release_commits)
            
            # Cache the latest release
            if releases:
                redis_manager.cache_last_release(full_name, releases[0].get('tag_name'))
        
        # Prepare data for database
        repo_data = {
            'github_id': repo['id'],
            'name': repo['name'],
            'full_name': full_name,
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
                'message': c.get('commit', {}).get('message') if isinstance(c.get('commit'), dict) else c.get('message'),
                'author_name': c.get('commit', {}).get('author', {}).get('name') if isinstance(c.get('commit'), dict) else c.get('author_name'),
                'date': c.get('commit', {}).get('author', {}).get('date') if isinstance(c.get('commit'), dict) else c.get('date'),
                'html_url': c.get('html_url')
            }
            for c in commits
        ]
        
        # Save to database
        success = upsert_repo_with_data(repo_data, releases_data, commits_data)
        
        if success:
            # Mark as processed in cache
            redis_manager.cache_repo_processed(full_name)
            print(f"✓ Successfully processed {full_name}")
            return True
        else:
            print(f"✗ Failed to process {full_name}")
            return False
            
    except Exception as e:
        logging.error(f"Error processing repo {repo.get('full_name', 'unknown')}: {e}")
        print(f"✗ Error processing {repo.get('full_name', 'unknown')}: {e}")
        return False
