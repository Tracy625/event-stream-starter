"""On-chain signal verification job."""

import os
import time
import logging
import uuid
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any, Literal
from decimal import Decimal

import redis
from sqlalchemy.sql import text as sa_text
from sqlalchemy.orm import Session

from api.database import get_db
from api.onchain.dto import OnchainFeature
from api.onchain.rules_engine import evaluate, load_rules
from api.providers.onchain.bq_provider import BQProvider
from api.core.metrics_store import log_json
from api.core.metrics import (
    onchain_lock_acquire_total,
    onchain_lock_release_total,
    onchain_lock_release_attempt_total,
    onchain_state_cas_conflict_total,
    onchain_lock_expired_seen_total,
    onchain_process_ms,
    onchain_lock_hold_ms,
    onchain_cooldown_hit_total,
)

logger = logging.getLogger(__name__)

# Configuration from environment
ONCHAIN_VERIFICATION_DELAY_SEC = int(os.getenv("ONCHAIN_VERIFICATION_DELAY_SEC", "180"))
ONCHAIN_VERIFICATION_TIMEOUT_SEC = int(os.getenv("ONCHAIN_VERIFICATION_TIMEOUT_SEC", "720"))
ONCHAIN_VERDICT_TTL_SEC = int(os.getenv("ONCHAIN_VERDICT_TTL_SEC", "900"))
BQ_ONCHAIN_FEATURES_VIEW = os.getenv("BQ_ONCHAIN_FEATURES_VIEW", "")
ONCHAIN_RULES = os.getenv("ONCHAIN_RULES", "off")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Lock configuration (Stage A)
ONCHAIN_LOCK_TTL_SEC = int(os.getenv("ONCHAIN_LOCK_TTL_SEC", "60"))
ONCHAIN_LOCK_MAX_RETRY = int(os.getenv("ONCHAIN_LOCK_MAX_RETRY", "0"))
ONCHAIN_LOCK_BACKOFF_MS_MIN = int(os.getenv("ONCHAIN_LOCK_BACKOFF_MS_MIN", "20"))
ONCHAIN_LOCK_BACKOFF_MS_MAX = int(os.getenv("ONCHAIN_LOCK_BACKOFF_MS_MAX", "40"))
ONCHAIN_LOCK_ENABLE = os.getenv("ONCHAIN_LOCK_ENABLE", "true").lower() in ("1", "true", "yes", "on")
ONCHAIN_CAS_ENABLE = os.getenv("ONCHAIN_CAS_ENABLE", "true").lower() in ("1", "true", "yes", "on")
DEPLOY_ENV = os.getenv("DEPLOY_ENV", os.getenv("APP_ENV", "prod"))

# Redis client timeouts
REDIS_SOCKET_TIMEOUT_MS = int(os.getenv("REDIS_SOCKET_TIMEOUT_MS", "2000"))
REDIS_CONNECT_TIMEOUT_MS = int(os.getenv("REDIS_CONNECT_TIMEOUT_MS", "1000"))

# Minimal cooldown for hot keys
ONCHAIN_COOLDOWN_FAILS = int(os.getenv("ONCHAIN_COOLDOWN_FAILS", "3"))
ONCHAIN_COOLDOWN_TTL_SEC = int(os.getenv("ONCHAIN_COOLDOWN_TTL_SEC", "45"))

# Metrics tracking
metrics = {
    "bq_query_count": 0,
    "bq_scanned_mb": 0.0
}


def get_redis_client() -> redis.Redis:
    """Get Redis client instance."""
    # Convert ms to seconds
    sock_to = max(0.001, REDIS_SOCKET_TIMEOUT_MS / 1000.0)
    conn_to = max(0.001, REDIS_CONNECT_TIMEOUT_MS / 1000.0)
    return redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_timeout=sock_to,
        socket_connect_timeout=conn_to,
    )


def _sanitize_for_key(event_key: str) -> str:
    # Remove whitespace/control chars
    safe = re.sub(r"[\s\x00-\x1F]+", "", str(event_key))
    if len(safe) <= 200:
        return safe
    h = hashlib.sha1(safe.encode()).hexdigest()[:8]
    return f"{safe[:191]}:{h}"


def _lock_key(event_key: str) -> str:
    return f"lock:{DEPLOY_ENV}:onchain:signal:{_sanitize_for_key(event_key)}"


