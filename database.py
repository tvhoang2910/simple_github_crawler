import psycopg2
from psycopg2 import pool
from config import DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT
from contextlib import contextmanager

# Global connection pool
db_pool = None

def init_db_pool(minconn=1, maxconn=10):
    global db_pool
    if db_pool is None:
        try:
            db_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn,
                maxconn,
                host=DB_HOST,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                port=DB_PORT
            )
            print("Database connection pool created successfully.")
        except (Exception, psycopg2.DatabaseError) as error:
            print("Error while connecting to PostgreSQL", error)

def close_db_pool():
    global db_pool
    if db_pool:
        db_pool.closeall()
        print("Database connection pool closed.")

@contextmanager
def get_db_connection():
    """
    Context manager to get a connection from the pool and return it automatically.
    Usage:
        with get_db_connection() as conn:
            cur = conn.cursor()
            ...
    """
    global db_pool
    if db_pool is None:
        # Fallback if pool is not initialized (e.g. running database.py directly)
        conn = psycopg2.connect(
            host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
        )
        try:
            yield conn
        finally:
            conn.close()
    else:
        conn = db_pool.getconn()
        try:
            yield conn
        finally:
            db_pool.putconn(conn)

def get_connection():
    """Deprecated: Use get_db_connection context manager instead"""
    global db_pool
    if db_pool:
        return db_pool.getconn()
    else:
        return psycopg2.connect(
            host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
        )

def release_connection(conn):
    """Deprecated: Use get_db_connection context manager instead"""
    global db_pool
    if db_pool:
        db_pool.putconn(conn)
    else:
        conn.close()

def create_tables():
    # Use a direct connection or pool for setup
    with get_db_connection() as conn:
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
    print("Tables created successfully.")


if __name__ == "__main__":
    create_tables()
