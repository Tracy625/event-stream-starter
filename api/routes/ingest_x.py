"""
X (Twitter) ingestion API routes.

Provides endpoints for manual polling and statistics.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy import text as sa_text
from sqlalchemy.orm import sessionmaker

# Import polling job (tolerant to import errors so the API doesn't crash)
try:
    from worker.jobs.x_kol_poll import run_once  # type: ignore

    _poll_import_error = None
except Exception as _e:  # pragma: no cover
    _poll_import_error = _e

    def run_once():
        # Minimal degraded placeholder; keeps the API alive when worker code is unavailable
        return {
            "fetched": 0,
            "inserted": 0,
            "dedup_hit": 0,
            "degraded": True,
            "error": str(_e),
        }


from api.core import idempotency
from api.core.metrics_store import log_json

router = APIRouter(prefix="/ingest/x", tags=["x-ingestion"])

# --- Replay helpers -------------------------------------------------------


class XReplayPayload(BaseModel):
    """Minimal payload envelope for replay endpoint."""

    payload: Dict[str, Any] = Field(default_factory=dict)


@router.post("/replay", status_code=204, summary="Replay endpoint for source=x")
def ingest_x_replay(
    body: XReplayPayload,
    idempotency_key: Optional[str] = Header(
        None, convert_underscores=False, alias="Idempotency-Key"
    ),
):
    """Lightweight replay entry-point guarded by Idempotency-Key."""

    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key")

    if idempotency.seen(idempotency_key):
        return Response(status_code=204)

    # TODO: hook into actual ingestion logic if needed (e.g., process_x(body.payload))
    idempotency.mark(idempotency_key)
    log_json(
        stage="x.replay.accepted", idempotency_key=idempotency_key, payload=body.payload
    )
    return Response(status_code=204)


# -------------------------------------------------------------------------


# DB session factory (module-level engine to avoid per-request engine creation)
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://app:app@db:5432/app")
ENGINE = create_engine(POSTGRES_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=ENGINE)


def get_db_session():
    """Get database session for stats queries."""
    return SessionLocal()


@router.get("/kol/poll")
async def poll_kol_tweets(
    once: bool = Query(True, description="Execute single polling cycle")
):
    """
    Trigger manual KOL tweet collection.

    Args:
        once: If true, executes single polling cycle (default: true)

    Returns:
        JSON with fetched, inserted, deduped, degraded counts
    """
    try:
        # Check if feature is enabled
        if os.getenv("ENABLE_X_INGESTOR", "true").lower() == "false":
            return {
                "fetched": 0,
                "inserted": 0,
                "deduped": 0,
                "degraded": True,
                "error": "X ingestion disabled",
            }

        # Execute polling
        stats = run_once()

        # Build response with standard field names
        response = {
            "fetched": stats.get("fetched", 0),
            "inserted": stats.get("inserted", 0),
            "deduped": stats.get("dedup_hit", 0),  # Map dedup_hit to deduped
            "degraded": False,
        }

        # Check for degradation
        if response["fetched"] == 0 and response["inserted"] == 0:
            response["degraded"] = True

        # Log API call
        log_json(stage="x.api.poll", once=once, result=response)

        return response

    except Exception as e:
        # Return degraded response on error
        error_response = {
            "fetched": 0,
            "inserted": 0,
            "deduped": 0,
            "degraded": True,
            "error": str(e),
        }
        log_json(stage="x.api.poll.error", error=str(e))
        return error_response


@router.get("/kol/stats")
async def get_kol_stats():
    """
    Get KOL collection statistics for the last hour.

    Returns:
        JSON with last_hour stats (fetched, inserted, deduped)
    """
    try:
        session = get_db_session()

        # Calculate 1 hour ago
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

        # Query inserted count in last hour
        query = sa_text(
            """
            SELECT COUNT(*) as count
            FROM raw_posts
            WHERE source = 'x'
            AND ts >= :one_hour_ago
        """
        )

        result = session.execute(query, {"one_hour_ago": one_hour_ago}).first()
        inserted_count = result.count if result else 0

        session.close()

        # Build response (minimal implementation)
        response = {
            "last_hour": {
                "fetched": 0,  # Not tracked in current implementation
                "inserted": inserted_count,
                "deduped": 0,  # Not tracked in current implementation
            }
        }

        # Log stats query
        log_json(stage="x.api.stats", window="1h", inserted=inserted_count)

        return response

    except Exception as e:
        # Return empty stats on error
        error_response = {
            "last_hour": {"fetched": 0, "inserted": 0, "deduped": 0},
            "error": str(e),
        }
        log_json(stage="x.api.stats.error", error=str(e))
        return error_response
