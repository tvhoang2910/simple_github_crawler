import logging
from typing import List, Dict, Any
from app.database.connection import DatabaseConnectionPool
from app.utils.redis_client import RedisManager
from app.utils.metrics import PROCESSING_TIME
from app.crawler.fetcher import fetch_with_retry, token_rotator

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


def process_repository(repo):
    """Xử lý một repo: gọi API chi tiết (releases/tags/commits), parse và lưu DB."""
    with PROCESSING_TIME.time():  # Đo trọn chu trình xử lý repo gồm cả I/O mạng
        headers = token_rotator.get_headers()  # Sử dụng token_rotator từ fetcher
        owner = repo["owner"]["login"]
        name = repo["name"]

        # Ví dụ: gọi releases
        releases_url = f"https://api.github.com/repos/{owner}/{name}/releases"
        releases = fetch_with_retry(releases_url)

        # Ví dụ: gọi tags
        tags_url = f"https://api.github.com/repos/{owner}/{name}/tags"
        tags = fetch_with_retry(tags_url)

        # Ví dụ: gọi commits (giới hạn để tránh quá nhiều requests)
        commits_url = f"https://api.github.com/repos/{owner}/{name}/commits?per_page=10"
        commits = fetch_with_retry(commits_url)

        # Parse và lưu vào DB
        repo_data = {
            'github_id': repo['id'],
            'name': repo['name'],
            'full_name': f"{owner}/{name}",
            'html_url': repo['html_url'],
            'stargazers_count': repo.get('stargazers_count'),
            'language': repo.get('language'),
            'created_at': repo.get('created_at')
        }

        # Convert releases/tags to expected format
        releases_data = []
        if releases:
            for rel in releases[:5]:  # Limit to 5 releases
                releases_data.append({
                    'name': rel.get('name'),
                    'tag_name': rel.get('tag_name'),
                    'published_at': rel.get('published_at'),
                    'html_url': rel.get('html_url')
                })

        # Convert commits to expected format
        commits_data = []
        if commits:
            for commit in commits[:10]:  # Limit to 10 commits
                commit_info = commit.get('commit', {})
                commits_data.append({
                    'sha': commit.get('sha'),
                    'message': commit_info.get('message'),
                    'author_name': commit_info.get('author', {}).get('name'),
                    'date': commit_info.get('author', {}).get('date'),
                    'html_url': commit.get('html_url')
                })

        # Save to database
        success = upsert_repo_with_data(repo_data, releases_data, commits_data)
        
        if success:
            redis_manager.cache_repo_processed(f"{owner}/{name}")
            print(f"✓ Successfully processed {owner}/{name}")
            return True
        else:
            print(f"✗ Failed to process {owner}/{name}")
            return False
