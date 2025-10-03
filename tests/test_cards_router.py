"""
Test card routing with frozen time and deterministic randomness
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from api.cards.registry import (
    CARD_ROUTES,
    CARD_TEMPLATES,
    UnknownCardTypeError,
    normalize_card_type,
)
from api.cards.render_pipeline import check_template_exists, render_and_push
from api.cards.transformers import to_pushcard


@freeze_time("2025-01-15 12:00:00")
class TestCardRouting:
    """Test card routing with frozen time"""

    def test_route_table_complete(self):
        """All four types have routes"""
        assert "primary" in CARD_ROUTES
        assert "secondary" in CARD_ROUTES
        assert "topic" in CARD_ROUTES
        assert "market_risk" in CARD_ROUTES
        assert len(CARD_ROUTES) == 4

    def test_template_table_complete(self):
        """All four types have templates"""
        assert "primary" in CARD_TEMPLATES
        assert "secondary" in CARD_TEMPLATES
        assert "topic" in CARD_TEMPLATES
        assert "market_risk" in CARD_TEMPLATES
        assert len(CARD_TEMPLATES) == 4

    def test_normalize_card_type(self):
        """Type normalization works correctly"""
        assert normalize_card_type("PRIMARY") == "primary"
        assert normalize_card_type(" Secondary ") == "secondary"
        assert normalize_card_type("Topic") == "topic"
        assert normalize_card_type("market_risk") == "market_risk"

    def test_unknown_type_raises(self):
        """Unknown types raise UnknownCardTypeError"""
        with pytest.raises(UnknownCardTypeError) as exc:
            normalize_card_type("invalid_type")
        assert "Unknown card type: invalid_type" in str(exc.value)

    def test_empty_type_raises(self):
        """Empty type raises error"""
        with pytest.raises(UnknownCardTypeError) as exc:
            normalize_card_type("")
        assert "Card type cannot be empty" in str(exc.value)

    @patch("api.cards.render_pipeline.check_template_exists")
    def test_generate_primary_card(self, mock_check):
        """Primary card generation with fixed time"""
        mock_check.return_value = True

        from api.cards.generator import generate_primary_card

        signal = {
            "type": "primary",
            "event_key": "ETH:TOKEN:123",
            "risk_level": "yellow",
            "token_info": {"symbol": "TEST", "chain": "eth"},
            "risk_note": "Test risk",
            "goplus_risk": "yellow",
        }

        now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = generate_primary_card(signal, now=now)

        assert result["template_name"] == "primary_card"
        assert result["context"]["type"] == "primary"
        assert result["context"]["data_as_of"] == "2025-01-15T12:00Z"
        assert result["meta"]["type"] == "primary"
        assert result["meta"]["event_key"] == "ETH:TOKEN:123"
        assert result["meta"]["template_base"] == "primary_card"

    @patch("api.cards.render_pipeline.TelegramNotifier")
    @patch("api.cards.render_pipeline.check_template_exists")
    def test_unknown_type_metrics(self, mock_check, mock_tg):
        """Unknown type increments metrics and logs"""
        mock_check.return_value = True

        with patch("api.cards.render_pipeline.cards_unknown_type_count") as mock_metric:
            with patch("api.cards.render_pipeline.log_json") as mock_log:
                result = render_and_push(
                    signal={"type": "invalid_type"}, channel_id="-123456"
                )

                assert not result["success"]
                assert "Unknown card type" in result["error"]

                # Check metric was incremented
                mock_metric.inc.assert_called_once_with({"type": "invalid_type"})

                # Check structured log - use correct kwargs access
                mock_log.assert_called()
                kwargs = mock_log.call_args.kwargs
                assert kwargs["stage"] == "cards.unknown_type"
                assert "Unknown card type" in kwargs["error"]

    def test_template_missing_degradation(self):
        """Missing template triggers degradation"""
        from api.cards.render_pipeline import render_template

        # Use dict literal instead of TypedDict constructor
        payload = {
            "template_name": "nonexistent_template",
            "context": {"type": "test", "risk_level": "yellow"},
            "meta": {
                "type": "test",
                "event_key": "TEST:123",
                "degrade": False,
                "template_base": "nonexistent_template",
                "latency_ms": None,
                "diagnostic_flags": None,
            },
        }

        with patch(
            "api.cards.render_pipeline.check_template_exists", return_value=False
        ):
            with patch(
                "api.cards.render_pipeline.cards_render_fail_total"
            ) as mock_metric:
                with patch("api.cards.render_pipeline.log_json") as mock_log:
                    text, is_degraded = render_template(payload, "tg")

                    assert is_degraded
                    assert "降级模式" in text

                    mock_metric.inc.assert_called_with(
                        {"type": "test", "reason": "template_missing"}
                    )

                    mock_log.assert_called_with(
                        stage="cards.template_missing",
                        template="nonexistent_template.tg.j2",
                        type="test",
                    )


class TestTransformers:
    """Test format transformations"""

    def test_to_pushcard_mapping(self):
        """Internal format maps correctly to pushcard"""

        # Use dict literal instead of TypedDict constructor
        payload = {
            "template_name": "primary_card",
            "context": {
                "type": "primary",
                "risk_level": "yellow",
                "token_info": {"symbol": "TEST"},
                "risk_note": "Test note",
                "verify_path": "/verify",
                "data_as_of": "2025-01-15T12:00Z",
            },
            "meta": {
                "type": "primary",
                "event_key": "TEST:123",
                "degrade": False,
                "template_base": "primary_card",
                "latency_ms": 100,
                "diagnostic_flags": None,
            },
        }

        result = to_pushcard(payload, "Test render", "tg")

        assert result["type"] == "primary"
        assert result["event_key"] == "TEST:123"  # Check event_key is mapped
        assert result["risk_level"] == "yellow"
        assert result["token_info"]["symbol"] == "TEST"
        assert result["risk_note"] == "Test note"
        assert result["verify_path"] == "/verify"
        assert result["data_as_of"] == "2025-01-15T12:00Z"
        assert result["rendered"]["tg"] == "Test render"
        assert result["states"]["degrade"] == False


@freeze_time("2025-01-15 12:00:00")
def test_snapshot_stability():
    """Template rendering produces stable snapshots"""
    from api.cards.generator import generate_primary_card

    signal = {
        "type": "primary",
        "event_key": "SNAP:TEST:001",
        "risk_level": "yellow",
        "token_info": {"symbol": "SNAP", "chain": "eth"},
        "risk_note": "Snapshot test",
    }

    # Fixed time for reproducibility
    now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    # Generate twice, should be identical
    result1 = generate_primary_card(signal, now=now)
    result2 = generate_primary_card(signal, now=now)

    assert json.dumps(result1, sort_keys=True) == json.dumps(result2, sort_keys=True)
    assert result1["context"]["data_as_of"] == "2025-01-15T12:00Z"
    assert result2["context"]["data_as_of"] == "2025-01-15T12:00Z"
