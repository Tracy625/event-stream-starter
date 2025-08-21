#!/usr/bin/env python3
"""
Demo ingestion script for testing the full pipeline.

This script demonstrates the complete data processing pipeline:
1. Filter - Check for crypto relevance and analyze sentiment
2. Refine - Extract structured data and generate event keys
3. Dedup - Check for duplicate events within time window
4. DB - Insert raw posts and upsert events

DEMO_MODE:
- True (default): Use hardcoded sample crypto posts
- False: TODO - integrate with external source (not implemented)

Usage:
    python scripts/demo_ingest.py
    
    # Or with environment variable
    DEMO_MODE=False python scripts/demo_ingest.py
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import pipeline modules
from api.filter import filters_text, analyze_sentiment
from api.refine import refine_post
from api.dedup import DeduplicationService
from api.db import insert_raw_post, upsert_event, with_session
from api.database import build_engine_from_env, get_sessionmaker


def get_sample_posts() -> List[Dict[str, Any]]:
    """
    Return hardcoded sample crypto-related posts for demo.
    
    Each post has: author, text, timestamp, urls
    """
    base_time = datetime.now(timezone.utc)
    
    samples = [
        {
            "author": "crypto_whale_123",
            "text": "Just discovered $PEPE launching on mainnet! Contract: 0x6982508145454ce325ddbe47a25d4ec3d2311933. This could be the next moon gem 🚀",
            "ts": base_time - timedelta(minutes=30),
            "urls": ["https://twitter.com/status/123456"]
        },
        {
            "author": "defi_analyst",
            "text": "New airdrop alert! $ARB token claim is now live. Don't miss out on this opportunity. The contract is solid and promising.",
            "ts": base_time - timedelta(minutes=20),
            "urls": ["https://arbitrum.io/airdrop"]
        },
        {
            "author": "whale_copy",  # Different author, same text for dedup test
            "text": "Just discovered $PEPE launching on mainnet! Contract: 0x6982508145454ce325ddbe47a25d4ec3d2311933. This could be the next moon gem 🚀",
            "ts": base_time - timedelta(minutes=10),
            "urls": ["https://twitter.com/status/123457"]
        }
    ]
    
    return samples


def log_json(data: Dict[str, Any]) -> None:
    """Output a JSON log line prefixed with [JSON]."""
    json_str = json.dumps(data, separators=(',', ':'))
    print(f"[JSON] {json_str}")


def process_post(post: Dict[str, Any], dedup_service: DeduplicationService, SessionClass) -> Dict[str, Any]:
    """
    Process a single post through the full pipeline.
    
    Returns dict with processing results for logging.
    """
    result = {
        "author": post["author"],
        "passed_filter": False,
        "sentiment": None,
        "event_key": None,
        "is_duplicate": None,
        "db_inserted": False,
        "raw_post_id": None,
        "event_upserted": False
    }
    
    # Step 1: Filter
    text = post["text"]
    if not filters_text(text):
        print(f"[FILTER] Post from {post['author']} filtered out - not crypto-relevant")
        
        # Log JSON for filtered out post
        log_json({
            "stage": "pipeline",
            "author": post["author"],
            "passed": False,
            "event_key": None,
            "dedup": None,
            "db": {"raw_post_id": None, "event_upserted": False},
            "ts": post["ts"].isoformat()
        })
        return result
    
    result["passed_filter"] = True
    
    # Analyze sentiment
    sentiment_label, sentiment_score = analyze_sentiment(text)
    result["sentiment"] = f"{sentiment_label} ({sentiment_score:.2f})"
    print(f"[FILTER] Post from {post['author']} passed - sentiment: {result['sentiment']}")
    
    # Step 2: Refine
    refined = refine_post(text)
    event_key = refined["event_key"]
    result["event_key"] = event_key
    print(f"[REFINE] Generated event_key: {event_key}, type: {refined['type']}, score: {refined['score']:.2f}")
    
    # Step 3: Dedup
    is_duplicate = dedup_service.is_duplicate(event_key, post["ts"])
    result["is_duplicate"] = is_duplicate
    
    if is_duplicate:
        print(f"[DEDUP] DUPLICATE HIT - event_key {event_key} already seen within window")
    else:
        print(f"[DEDUP] New event - recording event_key {event_key}")
        dedup_service.record(event_key, post["ts"])
    
    # Step 4: Database
    raw_id = None
    event_upserted = False
    
    try:
        with with_session(SessionClass) as session:
            # Always insert raw post
            raw_id = insert_raw_post(
                session=session,
                author=post["author"],
                text=text,
                ts=post["ts"],
                urls=post.get("urls", [])
            )
            print(f"[DB] Inserted raw_post id={raw_id}")
            result["raw_post_id"] = raw_id
            
            # Only upsert event if not duplicate
            if not is_duplicate:
                evidence = {
                    "raw_ids": [raw_id],
                    "assets": refined.get("assets", {}),
                    "sentiment": {"label": sentiment_label, "score": sentiment_score}
                }
                
                upsert_event(
                    session=session,
                    event_key=event_key,
                    type=refined["type"],
                    score=refined["score"],
                    summary=refined["summary"],
                    evidence=evidence,
                    ts=post["ts"]
                )
                print(f"[DB] Upserted event with key={event_key}")
                event_upserted = True
                result["event_upserted"] = True
            
            result["db_inserted"] = True
            
    except Exception as e:
        print(f"[DB] Error: {e}")
        result["db_inserted"] = False
        
        # Log JSON for error
        log_json({
            "stage": "error",
            "author": post["author"],
            "passed": True,
            "event_key": event_key,
            "dedup": "hit" if is_duplicate else "miss",
            "db": {"raw_post_id": None, "event_upserted": None},
            "ts": post["ts"].isoformat(),
            "error": str(e)
        })
        return result
    
    # Log JSON for successful processing
    log_json({
        "stage": "pipeline",
        "author": post["author"],
        "passed": True,
        "event_key": event_key,
        "dedup": "hit" if is_duplicate else "miss",
        "db": {"raw_post_id": raw_id, "event_upserted": event_upserted},
        "ts": post["ts"].isoformat()
    })
    
    return result


def main():
    """Main demo ingestion flow."""
    # Check DEMO_MODE
    demo_mode = os.getenv("DEMO_MODE", "True").lower() in ["true", "1", "yes"]
    
    print(f"=== Demo Ingestion Script ===")
    print(f"DEMO_MODE: {demo_mode}")
    print()
    
    if not demo_mode:
        print("TODO: External source ingestion not implemented")
        print("Please use DEMO_MODE=True for now")
        return 1
    
    # Get sample posts
    posts = get_sample_posts()
    print(f"Processing {len(posts)} sample posts...")
    print()
    
    # Initialize services
    try:
        # Database
        engine = build_engine_from_env()
        SessionClass = get_sessionmaker(engine)
        print("[INIT] Database connection established")
        
        # Dedup service (in-memory for demo)
        redis_url = os.getenv("REDIS_URL")
        dedup_service = DeduplicationService(redis_url=redis_url, window_sec=3600)
        mode = "Redis" if dedup_service.redis_client else "Memory"
        print(f"[INIT] Dedup service initialized ({mode} mode)")
        print()
        
    except Exception as e:
        print(f"[ERROR] Failed to initialize: {e}")
        return 1
    
    # Process each post
    results = []
    for i, post in enumerate(posts, 1):
        print(f"--- Processing post {i}/{len(posts)} ---")
        result = process_post(post, dedup_service, SessionClass)
        results.append(result)
        print()
    
    # Summary
    print("=== Processing Summary ===")
    passed = sum(1 for r in results if r["passed_filter"])
    duplicates = sum(1 for r in results if r["is_duplicate"])
    inserted = sum(1 for r in results if r["db_inserted"])
    
    print(f"Total posts: {len(posts)}")
    print(f"Passed filter: {passed}")
    print(f"Duplicates found: {duplicates}")
    print(f"DB inserts: {inserted}")
    print(f"Unique events: {passed - duplicates}")
    
    # Show event keys
    print("\nEvent keys generated:")
    for r in results:
        if r["event_key"]:
            dup_marker = " (DUPLICATE)" if r["is_duplicate"] else ""
            print(f"  - {r['event_key']}{dup_marker}")
    
    # Log summary JSON
    log_json({
        "stage": "summary",
        "author": "system",
        "passed": True,
        "event_key": "summary",
        "dedup": f"{duplicates} hits" if duplicates else "no hits",
        "db": {"raw_post_id": inserted, "event_upserted": passed - duplicates},
        "ts": datetime.now(timezone.utc).isoformat(),
        "total_posts": len(posts),
        "passed_filter": passed,
        "duplicates_found": duplicates,
        "unique_events": passed - duplicates
    })
    
    print("\n✅ Demo ingestion completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())