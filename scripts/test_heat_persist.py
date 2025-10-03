#!/usr/bin/env python3
"""
Test script for heat persistence functionality.
Tests atomic updates, row locking, and strict match modes.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy import text as sa_text

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.core.metrics_store import log_json
from api.signals.heat import compute_heat, persist_heat


def setup_test_row(db, symbol: str, token_ca: str):
    """Create or update a test row in signals table."""
    try:
        # Check if row exists
        check_q = sa_text(
            """
            SELECT 1 FROM signals 
            WHERE symbol = :symbol AND token_ca = :token_ca
        """
        )
        exists = db.execute(
            check_q, {"symbol": symbol, "token_ca": token_ca}
        ).fetchone()

        if not exists:
            # Create new row
            insert_q = sa_text(
                """
                INSERT INTO signals (symbol, token_ca, features_snapshot, last_ts)
                VALUES (:symbol, :token_ca, '{}'::jsonb, NOW())
            """
            )
            db.execute(insert_q, {"symbol": symbol, "token_ca": token_ca})
            print(f"Created test row: {symbol} / {token_ca}")
        else:
            print(f"Test row exists: {symbol} / {token_ca}")

        db.commit()
        return True
    except Exception as e:
        print(f"Setup error: {e}")
        db.rollback()
        return False


def test_basic_persist(db):
    """Test basic heat persistence."""
    print("\n=== Test Basic Persistence ===")

    symbol = "TEST"
    token_ca = "0xtest123"

    # Setup test row
    if not setup_test_row(db, symbol, token_ca):
        return False

    # Create heat data
    heat_data = {
        "cnt_10m": 42,
        "cnt_30m": 100,
        "slope": 2.5,
        "trend": "up",
        "asof_ts": datetime.now(timezone.utc).isoformat(),
    }

    # Persist heat
    result = persist_heat(
        db,
        token=symbol,
        token_ca=token_ca,
        heat=heat_data,
        upsert=True,
        strict_match=False,
    )

    print(f"Persist result: {result}")

    # Verify persistence
    verify_q = sa_text(
        """
        SELECT features_snapshot->'heat' as heat
        FROM signals
        WHERE symbol = :symbol AND token_ca = :token_ca
    """
    )

    row = db.execute(verify_q, {"symbol": symbol, "token_ca": token_ca}).fetchone()
    if row and row[0]:
        stored_heat = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        print(f"Stored heat: {json.dumps(stored_heat, indent=2)}")

        # Verify fields match
        assert stored_heat["cnt_10m"] == heat_data["cnt_10m"]
        assert stored_heat["slope"] == heat_data["slope"]
        assert stored_heat["trend"] == heat_data["trend"]
        print("✓ Basic persistence test passed")
        return True
    else:
        print("✗ No heat data found")
        return False


def test_atomic_update(db):
    """Test atomic update behavior."""
    print("\n=== Test Atomic Update ===")

    symbol = "ATOMIC"
    token_ca = "0xatomic456"

    # Setup test row
    if not setup_test_row(db, symbol, token_ca):
        return False

    # First update
    heat1 = {
        "cnt_10m": 10,
        "cnt_30m": 30,
        "slope": 1.0,
        "trend": "flat",
        "asof_ts": datetime.now(timezone.utc).isoformat(),
    }

    result1 = persist_heat(db, token=symbol, token_ca=token_ca, heat=heat1, upsert=True)
    print(f"First persist: {result1}")

    # Second update (should overwrite)
    time.sleep(1)
    heat2 = {
        "cnt_10m": 25,
        "cnt_30m": 60,
        "slope": 3.5,
        "trend": "up",
        "asof_ts": datetime.now(timezone.utc).isoformat(),
    }

    result2 = persist_heat(db, token=symbol, token_ca=token_ca, heat=heat2, upsert=True)
    print(f"Second persist: {result2}")

    # Verify latest values
    verify_q = sa_text(
        """
        SELECT features_snapshot->'heat' as heat
        FROM signals
        WHERE symbol = :symbol AND token_ca = :token_ca
    """
    )

    row = db.execute(verify_q, {"symbol": symbol, "token_ca": token_ca}).fetchone()
    if row and row[0]:
        stored_heat = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        print(f"Final heat: {json.dumps(stored_heat, indent=2)}")

        # Should have second update values
        assert stored_heat["cnt_10m"] == heat2["cnt_10m"]
        assert stored_heat["slope"] == heat2["slope"]
        assert stored_heat["trend"] == heat2["trend"]
        print("✓ Atomic update test passed")
        return True
    else:
        print("✗ Update verification failed")
        return False


def test_concurrent_updates(db):
    """Test concurrent update handling with row locking."""
    print("\n=== Test Concurrent Updates ===")

    symbol = "CONCUR"
    token_ca = "0xconcur789"

    # Setup test row
    if not setup_test_row(db, symbol, token_ca):
        return False

    def update_heat(thread_id: int):
        """Worker function for concurrent updates."""
        # Create separate connection for each thread
        engine = create_engine(os.getenv("POSTGRES_URL"), echo=False)
        with engine.connect() as conn:
            heat = {
                "cnt_10m": thread_id * 10,
                "cnt_30m": thread_id * 30,
                "slope": float(thread_id),
                "trend": "up" if thread_id > 5 else "flat",
                "asof_ts": datetime.now(timezone.utc).isoformat(),
            }

            try:
                result = persist_heat(
                    conn, token=symbol, token_ca=token_ca, heat=heat, upsert=True
                )
                return (thread_id, result, None)
            except Exception as e:
                return (thread_id, False, str(e))

    # Run concurrent updates
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(update_heat, i) for i in range(1, 6)]

        results = []
        for future in as_completed(futures):
            thread_id, success, error = future.result()
            results.append((thread_id, success, error))
            if success:
                print(f"Thread {thread_id}: Success")
            else:
                print(f"Thread {thread_id}: Failed - {error}")

    # At least one should succeed
    successful = sum(1 for _, success, _ in results if success)
    print(f"Successful updates: {successful}/5")

    if successful > 0:
        print("✓ Concurrent update test passed (handled lock conflicts)")
        return True
    else:
        print("✗ All concurrent updates failed")
        return False


def test_strict_match_mode(db):
    """Test strict match mode behavior."""
    print("\n=== Test Strict Match Mode ===")

    # Test 1: With token_ca (should work in strict mode)
    symbol1 = "STRICT1"
    token_ca1 = "0xstrict001"

    if not setup_test_row(db, symbol1, token_ca1):
        return False

    heat1 = {
        "cnt_10m": 15,
        "cnt_30m": 45,
        "slope": 1.5,
        "trend": "up",
        "asof_ts": datetime.now(timezone.utc).isoformat(),
    }

    # Should succeed with token_ca
    result1 = persist_heat(
        db,
        token_ca=token_ca1,  # Using token_ca
        heat=heat1,
        strict_match=True,  # Strict mode
    )
    print(f"Strict with token_ca: {result1}")

    # Test 2: Without token_ca (should fail in strict mode)
    symbol2 = "STRICT2"
    token_ca2 = "0xstrict002"

    if not setup_test_row(db, symbol2, token_ca2):
        return False

    heat2 = {
        "cnt_10m": 20,
        "cnt_30m": 50,
        "slope": 2.0,
        "trend": "flat",
        "asof_ts": datetime.now(timezone.utc).isoformat(),
    }

    # Should fail with only symbol in strict mode
    result2 = persist_heat(
        db,
        token=symbol2,  # Only symbol, no token_ca
        heat=heat2,
        strict_match=True,  # Strict mode
    )
    print(f"Strict with symbol only: {result2}")

    # Test 3: Without token_ca in loose mode (should succeed)
    result3 = persist_heat(
        db, token=symbol2, heat=heat2, strict_match=False  # Only symbol  # Loose mode
    )
    print(f"Loose with symbol only: {result3}")

    if result1 and not result2 and result3:
        print("✓ Strict match mode test passed")
        return True
    else:
        print("✗ Strict match mode behavior incorrect")
        return False


def test_nonexistent_row(db):
    """Test behavior when row doesn't exist."""
    print("\n=== Test Nonexistent Row ===")

    symbol = "NOTEXIST"
    token_ca = "0xnotexist999"

    # Don't create row, try to persist
    heat = {
        "cnt_10m": 99,
        "cnt_30m": 199,
        "slope": 9.9,
        "trend": "up",
        "asof_ts": datetime.now(timezone.utc).isoformat(),
    }

    result = persist_heat(db, token=symbol, token_ca=token_ca, heat=heat, upsert=True)

    print(f"Persist to nonexistent row: {result}")

    if not result:
        print("✓ Correctly refused to create new row")
        return True
    else:
        print("✗ Should not have succeeded for nonexistent row")
        return False


def main():
    """Run all tests."""
    # Set test environment
    os.environ["HEAT_ENABLE_PERSIST"] = "true"
    os.environ["HEAT_PERSIST_TIMEOUT_MS"] = "2000"

    # Get database connection
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        print("ERROR: POSTGRES_URL not set")
        return 1

    engine = create_engine(postgres_url, echo=False)

    tests = [
        ("Basic Persistence", test_basic_persist),
        ("Atomic Update", test_atomic_update),
        ("Concurrent Updates", test_concurrent_updates),
        ("Strict Match Mode", test_strict_match_mode),
        ("Nonexistent Row", test_nonexistent_row),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            with engine.connect() as db:
                if test_func(db):
                    passed += 1
                else:
                    failed += 1
        except Exception as e:
            print(f"✗ {test_name} raised exception: {e}")
            failed += 1

    print(f"\n=== Summary ===")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
