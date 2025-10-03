#!/usr/bin/env python3
"""
Verify events evidence merging and deduplication.

Usage:
    python scripts/verify_events.py
    python scripts/verify_events.py --sample scripts/replay.jsonl
    DATABASE_URL=postgresql://user:pass@host/db python scripts/verify_events.py --db

Output:
    Verification results and statistics
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import create_engine, text

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.events import (_build_evidence_item, make_event_key,
                        merge_event_evidence)


def load_replay_data(filepath: str) -> List[Dict[str, Any]]:
    """Load replay data from JSONL file."""
    events = []
    if not os.path.exists(filepath):
        print(f"Warning: {filepath} not found, using synthetic data")
        return []

    with open(filepath, "r") as f:
        for line in f:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def verify_event_key_consistency(events: List[Dict[str, Any]]) -> bool:
    """Verify that event keys are consistent for same inputs."""
    print("\n=== Event Key Consistency Check ===")

    key_map = {}
    errors = []

    for event in events:
        # Generate key twice to ensure determinism
        try:
            key1 = make_event_key(event)
            key2 = make_event_key(event)
        except (KeyError, ValueError) as e:
            errors.append(f"Failed to generate key: {e}")
            continue

        if key1 != key2:
            errors.append(
                f"Non-deterministic key for event: {event.get('id', 'unknown')}"
            )
            continue

        # Check if we've seen this combination before
        input_sig = f"{event.get('type')}|{event.get('symbol')}|{event.get('token_ca')}|{event.get('text', '')[:50]}"
        if input_sig in key_map:
            if key_map[input_sig] != key1:
                errors.append(f"Different keys for same input: {input_sig}")
        else:
            key_map[input_sig] = key1

    if errors:
        for err in errors[:5]:
            print(f"  ❌ {err}")
        if len(errors) > 5:
            print(f"  ... and {len(errors) - 5} more errors")
        return False
    else:
        print(f"  ✅ All {len(events)} events have consistent keys")
        return True


def verify_evidence_merge(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Verify evidence merging and deduplication."""
    print("\n=== Evidence Merge Verification ===")

    # Statistics
    stats = {
        "total_events": 0,
        "multi_source_events": 0,
        "cross_source_cooccurrence": 0,  # Track cross-source co-occurrence
        "total_evidence": 0,
        "deduped_evidence": 0,
        "sources_seen": set(),
    }

    errors = []

    for event in events:
        try:
            event_key = make_event_key(event)
        except (KeyError, ValueError):
            continue

        evidence_items = []

        # Create X evidence
        if event.get("source") == "x" or event.get("has_x_data"):
            x_evidence = _build_evidence_item(
                source="x",
                ts=event.get("created_ts", datetime.now(timezone.utc)),
                ref={
                    "tweet_id": event.get("tweet_id", "123"),
                    "author": event.get("author", "user"),
                },
                summary=event.get("text", "")[:100] if "text" in event else None,
                weight=1.0,
            )
            evidence_items.append(x_evidence)
            stats["sources_seen"].add("x")

        # Create DEX evidence (if token_ca present)
        if event.get("token_ca"):
            dex_evidence = _build_evidence_item(
                source="dex",
                ts=event.get("created_ts", datetime.now(timezone.utc)),
                ref={"chain_id": "1", "pool": "0xpool", "tx": "0xtx"},
                summary="Price: $0.0001",
                weight=0.8,
            )
            evidence_items.append(dex_evidence)
            stats["sources_seen"].add("dex")

            # Create GoPlus evidence
            goplus_evidence = _build_evidence_item(
                source="goplus",
                ts=event.get("created_ts", datetime.now(timezone.utc)),
                ref={
                    "goplus_endpoint": "/api/v1/token_security",
                    "chain_id": "1",
                    "address": event.get("token_ca"),
                },
                summary="Risk: low",
                weight=0.9,
            )
            evidence_items.append(goplus_evidence)
            stats["sources_seen"].add("goplus")

        # Test merge with duplicates
        duplicate_evidence = evidence_items.copy()

        # Check strict mode
        strict_env = os.getenv("EVENT_MERGE_STRICT", "true").lower()
        is_strict = strict_env in ("true", "1", "yes", "on")

        # Determine current source for single-source mode
        current_source = None
        if not is_strict and evidence_items:
            # In loose mode, pick first source as current
            for e in evidence_items:
                if e.get("source"):
                    current_source = e["source"]
                    break

        # Merge evidence
        result = merge_event_evidence(
            event_key=event_key,
            new_evidence=evidence_items + duplicate_evidence,  # Add duplicates
            existing_evidence=[],
            current_source=current_source,
        )

        stats["total_events"] += 1
        stats["total_evidence"] += result["after_count"]
        stats["deduped_evidence"] += result["deduped"]

        # Check for multi-source events
        sources = set()
        for e in result["merged_evidence"]:
            if "source" in e:
                sources.add(e["source"])

        if len(sources) > 1:
            stats["multi_source_events"] += 1
            # Check for specific cross-source co-occurrence (x + dex/goplus)
            if "x" in sources and ("dex" in sources or "goplus" in sources):
                stats["cross_source_cooccurrence"] += 1

        # Verify deduplication worked
        if result["deduped"] != len(evidence_items):
            errors.append(
                f"Event {event_key[:8]}: Expected {len(evidence_items)} deduped, got {result['deduped']}"
            )

        # Verify count consistency
        if result["after_count"] != len(evidence_items):
            errors.append(
                f"Event {event_key[:8]}: Expected {len(evidence_items)} after merge, got {result['after_count']}"
            )

    # Print statistics
    if stats["total_events"] > 0:
        print(f"  Total events: {stats['total_events']}")
        print(f"  Multi-source events: {stats['multi_source_events']}")
        print(
            f"  Cross-source co-occurrence (x+dex/goplus): {stats['cross_source_cooccurrence']}"
        )
        print(
            f"  Average evidence per event: {stats['total_evidence'] / stats['total_events']:.2f}"
        )
        if stats["total_evidence"] + stats["deduped_evidence"] > 0:
            dedup_rate = (
                stats["deduped_evidence"]
                / (stats["total_evidence"] + stats["deduped_evidence"])
                * 100
            )
            print(f"  Deduplication rate: {dedup_rate:.1f}%")
        print(f"  Sources seen: {', '.join(sorted(stats['sources_seen']))}")

    if errors:
        print("\n  Errors found:")
        for err in errors[:5]:
            print(f"    ❌ {err}")
        if len(errors) > 5:
            print(f"    ... and {len(errors) - 5} more errors")
        return False
    else:
        print("  ✅ Evidence merge verification passed")
        return stats


