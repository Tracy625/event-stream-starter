#!/usr/bin/env python3
"""
Event verification script for validating aggregation results.

Queries the events table and outputs JSON statistics about event aggregation.

Usage:
    DATABASE_URL=postgresql://user:pass@host/db python scripts/verify_events.py

Output:
    Single JSON line with: total, unique_event_keys, total_evidence, mean_evidence, p95_evidence
"""

import os
import sys
import json
from sqlalchemy import create_engine, text

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.metrics import log_json


def verify_events():
    """Query events table and compute statistics."""
    
    # Check for DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        log_json(
            stage="verify.events.error",
            error="DATABASE_URL environment variable not set"
        )
        sys.exit(1)
    
    try:
        # Create engine
        engine = create_engine(database_url, echo=False)
        
        # Query for statistics
        query = text("""
            SELECT 
                COALESCE(COUNT(*), 0) as total,
                COALESCE(COUNT(DISTINCT event_key), 0) as unique_event_keys,
                COALESCE(SUM(evidence_count), 0) as total_evidence,
                COALESCE(AVG(evidence_count), 0.0) as mean_evidence,
                COALESCE(
                    percentile_disc(0.95) WITHIN GROUP (ORDER BY evidence_count),
                    0
                ) as p95_evidence
            FROM events
        """)
        
        with engine.connect() as conn:
            result = conn.execute(query).fetchone()
            
            # Build stats dictionary
            stats = {
                "total": int(result[0]),
                "unique_event_keys": int(result[1]),
                "total_evidence": int(result[2]) if result[2] is not None else 0,
                "mean_evidence": float(result[3]) if result[3] is not None else 0.0,
                "p95_evidence": int(result[4]) if result[4] is not None else 0
            }
            
    except Exception as e:
        # Check if it's a table doesn't exist error
        error_str = str(e)
        if "events" in error_str and ("does not exist" in error_str or "doesn't exist" in error_str):
            # Table doesn't exist - return zeros
            stats = {
                "total": 0,
                "unique_event_keys": 0,
                "total_evidence": 0,
                "mean_evidence": 0.0,
                "p95_evidence": 0
            }
        else:
            # Other error - log and exit
            log_json(
                stage="verify.events.error",
                error=error_str,
                error_type=type(e).__name__
            )
            sys.exit(1)
    
    # Log the stats
    log_json(
        stage="verify.events",
        **stats
    )
    
    # Print JSON to stdout
    print(json.dumps(stats, separators=(',', ':')))
    
    return 0


if __name__ == "__main__":
    sys.exit(verify_events())