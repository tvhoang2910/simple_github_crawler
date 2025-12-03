import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT

def get_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )
    return conn

def create_tables():
    conn = get_connection()
    cur = conn.cursor()
    
    # Bảng lưu thông tin Repository
    cur.execute("""
        CREATE TABLE IF NOT EXISTS repositories (
            id SERIAL PRIMARY KEY,
            github_id BIGINT UNIQUE,
            name VARCHAR(255),
            full_name VARCHAR(255),
            html_url VARCHAR(500),
            stargazers_count INT,
            language VARCHAR(100),
            created_at TIMESTAMP
        );
    """)
    
    # Bảng lưu thông tin Releases
    cur.execute("""
        CREATE TABLE IF NOT EXISTS releases (
            id SERIAL PRIMARY KEY,
            repo_id INT REFERENCES repositories(id),
            release_name VARCHAR(255),
            tag_name VARCHAR(100),
            published_at TIMESTAMP,
            html_url VARCHAR(500)
        );
    """)
    
    # Bảng lưu thông tin Commits
    cur.execute("""
        CREATE TABLE IF NOT EXISTS commits (
            id SERIAL PRIMARY KEY,
            repo_id INT REFERENCES repositories(id),
            sha VARCHAR(40),
            message TEXT,
            author_name VARCHAR(255),
            date TIMESTAMP,
            html_url VARCHAR(500)
        );
    """)
    
    conn.commit()
    cur.close()
    conn.close()
    print("Tables created successfully.")

if __name__ == "__main__":
    create_tables()