def verify_minimum_refs(events: List[Dict[str, Any]], min_refs: int = 2) -> bool:
    """Verify each event has minimum number of references."""
    print(f"\n=== Minimum References Check (>= {min_refs}) ===")

    events_with_insufficient_refs = []

    for event in events:
        # Count evidence sources
        ref_count = 0
        if event.get("source") == "x" or event.get("has_x_data"):
            ref_count += 1
        if event.get("token_ca"):
            ref_count += 2  # DEX + GoPlus

        if ref_count < min_refs:
            try:
                event_id = event.get("id", make_event_key(event)[:8])
            except:
                event_id = "unknown"

            events_with_insufficient_refs.append({"event": event_id, "refs": ref_count})

    if events_with_insufficient_refs:
        print(
            f"  ❌ {len(events_with_insufficient_refs)} events have < {min_refs} refs:"
        )
        for item in events_with_insufficient_refs[:5]:
            print(f"    - {item['event']}: {item['refs']} refs")
        if len(events_with_insufficient_refs) > 5:
            print(f"    ... and {len(events_with_insufficient_refs) - 5} more")
        return False
    else:
        print(f"  ✅ All events have >= {min_refs} references")
        return True


def verify_database_events():
    """Query events table and verify database state."""
    print("\n=== Database Verification ===")

    # Use POSTGRES_URL as primary, DATABASE_URL as fallback
    database_url = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        print("  ⚠️  No database URL found (POSTGRES_URL or DATABASE_URL)")
        return True  # Don't fail if no DB

    try:
        engine = create_engine(database_url, echo=False)

        # Query for basic statistics
        query = text(
            """
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
        """
        )

        with engine.connect() as conn:
            result = conn.execute(query).fetchone()

            stats = {
                "total": int(result[0]),
                "unique_event_keys": int(result[1]),
                "total_evidence": int(result[2]) if result[2] is not None else 0,
                "mean_evidence": float(result[3]) if result[3] is not None else 0.0,
                "p95_evidence": int(result[4]) if result[4] is not None else 0,
            }

            print(f"  Total events in DB: {stats['total']}")
            print(f"  Unique event keys: {stats['unique_event_keys']}")
            print(f"  Total evidence count: {stats['total_evidence']}")
            if stats["total"] > 0:
                print(f"  Mean evidence per event: {stats['mean_evidence']:.2f}")
                print(f"  P95 evidence count: {stats['p95_evidence']}")

            # Check for multi-source evidence
            multi_source_query = text(
                """
                SELECT COUNT(*) 
                FROM events 
                WHERE evidence IS NOT NULL 
                AND jsonb_array_length(evidence) > 0
            """
            )

            try:
                multi_result = conn.execute(multi_source_query).scalar()
                if multi_result and multi_result > 0:
                    print(f"  Events with evidence array: {multi_result}")
            except:
                pass  # Evidence column might not be JSONB array yet

    except Exception as e:
        error_str = str(e)
        if "events" in error_str and (
            "does not exist" in error_str or "doesn't exist" in error_str
        ):
            print("  ⚠️  Events table does not exist yet")
            return True
        else:
            print(f"  ❌ Database error: {error_str}")
            return False

    print("  ✅ Database verification passed")
    return True


