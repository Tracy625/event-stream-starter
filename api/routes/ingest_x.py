"""
X (Twitter) ingestion API routes.

Provides endpoints for manual polling and statistics.
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from fastapi import APIRouter, Query
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker

# Import polling job
import sys
if '/app' not in sys.path:
    sys.path.append('/app')
from worker.jobs.x_kol_poll import run_once
from api.metrics import log_json

router = APIRouter(prefix="/ingest/x", tags=["x-ingestion"])


def get_db_session():
    """Get database session for stats queries."""
    postgres_url = os.getenv("POSTGRES_URL", "postgresql://app:app@db:5432/app")
    engine = create_engine(postgres_url)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


@router.get("/kol/poll")
async def poll_kol_tweets(once: bool = Query(True, description="Execute single polling cycle")):
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
                "error": "X ingestion disabled"
            }
        
        # Execute polling
        stats = run_once()
        
        # Build response with standard field names
        response = {
            "fetched": stats.get("fetched", 0),
            "inserted": stats.get("inserted", 0),
            "deduped": stats.get("dedup_hit", 0),  # Map dedup_hit to deduped
            "degraded": False
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
            "error": str(e)
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
        query = sa_text("""
            SELECT COUNT(*) as count
            FROM raw_posts
            WHERE source = 'x'
            AND ts >= :one_hour_ago
        """)
        
        result = session.execute(query, {"one_hour_ago": one_hour_ago}).first()
        inserted_count = result.count if result else 0
        
        session.close()
        
        # Build response (minimal implementation)
        response = {
            "last_hour": {
                "fetched": 0,  # Not tracked in current implementation
                "inserted": inserted_count,
                "deduped": 0   # Not tracked in current implementation
            }
        }
        
        # Log stats query
        log_json(stage="x.api.stats", window="1h", inserted=inserted_count)
        
        return response
        
    except Exception as e:
        # Return empty stats on error
        error_response = {
            "last_hour": {
                "fetched": 0,
                "inserted": 0,
                "deduped": 0
            },
            "error": str(e)
        }
        log_json(stage="x.api.stats.error", error=str(e))
        return error_response