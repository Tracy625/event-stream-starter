#!/usr/bin/env python
"""
CARD C — Signals summary API endpoint
Provides read-only access to signal state and onchain features with caching
"""

import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
import redis

logger = logging.getLogger(__name__)

from api.database import get_db
from api.onchain.rules_engine import load_rules, evaluate
from api.onchain.dto import OnchainFeature, Verdict


router = APIRouter(tags=["signals"])  # prefix added by main.py

# Redis client (lazy init)
_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """Get or create Redis client."""
    global _redis_client
    if _redis_client is None:
        import os
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def serialize_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO8601 UTC string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def serialize_decimal(d: Optional[Decimal]) -> Optional[float]:
    """Convert Decimal to float with 3 decimal places."""
    if d is None:
        return None
    # Use Decimal quantize for proper rounding
    quantized = Decimal(str(d)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(quantized)


def is_valid_event_key(event_key: str) -> bool:
    """Check if event_key matches the expected format (40 hex chars)."""
    return bool(re.match(r"^[0-9a-fA-F]{40}$", event_key))


@router.get("/{event_key}")
def get_signal_summary(
    event_key: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get signal summary with state, onchain features, and verdict.

    Returns:
        JSON with signal state, onchain features, verdict, and cache info

    Raises:
        404: Signal not found
        500: Internal error
    """

    # Validate event_key format (40 hex characters)
    # Return 404 for invalid patterns to let other routes match
    if not is_valid_event_key(event_key):
        raise HTTPException(status_code=404, detail="Not Found")

    # Check Redis cache first
    r = get_redis()
    cache_key = f"sig:view:{event_key}"
    
    try:
        cached = r.get(cache_key)
        if cached:
            # Get remaining TTL
            ttl_sec = r.ttl(cache_key)
            result = json.loads(cached)
            result["cache"] = {"hit": True, "ttl_sec": max(0, ttl_sec)}
            return result
    except Exception as e:
        # Log but don't fail on cache errors
        print(f"[ERROR] Redis cache error for {event_key}: {e}")
    
    try:
        # Query signal state with features_snapshot
        row = db.execute(sa_text("""
            SELECT
                event_key,
                type,
                state,
                onchain_asof_ts,
                onchain_confidence,
                features_snapshot
            FROM signals
            WHERE event_key = :k
            LIMIT 1
        """), {"k": event_key}).mappings().first()
        
        if not row:
            raise HTTPException(status_code=404, detail="Not Found")
        
        # Extract features from features_snapshot.onchain
        features = None
        snap = row.get("features_snapshot")
        try:
            on = (snap or {}).get("onchain") if isinstance(snap, dict) else None
            if on:
                # Create lightweight features object
                features = type("F", (), {})()
                features.active_addr_pctl = on.get("active_addr_pctl")
                features.growth_ratio = on.get("growth_ratio")
                features.top10_share = on.get("top10_share")
                features.self_loop_ratio = on.get("self_loop_ratio")
                features.window_min = on.get("window_min", 60)
                # Use snapshot's asof_ts, fallback to signals.onchain_asof_ts
                asof = on.get("asof_ts")
                if asof:
                    try:
                        features.asof_ts = datetime.fromisoformat(asof.replace("Z", "+00:00"))
                    except Exception:
                        features.asof_ts = row.get("onchain_asof_ts")
                else:
                    features.asof_ts = row.get("onchain_asof_ts")
        except Exception as e:
            logger.warning("features_snapshot parse failed for %s: %s", event_key, e)
            features = None
        
        # Build response
        response = {
            "event_key": row["event_key"],
            "type": row["type"],
            "state": row["state"] or "candidate",
            "onchain": None,
            "verdict": {
                "decision": "insufficient",
                "confidence": 0.0,
                "note": "No onchain features available"
            },
            "cache": {
                "hit": False,
                "ttl_sec": 120
            }
        }
        
        # Add onchain features if available
        if features:
            asof = getattr(features, "asof_ts", None)
            if asof and asof.tzinfo is None:
                asof = asof.replace(tzinfo=timezone.utc)
            response["onchain"] = {
                "asof_ts": asof.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if asof else None,
                "window_min": getattr(features, "window_min", 60),
                "active_addr_pctl": float(Decimal(str(getattr(features, "active_addr_pctl", 0) or 0)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)),
                "growth_ratio": float(Decimal(str(getattr(features, "growth_ratio", 0) or 0)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)),
                "top10_share": float(Decimal(str(getattr(features, "top10_share", 0) or 0)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)),
                "self_loop_ratio": float(Decimal(str(getattr(features, "self_loop_ratio", 0) or 0)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
            }
            
            # Evaluate verdict using rules engine
            try:
                rules = load_rules()
                feature_obj = OnchainFeature(
                    active_addr_pctl=float(features.active_addr_pctl or 0),
                    growth_ratio=float(features.growth_ratio or 0),
                    top10_share=float(features.top10_share or 0),
                    self_loop_ratio=float(features.self_loop_ratio or 0)
                )
                
                verdict = evaluate(feature_obj, rules, window_min=features.window_min)
                
                response["verdict"] = {
                    "decision": verdict.decision,
                    "confidence": float(Decimal(str(verdict.confidence)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)),
                    "note": verdict.note or ""
                }
            except Exception as e:
                # Log but use fallback verdict
                print(f"[ERROR] Rules evaluation failed for {event_key}: {e}")
                response["verdict"]["note"] = "Rules evaluation failed"
        
        elif row["onchain_confidence"] is not None:
            # Use stored confidence if no features but confidence exists
            response["verdict"]["confidence"] = serialize_decimal(row["onchain_confidence"])
            if row["state"] == "verified":
                response["verdict"]["decision"] = "upgrade"
                response["verdict"]["note"] = "Upgraded based on stored verdict"
            elif row["state"] == "downgraded":
                response["verdict"]["decision"] = "downgrade"
                response["verdict"]["note"] = "Downgraded based on stored verdict"
        
        # Cache the response
        try:
            r.setex(cache_key, 120, json.dumps(response))
        except Exception as e:
            # Log but don't fail on cache errors
            print(f"[ERROR] Failed to cache response for {event_key}: {e}")
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Failed to get signal summary for {event_key}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")