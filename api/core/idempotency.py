import os
from typing import Optional, List, Dict
from datetime import datetime

_memory_seen = {}  # Changed to dict to store timestamps for cleanup
_memory_stats = {"hits": 0, "misses": 0, "marks": 0}

_redis = None
try:
    import redis  # type: ignore

    _redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    if _redis_url:
        _redis = redis.Redis.from_url(_redis_url, decode_responses=True)
        # Test connection
        _redis.ping()
except Exception:
    _redis = None  # 任何 redis 失败都退回内存

_KEY_PREFIX = "idem:x:"
_MEMORY_MAX_SIZE = int(os.getenv("IDEM_MEMORY_MAX_SIZE", "10000"))

def _rkey(key: str) -> str:
    return f"{_KEY_PREFIX}{key}"

def seen(key: str) -> bool:
    """是否已处理过该幂等键。"""
    if _redis:
        try:
            exists = bool(_redis.exists(_rkey(key)))
            _memory_stats["hits" if exists else "misses"] += 1
            return exists
        except Exception:
            pass

    # Fallback to memory
    exists = key in _memory_seen
    _memory_stats["hits" if exists else "misses"] += 1
    return exists

def mark(key: str, ttl_seconds: Optional[int] = 24 * 3600) -> None:
    """标记该幂等键为已处理。默认 24h 过期；无 redis 则进程内常驻。"""
    _memory_stats["marks"] += 1

    if _redis:
        try:
            _redis.set(_rkey(key), "1", ex=ttl_seconds or 0)
            return
        except Exception:
            pass

    # Fallback to memory with timestamp for cleanup
    _memory_seen[key] = datetime.now()

    # Auto cleanup if memory grows too large
    if len(_memory_seen) > _MEMORY_MAX_SIZE:
        cleanup_memory(_MEMORY_MAX_SIZE)

def seen_batch(keys: List[str]) -> Dict[str, bool]:
    """批量检查多个键"""
    if _redis:
        try:
            pipeline = _redis.pipeline()
            for key in keys:
                pipeline.exists(_rkey(key))
            results = pipeline.execute()

            result_dict = dict(zip(keys, results))
            # Update stats
            for exists in results:
                _memory_stats["hits" if exists else "misses"] += 1
            return result_dict
        except Exception:
            pass

    # Fallback to memory
    result_dict = {key: key in _memory_seen for key in keys}
    for exists in result_dict.values():
        _memory_stats["hits" if exists else "misses"] += 1
    return result_dict

def mark_batch(keys: List[str], ttl_seconds: Optional[int] = 24 * 3600) -> None:
    """批量标记多个键为已处理"""
    _memory_stats["marks"] += len(keys)

    if _redis:
        try:
            pipeline = _redis.pipeline()
            for key in keys:
                pipeline.set(_rkey(key), "1", ex=ttl_seconds or 0)
            pipeline.execute()
            return
        except Exception:
            pass

    # Fallback to memory
    now = datetime.now()
    for key in keys:
        _memory_seen[key] = now

    # Auto cleanup if memory grows too large
    if len(_memory_seen) > _MEMORY_MAX_SIZE:
        cleanup_memory(_MEMORY_MAX_SIZE)

def cleanup_memory(max_size: int = None) -> int:
    """防止内存无限增长，保留最近使用的键"""
    global _memory_seen

    if max_size is None:
        max_size = _MEMORY_MAX_SIZE

    if len(_memory_seen) <= max_size:
        return 0

    # Sort by timestamp and keep the most recent
    sorted_items = sorted(_memory_seen.items(), key=lambda x: x[1], reverse=True)
    keep_size = max_size // 2  # Keep half of max size
    _memory_seen = dict(sorted_items[:keep_size])

    removed = len(sorted_items) - keep_size
    return removed

def stats() -> Dict[str, any]:
    """返回统计信息"""
    result = {
        "backend": "redis" if _redis else "memory",
        "hits": _memory_stats["hits"],
        "misses": _memory_stats["misses"],
        "marks": _memory_stats["marks"],
        "hit_rate": (_memory_stats["hits"] / max(_memory_stats["hits"] + _memory_stats["misses"], 1)) * 100
    }

    if _redis:
        try:
            # For stats, just check if Redis is working
            # (Avoid expensive KEYS/SCAN operations in production)
            _redis.ping()
            result["redis_available"] = True
        except Exception:
            result["redis_available"] = False
    else:
        result["memory_keys"] = len(_memory_seen)
        result["memory_max_size"] = _MEMORY_MAX_SIZE

    return result

def clear_all() -> int:
    """清除所有幂等键（仅用于测试或维护）"""
    count = 0

    if _redis:
        try:
            # Use KEYS for simplicity in test/maintenance scenarios
            # (SCAN is better for production but more complex)
            keys = _redis.keys(f"{_KEY_PREFIX}*")
            if keys:
                count = _redis.delete(*keys)
            return count
        except Exception as e:
            # Log but don't fail
            pass

    # Clear memory
    count = len(_memory_seen)
    _memory_seen.clear()
    return count

def reset_stats() -> None:
    """重置统计计数器"""
    global _memory_stats
    _memory_stats = {"hits": 0, "misses": 0, "marks": 0}