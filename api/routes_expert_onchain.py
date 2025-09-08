#!/usr/bin/env python
"""
CARD D — Expert onchain view endpoint
Internal-only endpoint for chain+address onchain features
"""

import os
import re
import json
import random
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Any, Tuple

from fastapi import APIRouter, HTTPException, Header, Depends, Request
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
import redis

from api.database import get_db
from api.utils.cache import RedisCache
from api.utils.logging import log_json


router = APIRouter(prefix="/expert", tags=["expert"])

# Redis client (lazy init)
_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """Get or create Redis client."""
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def quantize_decimal(value: Optional[float], places: int = 3) -> Optional[float]:
    """Quantize decimal to specified places with proper rounding."""
    if value is None:
        return None
    quantized = Decimal(str(value)).quantize(
        Decimal(10) ** -places, 
        rounding=ROUND_HALF_UP
    )
    return float(quantized)


def clamp_ratio(value: Optional[float]) -> Optional[float]:
    """Clamp ratio to [0, 1] range and quantize to 3 decimal places."""
    if value is None:
        return None
    clamped = max(0.0, min(1.0, float(value)))
    return quantize_decimal(clamped, 3)


def format_timestamp(dt: Optional[datetime]) -> Optional[str]:
    """Format datetime to UTC ISO8601 with Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def check_rate_limit(key: str) -> bool:
    """
    Check rate limit for given key.
    Returns True if rate limited (should block), False if allowed.
    """
    try:
        r = get_redis()
        limit = int(os.getenv("EXPERT_RATE_LIMIT_PER_MIN", "5"))
        
        # Create rate limit key with minute precision
        now = datetime.now(timezone.utc)
        minute_key = now.strftime("%Y%m%d%H%M")
        rl_key = f"rl:expert:{key}:{minute_key}"
        
        # Increment counter
        count = r.incr(rl_key)
        if count == 1:
            # First request in this minute, set expiry
            r.expire(rl_key, 60)
        
        return count > limit
        
    except Exception as e:
        log_json(stage="expert.rate_limit", error=str(e))
        # On Redis failure, allow request (fail open)
        return False


def get_cache(cache_key: str) -> Tuple[Optional[Dict], int]:
    """
    Get cached value and remaining TTL.
    Returns (cached_data, ttl_seconds).
    """
    try:
        r = get_redis()
        cached = r.get(cache_key)
        
        if cached:
            ttl = r.ttl(cache_key)
            ttl = max(0, ttl) if ttl else 0
            return json.loads(cached), ttl
        
        return None, 0
        
    except Exception as e:
        log_json(stage="expert.cache_get", error=str(e))
        return None, 0


def set_cache(cache_key: str, data: Dict, ttl_base: int) -> None:
    """Set cache with TTL and jitter."""
    try:
        r = get_redis()
        # Add 10% jitter to TTL
        jitter = random.uniform(-0.1, 0.1)
        ttl = int(ttl_base * (1 + jitter))
        ttl = max(60, ttl)  # Minimum 60 seconds
        
        r.setex(cache_key, ttl, json.dumps(data))
        
    except Exception as e:
        log_json(stage="expert.cache_set", error=str(e))


def fetch_series_pg(
    chain: str, 
    address: str, 
    db: Session
) -> Dict[str, Any]:
    """
    Fetch onchain features from PostgreSQL.
    
    Returns:
        Dict with series data and metadata
    """
    # Query for last 7 days, windows 30 and 60 only
    sql = sa_text("""
        SELECT 
            as_of_ts,
            window_minutes,
            addr_active,
            growth_ratio,
            top10_share,
            self_loop_ratio
        FROM onchain_features
        WHERE chain = :chain
          AND address = :address
          AND window_minutes IN (30, 60)
          AND as_of_ts >= NOW() - INTERVAL '7 days'
        ORDER BY as_of_ts ASC
    """)
    
    rows = db.execute(sql, {
        "chain": chain,
        "address": address
    }).fetchall()
    
    # Process rows into series
    now = datetime.now(timezone.utc)
    h24_cutoff = now - timedelta(hours=24)
    
    series = {
        "h24": {"w30": [], "w60": []},
        "d7": {"w30": [], "w60": []}
    }
    
    latest_top10 = None
    max_as_of_ts = None
    
    for row in rows:
        point = {
            "ts": format_timestamp(row.as_of_ts),
            "addr_active": row.addr_active
        }
        
        # Add to d7 series
        if row.window_minutes == 30:
            series["d7"]["w30"].append(point)
        elif row.window_minutes == 60:
            series["d7"]["w60"].append(point)
        
        # Add to h24 series if within 24 hours
        if row.as_of_ts >= h24_cutoff:
            if row.window_minutes == 30:
                series["h24"]["w30"].append(point)
            elif row.window_minutes == 60:
                series["h24"]["w60"].append(point)
        
        # Track latest values
        if max_as_of_ts is None or row.as_of_ts > max_as_of_ts:
            max_as_of_ts = row.as_of_ts
        
        # Track latest non-null top10_share
        if row.top10_share is not None:
            if latest_top10 is None or row.as_of_ts >= max_as_of_ts:
                latest_top10 = float(row.top10_share)
    
    # Build overview
    overview = {
        "top10_share": clamp_ratio(latest_top10) if latest_top10 is not None else None,
        "others_share": None
    }
    
    if overview["top10_share"] is not None:
        overview["others_share"] = quantize_decimal(
            max(0.0, 1.0 - overview["top10_share"]), 3
        )
    
    return {
        "series": series,
        "overview": overview,
        "data_as_of": format_timestamp(max_as_of_ts),
        "stale": False,
        "bq_scanned_mb": 0  # PG doesn't scan bytes
    }


def fetch_series_bq(
    chain: str, 
    address: str
) -> Dict[str, Any]:
    """
    Fetch onchain features from BigQuery.
    
    Returns:
        Dict with series data and metadata
    """
    try:
        from api.providers.onchain.bq_provider import BQProvider
        
        provider = BQProvider()
        
        # Fetch for window 30
        rows_30 = provider.query_light_features(chain, address, 30)
        
        # Fetch for window 60
        rows_60 = provider.query_light_features(chain, address, 60)
        
        # Combine and process
        all_rows = []
        
        for row in rows_30:
            all_rows.append({
                "as_of_ts": datetime.fromisoformat(
                    row["as_of_ts"].replace("Z", "+00:00")
                ) if isinstance(row["as_of_ts"], str) else row["as_of_ts"],
                "window_minutes": 30,
                "addr_active": row.get("addr_active"),
                "top10_share": row.get("top10_share")
            })
        
        for row in rows_60:
            all_rows.append({
                "as_of_ts": datetime.fromisoformat(
                    row["as_of_ts"].replace("Z", "+00:00")
                ) if isinstance(row["as_of_ts"], str) else row["as_of_ts"],
                "window_minutes": 60,
                "addr_active": row.get("addr_active"),
                "top10_share": row.get("top10_share")
            })
        
        # Sort by timestamp
        all_rows.sort(key=lambda x: x["as_of_ts"])
        
        # Filter to last 7 days
        now = datetime.now(timezone.utc)
        d7_cutoff = now - timedelta(days=7)
        h24_cutoff = now - timedelta(hours=24)
        
        all_rows = [r for r in all_rows if r["as_of_ts"] >= d7_cutoff]
        
        # Build series
        series = {
            "h24": {"w30": [], "w60": []},
            "d7": {"w30": [], "w60": []}
        }
        
        latest_top10 = None
        max_as_of_ts = None
        
        for row in all_rows:
            point = {
                "ts": format_timestamp(row["as_of_ts"]),
                "addr_active": row["addr_active"]
            }
            
            # Add to d7 series
            if row["window_minutes"] == 30:
                series["d7"]["w30"].append(point)
            elif row["window_minutes"] == 60:
                series["d7"]["w60"].append(point)
            
            # Add to h24 series if within 24 hours
            if row["as_of_ts"] >= h24_cutoff:
                if row["window_minutes"] == 30:
                    series["h24"]["w30"].append(point)
                elif row["window_minutes"] == 60:
                    series["h24"]["w60"].append(point)
            
            # Track latest values
            if max_as_of_ts is None or row["as_of_ts"] > max_as_of_ts:
                max_as_of_ts = row["as_of_ts"]
                if row["top10_share"] is not None:
                    latest_top10 = float(row["top10_share"])
        
        # Build overview
        overview = {
            "top10_share": clamp_ratio(latest_top10) if latest_top10 is not None else None,
            "others_share": None
        }
        
        if overview["top10_share"] is not None:
            overview["others_share"] = quantize_decimal(
                max(0.0, 1.0 - overview["top10_share"]), 3
            )
        
        # TODO: Get actual bytes scanned from BQ job
        bq_scanned_mb = 10.0  # Placeholder
        
        return {
            "series": series,
            "overview": overview,
            "data_as_of": format_timestamp(max_as_of_ts),
            "stale": False,
            "bq_scanned_mb": bq_scanned_mb
        }
        
    except Exception as e:
        log_json(stage="expert.bq_fetch", error=str(e))
        # Return empty result with stale=true on BQ error
        return {
            "series": {
                "h24": {"w30": [], "w60": []},
                "d7": {"w30": [], "w60": []}
            },
            "overview": {
                "top10_share": None,
                "others_share": None
            },
            "data_as_of": None,
            "stale": True,
            "bq_scanned_mb": 0
        }


@router.get("/onchain")
def get_expert_onchain(
    chain: str,
    address: str,
    x_expert_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get expert onchain view for chain+address.
    
    Args:
        chain: Blockchain name (only "eth" supported)
        address: Contract address (0x + 40 hex chars)
        x_expert_key: Expert access key header
        db: Database session
        
    Returns:
        JSON response with series and overview
        
    Raises:
        404: Expert view disabled
        403: Missing or invalid key
        400: Invalid parameters
        429: Rate limited
    """
    
    # Check if expert view is enabled
    if os.getenv("EXPERT_VIEW", "off") != "on":
        raise HTTPException(status_code=404, detail="Not found")
    
    # Check expert key
    expected_key = os.getenv("EXPERT_KEY", "")
    if not expected_key or x_expert_key != expected_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    # Validate chain
    if chain.lower() != "eth":
        raise HTTPException(status_code=400, detail="Unsupported chain")
    chain = "eth"
    
    # Validate address format
    if not re.match(r"^0x[a-fA-F0-9]{40}$", address):
        raise HTTPException(status_code=400, detail="Invalid address format")
    address = address.lower()
    
    # Check rate limit
    if check_rate_limit(x_expert_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Cache key
    cache_key = f"expert:onchain:{chain}:{address}"
    
    # Check cache
    cached_data, ttl = get_cache(cache_key)
    
    # Determine source
    source = os.getenv("EXPERT_SOURCE", "pg")
    
    # If we have fresh cache and using PG source, return immediately
    if cached_data and source == "pg":
        # Update cache metadata
        cached_data["cache"] = {"hit": True, "ttl_sec": ttl}
        
        # Log metrics
        log_json(
            stage="expert.onchain",
            cache_hit=True,
            source=source,
            chain=chain,
            address=address
        )
        
        return cached_data
    
    # For BQ source, keep cache for fallback but try fresh first
    if source == "bq":
        result = fetch_series_bq(chain, address)
        
        # If BQ failed and we have cache, return stale cache
        if result["stale"] and cached_data:
            cached_data["stale"] = True
            cached_data["cache"] = {"hit": True, "ttl_sec": ttl}
            log_json(
                stage="expert.onchain",
                cache_hit=True,
                source=source,
                chain=chain,
                address=address,
                stale=True
            )
            return cached_data
    else:
        result = fetch_series_pg(chain, address, db)
    
    # Build response
    response = {
        "chain": chain,
        "address": address,
        "series": result["series"],
        "overview": result["overview"],
        "data_as_of": result["data_as_of"],
        "stale": result["stale"],
        "cache": {"hit": False, "ttl_sec": int(os.getenv("EXPERT_CACHE_TTL_SEC", "180"))}
    }
    
    # Cache the response (only if not stale)
    if not result["stale"]:
        ttl_base = int(os.getenv("EXPERT_CACHE_TTL_SEC", "180"))
        ttl_base = max(120, min(300, ttl_base))  # Clamp to [120, 300]
        set_cache(cache_key, response, ttl_base)
    
    # Log metrics
    log_json(
        stage="expert.onchain",
        cache_hit=False,
        source=source,
        chain=chain,
        address=address,
        bq_scanned_mb=result.get("bq_scanned_mb", 0),
        stale=result["stale"]
    )
    
    return response