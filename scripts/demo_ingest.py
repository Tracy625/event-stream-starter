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

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import db functions directly from the module file
import importlib.util

from api.dedup import DeduplicationService

# Import pipeline modules
from api.filter import analyze_sentiment, filters_text
from api.refiner import RulesRefiner

spec = importlib.util.spec_from_file_location("api_db_module", "api/db.py")
api_db_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api_db_module)
insert_raw_post = api_db_module.insert_raw_post
with_session = api_db_module.with_session

from api.core.metrics_store import log_json as metrics_log_json
from api.database import build_engine_from_env, get_sessionmaker
from api.services.topic_analyzer import TopicAnalyzer
from worker.pipeline.is_memeable_topic import MemeableTopicDetector


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
            "urls": ["https://twitter.com/status/123456"],
        },
        {
            "author": "defi_analyst",
            "text": "New airdrop alert! $ARB token claim is now live. Don't miss out on this opportunity. The contract is solid and promising.",
            "ts": base_time - timedelta(minutes=20),
            "urls": ["https://arbitrum.io/airdrop"],
        },
        {
            "author": "whale_copy",  # Different author, same text for dedup test
            "text": "Just discovered $PEPE launching on mainnet! Contract: 0x6982508145454ce325ddbe47a25d4ec3d2311933. This could be the next moon gem 🚀",
            "ts": base_time - timedelta(minutes=10),
            "urls": ["https://twitter.com/status/123457"],
        },
    ]

    return samples


def log_json(data: Dict[str, Any]) -> None:
    """Output a JSON log line prefixed with [JSON]."""
    json_str = json.dumps(data, separators=(",", ":"))
    print(f"[JSON] {json_str}")


