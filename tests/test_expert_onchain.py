#!/usr/bin/env python
"""
CARD D — Tests for expert onchain endpoint
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


def test_404_when_expert_view_off():
    """Test that endpoint returns 404 when EXPERT_VIEW is off."""
    from fastapi import HTTPException

    from api.routes_expert_onchain import get_expert_onchain

    with patch.dict(os.environ, {"EXPERT_VIEW": "off"}):
        with pytest.raises(HTTPException) as exc_info:
            get_expert_onchain(
                chain="eth",
                address="0x1111111111111111111111111111111111111111",
                x_expert_key="testkey",
                db=Mock(),
            )
        assert exc_info.value.status_code == 404
        assert "Not found" in str(exc_info.value.detail)


def test_403_when_missing_or_wrong_key():
    """Test that endpoint returns 403 with missing or wrong key."""
    from fastapi import HTTPException

    from api.routes_expert_onchain import get_expert_onchain

    with patch.dict(os.environ, {"EXPERT_VIEW": "on", "EXPERT_KEY": "correctkey"}):
        # Missing key
        with pytest.raises(HTTPException) as exc_info:
            get_expert_onchain(
                chain="eth",
                address="0x1111111111111111111111111111111111111111",
                x_expert_key=None,
                db=Mock(),
            )
        assert exc_info.value.status_code == 403

        # Wrong key
        with pytest.raises(HTTPException) as exc_info:
            get_expert_onchain(
                chain="eth",
                address="0x1111111111111111111111111111111111111111",
                x_expert_key="wrongkey",
                db=Mock(),
            )
        assert exc_info.value.status_code == 403


def test_400_when_invalid_address():
    """Test that endpoint returns 400 for invalid address format."""
    from fastapi import HTTPException

    from api.routes_expert_onchain import get_expert_onchain

    with patch.dict(os.environ, {"EXPERT_VIEW": "on", "EXPERT_KEY": "testkey"}):
        # Invalid hex
        with pytest.raises(HTTPException) as exc_info:
            get_expert_onchain(
                chain="eth", address="0xINVALID", x_expert_key="testkey", db=Mock()
            )
        assert exc_info.value.status_code == 400
        assert "Invalid address" in str(exc_info.value.detail)

        # Wrong length
        with pytest.raises(HTTPException) as exc_info:
            get_expert_onchain(
                chain="eth", address="0x123", x_expert_key="testkey", db=Mock()
            )
        assert exc_info.value.status_code == 400


def test_rate_limit_429():
    """Test rate limiting returns 429 after limit exceeded."""
    from fastapi import HTTPException

    from api.routes_expert_onchain import check_rate_limit, get_expert_onchain

    mock_redis = Mock()
    mock_redis.incr.side_effect = [1, 2, 3, 4, 5, 6]  # Simulate incrementing counter
    mock_redis.expire.return_value = True

    with patch.dict(
        os.environ,
        {
            "EXPERT_VIEW": "on",
            "EXPERT_KEY": "testkey",
            "EXPERT_RATE_LIMIT_PER_MIN": "5",
        },
    ):
        with patch("api.routes_expert_onchain.get_redis", return_value=mock_redis):
            # First 5 should work (mocked to not actually call through)
            for i in range(5):
                assert check_rate_limit("testkey") == False

            # 6th should be rate limited
            assert check_rate_limit("testkey") == True

            # Different key should not be affected
            mock_redis.incr.return_value = 1
            assert check_rate_limit("otherkey") == False


def test_cache_hit_and_ttl_decrease():
    """Test cache miss then hit with TTL decrease."""
    from api.routes_expert_onchain import get_expert_onchain

    mock_db = Mock()
    mock_redis = Mock()

    # Mock database response
    mock_db.execute.return_value.fetchall.return_value = [
        Mock(
            as_of_ts=datetime.now(timezone.utc) - timedelta(hours=1),
            window_minutes=30,
            addr_active=100,
            growth_ratio=1.5,
            top10_share=Decimal("0.333"),
            self_loop_ratio=Decimal("0.05"),
        )
    ]

    with patch.dict(
        os.environ,
        {"EXPERT_VIEW": "on", "EXPERT_KEY": "testkey", "EXPERT_CACHE_TTL_SEC": "180"},
    ):
        with patch("api.routes_expert_onchain.get_redis", return_value=mock_redis):
            with patch(
                "api.routes_expert_onchain.check_rate_limit", return_value=False
            ):
                # First call - cache miss
                mock_redis.get.return_value = None
                mock_redis.ttl.return_value = 0
                mock_redis.setex.return_value = True

                result1 = get_expert_onchain(
                    chain="eth",
                    address="0x1111111111111111111111111111111111111111",
                    x_expert_key="testkey",
                    db=mock_db,
                )

                assert result1["cache"]["hit"] == False
                assert result1["cache"]["ttl_sec"] == 180

                # Second call - cache hit
                cached_data = result1.copy()
                cached_data.pop("cache")  # Remove cache field for storage
                mock_redis.get.return_value = json.dumps(cached_data)
                mock_redis.ttl.return_value = 150  # TTL decreased

                result2 = get_expert_onchain(
                    chain="eth",
                    address="0x1111111111111111111111111111111111111111",
                    x_expert_key="testkey",
                    db=mock_db,
                )

                assert result2["cache"]["hit"] == True
                assert result2["cache"]["ttl_sec"] == 150
                assert result2["cache"]["ttl_sec"] < 180


def test_pg_series_ok():
    """Test PG data fetching with proper series generation."""
    from api.routes_expert_onchain import fetch_series_pg

    mock_db = Mock()

    now = datetime.now(timezone.utc)

    # Mock rows for 2 days of data
    mock_rows = [
        # 2 days ago
        Mock(
            as_of_ts=now - timedelta(days=2),
            window_minutes=30,
            addr_active=100,
            growth_ratio=1.5,
            top10_share=Decimal("0.330"),
            self_loop_ratio=Decimal("0.05"),
        ),
        Mock(
            as_of_ts=now - timedelta(days=2),
            window_minutes=60,
            addr_active=150,
            growth_ratio=1.4,
            top10_share=Decimal("0.340"),
            self_loop_ratio=Decimal("0.06"),
        ),
        # 12 hours ago (within h24)
        Mock(
            as_of_ts=now - timedelta(hours=12),
            window_minutes=30,
            addr_active=120,
            growth_ratio=1.6,
            top10_share=Decimal("0.350"),
            self_loop_ratio=Decimal("0.04"),
        ),
        Mock(
            as_of_ts=now - timedelta(hours=12),
            window_minutes=60,
            addr_active=180,
            growth_ratio=1.3,
            top10_share=Decimal("0.360"),
            self_loop_ratio=Decimal("0.07"),
        ),
    ]

    mock_db.execute.return_value.fetchall.return_value = mock_rows

    result = fetch_series_pg(
        "eth", "0x1111111111111111111111111111111111111111", mock_db
    )

    # Check d7 has all data
    assert len(result["series"]["d7"]["w30"]) == 2
    assert len(result["series"]["d7"]["w60"]) == 2

    # Check h24 only has recent data
    assert len(result["series"]["h24"]["w30"]) == 1
    assert len(result["series"]["h24"]["w60"]) == 1

    # Check overview uses latest top10_share
    assert (
        result["overview"]["top10_share"] == 0.360
    )  # Latest value, clamped and rounded
    assert result["overview"]["others_share"] == 0.640  # 1 - 0.360

    # Check data_as_of
    assert result["data_as_of"] is not None
    assert result["data_as_of"].endswith("Z")

    # Check timestamps are in Z format
    for point in result["series"]["h24"]["w30"]:
        assert point["ts"].endswith("Z")


def test_bq_fallback_stale_true():
    """Test BQ failure returns stale data or empty with stale=true."""
    from api.routes_expert_onchain import get_expert_onchain

    mock_db = Mock()
    mock_redis = Mock()

    with patch.dict(
        os.environ,
        {"EXPERT_VIEW": "on", "EXPERT_KEY": "testkey", "EXPERT_SOURCE": "bq"},
    ):
        with patch("api.routes_expert_onchain.get_redis", return_value=mock_redis):
            with patch(
                "api.routes_expert_onchain.check_rate_limit", return_value=False
            ):
                # Mock BQ provider to raise error
                with patch("api.providers.onchain.bq_provider.BQProvider") as mock_bq:
                    mock_bq.return_value.query_light_features.side_effect = Exception(
                        "BQ Error"
                    )

                    # Case 1: No cache, return empty with stale=true
                    mock_redis.get.return_value = None
                    mock_redis.ttl.return_value = 0

                    result1 = get_expert_onchain(
                        chain="eth",
                        address="0x1111111111111111111111111111111111111111",
                        x_expert_key="testkey",
                        db=mock_db,
                    )

                    assert result1["stale"] == True
                    assert result1["overview"]["top10_share"] is None
                    assert len(result1["series"]["h24"]["w30"]) == 0

                    # Case 2: Has cache, return cached with stale=true
                    cached_data = {
                        "chain": "eth",
                        "address": "0x1111111111111111111111111111111111111111",
                        "series": {
                            "h24": {
                                "w30": [
                                    {"ts": "2025-01-01T00:00:00Z", "addr_active": 100}
                                ],
                                "w60": [],
                            },
                            "d7": {"w30": [], "w60": []},
                        },
                        "overview": {"top10_share": 0.300, "others_share": 0.700},
                        "data_as_of": "2025-01-01T00:00:00Z",
                        "stale": False,
                    }

                    mock_redis.get.return_value = json.dumps(cached_data)
                    mock_redis.ttl.return_value = 100

                    result2 = get_expert_onchain(
                        chain="eth",
                        address="0x1111111111111111111111111111111111111111",
                        x_expert_key="testkey",
                        db=mock_db,
                    )

                    assert result2["stale"] == True
                    assert result2["overview"]["top10_share"] == 0.300
                    assert result2["cache"]["hit"] == True


def test_no_event_key_usage():
    """Test that implementation doesn't use event_key field."""
    import api.routes_expert_onchain as module

    # Read the source code
    with open(module.__file__, "r") as f:
        source_code = f.read()

    # Assert event_key is not referenced
    assert (
        "event_key" not in source_code.lower()
    ), "Implementation should not reference event_key"