def acquire_lock(redis_client: redis.Redis, event_key: str) -> Optional[str]:
    """Acquire distributed lock; returns token if acquired else None."""
    try:
        token = uuid.uuid4().hex
        ok = redis_client.set(_lock_key(event_key), token, nx=True, ex=ONCHAIN_LOCK_TTL_SEC)
        if ok:
            onchain_lock_acquire_total.inc({"status": "ok"})
            log_json(stage="onchain.lock.acquire", event_key=event_key, token=token, ttl=ONCHAIN_LOCK_TTL_SEC)
            return token
        else:
            onchain_lock_acquire_total.inc({"status": "fail"})
            log_json(stage="onchain.lock.acquire", event_key=event_key, status="fail")
            return None
    except Exception as e:
        onchain_lock_acquire_total.inc({"status": "error"})
        log_json(stage="onchain.lock.acquire", event_key=event_key, error=str(e))
        # jitter backoff to avoid thundering herd
        import random
        time.sleep(random.uniform(ONCHAIN_LOCK_BACKOFF_MS_MIN, ONCHAIN_LOCK_BACKOFF_MS_MAX) / 1000.0)
        return None


def release_lock(redis_client: redis.Redis, event_key: str, token: Optional[str]) -> str:
    """Release lock if token matches. Returns 'ok'|'mismatch'|'error'|'expired'."""
    if not token:
        return "error"
    try:
        onchain_lock_release_attempt_total.inc()
        # Lua script: if get(key)==token then del(key) else return 0
        lua = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        sha = hashlib.sha1(lua.encode()).hexdigest()
        try:
            res = redis_client.evalsha(sha, 1, _lock_key(event_key), token)
        except Exception as e:
            # NOSCRIPT or others: fall back to EVAL
            res = redis_client.eval(lua, 1, _lock_key(event_key), token)
        if res == 1:
            onchain_lock_release_total.inc({"status": "ok"})
            log_json(stage="onchain.lock.release", event_key=event_key, status="ok")
            return "ok"
        else:
            # Distinguish expired vs mismatch
            val = redis_client.get(_lock_key(event_key))
            if val is None:
                onchain_lock_expired_seen_total.inc()
                onchain_lock_release_total.inc({"status": "expired"})
                log_json(stage="onchain.lock.release", event_key=event_key, status="expired")
                return "expired"
            else:
                onchain_lock_release_total.inc({"status": "mismatch"})
                log_json(stage="onchain.lock.release", event_key=event_key, status="mismatch")
                return "mismatch"
    except Exception as e:
        onchain_lock_release_total.inc({"status": "error"})
        # Avoid logging full value; include value length only (best-effort)
        try:
            val = redis_client.get(_lock_key(event_key))
            vlen = len(val) if val is not None else 0
        except Exception:
            vlen = -1
        log_json(stage="onchain.lock.release", event_key=event_key, error=str(e)[:200], value_len=vlen)
        return "error"


