"""
Heat calculation service for token signals.

Provides heat metrics (counts, slopes, trends) based on recent activity.
"""

import os
import re
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple
from sqlalchemy import text as sa_text
from api.metrics import log_json, timeit

# EMA state cache (in-memory for simplicity)
_ema_cache = {}


def normalize_token(symbol: str) -> str:
    """
    Normalize token symbol.
    
    Args:
        symbol: Token symbol
    
    Returns:
        Normalized symbol (stripped and uppercased)
    """
    if not symbol:
        return ""
    return symbol.strip().upper()


def normalize_token_ca(addr: str) -> str:
    """
    Normalize and validate token contract address.
    
    Args:
        addr: Contract address
    
    Returns:
        Normalized address (lowercase with 0x prefix)
    
    Raises:
        ValueError: If address is invalid (missing 0x or non-hex)
    """
    if not addr:
        return ""
    
    addr_lower = addr.lower().strip()
    
    # Check 0x prefix
    if not addr_lower.startswith("0x"):
        raise ValueError(f"Token CA missing 0x prefix: {addr}")
    
    # Check hex characters (after 0x)
    if not re.match(r'^0x[0-9a-f]+$', addr_lower):
        raise ValueError(f"Token CA contains non-hex characters: {addr}")
    
    return addr_lower


def _get_redis_client():
    """Get Redis client for caching."""
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        return redis.from_url(redis_url, decode_responses=True)
    except:
        return None


def _calculate_ema(current: float, previous: Optional[float], alpha: float) -> float:
    """
    Calculate exponential moving average.
    
    Args:
        current: Current value
        previous: Previous EMA value (None for first calculation)
        alpha: Smoothing factor (0 < alpha <= 1)
    
    Returns:
        EMA value
    """
    if previous is None:
        return current
    return alpha * current + (1 - alpha) * previous