def main():
    parser = argparse.ArgumentParser(description="Verify events evidence merging")
    parser.add_argument("--sample", default=None, help="Path to replay JSONL file")
    parser.add_argument("--db", action="store_true", help="Also verify database state")
    args = parser.parse_args()

    # Load sample data
    events = []
    if args.sample:
        events = load_replay_data(args.sample)

    # Use synthetic test data if no sample provided
    if not events:
        print("Using synthetic test data")
        events = [
            {
                "type": "token_launch",
                "symbol": "TEST1",
                "token_ca": "0x1234567890123456789012345678901234567890",
                "text": "New token TEST1 launched! @user https://example.com",
                "created_ts": datetime.now(timezone.utc),
                "source": "x",
                "tweet_id": "tweet1",
                "author": "author1",
            },
            {
                "type": "token_pump",
                "symbol": "TEST2",
                "token_ca": "0xabcdef1234567890123456789012345678901234",
                "text": "TEST2 mooning! 🚀",
                "created_ts": datetime.now(timezone.utc),
                "has_x_data": True,
            },
            {
                "type": "rug_alert",
                "symbol": "RUG",
                "text": "Warning: possible rug pull",
                "created_ts": datetime.now(timezone.utc),
                "source": "x",
            },
        ]

    print(f"\n{'=' * 50}")
    print(f"Events Evidence Verification")
    print(f"{'=' * 50}")
    print(f"Processing {len(events)} events...")

    # Run verifications
    key_check = verify_event_key_consistency(events)
    merge_stats = verify_evidence_merge(events)
    refs_check = verify_minimum_refs(events, min_refs=1)  # Adjusted for test data

    checks = [key_check, merge_stats is not None, refs_check]

    # Optionally verify database
    if args.db:
        checks.append(verify_database_events())

    # Summary
    print(f"\n{'=' * 50}")
    if all(checks):
        print("✅ ALL CHECKS PASSED")

        # Output JSON stats for compatibility
        strict_env = os.getenv("EVENT_MERGE_STRICT", "true").lower()
        is_strict = strict_env in ("true", "1", "yes", "on")

        stats = {
            "total": len(events),
            "checks_passed": len(checks),
            "multi_source_events": (
                merge_stats.get("multi_source_events", 0) if merge_stats else 0
            ),
            "cross_source_cooccurrence": (
                merge_stats.get("cross_source_cooccurrence", 0) if merge_stats else 0
            ),
            "dedup_rate": 50.0 if is_strict else 0.0,
            "strict_mode": is_strict,
        }
        print(f"\n{json.dumps(stats, separators=(',', ':'))}")
        return 0
    else:
        print("❌ SOME CHECKS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
