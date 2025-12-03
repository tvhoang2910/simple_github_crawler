# Cấu hình kết nối PostgreSQL
DB_HOST = "localhost"
DB_NAME = "github_crawler"
DB_USER = "postgres"
DB_PASS = "27092005"
DB_PORT = "5432"

# GitHub API Token (Để trống nếu muốn chạy với giới hạn rate limit thấp - dễ bị chặn/limit)
# Nếu có token, rate limit sẽ cao hơn (5000 req/hour)
GITHUB_TOKEN = ""
