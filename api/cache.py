"""
Cache module with TTL-based memoization.

Provides:
- memoize_ttl: Decorator to cache function results with time-to-live expiration

Usage:
    @memoize_ttl(seconds=300)
    def expensive_analysis(text: str) -> dict:
        # Heavy computation here
        return {"result": text.upper()}
    
    # First call computes
    result1 = expensive_analysis("hello")
    
    # Second call returns cached value within TTL
    result2 = expensive_analysis("hello")
"""

import time
import threading
import os
import functools
from typing import Any, Callable, Optional, Tuple

from api.metrics import log_json

try:
    import redis  # type: ignore
except Exception:  # 本地没装也别炸
    redis = None  # type: ignore

_redis_client = None


def get_redis_client():
    """Get Redis client singleton"""
    global _redis_client
    if _redis_client is None and redis is not None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            _redis_client = redis.from_url(redis_url, decode_responses=False)
        except Exception as e:
            log_json(stage="redis.connect.error", error=str(e))
    return _redis_client


def _make_cache_key(func_name: str, args: Tuple, kwargs: dict) -> str:
    """
    Create a cache key from function name, args, and kwargs.
    
    Args:
        func_name: Name of the function
        args: Positional arguments
        kwargs: Keyword arguments
    
    Returns:
        String representation of the cache key
    """
    # Convert kwargs to sorted tuple for consistent hashing
    kwargs_items = tuple(sorted(kwargs.items())) if kwargs else ()
    
    # Create key from function name and arguments
    key_parts = [func_name]
    
    # Add args
    if args:
        key_parts.append(str(args))
    
    # Add kwargs if present
    if kwargs_items:
        key_parts.append(str(kwargs_items))
    
    return "|".join(key_parts)


def memoize_ttl(seconds: int) -> Callable:
    """
    Decorator to cache function results with TTL expiration.
    
    Args:
        seconds: Time-to-live in seconds for cached values
    
    Caches function results in memory with automatic expiration.
    Thread-safe implementation using locks.
    
    Example:
        @memoize_ttl(seconds=60)
        def analyze_sentiment(text: str) -> tuple:
            # Expensive computation
            return ("positive", 0.8)
    """
    def decorator(func: Callable) -> Callable:
        # Cache storage: key -> (value, expiry_time)
        cache = {}
        # Thread safety lock
        lock = threading.Lock()
        
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Generate cache key
            cache_key = _make_cache_key(func.__name__, args, kwargs)
            
            # Get current time
            current_time = time.time()
            
            # Check cache with lock
            with lock:
                if cache_key in cache:
                    cached_value, expiry_time = cache[cache_key]
                    
                    # Check if still valid
                    if current_time < expiry_time:
                        # Cache hit
                        log_json(
                            stage="cache",
                            hit=True,
                            key=str(args),
                            func=func.__name__
                        )
                        return cached_value
                    else:
                        # Expired, will recompute
                        log_json(
                            stage="cache",
                            hit=False,
                            key=str(args),
                            func=func.__name__,
                            reason="expired"
                        )
                else:
                    # Cache miss
                    log_json(
                        stage="cache",
                        hit=False,
                        key=str(args),
                        func=func.__name__,
                        reason="miss"
                    )
            
            # Compute new value
            result = func(*args, **kwargs)
            
            # Store in cache with new expiry time
            with lock:
                expiry_time = current_time + seconds
                cache[cache_key] = (result, expiry_time)
            
            return result
        
        # Add cache management methods
        def clear_cache():
            """Clear all cached values."""
            with lock:
                cache.clear()
        
        def cache_info():
            """Get cache statistics."""
            with lock:
                return {
                    "size": len(cache),
                    "keys": list(cache.keys())
                }
        
        # Attach utility methods to wrapper
        wrapper.clear_cache = clear_cache
        wrapper.cache_info = cache_info
        
        return wrapper
    
    return decorator

# --- compatibility shims for Day9.1 ---


def get_redis_client() -> Optional["redis.Redis"]:
    """
    Return a Redis client if available, else None.
    Env: REDIS_URL or REDIS_HOST/REDIS_PORT/REDIS_DB
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if redis is None:
        return None
    url = os.getenv("REDIS_URL")
    if url:
        _redis_client = redis.from_url(url, decode_responses=True)
        return _redis_client
    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))
    _redis_client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
    return _redis_client

def memoize_ttl(ttl_seconds: int):
    """
    Simple Redis-backed memoize. If Redis missing, it’s a no-op.
    Only cache simple repr-able results.
    """
    def decorator(func: Callable):
        rc = get_redis_client()
        if rc is None:
            return func

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = f"memo:{func.__module__}.{func.__name__}:{repr(args)}:{repr(sorted(kwargs.items()))}"
            val = rc.get(key)
            if val is not None:
                try:
                    return eval(val)
                except Exception:
                    pass
            result = func(*args, **kwargs)
            try:
                rc.setex(key, ttl_seconds, repr(result))
            except Exception:
                pass
            return result
        return wrapper
    return decorator