def test_decimal_rounding_and_clamp():
    """Test decimal rounding and clamping behavior."""
    from api.routes_expert_onchain import clamp_ratio, quantize_decimal

    # Test clamping
    assert clamp_ratio(1.001) == 1.000
    assert clamp_ratio(-0.01) == 0.000
    assert clamp_ratio(0.5555) == 0.556  # Rounded to 3 places
    assert clamp_ratio(0.3333) == 0.333
    assert clamp_ratio(None) is None

    # Test quantization
    assert quantize_decimal(0.1234567, 3) == 0.123
    assert quantize_decimal(0.9999, 3) == 1.000
    assert quantize_decimal(0.5555, 3) == 0.556  # Round half up
    assert quantize_decimal(None, 3) is None


def test_unsupported_chain():
    """Test that non-eth chains return 400."""
    from fastapi import HTTPException

    from api.routes_expert_onchain import get_expert_onchain

    with patch.dict(os.environ, {"EXPERT_VIEW": "on", "EXPERT_KEY": "testkey"}):
        with pytest.raises(HTTPException) as exc_info:
            get_expert_onchain(
                chain="polygon",
                address="0x1111111111111111111111111111111111111111",
                x_expert_key="testkey",
                db=Mock(),
            )
        assert exc_info.value.status_code == 400
        assert "Unsupported chain" in str(exc_info.value.detail)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
