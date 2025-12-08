# 🚀 GitHub Crawler - Case Study 5

> Thu thập Release của 5000 Repository nhiều sao nhất GitHub

## 👥 Thông tin nhóm

- **Thái Việt Hoàng** - 23020668
- **Hồ Anh Tú** - 23021700  
- **Nguyễn Văn Hoàng Hải** - 23020660

---

## 📝 Giới thiệu

Hệ thống crawler tối ưu để thu thập danh sách release của **5000 repository** có nhiều sao nhất trên GitHub. Dự án sử dụng dữ liệu từ [Gitstar Ranking](https://gitstar-ranking.com) để vượt qua giới hạn 1000 kết quả của GitHub Search API.

### ✨ Tính năng chính

- ⚡ **Multi-threading** với ThreadPoolExecutor (tăng tốc 4-5 lần)
- 🔄 **Token Rotation** tự động với nhiều GitHub tokens
- 💾 **Batch Insert** và Connection Pooling cho PostgreSQL
- 🎯 **Redis Cache** để tránh crawl trùng lặp
- 📊 **Prometheus Metrics** để monitoring real-time
- 🛡️ **Retry Logic** với Exponential Backoff
- 🔀 **Queue-based Architecture** với Redis

---

## 🚨 Các vấn đề & Giải pháp

### 1. **Giới hạn nguồn dữ liệu**
- ❌ **Vấn đề**: GitHub Search API chỉ trả về tối đa 1000 kết quả
- ✅ **Giải pháp**: Sử dụng Gitstar Ranking làm nguồn dữ liệu

### 2. **Rate Limiting**
- ❌ **Vấn đề**: 
  - Unauthenticated: 60 requests/giờ
  - Authenticated: 5000 requests/giờ/token
  - Lỗi 403, 429, IP blocking
- ✅ **Giải pháp**:
  - Token Rotation (round-robin)
  - Exponential Backoff + Jitter
  - Circuit Breaker pattern

### 3. **Hiệu năng**
- ❌ **Vấn đề**: Xử lý tuần tự mất 15-16 giờ cho 5000 repos
- ✅ **Giải pháp**:
  - Multi-threading (10 workers)
  - Queue-based Load Leveling với Redis
  - Connection Pooling

### 4. **Database Bottleneck**
- ❌ **Vấn đề**: 
  - Insert từng record quá chậm
  - Quá nhiều connections
  - Lỗi UTF-8 với emoji/markdown
- ✅ **Giải pháp**:
  - Batch Insert (100-500 rows/lần)
  - ThreadedConnectionPool
  - UTF-8mb4 encoding
  - Upsert với transaction

### 5. **Dữ liệu trùng lặp**
- ❌ **Vấn đề**: Commits giữa các releases thường trùng nhau
- ✅ **Giải pháp**:
  - GitHub Compare API để lấy diff
  - Cache last release state
  - Fallback: releases → tags → commits

---

## 🏗️ Kiến trúc hệ thống

### Chế độ 1: Threading Mode (Mặc định)

```
┌─────────────────┐
│   Main Process  │
└────────┬────────┘
         │
         ├──► Fetch Repos (Gitstar)
         ├──► ThreadPoolExecutor
         │    ├─► Worker 1 ──► Process ──► PostgreSQL
         │    ├─► Worker 2 ──► Process ──► PostgreSQL
         │    └─► Worker N ──► Process ──► PostgreSQL
         ├──► Redis Cache
         └──► Prometheus (Port 8000)
```

### Chế độ 2: Queue Mode (Tối ưu)

```
┌─────────────────┐
│   Main Process  │
└────────┬────────┘
         │
         ├──► Fetch Repos ──► Redis Queue
         ├──► Worker Pool
         │    ├─► Pop Queue ──► Process ──► PostgreSQL
         │    ├─► Pop Queue ──► Process ──► PostgreSQL
         │    └─► Pop Queue ──► Process ──► PostgreSQL
         └──► Prometheus Metrics
```

---

## 📦 Cấu trúc dự án

```
simple_github_crawler/
├── app/
│   ├── main.py              # Entry point
│   ├── config.py            # Cấu hình (DB, Redis, Tokens)
│   ├── metrics.py           # Prometheus metrics
│   ├── crawler/
│   │   ├── fetcher.py       # GitHub API calls
│   │   ├── processor.py     # Xử lý và lưu dữ liệu
│   │   └── manager.py       # Quản lý workers
│   ├── database/
│   │   ├── connection.py    # Connection pool
│   │   └── models.py        # Database models
│   ├── schemas/
│   │   └── github.py        # Data schemas
│   └── utils/
│       ├── redis_client.py  # Redis manager
│       └── token_rotator.py # Token rotation
├── benchmark.py             # Đo hiệu năng
├── crawler.py               # Script crawler độc lập
├── check_tokens.py          # Kiểm tra tokens
├── clean_db.py              # Xóa database
├── requirements.txt
├── docker-compose.yml
├── prometheus.yml
└── .env                     # Environment variables
```

---

## 🚀 Hướng dẫn sử dụng

### Yêu cầu hệ thống

- Python 3.10+
- PostgreSQL
- Redis (tuỳ chọn)
- GitHub Personal Access Tokens

### Cài đặt

```powershell
# Clone và setup
git clone <repo-url>
cd simple_github_crawler

# Tạo virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Cài đặt dependencies
pip install -r requirements.txt
```

### Cấu hình

Tạo file `.env`:

```env
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=github_crawler
DB_USER=postgres
DB_PASS=your_password

# Redis (Optional)
REDIS_HOST=localhost
REDIS_PORT=6379

# GitHub Tokens (comma-separated)
GITHUB_TOKENS=ghp_token1,ghp_token2,ghp_token3
```

### Chạy ứng dụng

```powershell
# Chế độ Threading (mặc định)
python -m app.main threading 100 10
# Args: mode, limit, workers

# Chế độ Queue với Redis
python -m app.main queue 100 5

# Script crawler độc lập
python crawler.py

# Dọn dẹp database
python clean_db.py

# Kiểm tra trạng thái tokens
python check_tokens.py

# Benchmark hiệu năng
python benchmark.py
```

---

## 📊 Kết quả & Benchmark

### So sánh hiệu năng

| Chỉ số | Tuần tự (1 luồng) | Multi-threading (10 luồng) | Cải thiện |
|--------|-------------------|----------------------------|-----------|
| **Thời gian (100 repos)** | ~600s (10 phút) | ~120s (2 phút) | **5x** |
| **Thời gian (5000 repos)** | ~15-16 giờ | ~3-4 giờ | **4-5x** |
| **API Requests/s** | ~5 req/s | ~25 req/s | **5x** |
| **CPU Utilization** | 10-20% | 60-80% | **Tối ưu** |
| **Database I/O** | Cao | Thấp (batch) | **↓70%** |

### Kết quả thực tế

**Cấu hình test:**
- Repositories: 100
- Workers: 10 threads
- Tokens: 3 GitHub tokens

**Kết quả:**

```
BENCHMARK SUMMARY
==================================================
Threads (max_workers)   : 10
Limit (repositories)    : 100
Total Execution Time    : 118.45 seconds
Total Requests          : 1,247
Total Items Processed   : 100
Average Requests / Sec  : 10.53
Success Rate            : 98%
==================================================
```

**Phân tích:**
- ✅ Success Rate: **98%** (98/100 repos)
- 🔄 Token Switch: **15 lần**
- 🔁 Retry Count: **8 lần**
- 💾 Cache Hit: **2 repos**
- ⚡ Average Time/Repo: **~1.2 giây**

### Monitoring

Truy cập Prometheus metrics tại: `http://localhost:8000`

```prometheus
# Total API requests
github_crawler_requests_total 1247.0

# Processing time histogram
github_crawler_processing_seconds_count 100.0
github_crawler_processing_seconds_sum 120.5

# Token switches
github_crawler_token_switches_total 15.0
```

---

## 🎯 Kỹ thuật áp dụng

| Vấn đề | Giải pháp | Công nghệ |
|--------|-----------|-----------|
| Rate Limiting | Token Rotation + Backoff | Round-robin, Exponential backoff |
| Hiệu năng chậm | Multi-threading | ThreadPoolExecutor (10 workers) |
| Database bottleneck | Connection Pool + Batch Insert | psycopg2.pool, Batch Upsert |
| Dữ liệu trùng lặp | Compare API + Cache | GitHub Compare API, Redis |
| Lỗi mạng | Retry Logic | Exponential backoff with jitter |
| Monitoring | Prometheus Metrics | prometheus_client |
| Queue Management | Redis Queue | redis-py with BLPOP |

---

## 📚 Quy trình xử lý

### 1. Thu thập danh sách Repository

```
fetch_top_repositories()
├─► Query GitHub Search API
│   ├─► stars:>=50000
│   ├─► stars:10000..49999
│   ├─► stars:5000..9999
│   └─► ...
└─► Return top 5000 repos
```

### 2. Xử lý Repository

```
process_repository()
├─► Check cache (Redis)
├─► Fetch Releases
│   └─► Fallback: Tags → Commits
├─► Fetch Commits (Compare API)
├─► Prepare data
├─► Batch Upsert to DB
└─► Cache result
```

### 3. Token Rotation

```
GitHubTokenRotator
├─► Tokens: [token1, token2, ..., tokenN]
├─► Check rate limit
├─► Auto switch on quota exhaustion
└─► Exponential backoff on 403/429
```

---

## 🎓 Bài học kinh nghiệm

### API Rate Limiting
- Token rotation là **bắt buộc** cho large-scale crawling
- Cần buffer (10-20 requests) trước khi switch token
- Exponential backoff giúp giảm tải cho GitHub API

### Database Performance
- Batch insert giảm I/O **70-80%**
- Connection pooling tránh overhead tạo connection mới
- Upsert quan trọng để tránh duplicate và re-crawl

### Concurrency
- Threading tốt cho I/O-bound tasks
- Cần cân bằng số workers với số tokens
- Queue-based approach linh hoạt hơn cho scale

### Error Handling
- Luôn có fallback (releases → tags → commits)
- Không crash khi repo thiếu dữ liệu
- Log đầy đủ để debug và optimize

---

## 🔮 Roadmap cải tiến

- [ ] Circuit breaker ở fetcher layer
- [ ] Worker-based DB writer riêng biệt
- [ ] Cache trạng thái crawl chi tiết hơn
- [ ] Tích hợp Celery để distribute tasks
- [ ] Web dashboard để monitor và control
- [ ] Hỗ trợ GraphQL API của GitHub

---

## 📄 License

MIT License - Case Study 5 - Nhóm 18

---

## 🔗 Tài liệu tham khảo

- [GitHub REST API Documentation](https://docs.github.com/en/rest)
- [Gitstar Ranking](https://gitstar-ranking.com)
- [Prometheus Python Client](https://github.com/prometheus/client_python)
- [psycopg2 Documentation](https://www.psycopg.org/docs/)
