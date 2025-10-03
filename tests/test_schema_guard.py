#!/usr/bin/env python
"""
CARD C — Schema and routing guard tests
Prevent regressions in API routing and database schema
"""

import json
import os
import sys
from unittest.mock import Mock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def test_no_duplicate_route_prefix():
    """Test that routes don't have duplicate /signals/signals prefix."""
    # Check using curl to avoid import issues
    import json
    import subprocess

    # Get OpenAPI schema from running server
    result = subprocess.run(
        ["curl", "-s", "http://localhost:8000/openapi.json"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.skip("API server not running, skipping route test")
        return

    try:
        openapi = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.skip("Could not get OpenAPI schema, skipping route test")
        return

    paths = list(openapi.get("paths", {}).keys())

    # Check no duplicate /signals/signals prefix
    duplicate_routes = [p for p in paths if p.startswith("/signals/signals/")]
    assert (
        len(duplicate_routes) == 0
    ), f"Found duplicate route prefixes: {duplicate_routes}"

    # Verify correct /signals/{event_key} exists
    assert "/signals/{event_key}" in paths, "Missing /signals/{event_key} route"

    print(f"✓ Routes verified: {[p for p in paths if 'signals' in p]}")


def test_signals_table_required_columns():
    """Test that signals table has all required columns."""
    import subprocess

    # Required columns for the API to work
    required_columns = [
        "event_key",
        "state",
        "ts",
        "onchain_asof_ts",
        "onchain_confidence",
        "features_snapshot",
    ]

    # Query via docker exec
    cmd = [
        "docker",
        "compose",
        "-f",
        "infra/docker-compose.yml",
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        "app",
        "-d",
        "app",
        "-t",
        "-c",
        """SELECT column_name FROM information_schema.columns 
           WHERE table_schema = current_schema() 
           AND table_name = 'signals'""",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        pytest.skip("Database not accessible, skipping schema test")
        return

    existing_columns = [
        line.strip() for line in result.stdout.split("\n") if line.strip()
    ]

    # Check all required columns exist
    missing_columns = []
    for col in required_columns:
        if col not in existing_columns:
            missing_columns.append(col)

    assert (
        len(missing_columns) == 0
    ), f"Missing required columns in signals table: {missing_columns}"

    print(f"✓ All required columns exist: {required_columns}")


def test_api_graceful_degradation():
    """Test that API degrades gracefully when features are missing."""
    from api.routes.signals_summary import get_signal_summary

    mock_db = Mock()
    mock_redis = Mock()

    # Signal with no features_snapshot
    signal_row = {
        "event_key": "test_degradation",
        "state": "candidate",
        "onchain_asof_ts": None,
        "onchain_confidence": None,
        "features_snapshot": None,
    }

    mock_db.execute.return_value.mappings.return_value.first.return_value = signal_row
    mock_redis.get.return_value = None
    mock_redis.setex.return_value = True
    mock_redis.ttl.return_value = 120

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        result = get_signal_summary("test_degradation", mock_db)

    # Should return insufficient, not error
    assert result["verdict"]["decision"] == "insufficient"
    assert result["verdict"]["confidence"] == 0.0
    assert result["onchain"] is None
    assert result["cache"]["hit"] == False

    print("✓ API gracefully degrades when features missing")


def test_redis_connection_resilience():
    """Test that API continues working when Redis is down."""
    from api.routes.signals_summary import get_signal_summary

    mock_db = Mock()
    mock_redis = Mock()

    # Make Redis fail
    mock_redis.get.side_effect = Exception("Redis connection failed")
    mock_redis.setex.side_effect = Exception("Redis connection failed")
    mock_redis.ttl.side_effect = Exception("Redis connection failed")

    signal_row = {
        "event_key": "test_redis_down",
        "state": "candidate",
        "onchain_asof_ts": None,
        "onchain_confidence": None,
        "features_snapshot": None,
    }

    mock_db.execute.return_value.mappings.return_value.first.return_value = signal_row

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        # Should not raise exception
        result = get_signal_summary("test_redis_down", mock_db)

    # Should return valid response
    assert result["event_key"] == "test_redis_down"
    assert result["cache"]["hit"] == False
    assert result["verdict"]["decision"] == "insufficient"

    print("✓ API resilient to Redis failures")


def test_utc_timestamp_format():
    """Test that timestamps are properly formatted as UTC with Z suffix."""
    from datetime import datetime, timezone

    from api.routes.signals_summary import serialize_datetime

    # Test various datetime inputs
    test_cases = [
        datetime(2025, 1, 1, 12, 0, 0),  # Naive
        datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),  # UTC
    ]

    for dt in test_cases:
        result = serialize_datetime(dt)
        assert result.endswith("Z"), f"Timestamp should end with Z: {result}"
        assert "+00:00" not in result, f"Should not contain +00:00: {result}"
        assert "-00:00" not in result, f"Should not contain -00:00: {result}"

    # None should return None
    assert serialize_datetime(None) is None

    print("✓ UTC timestamps properly formatted with Z suffix")


def test_decimal_precision():
    """Test that numeric values have exactly 3 decimal places."""
    from decimal import Decimal

    from api.routes.signals_summary import serialize_decimal

    test_cases = [
        (Decimal("0.1234567"), 0.123),
        (Decimal("0.9999"), 1.0),
        (Decimal("0.1235"), 0.124),  # Round up
        (Decimal("0.1234"), 0.123),
        (None, None),
    ]

    for input_val, expected in test_cases:
        result = serialize_decimal(input_val)
        assert (
            result == expected
        ), f"serialize_decimal({input_val}) = {result}, expected {expected}"

    print("✓ Decimal precision validated (3 places with proper rounding)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