def fetch_onchain_features(
    chain: str, 
    address: str,
    window_min: int = 60,
    timeout_sec: int = ONCHAIN_VERIFICATION_TIMEOUT_SEC
) -> Optional[Dict[str, Any]]:
    """
    Fetch on-chain features from BigQuery.
    
    Args:
        chain: Blockchain identifier
        address: Contract address
        window_min: Time window in minutes
        timeout_sec: Query timeout
        
    Returns:
        Feature dict or None if not found/timeout
    """
    if not BQ_ONCHAIN_FEATURES_VIEW:
        logger.error("BQ_ONCHAIN_FEATURES_VIEW not configured")
        return None
    
    try:
        provider = BQProvider()
        
        # Query with retry logic
        max_retries = 3
        delays = [5, 15, 30]
        
        for attempt in range(max_retries):
            try:
                # Use run_template with onchain_features template
                result = provider.run_template(
                    "onchain_features",
                    chain=chain,
                    address=address,
                    window_minutes=window_min
                )
                
                if result and result.get("data"):
                    # Track metrics
                    if "metadata" in result:
                        bytes_processed = result["metadata"].get("total_bytes_processed", 0)
                        metrics["bq_query_count"] += 1
                        metrics["bq_scanned_mb"] += bytes_processed / (1024 * 1024)
                    
                    # Check if data is fresh (< 90 minutes old)
                    data = result["data"]
                    if isinstance(data, list) and len(data) > 0:
                        data = data[0]  # Take first row
                    
                    if "asof_ts" in data:
                        asof = datetime.fromisoformat(data["asof_ts"])
                        if datetime.now(timezone.utc) - asof > timedelta(minutes=90):
                            logger.warning(f"Features too old for {chain}/{address}: {asof}")
                            return None
                    
                    return data
                
                return None
                
            except Exception as e:
                logger.warning(f"BQ query attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(delays[attempt])
                else:
                    raise
                    
    except Exception as e:
        logger.error(f"Failed to fetch features for {chain}/{address}: {e}")
        return None


def process_candidate(
    db: Session,
    signal: Any,
    rules: Any,
    redis_client: redis.Redis
) -> str:
    """
    Process a single candidate signal.
    
    Args:
        db: Database session
        signal: Signal record
        rules: Loaded rules configuration
        redis_client: Redis client
        
    Returns:
        Status: "updated", "skipped", "error"
    """
    try:
        # Check delay using the time column (could be created_at, updated_at, or ts)
        time_value = getattr(signal, 'time_col', None) or getattr(signal, 'created_at', None)
        if isinstance(time_value, str):
            time_value = datetime.fromisoformat(time_value)
        
        if time_value and datetime.now(timezone.utc) - time_value < timedelta(seconds=ONCHAIN_VERIFICATION_DELAY_SEC):
            logger.debug(f"Skipping {signal.event_key}: too recent")
            return "skipped"
        
        # Check cooldown for hot keys (best-effort)
        try:
            if redis_client and redis_client.get(f"cooldown:{_sanitize_for_key(signal.event_key)}"):
                log_json(stage="onchain.cooldown.skip", event_key=signal.event_key)
                onchain_cooldown_hit_total.inc()
                return "skipped"
        except Exception:
            # Do not execute without lock on Redis error; skip conservatively
            logger.error("Redis error during cooldown check; skipping")
            return "skipped"

        # Parse chain and address from event_key (format: chain:address:timestamp)
        parts = signal.event_key.split(":")
        if len(parts) < 2:
            logger.error(f"Invalid event_key format: {signal.event_key}")
            return "error"
        
        chain = parts[0]
        address = parts[1]
        
        # Fetch features (outside lock to minimize hold time)
        features_data = fetch_onchain_features(chain, address, window_min=60)
        
        
        # Create feature object
        try:
            feature = OnchainFeature(
                active_addr_pctl=features_data.get("active_addr_pctl", 0.0),
                growth_ratio=features_data.get("growth_ratio", 0.0),
                top10_share=features_data.get("top10_share", 0.0),
                self_loop_ratio=features_data.get("self_loop_ratio", 0.0),
                asof_ts=datetime.fromisoformat(features_data["asof_ts"]),
                window_min=60
            )
        except Exception as e:
            logger.error(f"Failed to parse features for {signal.event_key}: {e}")
            return "error"
        
        # Evaluate rules
        verdict = evaluate(feature, rules) if features_data else None
        
        # Acquire lock with small retry and jitter (optional kill-switch)
        op_id = uuid.uuid4().hex
        start_total = time.perf_counter()
        token: Optional[str] = None
        wait_start = time.perf_counter()
        if ONCHAIN_LOCK_ENABLE:
            import random
            for attempt in range(ONCHAIN_LOCK_MAX_RETRY + 1):
                token = acquire_lock(redis_client, signal.event_key)
                if token:
                    break
                if attempt < ONCHAIN_LOCK_MAX_RETRY:
                    backoff = random.uniform(ONCHAIN_LOCK_BACKOFF_MS_MIN, ONCHAIN_LOCK_BACKOFF_MS_MAX) / 1000.0
                    time.sleep(backoff)
            if not token:
                # record wait 0 on fail as required
                from api.core.metrics import onchain_lock_wait_ms
                onchain_lock_wait_ms.observe(0)
                log_json(stage="onchain.lock.skip", event_key=signal.event_key, operation_id=op_id)
                # bump cooldown fail count best-effort
                try:
                    cnt = redis_client.incr(f"failcnt:{signal.event_key}")
                    redis_client.expire(f"failcnt:{signal.event_key}", 60)
                    if cnt >= ONCHAIN_COOLDOWN_FAILS:
                        redis_client.setex(f"cooldown:{signal.event_key}", ONCHAIN_COOLDOWN_TTL_SEC, "1")
                        redis_client.delete(f"failcnt:{signal.event_key}")
                except Exception:
                    pass
                return "skipped"
        else:
            log_json(stage="onchain.lock.disabled", event_key=signal.event_key, operation_id=op_id)
        # Record wait time (0 if lock disabled)
        from api.core.metrics import onchain_lock_wait_ms
        lock_wait_ms = int(round((time.perf_counter() - wait_start) * 1000)) if token else 0
        onchain_lock_wait_ms.observe(lock_wait_ms)

        start_hold = time.perf_counter()
        try:
            # DB timeouts guardrails
            db.execute(sa_text(f"SET LOCAL lock_timeout = '1000ms'"))
            db.execute(sa_text(f"SET LOCAL statement_timeout = '10000ms'"))

            if not features_data:
                # Evidence delayed - record event but don't change state (CAS on state)
                db.execute(sa_text("""
                    INSERT INTO signal_events (event_key, type, metadata, created_at)
                    VALUES (:event_key, 'onchain_verify', :metadata, NOW())
                """), {
                    "event_key": signal.event_key,
                    "metadata": '{"verdict_decision": "insufficient", "verdict_note": "evidence_delayed"}'
                })

                if ONCHAIN_CAS_ENABLE:
                    res = db.execute(sa_text("""
                        UPDATE signals 
                        SET onchain_asof_ts = NOW(),
                            onchain_confidence = 0,
                            updated_at = NOW()
                        WHERE event_key = :event_key AND state = :prev_state
                    """), {"event_key": signal.event_key, "prev_state": signal.state})
                else:
                    res = db.execute(sa_text("""
                        UPDATE signals 
                        SET onchain_asof_ts = NOW(),
                            onchain_confidence = 0,
                            updated_at = NOW()
                        WHERE event_key = :event_key
                    """), {"event_key": signal.event_key})

                if ONCHAIN_CAS_ENABLE and hasattr(res, "rowcount") and res.rowcount == 0:
                    onchain_state_cas_conflict_total.inc()
                    log_json(stage="onchain.state.cas_conflict", event_key=signal.event_key,
                             operation_id=op_id, prev_state=signal.state,
                             prev_updated_at=str(getattr(signal, 'updated_at', None)))
                    db.rollback()
                    return "skipped"

                db.commit()
                log_json(stage="onchain.processed", event_key=signal.event_key,
                         operation_id=op_id, decision="insufficient")
                return "updated"

            # With features and verdict, update state via CAS
            new_state = signal.state
            if ONCHAIN_RULES == "on" and verdict and verdict.decision in ["upgrade", "downgrade"]:
                new_state = "verified" if verdict.decision == "upgrade" else "rejected"

            if ONCHAIN_CAS_ENABLE:
                res = db.execute(sa_text("""
                    UPDATE signals 
                    SET onchain_asof_ts = :asof_ts,
                        onchain_confidence = :confidence,
                        state = :state,
                        updated_at = NOW()
                    WHERE event_key = :event_key AND state = :prev_state
                """), {
                    "event_key": signal.event_key,
                    "asof_ts": feature.asof_ts,
                    "confidence": Decimal(str(verdict.confidence)),
                    "state": new_state,
                    "prev_state": signal.state,
                })
            else:
                res = db.execute(sa_text("""
                    UPDATE signals 
                    SET onchain_asof_ts = :asof_ts,
                        onchain_confidence = :confidence,
                        state = :state,
                        updated_at = NOW()
                    WHERE event_key = :event_key
                """), {
                    "event_key": signal.event_key,
                    "asof_ts": feature.asof_ts,
                    "confidence": Decimal(str(verdict.confidence)),
                    "state": new_state,
                })

            if ONCHAIN_CAS_ENABLE and hasattr(res, "rowcount") and res.rowcount == 0:
                onchain_state_cas_conflict_total.inc()
                log_json(stage="onchain.state.cas_conflict", event_key=signal.event_key,
                         operation_id=op_id, prev_state=signal.state, next_state=new_state,
                         prev_updated_at=str(getattr(signal, 'updated_at', None)))
                db.rollback()
                return "skipped"

            metadata = {
                "verdict_decision": verdict.decision,
                "verdict_confidence": float(verdict.confidence),
                "asof_ts": feature.asof_ts.isoformat()
            }
            if verdict.note:
                metadata["verdict_note"] = verdict.note

            db.execute(sa_text("""
                INSERT INTO signal_events (event_key, type, metadata, created_at)
                VALUES (:event_key, 'onchain_verify', :metadata, NOW())
            """), {
                "event_key": signal.event_key,
                "metadata": str(metadata).replace("'", '"')
            })

            db.commit()
            log_json(stage="onchain.processed", event_key=signal.event_key,
                     operation_id=op_id, decision=verdict.decision, confidence=float(verdict.confidence),
                     lock_wait_ms=lock_wait_ms)
            return "updated"
        finally:
            hold_ms = int(round((time.perf_counter() - start_hold) * 1000))
            onchain_lock_hold_ms.observe(hold_ms)
            release_lock(redis_client, signal.event_key, token)
            total_ms = int(round((time.perf_counter() - start_total) * 1000))
            onchain_process_ms.observe(total_ms)
        
    except Exception as e:
        logger.error(f"Error processing {signal.event_key}: {e}", exc_info=True)
        db.rollback()
        return "error"


def _detect_time_column(db) -> Literal["created_at", "updated_at", "ts"]:
    """
    Detect available timestamp column on 'signals' table.
    Priority: created_at > updated_at > ts. Fallback to 'ts' if nothing found.
    """
    col = db.execute(sa_text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'signals'
          AND column_name IN ('created_at', 'updated_at', 'ts')
        ORDER BY CASE column_name
            WHEN 'created_at' THEN 1
            WHEN 'updated_at' THEN 2
            WHEN 'ts' THEN 3
            ELSE 4
        END
        LIMIT 1
    """)).scalar()
    return col or "ts"


def _has_column(db, table: str, column: str) -> bool:
    """Check if a column exists in current schema."""
    try:
        q = sa_text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :t
              AND column_name = :c
            LIMIT 1
            """
        )
        return db.execute(q, {"t": table, "c": column}).scalar() is not None
    except Exception:
        return False


def run_once(limit: int = 100) -> Dict[str, int]:
    """
    Run one iteration of on-chain verification.
    
    Args:
        limit: Maximum number of candidates to process
        
    Returns:
        Statistics dictionary
    """
    stats = {
        "scanned": 0,
        "evaluated": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0
    }
    
    # Check configuration
    if not BQ_ONCHAIN_FEATURES_VIEW:
        logger.error("BQ_ONCHAIN_FEATURES_VIEW not configured")
        stats["errors"] = 1
        return stats
    
    try:
        # Load rules
        rules = load_rules("rules/onchain.yml")
    except Exception as e:
        logger.error(f"Failed to load rules: {e}")
        stats["errors"] = 1
        return stats
    
    redis_client = get_redis_client()
    
    with next(get_db()) as db:
        # Check if state column exists
        state_check = db.execute(sa_text("""
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_schema = current_schema()
              AND table_name = 'signals' 
              AND column_name = 'state'
        """)).scalar()
        
        if not state_check:
            logger.error("Column 'state' does not exist in signals table. Run migration: alembic upgrade head")
            stats["errors"] = 1
            return stats
        
        # Detect usable time column (created_at / updated_at / ts)
        time_col = _detect_time_column(db)
        logger.info(f"Using time column '{time_col}' for candidate scan")
        
        # Query recent candidates
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        # Build query with validated identifier (safe since we control the column name)
        include_updated_at = _has_column(db, 'signals', 'updated_at')
        select_cols = f"event_key, state, {time_col} AS time_col"
        if include_updated_at:
            select_cols += ", updated_at"
        candidates_sql = f"""
            SELECT {select_cols}
            FROM signals
            WHERE state = 'candidate'
              AND {time_col} >= :cutoff
            ORDER BY {time_col} DESC
            LIMIT :limit
        """
        candidates = db.execute(sa_text(candidates_sql), {"cutoff": cutoff, "limit": limit}).fetchall()
        
        stats["scanned"] = len(candidates)
        
        for candidate in candidates:
            stats["evaluated"] += 1
            
            result = process_candidate(db, candidate, rules, redis_client)
            
            if result == "updated":
                stats["updated"] += 1
            elif result == "skipped":
                stats["skipped"] += 1
            elif result == "error":
                stats["errors"] += 1
    
    # Log statistics
    logger.info(f"Verification run complete: {stats}")
    logger.info(f"BQ metrics: queries={metrics['bq_query_count']}, scanned_mb={metrics['bq_scanned_mb']:.2f}")
    
    return stats


if __name__ == "__main__":
    # CLI entry point
    import json
    logging.basicConfig(level=logging.INFO)
    result = run_once()
    print(json.dumps(result))
