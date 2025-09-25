"""
X Avatar polling job - monitors KOL avatar changes.
"""

import os
import sys
import json
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# Add API path for imports
sys.path.append('/app')

from api.core.metrics_store import log_json
from api.clients.x_client import get_x_client
import redis
import yaml


def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client from environment."""
    try:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        return redis.from_url(redis_url, decode_responses=True)
    except Exception as e:
        log_json(stage="x.avatar.error", error=f"Redis connection failed: {e}")
        return None


def load_kol_handles() -> List[str]:
    """Load KOL handles from config file or environment."""
    handles = []
    
    # Try config file first
    config_path = "/app/configs/x_kol.yaml"
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f) or {}
                kol_list = config.get("kol", [])
                handles = [item["handle"] for item in kol_list if "handle" in item]
                if handles:
                    log_json(stage="x.avatar.info", source="config", count=len(handles))
                    return handles
        except Exception as e:
            log_json(stage="x.avatar.error", error=f"Config parse failed: {e}")
    
    # Fallback to environment variable
    env_handles = os.getenv("X_KOL_HANDLES", "").strip()
    if env_handles:
        handles = [h.strip() for h in env_handles.split(",") if h.strip()]
        log_json(stage="x.avatar.info", source="env", count=len(handles))
    else:
        log_json(stage="x.avatar.error", error="No KOL handles found")
    
    return handles


def process_handle(r: redis.Redis, client: Any, handle: str) -> bool:
    """Process a single handle, return True if changed."""
    # Redis keys (TTL=14d) per spec
    last_hash_key      = f"x:avatar:{handle}:last_hash"
    last_seen_ts_key   = f"x:avatar:{handle}:last_seen_ts"
    last_change_ts_key = f"x:avatar:{handle}:last_change_ts"
    
    log_json(stage="x.avatar.request", handle=handle)
    
    # Fetch profile
    profile = client.fetch_user_profile(handle)
    if not profile or not profile.get("avatar_url"):
        log_json(stage="x.avatar.skip", handle=handle, reason="empty")
        return False
    
    # compute current hash
    cur_url = profile["avatar_url"]
    cur_hash = hashlib.sha1(cur_url.encode()).hexdigest()
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
    
    log_json(stage="x.avatar.success", handle=handle, avatar_url=cur_url)
    
    # Check for changes
    old_hash = r.get(last_hash_key)
    if not old_hash:
        r.setex(last_hash_key, 14*24*3600, cur_hash)
        r.setex(last_seen_ts_key, 14*24*3600, now_iso)
        r.setex(last_change_ts_key, 14*24*3600, now_iso)
        log_json(stage="x.avatar.success", handle=handle, first_seen=True, hash=cur_hash)
        return False
    
    if old_hash != cur_hash:
        r.setex(last_hash_key, 14*24*3600, cur_hash)
        r.setex(last_seen_ts_key, 14*24*3600, now_iso)
        r.setex(last_change_ts_key, 14*24*3600, now_iso)
        log_json(stage="x.avatar.change", handle=handle, old=old_hash, new=cur_hash)
        return True
    
    # no change
    r.setex(last_seen_ts_key, 14*24*3600, now_iso)
    log_json(stage="x.avatar.success", handle=handle, first_seen=False, hash=cur_hash)
    return False


def run_once() -> Dict[str, Any]:
    """Run one iteration of avatar polling."""
    stats = {"checked": 0, "changed": 0, "errors": 0}
    
    # Check if monitoring is enabled
    if os.getenv("X_ENABLE_AVATAR_MONITOR", "false").lower() == "false":
        log_json(stage="x.avatar.error", error="Monitoring disabled via X_ENABLE_AVATAR_MONITOR=false")
        return stats
    
    # Get Redis client
    r = get_redis_client()
    if not r:
        log_json(stage="x.avatar.error", error="Redis unavailable")
        stats["errors"] = 1
        return stats
    
    # Load KOL handles
    handles = load_kol_handles()
    if not handles:
        log_json(stage="x.avatar.error", error="No KOL handles found")
        stats["errors"] = 1
        return stats
    
    # Get X client
    backend = os.getenv("X_BACKEND", "graphql")
    try:
        client = get_x_client(backend)
    except Exception as e:
        log_json(stage="x.avatar.error", error=f"Client init failed: {e}")
        stats["errors"] = 1
        return stats
    
    # Poll each handle
    for h in handles:
        try:
            changed = process_handle(r, client, h)
            stats["checked"] += 1
            if changed:
                stats["changed"] += 1
        except Exception as e:
            log_json(stage="x.avatar.error", handle=h, error=str(e))
            stats["errors"] += 1
    
    log_json(stage="x.avatar.stats", **stats)
    return stats


if __name__ == "__main__":
    result = run_once()
    print(json.dumps(result))