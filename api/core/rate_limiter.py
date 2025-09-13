"""Minimal rate limiter for Telegram API calls with Redis 1s window"""
import os
import time
from typing import Optional
from api.cache import get_redis_client


def allow_or_wait(channel_id: Optional[int], max_wait_ms: int = 1000) -> bool:
    """
    Check if request is allowed under rate limit or wait briefly.
    
    Args:
        channel_id: Optional channel ID for per-channel limiting
        max_wait_ms: Maximum wait time in milliseconds
        
    Returns:
        True if request allowed, False if rate limited after waiting
    """
    # Get rate limit from environment
    limit = int(os.getenv("TG_RATE_LIMIT", "20"))
    
    # Get Redis client
    redis = get_redis_client()
    
    # If Redis unavailable, gracefully degrade with small sleep
    if redis is None:
        time.sleep(0.02)  # 20ms sleep
        return True
    
    # Prepare keys
    global_key = "rate:tg:global"
    channel_key = f"rate:tg:channel:{channel_id}" if channel_id else None
    
    try:
        # Increment both counters
        global_count = redis.incr(global_key)
        if global_count == 1:
            redis.expire(global_key, 1)
        
        channel_count = 0
        if channel_key:
            channel_count = redis.incr(channel_key)
            if channel_count == 1:
                redis.expire(channel_key, 1)
        
        # Get max count
        current_count = max(global_count, channel_count)
        
        # If within limit, allow immediately
        if current_count <= limit:
            return True
        
        # Over limit - spin wait up to max_wait_ms
        start_time = time.time()
        wait_seconds = max_wait_ms / 1000.0
        
        while (time.time() - start_time) < wait_seconds:
            # Wait 50ms
            time.sleep(0.05)
            
            # Re-check counts (don't increment, just get)
            global_count = redis.get(global_key)
            global_count = int(global_count) if global_count else 0
            
            channel_count = 0
            if channel_key:
                channel_count = redis.get(channel_key)
                channel_count = int(channel_count) if channel_count else 0
            
            current_count = max(global_count, channel_count)
            
            # If window reset or under limit now, allow
            if current_count <= limit:
                # Re-increment since we'll be sending
                redis.incr(global_key)
                if channel_key:
                    redis.incr(channel_key)
                return True
        
        # Still over limit after waiting
        return False
        
    except Exception:
        # On any Redis error, gracefully degrade
        time.sleep(0.02)
        return True