def process_post(
    post: Dict[str, Any], dedup_service: DeduplicationService, SessionClass
) -> Dict[str, Any]:
    """
    Process a single post through the full pipeline with timing metrics.

    Returns dict with processing results for logging.
    """
    # Track overall pipeline start
    pipeline_start = time.perf_counter()

    # Get latency budgets from environment
    budget_filter = int(os.getenv("LATENCY_BUDGET_MS_FILTER", "1000"))
    budget_refine = int(os.getenv("LATENCY_BUDGET_MS_REFINE", "1000"))
    budget_total = int(os.getenv("LATENCY_BUDGET_MS_TOTAL", "2000"))

    result = {
        "author": post["author"],
        "passed_filter": False,
        "sentiment": None,
        "event_key": None,
        "is_duplicate": None,
        "db_inserted": False,
        "raw_post_id": None,
        "event_upserted": False,
        "timings": {},
        "topic_detected": False,
        "topic_id": None,
    }

    text = post["text"]

    # Step 1: Filter with timing
    filter_start = time.perf_counter()
    filter_backend = "rules"  # Default backend

    try:
        passed = filters_text(text)
        if passed:
            sentiment_label, sentiment_score = analyze_sentiment(text)
            result["sentiment"] = f"{sentiment_label} ({sentiment_score:.2f})"
    except Exception as e:
        passed = False
        sentiment_label, sentiment_score = None, None

    filter_ms = int(round((time.perf_counter() - filter_start) * 1000))
    result["timings"]["t_filter_ms"] = filter_ms

    # Check if filter exceeded budget
    if filter_ms > budget_filter:
        filter_backend = "rules"  # Force degradation
        metrics_log_json(
            stage="degradation",
            phase="filter",
            exceeded_ms=filter_ms,
            budget_ms=budget_filter,
            backend="rules",
        )

    if not passed:
        print(f"[FILTER] Post from {post['author']} filtered out - not crypto-relevant")

        # Calculate total time
        total_ms = int(round((time.perf_counter() - pipeline_start) * 1000))
        result["timings"]["t_total_ms"] = total_ms

        # Log JSON for filtered out post
        log_json(
            {
                "stage": "pipeline",
                "author": post["author"],
                "passed": False,
                "event_key": None,
                "dedup": None,
                "db": {"raw_post_id": None, "event_upserted": False},
                "ts": post["ts"].isoformat(),
                "t_filter_ms": filter_ms,
                "t_total_ms": total_ms,
                "backend_filter": filter_backend,
            }
        )
        return result

    result["passed_filter"] = True
    print(
        f"[FILTER] Post from {post['author']} passed - sentiment: {result['sentiment']}"
    )

    # Step 2: Refine with timing
    refine_start = time.perf_counter()
    refine_backend = "rules"

    # Use RulesRefiner from api.refiner
    refiner = RulesRefiner()
    refined_result = refiner.refine([text])  # Pass as list of evidence texts

    # Map fields from refiner output to expected format
    # Generate event_key from text hash
    import hashlib

    text_hash = hashlib.sha256(text.encode()).hexdigest()[:12]
    event_key = f"EVENT:{text_hash}"

    refined = {
        "event_key": event_key,
        "type": refined_result.get("type", "market-update"),
        "score": refined_result.get("confidence", 0.5),
        "keywords": refined_result.get("impacted_assets", []),
        "assets": {
            "symbol": (
                refined_result.get("impacted_assets", [None])[0]
                if refined_result.get("impacted_assets")
                else None
            ),
            "ca": None,  # Refiner doesn't extract contract addresses
        },
    }

    result["event_key"] = event_key

    refine_ms = int(round((time.perf_counter() - refine_start) * 1000))
    result["timings"]["t_refine_ms"] = refine_ms

    # Check if refine exceeded budget
    if refine_ms > budget_refine:
        refine_backend = "rules"  # Force degradation
        metrics_log_json(
            stage="degradation",
            phase="refine",
            exceeded_ms=refine_ms,
            budget_ms=budget_refine,
            backend="rules",
        )

    print(
        f"[REFINE] Generated event_key: {event_key}, type: {refined['type']}, score: {refined['score']:.2f}"
    )

    # Step 3: Dedup with timing
    dedup_start = time.perf_counter()

    is_duplicate = dedup_service.is_duplicate(event_key, post["ts"])
    result["is_duplicate"] = is_duplicate

    if is_duplicate:
        print(
            f"[DEDUP] DUPLICATE HIT - event_key {event_key} already seen within window"
        )
    else:
        print(f"[DEDUP] New event - recording event_key {event_key}")
        dedup_service.record(event_key, post["ts"])

    dedup_ms = int(round((time.perf_counter() - dedup_start) * 1000))
    result["timings"]["t_dedup_ms"] = dedup_ms

    # Step 3.5: Topic Detection (before event aggregation)
    print("[TOPIC] Starting topic detection...")
    topic_start = time.perf_counter()
    topic_hash_override = None
    topic_entities = None

    try:
        detector = MemeableTopicDetector()
        is_meme, entities, confidence = detector.is_memeable(
            text, {"author": post["author"]}
        )

        if is_meme and entities:
            analyzer = TopicAnalyzer()

            # Use private method since no public method exists
            if hasattr(analyzer, "_generate_topic_id"):
                topic_id = analyzer._generate_topic_id(entities)
                topic_hash_override = topic_id
                topic_entities = entities  # Keep as list

                result["topic_detected"] = True
                result["topic_id"] = topic_id

                metrics_log_json(
                    stage="topic.detected",
                    topic_id=topic_id,
                    entities=entities,
                    confidence=confidence,
                )
                print(f"[TOPIC] Detected memeable topic: {entities} -> {topic_id}")
            else:
                metrics_log_json(
                    stage="topic.detection.error",
                    error="TopicAnalyzer has no _generate_topic_id method",
                )
    except Exception as e:
        metrics_log_json(stage="topic.detection.error", error=str(e))
        # Continue processing even if topic detection fails

    topic_ms = int(round((time.perf_counter() - topic_start) * 1000))
    result["timings"]["t_topic_ms"] = topic_ms

    # Step 4: Event aggregation (NEW)
    # Always aggregate events - duplicates increase evidence_count
    event_start = time.perf_counter()
    event_result = None
    event_aggregated = False

    # Event aggregation MUST come from api.events (avoid name clash with api.db)
    from api.events import upsert_event as events_upsert_event

    # Build enriched post dict for event aggregation (include required type/text for key)
    enriched_post = {
        "type": refined.get("type", "market-update"),
        "text": text,
        "symbol": refined.get("assets", {}).get("symbol"),
        "token_ca": refined.get("assets", {}).get("ca"),
        "keywords": refined.get("keywords", []),
        "sentiment_label": sentiment_label,
        "sentiment_score": sentiment_score,
        "created_ts": post["ts"],
    }

    # Add topic data if detected (will be written to DB)
    if topic_hash_override:
        enriched_post["topic_hash"] = topic_hash_override
        enriched_post["topic_entities"] = topic_entities

    try:
        # Always perform event aggregation (even for duplicates - increases evidence_count)
        event_result = events_upsert_event(enriched_post)
        result["event_aggregation"] = event_result
        event_aggregated = True

        # Calculate timing before logging
        event_ms = int(round((time.perf_counter() - event_start) * 1000))
        result["timings"]["t_event_ms"] = event_ms

        # Log event aggregation
        metrics_log_json(
            stage="pipeline.event",
            event_key=event_result["event_key"],
            evidence_count=event_result["evidence_count"],
            candidate_score=event_result["candidate_score"],
            symbol=enriched_post.get("symbol"),
            t_event_ms=event_ms,
        )

        print(
            f"[EVENT] Aggregated event_key={event_result['event_key']}, evidence_count={event_result['evidence_count']}, candidate_score={event_result['candidate_score']:.2f}"
        )
    except Exception as e:
        print(f"[EVENT] Error during event aggregation: {e}")
        result["event_aggregation"] = {"error": str(e)}
        event_aggregated = False

        # Calculate timing even on error
        event_ms = int(round((time.perf_counter() - event_start) * 1000))
        result["timings"]["t_event_ms"] = event_ms

    # Step 5: Database with timing (existing code)
    db_start = time.perf_counter()
    raw_id = None

    try:
        with with_session(SessionClass) as session:
            # Always insert raw post
            raw_id = insert_raw_post(
                session=session,
                author=post["author"],
                text=text,
                ts=post["ts"],
                urls=post.get("urls", []),
            )
            print(f"[DB] Inserted raw_post id={raw_id}")
            result["raw_post_id"] = raw_id

            # Legacy event table update removed - now handled by api.events.upsert_event
            # The new event aggregation happens in Step 4 above
            # Track that event was aggregated (not using old upsert)
            result["event_upserted"] = event_aggregated

            result["db_inserted"] = True

    except Exception as e:
        print(f"[DB] Error: {e}")
        result["db_inserted"] = False

        db_ms = int(round((time.perf_counter() - db_start) * 1000))
        result["timings"]["t_db_ms"] = db_ms

        # Calculate total time
        total_ms = int(round((time.perf_counter() - pipeline_start) * 1000))
        result["timings"]["t_total_ms"] = total_ms

        # Log JSON for error
        log_json(
            {
                "stage": "error",
                "author": post["author"],
                "passed": True,
                "event_key": event_key,
                "dedup": "hit" if is_duplicate else "miss",
                "db": {"raw_post_id": None, "event_upserted": event_aggregated},
                "ts": post["ts"].isoformat(),
                "error": str(e),
                "t_filter_ms": filter_ms,
                "t_refine_ms": refine_ms,
                "t_dedup_ms": dedup_ms,
                "t_event_ms": event_ms,
                "t_db_ms": db_ms,
                "t_total_ms": total_ms,
                "backend_filter": filter_backend,
                "backend_refine": refine_backend,
            }
        )
        return result

    db_ms = int(round((time.perf_counter() - db_start) * 1000))
    result["timings"]["t_db_ms"] = db_ms

    # Calculate total time
    total_ms = int(round((time.perf_counter() - pipeline_start) * 1000))
    result["timings"]["t_total_ms"] = total_ms

    # Check if total exceeded budget
    if total_ms > budget_total:
        metrics_log_json(
            stage="degradation",
            phase="total",
            exceeded_ms=total_ms,
            budget_ms=budget_total,
            backend="rules",
        )

    # Log JSON for successful processing
    log_json(
        {
            "stage": "pipeline",
            "author": post["author"],
            "passed": True,
            "event_key": event_key,
            "dedup": "hit" if is_duplicate else "miss",
            "db": {"raw_post_id": raw_id, "event_upserted": event_aggregated},
            "ts": post["ts"].isoformat(),
            "t_filter_ms": filter_ms,
            "t_refine_ms": refine_ms,
            "t_dedup_ms": dedup_ms,
            "t_event_ms": event_ms,
            "t_db_ms": db_ms,
            "t_total_ms": total_ms,
            "backend_filter": filter_backend,
            "backend_refine": refine_backend,
        }
    )

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

    # Event aggregation stats
    unique_event_keys = set()
    total_evidence_count = 0

    for r in results:
        if "event_aggregation" in r and isinstance(r["event_aggregation"], dict):
            if "event_key" in r["event_aggregation"]:
                unique_event_keys.add(r["event_aggregation"]["event_key"])
            if "evidence_count" in r["event_aggregation"]:
                # Only count the last evidence_count for each unique key
                pass  # Will be calculated differently

    # Get actual evidence counts from event aggregation results
    event_evidence_map = {}
    for r in results:
        if "event_aggregation" in r and isinstance(r["event_aggregation"], dict):
            if (
                "event_key" in r["event_aggregation"]
                and "evidence_count" in r["event_aggregation"]
            ):
                event_evidence_map[r["event_aggregation"]["event_key"]] = r[
                    "event_aggregation"
                ]["evidence_count"]

    total_evidence_count = sum(event_evidence_map.values())

    print(f"Total posts: {len(posts)}")
    print(f"Passed filter: {passed}")
    print(f"Duplicates found: {duplicates}")
    print(f"DB inserts: {inserted}")
    print(f"Unique events: {passed - duplicates}")
    print(f"Unique event keys (aggregated): {len(unique_event_keys)}")
    print(f"Total evidence count: {total_evidence_count}")

    # Show event keys
    print("\nEvent keys generated:")
    for r in results:
        if r["event_key"]:
            dup_marker = " (DUPLICATE)" if r["is_duplicate"] else ""
            agg_info = ""
            if "event_aggregation" in r and isinstance(r["event_aggregation"], dict):
                if "evidence_count" in r["event_aggregation"]:
                    agg_info = (
                        f" [evidence_count={r['event_aggregation']['evidence_count']}]"
                    )
            print(f"  - {r['event_key']}{dup_marker}{agg_info}")

    # Log summary JSON
    log_json(
        {
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
            "unique_events": passed - duplicates,
            "unique_event_keys": len(unique_event_keys),
            "total_evidence_count": total_evidence_count,
        }
    )

    print("\n✅ Demo ingestion completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