@timeit("signals.heat.compute")
def compute_heat(db, *, token: Optional[str] = None, token_ca: Optional[str] = None, 
                 now_ts: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Compute heat metrics for a token.
    
    Args:
        db: Database connection
        token: Token symbol (optional)
        token_ca: Token contract address (optional)
        now_ts: Current timestamp override (for testing)
    
    Returns:
        Dictionary with heat metrics:
            - cnt_10m: Count in last 10 minutes
            - cnt_30m: Count in last 30 minutes
            - slope: Rate of change (count/min) or null
            - trend: "up", "down", or "flat"
            - window: Time windows used
            - degrade: Whether results are degraded
    """
    # Read environment variables
    theta_rise = float(os.getenv("THETA_RISE", "0.2"))
    min_sample = int(os.getenv("HEAT_MIN_SAMPLE", "3"))
    noise_floor = int(os.getenv("HEAT_NOISE_FLOOR", "1"))
    ema_alpha = float(os.getenv("HEAT_EMA_ALPHA", "0.0"))
    cache_ttl = int(os.getenv("HEAT_CACHE_TTL", "30"))
    max_rows = int(os.getenv("HEAT_MAX_ROWS", "50000"))
    timeout_ms = int(os.getenv("HEAT_TIMEOUT_MS", "1500"))
    
    # Use provided timestamp or database now()
    if now_ts:
        now = now_ts
        asof_ts = now
    else:
        # Get database server time to avoid drift
        result = db.execute(sa_text("SELECT NOW() as now")).fetchone()
        now = result[0]
        asof_ts = now
    
    # Check cache first
    from_cache = False
    cache_key = None
    
    if cache_ttl > 0:
        redis_client = _get_redis_client()
        if redis_client:
            # Create cache key based on identifier and time bucket
            identifier = token_ca or token or "unknown"
            time_bucket = int(now.timestamp()) // cache_ttl * cache_ttl
            cache_key = f"heat:{identifier}:{time_bucket}"
            
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    result = json.loads(cached)
                    result["from_cache"] = True
                    result["asof_ts"] = asof_ts.isoformat() if hasattr(asof_ts, 'isoformat') else str(asof_ts)
                    return result
            except:
                pass  # Cache miss or error, continue
    
    # Calculate time windows
    window_10m = timedelta(minutes=10)
    window_30m = timedelta(minutes=30)
    
    t_10m_ago = now - window_10m
    t_30m_ago = now - window_30m
    t_20m_ago = now - timedelta(minutes=20)
    
    # Initialize result
    result = {
        "cnt_10m": 0,
        "cnt_30m": 0,
        "slope": None,
        "trend": "flat",
        "window": {
            "ten": 600,  # seconds
            "thirty": 1800
        },
        "degrade": False,
        "from_cache": from_cache,
        "asof_ts": asof_ts.isoformat() if hasattr(asof_ts, 'isoformat') else str(asof_ts)
    }
    
    # Add EMA fields if enabled
    if ema_alpha > 0:
        result["slope_ema"] = None
        result["trend_ema"] = "flat"
    
    try:
        # Set statement timeout for this query
        if timeout_ms > 0:
            db.execute(sa_text(f"SET LOCAL statement_timeout = {timeout_ms}"))
        
        # Build query conditions
        conditions = []
        params = {"t_30m_ago": t_30m_ago, "t_10m_ago": t_10m_ago, "t_20m_ago": t_20m_ago, "max_rows": max_rows}
        
        if token:
            conditions.append("symbol = :token")
            params["token"] = token
        if token_ca:
            conditions.append("token_ca = :token_ca")
            params["token_ca"] = token_ca
        
        if not conditions:
            # No filter specified
            result["degrade"] = True
            return result
        
        where_clause = " OR ".join(conditions)
        
        # Query for 30m count (includes 10m)
        query_30m = sa_text(f"""
            SELECT COUNT(*) as cnt
            FROM (
                SELECT 1
                FROM raw_posts
                WHERE ({where_clause})
                  AND ts >= :t_30m_ago
                LIMIT :max_rows
            ) t
        """)
        
        cnt_30m_result = db.execute(query_30m, params).scalar()
        cnt_30m = int(cnt_30m_result) if cnt_30m_result else 0
        result["cnt_30m"] = cnt_30m
        
        # Query for 10m count
        query_10m = sa_text(f"""
            SELECT COUNT(*) as cnt
            FROM (
                SELECT 1
                FROM raw_posts
                WHERE ({where_clause})
                  AND ts >= :t_10m_ago
                LIMIT :max_rows
            ) t
        """)
        
        cnt_10m_result = db.execute(query_10m, params).scalar()
        cnt_10m = int(cnt_10m_result) if cnt_10m_result else 0
        result["cnt_10m"] = cnt_10m
        
        # Track rows scanned (approximate)
        rows_scanned = min(cnt_30m, max_rows)
        
        # Check noise floor first
        if cnt_10m < noise_floor:
            # Below noise floor - return flat trend without degradation
            result["slope"] = None
            result["trend"] = "flat"
            result["degrade"] = False
        elif cnt_30m < min_sample:
            # Insufficient samples - degrade
            result["degrade"] = True
            result["slope"] = None
            result["trend"] = "flat"
        else:
            # Query for previous 10m window (20m-10m ago)
            query_prev = sa_text(f"""
                SELECT COUNT(*) as cnt
                FROM (
                    SELECT 1
                    FROM raw_posts
                    WHERE ({where_clause})
                      AND ts >= :t_20m_ago
                      AND ts < :t_10m_ago
                    LIMIT :max_rows
                ) t
            """)
            
            prev_10m_result = db.execute(query_prev, params).scalar()
            prev_10m = int(prev_10m_result) if prev_10m_result else 0
            
            # Calculate slope (count per minute)
            slope = (cnt_10m - prev_10m) / 10.0
            result["slope"] = round(slope, 2)
            
            # Determine trend based on threshold boundaries
            if slope >= theta_rise:
                result["trend"] = "up"
            elif slope <= -theta_rise:
                result["trend"] = "down"
            else:
                result["trend"] = "flat"
            
            # Calculate EMA if enabled
            if ema_alpha > 0:
                ema_key = f"ema:{token_ca or token or 'unknown'}"
                prev_ema = _ema_cache.get(ema_key)
                
                slope_ema = _calculate_ema(slope, prev_ema, ema_alpha)
                _ema_cache[ema_key] = slope_ema
                
                result["slope_ema"] = round(slope_ema, 2)
                
                # Determine EMA trend
                if slope_ema >= theta_rise:
                    result["trend_ema"] = "up"
                elif slope_ema <= -theta_rise:
                    result["trend_ema"] = "down"
                else:
                    result["trend_ema"] = "flat"
            
            rows_scanned += min(prev_10m, max_rows)
        
        # Log computation details
        log_data = {
            "stage": "signals.heat.compute",
            "token": token,
            "token_ca": token_ca,
            "cnt_10m": cnt_10m,
            "cnt_30m": cnt_30m,
            "prev_10m": prev_10m if 'prev_10m' in locals() else None,
            "slope": result["slope"],
            "trend": result["trend"],
            "degrade": result["degrade"],
            "rows_scanned": rows_scanned,
            "from_cache": from_cache
        }
        
        if ema_alpha > 0 and "slope_ema" in result:
            log_data["slope_ema"] = result["slope_ema"]
            log_data["trend_ema"] = result["trend_ema"]
        
        log_json(**log_data)
        
        # Cache the result if caching is enabled
        if cache_ttl > 0 and cache_key and not from_cache:
            redis_client = _get_redis_client()
            if redis_client:
                try:
                    redis_client.setex(cache_key, cache_ttl, json.dumps(result))
                except:
                    pass  # Cache write failure, ignore
    
    except Exception as e:
        # On error, return degraded result
        log_json(
            stage="signals.heat.compute",
            token=token,
            token_ca=token_ca,
            error=str(e),
            degrade=True,
            from_cache=False
        )
        result["degrade"] = True
        result["slope"] = None
        result["trend"] = "flat"
        result["from_cache"] = False
    
    return result


def resolve_event_key_by_token_ca(db, token_ca: str) -> Optional[str]:
    """
    Resolve event_key by token contract address.
    
    Args:
        db: Database connection
        token_ca: Token contract address
    
    Returns:
        event_key if found, None otherwise
    """
    # Validate token_ca format
    if not token_ca:
        return None
    
    token_ca_lower = token_ca.lower().strip()
    
    # Check 0x prefix and hex format
    if not token_ca_lower.startswith("0x"):
        log_json(
            stage="signals.heat.resolve",
            reason="invalid_token_ca",
            token_ca=token_ca,
            error="Missing 0x prefix"
        )
        return None
    
    if not re.match(r'^0x[0-9a-f]+$', token_ca_lower):
        log_json(
            stage="signals.heat.resolve",
            reason="invalid_token_ca",
            token_ca=token_ca,
            error="Non-hex characters"
        )
        return None
    
    try:
        # Query for event_key by token_ca
        query = sa_text("""
            SELECT event_key 
            FROM events 
            WHERE token_ca = :ca 
            ORDER BY last_ts DESC 
            LIMIT 1
        """)
        
        result = db.execute(query, {"ca": token_ca_lower}).fetchone()
        
        if result:
            return result[0]
        
        return None
        
    except Exception as e:
        log_json(
            stage="signals.heat.resolve",
            reason="query_error",
            token_ca=token_ca,
            error=str(e)
        )
        return None


def resolve_event_key_by_symbol(db, symbol: str) -> Optional[str]:
    """
    Resolve event_key by token symbol.
    
    Args:
        db: Database connection
        symbol: Token symbol
    
    Returns:
        event_key if found, None otherwise
    """
    if not symbol:
        return None
    
    # Normalize symbol
    symbol_norm = symbol.strip().upper()
    
    try:
        # Query for event_key by symbol
        query = sa_text("""
            SELECT event_key 
            FROM events 
            WHERE symbol = :sym 
            ORDER BY last_ts DESC 
            LIMIT 1
        """)
        
        result = db.execute(query, {"sym": symbol_norm}).fetchone()
        
        if result:
            return result[0]
        
        return None
        
    except Exception as e:
        log_json(
            stage="signals.heat.resolve",
            reason="query_error",
            symbol=symbol,
            error=str(e)
        )
        return None


def persist_heat(db, *, token: Optional[str] = None, token_ca: Optional[str] = None, 
                 heat: Dict[str, Any], upsert: Optional[bool] = None, 
                 strict_match: Optional[bool] = None) -> bool:
    """
    Persist heat data to signals.features_snapshot.heat atomically and idempotently.
    Uses event_key as the anchor point for updates.
    
    Args:
        db: Database connection
        token: Token symbol
        token_ca: Token contract address
        heat: Heat data to persist
        upsert: Override HEAT_PERSIST_UPSERT setting
        strict_match: Override HEAT_PERSIST_STRICT_MATCH setting
    
    Returns:
        True if persisted successfully, False otherwise
    """
    # Check if persistence is enabled
    enable_persist = os.getenv("HEAT_ENABLE_PERSIST", "false").lower() in ("true", "1", "yes", "on")
    if not enable_persist:
        log_json(
            stage="signals.heat.persist",
            token=token,
            token_ca=token_ca,
            persisted=False,
            reason="disabled"
        )
        return False
    
    # Read configuration
    if upsert is None:
        upsert = os.getenv("HEAT_PERSIST_UPSERT", "true").lower() in ("true", "1", "yes", "on")
    if strict_match is None:
        strict_match = os.getenv("HEAT_PERSIST_STRICT_MATCH", "true").lower() in ("true", "1", "yes", "on")
    timeout_ms = int(os.getenv("HEAT_PERSIST_TIMEOUT_MS", "1500"))
    
    # Resolve event_key based on priority: token_ca > symbol
    event_key = None
    resolved_from = "none"
    
    if token_ca:
        event_key = resolve_event_key_by_token_ca(db, token_ca)
        if event_key:
            resolved_from = "token_ca"
    
    # Fallback to symbol if strict_match allows and no token_ca match
    if not event_key and token and not strict_match:
        event_key = resolve_event_key_by_symbol(db, token)
        if event_key:
            resolved_from = "symbol"
    
    # If no event_key resolved, cannot persist
    if not event_key:
        log_json(
            stage="signals.heat.persist",
            token=token,
            token_ca=token_ca,
            persisted=False,
            reason="event_key_not_found",
            strict_match=strict_match,
            match_key="event_key",
            resolved_from=resolved_from
        )
        return False
    
    try:
        # Set statement timeout for persistence transaction
        if timeout_ms > 0:
            db.execute(sa_text(f"SET LOCAL statement_timeout = {timeout_ms}"))
        
        # Prepare heat payload with required and optional fields
        heat_payload = {
            "cnt_10m": heat.get("cnt_10m", 0),
            "cnt_30m": heat.get("cnt_30m", 0),
            "slope": heat.get("slope"),
            "trend": heat.get("trend", "flat"),
            "asof_ts": heat.get("asof_ts", datetime.now(timezone.utc).isoformat()),
            # Include context for debugging
            "token": token,
            "token_ca": token_ca
        }
        
        # Add optional EMA fields if present
        if "slope_ema" in heat:
            heat_payload["slope_ema"] = heat["slope_ema"]
        if "trend_ema" in heat:
            heat_payload["trend_ema"] = heat["trend_ema"]
        
        # Prepare JSON payload
        heat_json = json.dumps(heat_payload)
        params = {"event_key": event_key, "payload": heat_json}
        
        # First check if row exists (with optional lock for concurrency)
        check_query = sa_text("""
            SELECT 1 
            FROM signals
            WHERE event_key = :event_key
            FOR UPDATE NOWAIT
        """)
        
        try:
            row_exists = db.execute(check_query, {"event_key": event_key}).fetchone() is not None
        except Exception as lock_err:
            # Lock conflict - another process is updating
            log_json(
                stage="signals.heat.persist",
                token=token,
                token_ca=token_ca,
                event_key=event_key,
                persisted=False,
                reason="lock_conflict",
                error=str(lock_err),
                strict_match=strict_match,
                match_key="event_key",
                resolved_from=resolved_from
            )
            return False
        
        if not row_exists:
            # Row doesn't exist - we don't create new rows
            log_json(
                stage="signals.heat.persist",
                token=token,
                token_ca=token_ca,
                event_key=event_key,
                persisted=False,
                reason="row_not_found",
                upsert=upsert,
                strict_match=strict_match,
                match_key="event_key",
                resolved_from=resolved_from
            )
            return False
        
        # Perform atomic update using jsonb_set for idempotency
        # Direct update by event_key, no join needed
        update_query = sa_text("""
            UPDATE signals
            SET features_snapshot = jsonb_set(
                    COALESCE(features_snapshot, '{}'::jsonb),
                    '{heat}',
                    (:payload)::jsonb,
                    true
                ),
                ts = NOW()
            WHERE event_key = :event_key
        """)
        
        result = db.execute(update_query, params)
        
        # Check if update affected any rows
        if result.rowcount == 0:
            log_json(
                stage="signals.heat.persist",
                token=token,
                token_ca=token_ca,
                event_key=event_key,
                persisted=False,
                reason="update_failed",
                upsert=upsert,
                strict_match=strict_match,
                match_key="event_key",
                resolved_from=resolved_from
            )
            return False
        
        # Transaction commits when context exits
        # Log successful persistence
        log_json(
            stage="signals.heat.persist",
            token=token,
            token_ca=token_ca,
            event_key=event_key,
            persisted=True,
            upsert=upsert,
            strict_match=strict_match,
            match_key="event_key",
            resolved_from=resolved_from,
            asof_ts=heat_payload["asof_ts"]
        )
        
        return True
        
    except Exception as e:
        # Log persistence failure
        error_msg = str(e)
        reason = "timeout" if "statement timeout" in error_msg.lower() else "exception"
        
        log_json(
            stage="signals.heat.persist",
            token=token,
            token_ca=token_ca,
            event_key=event_key,
            persisted=False,
            reason=reason,
            error=error_msg,
            upsert=upsert,
            strict_match=strict_match,
            match_key="event_key",
            resolved_from=resolved_from
        )
        return False