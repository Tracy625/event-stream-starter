#!/usr/bin/env python
"""
CARD B-verify (final) — Three-branch verification test
Tests OFF mode, upgrade path, and downgrade path
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

# Ensure we're using the app path
sys.path.insert(0, "/app")


def run_three_branch_test():
    """Run comprehensive three-branch verification test."""

    print("=" * 60)
    print("CARD B-verify (final) — Three-Branch Verification")
    print("=" * 60)
    print()

    # Import required modules
    from sqlalchemy import text as sa_text

    from api.database import get_db

    # Step 1: Create test candidates
    print("1. Creating test candidates...")
    print("-" * 40)

    with next(get_db()) as db:
        db.execute(
            sa_text(
                """
            INSERT INTO signals (event_key, state, ts) VALUES
            ('demo_event_up', 'candidate', NOW() - INTERVAL '10 minutes'),
            ('demo_event_down', 'candidate', NOW() - INTERVAL '10 minutes')
            ON CONFLICT (event_key) DO UPDATE 
            SET state = 'candidate',
                ts = NOW() - INTERVAL '10 minutes',
                onchain_asof_ts = NULL,
                onchain_confidence = NULL
        """
            )
        )
        db.commit()
        print("✓ Created: demo_event_up, demo_event_down")

    print()

    # Branch A: Test ONCHAIN_RULES=off
    print("=" * 60)
    print("BRANCH A: Testing ONCHAIN_RULES=off")
    print("=" * 60)

    os.environ["ONCHAIN_RULES"] = "off"
    os.environ["ONCHAIN_VERIFICATION_DELAY_SEC"] = "0"
    os.environ["ONCHAIN_VERDICT_TTL_SEC"] = "1"
    os.environ["BQ_ONCHAIN_FEATURES_VIEW"] = "dummy.table"

    # Mock the fetch_onchain_features function
    print("Setting up mock for OFF mode...")

    def mock_fetch_off(chain, address, window_min=60, timeout_sec=720):
        """Mock that returns features for OFF mode test"""
        return {
            "active_addr_pctl": 0.99,
            "growth_ratio": 2.5,
            "top10_share": 0.10,
            "self_loop_ratio": 0.01,
            "asof_ts": datetime.now(timezone.utc).isoformat(),
        }

    # Import and monkey-patch
    import worker.jobs.onchain.verify_signal as verify_module

    original_fetch = verify_module.fetch_onchain_features
    verify_module.fetch_onchain_features = mock_fetch_off

    # Run the job
    from worker.jobs.onchain.verify_signal import run_once

    result = run_once(limit=10)
    print(f"OFF mode result: {result}")

    # Check results
    with next(get_db()) as db:
        rows = db.execute(
            sa_text(
                """
            SELECT event_key, state, 
                   CASE WHEN onchain_asof_ts IS NOT NULL THEN 'SET' ELSE 'NULL' END as asof,
                   COALESCE(onchain_confidence::text, 'NULL') as conf
            FROM signals 
            WHERE event_key IN ('demo_event_up', 'demo_event_down')
            ORDER BY event_key
        """
            )
        ).fetchall()

        print("\nResults after OFF mode:")
        for row in rows:
            print(
                f"  {row.event_key}: state={row.state}, asof={row.asof}, conf={row.conf}"
            )
            if row.state != "candidate":
                print(f"    ⚠ Warning: State changed in OFF mode!")

    print()
    time.sleep(2)  # Allow locks to expire

    # Branch B: Test upgrade path
    print("=" * 60)
    print("BRANCH B: Testing ONCHAIN_RULES=on (Upgrade Path)")
    print("=" * 60)

    os.environ["ONCHAIN_RULES"] = "on"

    def mock_fetch_upgrade(chain, address, window_min=60, timeout_sec=720):
        """Mock that returns upgrade-triggering features for demo_event_up"""
        if "up" in str(address):
            # Features that satisfy upgrade conditions
            return {
                "active_addr_pctl": 0.96,  # >= 0.95 (high)
                "growth_ratio": 2.5,  # >= 2.0 (fast)
                "top10_share": 0.10,  # < 0.70 (not high_risk)
                "self_loop_ratio": 0.01,  # < 0.20 (not suspicious)
                "asof_ts": datetime.now(timezone.utc).isoformat(),
            }
        else:
            # Neutral features
            return {
                "active_addr_pctl": 0.85,
                "growth_ratio": 1.1,
                "top10_share": 0.20,
                "self_loop_ratio": 0.05,
                "asof_ts": datetime.now(timezone.utc).isoformat(),
            }

    verify_module.fetch_onchain_features = mock_fetch_upgrade

    # Clear Redis locks for demo_event_up
    try:
        import redis

        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.delete("onchain:verify:demo_event_up")
    except:
        pass

    result = run_once(limit=10)
    print(f"ON-upgrade result: {result}")

    # Check results
    with next(get_db()) as db:
        row = db.execute(
            sa_text(
                """
            SELECT event_key, state, onchain_confidence
            FROM signals WHERE event_key = 'demo_event_up'
        """
            )
        ).fetchone()

        if row:
            print(f"\ndemo_event_up after upgrade:")
            print(f"  state: {row.state}")
            print(f"  confidence: {row.onchain_confidence}")
            if row.state == "verified":
                print("  ✓ Upgrade successful!")
            else:
                print(f"  ⚠ Expected 'verified', got '{row.state}'")

    print()
    time.sleep(2)

    # Branch C: Test downgrade path
    print("=" * 60)
    print("BRANCH C: Testing ONCHAIN_RULES=on (Downgrade Path)")
    print("=" * 60)

    def mock_fetch_downgrade(chain, address, window_min=60, timeout_sec=720):
        """Mock that returns downgrade-triggering features for demo_event_down"""
        if "down" in str(address):
            # Features that satisfy downgrade conditions
            return {
                "active_addr_pctl": 0.50,
                "growth_ratio": 0.8,
                "top10_share": 0.75,  # >= 0.70 (high_risk)
                "self_loop_ratio": 0.25,  # >= 0.20 (suspicious)
                "asof_ts": datetime.now(timezone.utc).isoformat(),
            }
        else:
            # Neutral features
            return {
                "active_addr_pctl": 0.85,
                "growth_ratio": 1.1,
                "top10_share": 0.20,
                "self_loop_ratio": 0.05,
                "asof_ts": datetime.now(timezone.utc).isoformat(),
            }

    verify_module.fetch_onchain_features = mock_fetch_downgrade

    # Clear Redis locks for demo_event_down
    try:
        import redis

        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.delete("onchain:verify:demo_event_down")
    except:
        pass

    result = run_once(limit=10)
    print(f"ON-downgrade result: {result}")

    # Check results
    with next(get_db()) as db:
        row = db.execute(
            sa_text(
                """
            SELECT event_key, state, onchain_confidence
            FROM signals WHERE event_key = 'demo_event_down'
        """
            )
        ).fetchone()

        if row:
            print(f"\ndemo_event_down after downgrade:")
            print(f"  state: {row.state}")
            print(f"  confidence: {row.onchain_confidence}")
            if row.state in ("downgraded", "rejected"):
                print("  ✓ Downgrade successful!")
            else:
                print(f"  ⚠ Expected 'downgraded' or 'rejected', got '{row.state}'")

    # Restore original function
    verify_module.fetch_onchain_features = original_fetch

    print()
    print("=" * 60)
    print("Final State Summary")
    print("=" * 60)

    with next(get_db()) as db:
        rows = db.execute(
            sa_text(
                """
            SELECT event_key, state, 
                   onchain_asof_ts,
                   onchain_confidence
            FROM signals 
            WHERE event_key IN ('demo_event_up', 'demo_event_down')
            ORDER BY event_key
        """
            )
        ).fetchall()

        print("\nFinal signal states:")
        for row in rows:
            print(f"  {row.event_key}:")
            print(f"    state: {row.state}")
            print(f"    asof_ts: {'SET' if row.onchain_asof_ts else 'NULL'}")
            print(f"    confidence: {row.onchain_confidence or 'NULL'}")

        # Check events
        events = db.execute(
            sa_text(
                """
            SELECT event_key, type, metadata
            FROM signal_events 
            WHERE event_key IN ('demo_event_up', 'demo_event_down')
              AND type = 'onchain_verify'
            ORDER BY created_at DESC
            LIMIT 6
        """
            )
        ).fetchall()

        if events:
            print(f"\nVerification events recorded: {len(events)}")
            for evt in events:
                print(f"  {evt.event_key}: {evt.type}")

    # Cleanup
    print()
    print("=" * 60)
    cleanup = input("Delete test data? (y/n): ").strip().lower()
    if cleanup == "y":
        with next(get_db()) as db:
            db.execute(
                sa_text(
                    """
                DELETE FROM signal_events 
                WHERE event_key IN ('demo_event_up', 'demo_event_down')
            """
                )
            )
            db.execute(
                sa_text(
                    """
                DELETE FROM signals 
                WHERE event_key IN ('demo_event_up', 'demo_event_down')
            """
                )
            )
            db.commit()
            print("✓ Test data cleaned up")
    else:
        print("Test data retained for inspection")

    print()
    print("=" * 60)
    print("Three-Branch Verification Complete!")
    print("=" * 60)
    print("\nExpected Results:")
    print("  Branch A: Both remain 'candidate', confidence = 0 or 1.0")
    print("  Branch B: demo_event_up → 'verified', confidence > 0")
    print("  Branch C: demo_event_down → 'downgraded', confidence > 0")

    return 0


if __name__ == "__main__":
    sys.exit(run_three_branch_test())
