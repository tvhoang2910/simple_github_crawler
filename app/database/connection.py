import logging
import psycopg2
import psycopg2.pool
from contextlib import contextmanager
from typing import Optional
from urllib.parse import quote_plus
from tortoise import Tortoise

from app.config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT

# ============================================================================
# SYNC CONNECTION POOLING (psycopg2)
# ============================================================================

class DatabaseConnectionPool:
    """Database connection pool manager."""
    
    _pool = None
    
    @classmethod
    def initialize(cls, minconn=5, maxconn=20):
        """Initialize the connection pool."""
        if cls._pool is None:
            try:
                cls._pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn,
                    maxconn,
                    host=DB_HOST,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASS,
                    port=DB_PORT
                )
                logging.info(f"Connection pool initialized with {minconn}-{maxconn} connections")
            except Exception as e:
                logging.error(f"Failed to initialize connection pool: {e}")
                raise
    
    @classmethod
    @contextmanager
    def get_connection(cls):
        """Get a connection from the pool (context manager)."""
        if cls._pool is None:
            cls.initialize()
        
        conn = cls._pool.getconn()
        try:
            yield conn
        finally:
            cls._pool.putconn(conn)
    
    @classmethod
    def close_all(cls):
        """Close all connections in the pool."""
        if cls._pool is not None:
            cls._pool.closeall()
            cls._pool = None
            logging.info("Connection pool closed")

def create_tables_sync():
    """
    Create database tables for repositories, releases, and commits if they don't exist.
    """
    with DatabaseConnectionPool.get_connection() as conn:
        with conn.cursor() as cur:
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
    print("Tables created successfully (sync).")


# ============================================================================
# ASYNC CONNECTION (Tortoise ORM)
# ============================================================================

class ServiceFactory:
    _initialized: bool = False

    @staticmethod
    def _build_db_url(
        min_size: int = 1,
        max_size: int = 10,
        ssl: Optional[str] = None,
    ) -> str:
        user = quote_plus(DB_USER)
        pwd = quote_plus(DB_PASS or "")
        host = DB_HOST
        port = DB_PORT
        db = DB_NAME
        params = [f"min_size={min_size}", f"max_size={max_size}"]
        if ssl:
            params.append(f"ssl={ssl}")
        query = "&".join(params)
        return f"postgres://{user}:{pwd}@{host}:{port}/{db}?{query}"

    @staticmethod
    async def init_orm(
        models_modules: Optional[list[str]] = None,
        generate_schemas: bool = True
    ) -> None:
        """
        Initialize Tortoise ORM with database connection and models.
        """
        if ServiceFactory._initialized:
            return

        db_url = ServiceFactory._build_db_url(min_size=5, max_size=20)
        # Update module path to new location
        modules = {"models": models_modules or ["app.database.models"]}

        await Tortoise.init(
            db_url=db_url,
            modules=modules,
            timezone="UTC"
        )
        
        if generate_schemas:
            await Tortoise.generate_schemas(safe=True)
            
        ServiceFactory._initialized = True

    @staticmethod
    async def get_db():
        if not ServiceFactory._initialized:
            await ServiceFactory.init_orm()
        return Tortoise.get_connection("default")

    @staticmethod
    async def shutdown() -> None:
        if ServiceFactory._initialized:
            await Tortoise.close_connections()
            ServiceFactory._initialized = False
