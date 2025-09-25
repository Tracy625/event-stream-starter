"""Beat heartbeat task and helpers."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from api.cache import get_redis_client
from api.core import metrics

def _heartbeat_key() -> str:
    return os.getenv("BEAT_HEARTBEAT_KEY", "beat:last_heartbeat")


def heartbeat() -> Dict[str, Any]:
    """Record a beat heartbeat and persist the timestamp."""
    counter = metrics.counter("beat_heartbeat", "Celery beat heartbeat count")
    counter.inc()

    now = datetime.now(timezone.utc)
    timestamp = now.timestamp()

    redis = get_redis_client()
    key = _heartbeat_key()
    if redis is not None:
        redis.set(key, str(timestamp))
    else:
        # Fallback：记录在 metrics 中，便于调试
        gauge = metrics.gauge("beat_heartbeat_timestamp", "Last beat heartbeat timestamp")
        gauge.set(timestamp)

    return {"timestamp": timestamp}


def get_last_heartbeat(default: float | None = None) -> float | None:
    """Fetch the last heartbeat timestamp from Redis (or return default)."""
    redis = get_redis_client()
    key = _heartbeat_key()
    if redis is None:
        gauge = metrics.gauge("beat_heartbeat_timestamp", "Last beat heartbeat timestamp")
        stored = gauge.values.get("", None)
        return float(stored) if stored is not None else default

    value = redis.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
