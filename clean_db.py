import logging
from app.database.connection import DatabaseConnectionPool
from app.utils.redis_client import RedisManager

# Cấu hình logging cơ bản để thấy thông báo lỗi nếu có
logging.basicConfig(level=logging.INFO)


def clean_database():
    """
    Xóa sạch dữ liệu trong các bảng repositories, releases, commits
    VÀ xóa cache Redis để chuẩn bị cho benchmark mới.
    """
    print("Starting system cleanup (DB + Redis)...")

    # 1. Clean Redis
    try:
        print("Flushing Redis cache...")
        redis_manager = RedisManager()
        redis_manager.redis_client.flushdb()
        print("Successfully flushed Redis database.")
    except Exception as e:
        print(f"Error cleaning Redis: {e}")

    # 2. Clean PostgreSQL
    # Khởi tạo connection pool (chỉ cần 1 kết nối là đủ để clean)
    DatabaseConnectionPool.initialize(minconn=1, maxconn=1)

    try:
        with DatabaseConnectionPool.get_connection() as conn:
            with conn.cursor() as cursor:
                # Sử dụng TRUNCATE với CASCADE để xóa dữ liệu bảng cha và tất cả bảng con liên quan
                # Điều này nhanh hơn DELETE và tự động xử lý khóa ngoại
                print("Truncating PostgreSQL tables...")
                cursor.execute("TRUNCATE TABLE repositories RESTART IDENTITY CASCADE;")
                conn.commit()
                print(
                    "Successfully cleaned all data from 'repositories' and related tables."
                )

    except Exception as e:
        print(f"Error cleaning database: {e}")
    finally:
        # Đóng pool kết nối (nếu cần thiết, dù script sắp kết thúc)
        if DatabaseConnectionPool._pool:
            DatabaseConnectionPool._pool.closeall()
            print("Connection pool closed.")


if __name__ == "__main__":
    clean_database()
