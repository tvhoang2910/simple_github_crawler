import redis
import json
import logging
from typing import Dict, Any, Optional
from app.config import REDIS_HOST, REDIS_PORT

class RedisManager:
    """Manages Redis operations for caching and queueing."""
    
    def __init__(self, host: str = REDIS_HOST, port: int = int(REDIS_PORT)):
        self.redis_client = redis.Redis(
            host=host,
            port=port,
            decode_responses=True,
            socket_connect_timeout=5
        )
        self.queue_name = "github_crawler:queue"
        self.cache_prefix = "github_crawler:cache:"
    
    def push_to_queue(self, repo_data: Dict[str, Any]):
        """Push repository data to processing queue."""
        try:
            self.redis_client.rpush(self.queue_name, json.dumps(repo_data))
        except Exception as e:
            logging.error(f"Failed to push to queue: {e}")
    
    def pop_from_queue(self, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """Pop repository data from processing queue."""
        try:
            result = self.redis_client.blpop(self.queue_name, timeout=timeout)
            if result:
                _, data = result
                return json.loads(data)
        except Exception as e:
            logging.error(f"Failed to pop from queue: {e}")
        return None
    
    def get_queue_size(self) -> int:
        """Get current queue size."""
        try:
            return self.redis_client.llen(self.queue_name)
        except Exception as e:
            logging.error(f"Failed to get queue size: {e}")
            return 0
    
    def cache_last_release(self, repo_full_name: str, tag_name: str):
        """Cache the last crawled release for a repository."""
        try:
            key = f"{self.cache_prefix}last_release:{repo_full_name}"
            self.redis_client.set(key, tag_name, ex=86400 * 7)  # 7 days TTL
        except Exception as e:
            logging.error(f"Failed to cache last release: {e}")
    
    def get_last_release(self, repo_full_name: str) -> Optional[str]:
        """Get the last crawled release for a repository."""
        try:
            key = f"{self.cache_prefix}last_release:{repo_full_name}"
            return self.redis_client.get(key)
        except Exception as e:
            logging.error(f"Failed to get last release: {e}")
            return None
    
    def cache_repo_processed(self, repo_full_name: str):
        """Mark repository as processed."""
        try:
            key = f"{self.cache_prefix}processed:{repo_full_name}"
            self.redis_client.set(key, "1", ex=86400)  # 1 day TTL
        except Exception as e:
            logging.error(f"Failed to cache processed repo: {e}")
    
    def is_repo_processed(self, repo_full_name: str) -> bool:
        """Check if repository was recently processed."""
        try:
            key = f"{self.cache_prefix}processed:{repo_full_name}"
            return bool(self.redis_client.exists(key))
        except Exception as e:
            logging.error(f"Failed to check processed status: {e}")
            return False
