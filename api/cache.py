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
import functools
import threading
from typing import Any, Callable, Tuple
from api.metrics import log_json


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