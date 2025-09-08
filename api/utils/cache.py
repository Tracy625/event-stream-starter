"""Redis cache utilities for onchain data."""
import os
import json
import random
import redis
from typing import Optional, Any
from api.utils.logging import log_json


class RedisCache:
    """Simple Redis cache helper."""
    
    def __init__(self):
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            self.client = redis.from_url(redis_url, decode_responses=True)
            self.enabled = True
        except Exception as e:
            log_json(stage="cache.init", error=str(e), redis_disabled=True)
            self.client = None
            self.enabled = False
    
    def get_json(self, key: str) -> Optional[Any]:
        """
        Get JSON value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if miss
        """
        if not self.enabled:
            return None
            
        try:
            value = self.client.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            log_json(stage="cache.get", error=str(e), key=key)
        return None
    
    def set_json(self, key: str, value: Any, ttl_s: Optional[int] = None):
        """
        Set JSON value in cache with TTL.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_s: TTL in seconds (random 60-120 if not specified)
        """
        if not self.enabled:
            return
            
        if ttl_s is None:
            ttl_s = random.randint(60, 120)
        try:
            self.client.setex(key, ttl_s, json.dumps(value))
        except Exception as e:
            log_json(stage="cache.set", error=str(e), key=key)