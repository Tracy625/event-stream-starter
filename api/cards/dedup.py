"""Card deduplication and recheck queue management"""
import os
import json
import redis
from typing import Optional

def log_json(stage: str, **kwargs):
    """Structured JSON logging"""
    log_entry = {"stage": stage, **kwargs}
    print(f"[JSON] {json.dumps(log_entry)}")

def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client from environment"""
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        return redis.from_url(redis_url, decode_responses=True)
    except Exception as e:
        log_json(stage="card.redis.error", error=str(e))
        return None

def should_send(event_key: str, ttl_s: int = 1800) -> bool:
    """
    Check if card should be sent (deduplication)
    
    Args:
        event_key: Unique event identifier
        ttl_s: TTL in seconds for dedup window (default 30 min)
        
    Returns:
        True if should send (first time), False if duplicate
    """
    try:
        r = get_redis_client()
        if not r:
            # Redis unavailable, allow send (no dedup)
            log_json(stage="card.dedup.bypass", event_key=event_key)
            return True
            
        key = f"card:sent:{event_key}"
        
        # Try to set with NX (only if not exists)
        result = r.set(key, "1", nx=True, ex=ttl_s)
        
        if result:
            # First time, should send
            log_json(stage="card.dedup.miss", event_key=event_key)
            return True
        else:
            # Already sent within TTL window
            log_json(stage="card.dedup.hit", event_key=event_key)
            return False
            
    except Exception as e:
        log_json(
            stage="card.redis.error",
            operation="dedup",
            error=str(e),
            event_key=event_key
        )
        # On error, allow send (no dedup)
        return True

def add_to_recheck(event_key: str, priority: int) -> None:
    """
    Add event to recheck queue
    
    Args:
        event_key: Event identifier to recheck
        priority: Priority score (lower = higher priority)
    """
    try:
        r = get_redis_client()
        if not r:
            # Redis unavailable, skip recheck queue
            log_json(stage="card.recheck.bypass", event_key=event_key)
            return
            
        # Add to sorted set with priority as score
        r.zadd("recheck:hot", {event_key: priority})
        
        log_json(
            stage="card.recheck.add",
            event_key=event_key,
            priority=priority
        )
        
    except Exception as e:
        log_json(
            stage="card.redis.error",
            operation="recheck",
            error=str(e),
            event_key=event_key
        )
        # Silently fail, don't interrupt flow