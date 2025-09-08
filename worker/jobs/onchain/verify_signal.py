"""On-chain signal verification job."""

import os
import time
import logging
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

logger = logging.getLogger(__name__)

# Configuration from environment
ONCHAIN_VERIFICATION_DELAY_SEC = int(os.getenv("ONCHAIN_VERIFICATION_DELAY_SEC", "180"))
ONCHAIN_VERIFICATION_TIMEOUT_SEC = int(os.getenv("ONCHAIN_VERIFICATION_TIMEOUT_SEC", "720"))
ONCHAIN_VERDICT_TTL_SEC = int(os.getenv("ONCHAIN_VERDICT_TTL_SEC", "900"))
BQ_ONCHAIN_FEATURES_VIEW = os.getenv("BQ_ONCHAIN_FEATURES_VIEW", "")
ONCHAIN_RULES = os.getenv("ONCHAIN_RULES", "off")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Metrics tracking
metrics = {
    "bq_query_count": 0,
    "bq_scanned_mb": 0.0
}


def get_redis_client() -> redis.Redis:
    """Get Redis client instance."""
    return redis.from_url(REDIS_URL, decode_responses=True)


def acquire_lock(redis_client: redis.Redis, event_key: str) -> bool:
    """
    Acquire distributed lock for event processing.
    
    Args:
        redis_client: Redis client
        event_key: Event key to lock
        
    Returns:
        True if lock acquired, False otherwise
    """
    lock_key = f"onchain:verify:{event_key}"
    return redis_client.set(lock_key, "1", nx=True, ex=ONCHAIN_VERDICT_TTL_SEC)


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
        
        # Acquire lock
        if not acquire_lock(redis_client, signal.event_key):
            logger.debug(f"Skipping {signal.event_key}: lock not acquired")
            return "skipped"
        
        # Parse chain and address from event_key (format: chain:address:timestamp)
        parts = signal.event_key.split(":")
        if len(parts) < 2:
            logger.error(f"Invalid event_key format: {signal.event_key}")
            return "error"
        
        chain = parts[0]
        address = parts[1]
        
        # Fetch features
        features_data = fetch_onchain_features(chain, address, window_min=60)
        
        if not features_data:
            # Evidence delayed - record event but don't change state
            db.execute(sa_text("""
                INSERT INTO signal_events (event_key, type, metadata, created_at)
                VALUES (:event_key, 'onchain_verify', :metadata, NOW())
            """), {
                "event_key": signal.event_key,
                "metadata": '{"verdict_decision": "insufficient", "verdict_note": "evidence_delayed"}'
            })
            
            # Update asof_ts and confidence
            db.execute(sa_text("""
                UPDATE signals 
                SET onchain_asof_ts = NOW(),
                    onchain_confidence = 0
                WHERE event_key = :event_key
            """), {"event_key": signal.event_key})
            
            db.commit()
            logger.info(f"Evidence delayed for {signal.event_key}")
            return "updated"
        
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
        verdict = evaluate(feature, rules)
        
        # Update database
        new_state = signal.state
        if ONCHAIN_RULES == "on" and verdict.decision in ["upgrade", "downgrade"]:
            if verdict.decision == "upgrade":
                new_state = "verified"
            elif verdict.decision == "downgrade":
                new_state = "rejected"
        
        # Update signal
        db.execute(sa_text("""
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
            "state": new_state
        })
        
        # Record event
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
            "metadata": str(metadata).replace("'", '"')  # Convert to JSON string
        })
        
        db.commit()
        
        logger.info(f"Processed {signal.event_key}: {verdict.decision} (confidence={verdict.confidence})")
        return "updated"
        
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
        candidates_sql = f"""
            SELECT event_key, state, {time_col} AS time_col
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