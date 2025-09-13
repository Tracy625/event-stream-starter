"""Redis cache key templates and TTL definitions (Day20+21)"""
from datetime import datetime
from typing import Optional
from hashlib import sha1


# TTL definitions
RATE_LIMIT_TTL = 2  # seconds
DEDUP_TTL = 5400  # 1.5 hours in seconds


def dedup_key(event_key: str, dt: datetime) -> str:
    """
    Generate deduplication key for cards sent tracking
    
    Args:
        event_key: Event identifier
        dt: Datetime for bucketing
    
    Returns:
        Redis key string like 'cards:sent:EVENT_KEY:2025091210'
    """
    bucket = dt.strftime("%Y%m%d%H")
    return f"cards:sent:{event_key}:{bucket}"


def rate_key_global() -> str:
    """
    Generate global rate limit key
    
    Returns:
        Redis key string 'rate:tg:global'
    """
    return "rate:tg:global"


def rate_key_channel(channel_id: int | str) -> str:
    """
    Generate per-channel rate limit key
    
    Args:
        channel_id: Telegram channel ID
    
    Returns:
        Redis key string like 'rate:tg:CHANNEL_ID'
    """
    return f"rate:tg:channel:{channel_id}"


def idemp_key(event_key: str, channel_id: int | str, template_v: str) -> str:
    """
    Build idempotency key: cards:idemp:{sha1(f"{event_key}|{channel_id}|{template_v}")}
    """
    raw = f"{event_key}|{channel_id}|{template_v}".encode("utf-8")
    return f"cards:idemp:{sha1(raw).hexdigest()}"