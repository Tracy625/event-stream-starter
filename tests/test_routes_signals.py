#!/usr/bin/env python
"""
CARD C — Tests for signals summary API endpoint
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def test_cache_ttl_decreases():
    """Test that TTL decreases on cache hit."""
    from api.routes.signals_summary import get_signal_summary

    mock_db = Mock()
    mock_redis = Mock()

    # First call - cache miss
    signal_row = {
        "event_key": "test_signal",
        "state": "candidate",
        "onchain_asof_ts": datetime.now(timezone.utc),
        "onchain_confidence": Decimal("0.750"),
        "features_snapshot": None,
    }

    mock_db.execute.return_value.mappings.return_value.first.return_value = signal_row

    mock_redis.get.return_value = None
    mock_redis.setex.return_value = True
    mock_redis.ttl.return_value = 120

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        result1 = get_signal_summary("test_signal", mock_db)

    assert result1["cache"]["hit"] == False
    assert result1["cache"]["ttl_sec"] == 120

    # Second call - cache hit with decreased TTL
    cached_response = json.dumps(result1)
    cached_response_dict = json.loads(cached_response)
    cached_response_dict.pop("cache", None)  # Remove cache field for clean comparison

    mock_redis.get.return_value = json.dumps(cached_response_dict)
    mock_redis.ttl.return_value = 95  # TTL has decreased

    mock_db.execute.side_effect = []  # Should not be called

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        result2 = get_signal_summary("test_signal", mock_db)

    assert result2["cache"]["hit"] == True
    assert result2["cache"]["ttl_sec"] == 95
    assert result2["cache"]["ttl_sec"] < 120


def test_confidence_precision():
    """Test that confidence has at most 3 decimal places."""
    from api.routes.signals_summary import get_signal_summary

    mock_db = Mock()
    mock_redis = Mock()

    # Create mock row with features_snapshot
    signal_row = {
        "event_key": "test_precision",
        "state": "verified",
        "onchain_asof_ts": datetime.now(timezone.utc),
        "onchain_confidence": Decimal("0.87654321"),
        "features_snapshot": {
            "onchain": {
                "active_addr_pctl": 0.9123456,
                "growth_ratio": 1.8765432,
                "top10_share": 0.3456789,
                "self_loop_ratio": 0.0654321,
                "window_min": 60,
                "asof_ts": datetime.now(timezone.utc).isoformat(),
            }
        },
    }

    mock_db.execute.return_value.mappings.return_value.first.return_value = signal_row

    mock_redis.get.return_value = None
    mock_redis.setex.return_value = True
    mock_redis.ttl.return_value = 120

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        result = get_signal_summary("test_precision", mock_db)

    # Check confidence precision (using stored value when no rules evaluation)
    if result["verdict"]["confidence"] != 0:
        confidence_str = f"{result['verdict']['confidence']:.10f}".rstrip("0").rstrip(
            "."
        )
        if "." in confidence_str:
            decimal_part = confidence_str.split(".")[1]
            assert (
                len(decimal_part) <= 3
            ), f"Confidence {result['verdict']['confidence']} has more than 3 decimal places"

    # Check onchain numeric fields precision
    if result["onchain"]:
        for key in [
            "active_addr_pctl",
            "growth_ratio",
            "top10_share",
            "self_loop_ratio",
        ]:
            value = result["onchain"][key]
            value_str = f"{value:.10f}".rstrip("0").rstrip(".")
            if "." in value_str:
                decimal_part = value_str.split(".")[1]
                assert (
                    len(decimal_part) <= 3
                ), f"{key} value {value} has more than 3 decimal places"


def test_asof_ts_utc_z():
    """Test that asof_ts ends with Z for UTC."""
    from api.routes.signals_summary import get_signal_summary

    mock_db = Mock()
    mock_redis = Mock()

    # Test with naive datetime in features_snapshot
    signal_row = {
        "event_key": "test_utc",
        "state": "candidate",
        "onchain_asof_ts": datetime(2025, 9, 8, 12, 0, 0),
        "onchain_confidence": None,
        "features_snapshot": {
            "onchain": {
                "active_addr_pctl": 0.85,
                "growth_ratio": 1.5,
                "top10_share": 0.25,
                "self_loop_ratio": 0.05,
                "window_min": 60,
                "asof_ts": "2025-09-08T11:30:00",  # Naive datetime string
            }
        },
    }

    mock_db.execute.return_value.mappings.return_value.first.return_value = signal_row

    mock_redis.get.return_value = None
    mock_redis.setex.return_value = True
    mock_redis.ttl.return_value = 120

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        result = get_signal_summary("test_utc", mock_db)

    if result["onchain"] and result["onchain"]["asof_ts"]:
        asof_ts = result["onchain"]["asof_ts"]
        assert asof_ts.endswith("Z"), f"asof_ts should end with Z, got: {asof_ts}"
        # Should not have +00:00 or other timezone indicators
        assert "+00:00" not in asof_ts
        assert "-00:00" not in asof_ts


def test_redis_failure_graceful():
    """Test graceful handling when Redis fails."""
    from api.routes.signals_summary import get_signal_summary

    mock_db = Mock()
    mock_redis = Mock()

    # Make Redis operations fail
    mock_redis.get.side_effect = Exception("Redis connection failed")
    mock_redis.setex.side_effect = Exception("Redis connection failed")
    mock_redis.ttl.side_effect = Exception("Redis connection failed")

    signal_row = {
        "event_key": "test_redis_fail",
        "state": "candidate",
        "onchain_asof_ts": datetime.now(timezone.utc),
        "onchain_confidence": Decimal("0.5"),
        "features_snapshot": None,
    }

    mock_db.execute.return_value.mappings.return_value.first.return_value = signal_row

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        # Should not raise exception
        result = get_signal_summary("test_redis_fail", mock_db)

    # Should return valid response with cache.hit=false
    assert result["event_key"] == "test_redis_fail"
    assert result["cache"]["hit"] == False
    assert result["cache"]["ttl_sec"] == 120  # Default TTL


def test_not_found():
    """Test 404 when signal not found."""
    from fastapi import HTTPException

    from api.routes.signals_summary import get_signal_summary

    mock_db = Mock()
    mock_redis = Mock()

    # No signal found
    mock_db.execute.return_value.mappings.return_value.first.return_value = None
    mock_redis.get.return_value = None

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        with pytest.raises(HTTPException) as exc_info:
            get_signal_summary("nonexistent", mock_db)

    assert exc_info.value.status_code == 404
    assert "not found" in str(exc_info.value.detail).lower()


def test_insufficient_verdict():
    """Test insufficient verdict when no features."""
    from api.routes.signals_summary import get_signal_summary

    mock_db = Mock()
    mock_redis = Mock()

    signal_row = {
        "event_key": "test_insufficient",
        "state": "candidate",
        "onchain_asof_ts": None,
        "onchain_confidence": None,
        "features_snapshot": None,  # No features
    }

    mock_db.execute.return_value.mappings.return_value.first.return_value = signal_row

    mock_redis.get.return_value = None
    mock_redis.setex.return_value = True
    mock_redis.ttl.return_value = 120

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        result = get_signal_summary("test_insufficient", mock_db)

    assert result["verdict"]["decision"] == "insufficient"
    assert result["verdict"]["confidence"] == 0.0
    assert "No onchain features" in result["verdict"]["note"]


def test_serialize_functions():
    """Test serialization helper functions."""
    from api.routes.signals_summary import serialize_datetime, serialize_decimal

    # Test datetime serialization
    dt_naive = datetime(2025, 9, 8, 12, 0, 0)
    dt_utc = datetime(2025, 9, 8, 12, 0, 0, tzinfo=timezone.utc)

    result_naive = serialize_datetime(dt_naive)
    assert result_naive.endswith("Z")
    assert "+00:00" not in result_naive

    result_utc = serialize_datetime(dt_utc)
    assert result_utc.endswith("Z")
    assert "+00:00" not in result_utc

    assert serialize_datetime(None) is None

    # Test decimal serialization
    assert serialize_decimal(Decimal("0.12345678")) == 0.123
    assert serialize_decimal(Decimal("0.9999")) == 1.0
    assert serialize_decimal(Decimal("0.1234")) == 0.123
    assert serialize_decimal(Decimal("0.1235")) == 0.124  # Rounding
    assert serialize_decimal(None) is None


def test_stored_verdict_fallback():
    """Test using stored confidence when features unavailable."""
    from api.routes.signals_summary import get_signal_summary

    mock_db = Mock()
    mock_redis = Mock()

    # Verified signal without features but with stored confidence
    signal_row = {
        "event_key": "verified_signal",
        "state": "verified",
        "onchain_asof_ts": datetime.now(timezone.utc),
        "onchain_confidence": Decimal("0.920"),
        "features_snapshot": None,
    }

    mock_db.execute.return_value.mappings.return_value.first.return_value = signal_row

    mock_redis.get.return_value = None
    mock_redis.setex.return_value = True
    mock_redis.ttl.return_value = 120

    with patch("api.routes_signals.get_redis", return_value=mock_redis):
        result = get_signal_summary("verified_signal", mock_db)

    # Verify stored verdict used
    assert result["state"] == "verified"
    assert result["verdict"]["decision"] == "upgrade"
    assert result["verdict"]["confidence"] == 0.920
    assert "stored verdict" in result["verdict"]["note"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
