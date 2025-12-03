import requests
import time
import logging
from database import get_connection, create_tables
from config import GITHUB_TOKEN

# Cấu hình logging
logging.basicConfig(
    filename='crawler.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Cấu hình Header cho request
HEADERS = {
    "Accept": "application/vnd.github.v3+json"
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

def fetch_top_repositories(limit=100):
    """
    Tìm kiếm các repository nhiều sao nhất trên GitHub.
    Lưu ý: GitHub Search API giới hạn 1000 kết quả cho mỗi query.
    Để lấy 5000, cần logic phức tạp hơn (chia nhỏ theo ngày hoặc số sao),
    nhưng ở đây ta làm phiên bản đơn giản nhất.
    """
    repos = []
    page = 1
    per_page = 100 # Max allowed by GitHub
    
    print(f"Starting to crawl top {limit} repositories...")
    
    while len(repos) < limit:
        url = f"https://api.github.com/search/repositories?q=stars:>1000&sort=stars&order=desc&per_page={per_page}&page={page}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error fetching repos page {page}: {e}")
            print(f"Network error: {e}")
            break
        
        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])
            if not items:
                break
            
            repos.extend(items)
            print(f"Fetched page {page}, total repos: {len(repos)}")
            page += 1
            
            # Đơn giản: không sleep để dễ bị rate limit (theo yêu cầu bài tập)
            # time.sleep(1) 
        elif response.status_code == 403:
            logging.error(f"Rate limit or block on repos page {page}: {response.json()}")
            print("Rate limit exceeded or blocked!")
            print(response.json())
            break
        else:
            logging.error(f"Error fetching repos page {page}: {response.status_code} - {response.text}")
            print(f"Error fetching repos: {response.status_code}")
            break
            
    return repos[:limit]

def fetch_releases(owner, repo_name):
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
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        # 1. Insert Repository
        print(f"Processing repo: {repo['full_name']}")
        cur.execute("""
            INSERT INTO repositories (github_id, name, full_name, html_url, stargazers_count, language, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (github_id) DO NOTHING
            RETURNING id;
        """, (
            repo['id'], repo['name'], repo['full_name'], repo['html_url'], 
            repo['stargazers_count'], repo['language'], repo['created_at']
        ))
        
        repo_db_id = cur.fetchone()
        
        # Nếu repo đã tồn tại, lấy ID của nó
        if not repo_db_id:
            cur.execute("SELECT id FROM repositories WHERE github_id = %s", (repo['id'],))
            repo_db_id = cur.fetchone()
            
        if repo_db_id:
            repo_id = repo_db_id[0]
            
            # 2. Fetch & Insert Releases
            releases = fetch_releases(repo['owner']['login'], repo['name'])
            for rel in releases:
                cur.execute("""
                    INSERT INTO releases (repo_id, release_name, tag_name, published_at, html_url)
                    VALUES (%s, %s, %s, %s, %s)
                """, (repo_id, rel.get('name'), rel.get('tag_name'), rel.get('published_at'), rel.get('html_url')))
            
            # 3. Fetch & Insert Commits
            commits = fetch_commits(repo['owner']['login'], repo['name'])
            for c in commits:
                commit_info = c.get('commit', {})
                author_info = commit_info.get('author', {})
                cur.execute("""
                    INSERT INTO commits (repo_id, sha, message, author_name, date, html_url)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    repo_id, c.get('sha'), commit_info.get('message'), 
                    author_info.get('name'), author_info.get('date'), c.get('html_url')
                ))
                
            conn.commit()
            
    except Exception as e:
        logging.error(f"Error saving repo {repo['full_name']}: {e}")
        print(f"Error saving repo {repo['full_name']}: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def main():
    start_time = time.time()
    
    # Tạo bảng nếu chưa có
    create_tables()
    
    # Lấy danh sách repo (Thử lấy 5000, nhưng API search chỉ cho tối đa 1000 kết quả đầu tiên)
    # Đây là điểm yếu của phiên bản đơn giản này -> Cần cải tiến sau
    repos = fetch_top_repositories(limit=5000)
    
    print(f"Found {len(repos)} repositories. Starting detailed crawl...")
    
    for i, repo in enumerate(repos):
        save_to_db(repo)
        print(f"[{i+1}/{len(repos)}] Saved data for {repo['full_name']}")
        
        # Không sleep để dễ bị chặn (theo yêu cầu)
        # time.sleep(0.5)
    
    end_time = time.time()
    total_time = end_time - start_time
    print(f"\nCrawling completed in {total_time:.2f} seconds ({total_time/60:.2f} minutes)")

if __name__ == "__main__":
    main()
