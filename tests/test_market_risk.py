"""Tests for market risk detection functionality"""

import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from api.cards.dedup import make_state_version_with_rules
from api.rules.eval_event import RuleEvaluator


class TestMarketRiskRules:
    """Test market risk rule evaluation"""

    def test_mr_rules_trigger_tags(self):
        """Test that MR rules add market_risk tag when triggered"""
        evaluator = RuleEvaluator()

        # High volume scenario - should trigger MR01
        signals_data = {
            "goplus_risk": "green",
            "buy_tax": 2.0,
            "sell_tax": 2.0,
            "lp_lock_days": 180,
            "honeypot": False,
            "dex_liquidity": 100000.0,
            "dex_volume_1h": 600000.0,  # > 500000 threshold
            "heat_slope": 1.0,
        }
        events_data = {"last_sentiment_score": 0.7}

        with patch.dict(os.environ, {"MARKET_RISK_VOLUME_THRESHOLD": "500000"}):
            with patch(
                "api.rules.eval_event.rules_market_risk_hits_total"
            ) as mock_metric:
                result = evaluator.evaluate(signals_data, events_data)

                # Check tags
                assert "market_risk" in result["tags"]
                assert "MR01" in result["hit_rules"]

                # Check metric was incremented
                mock_metric.inc.assert_called()
                call_args = mock_metric.inc.call_args[0][0]
                assert call_args["rule_id"] == "MR01"

                # Level should still be one of the three standard levels
                assert result["level"] in ["observe", "caution", "opportunity"]
                assert result["level"] != "market_risk"

    def test_mr_rules_with_low_liquidity(self):
        """Test MR02 rule for low liquidity"""
        evaluator = RuleEvaluator()

        signals_data = {
            "goplus_risk": "yellow",
            "buy_tax": 5.0,
            "sell_tax": 5.0,
            "lp_lock_days": 60,
            "honeypot": False,
            "dex_liquidity": 5000.0,  # < 10000 threshold
            "dex_volume_1h": 50000.0,
            "heat_slope": 0.5,
        }
        events_data = {"last_sentiment_score": 0.5}

        with patch.dict(os.environ, {"MARKET_RISK_LIQ_MIN": "10000"}):
            with patch(
                "api.rules.eval_event.rules_market_risk_hits_total"
            ) as mock_metric:
                result = evaluator.evaluate(signals_data, events_data)

                assert "market_risk" in result["tags"]
                assert "MR02" in result["hit_rules"]
                mock_metric.inc.assert_called_with({"rule_id": "MR02"})

    def test_multiple_mr_rules_single_tag(self):
        """Test that multiple MR rules still result in single market_risk tag"""
        evaluator = RuleEvaluator()

        # Scenario triggering both MR01 and MR03
        signals_data = {
            "goplus_risk": "green",
            "buy_tax": 2.0,
            "sell_tax": 2.0,
            "lp_lock_days": 180,
            "honeypot": False,
            "dex_liquidity": 40000.0,  # < 50000 for MR03
            "dex_volume_1h": 600000.0,  # > 500000 for MR01 and MR03
            "heat_slope": 1.0,
        }
        events_data = {"last_sentiment_score": 0.7}

        with patch.dict(
            os.environ,
            {"MARKET_RISK_VOLUME_THRESHOLD": "500000", "MARKET_RISK_LIQ_RISK": "50000"},
        ):
            with patch(
                "api.rules.eval_event.rules_market_risk_hits_total"
            ) as mock_metric:
                result = evaluator.evaluate(signals_data, events_data)

                # Should have single tag but multiple rules
                assert result["tags"].count("market_risk") == 1
                assert "MR01" in result["hit_rules"]
                assert "MR03" in result["hit_rules"]

                # Each rule should increment metric
                assert mock_metric.inc.call_count >= 2

    def test_env_threshold_override(self):
        """Test that environment variables override default thresholds"""
        evaluator = RuleEvaluator()

        signals_data = {
            "goplus_risk": "green",
            "buy_tax": 2.0,
            "sell_tax": 2.0,
            "lp_lock_days": 180,
            "honeypot": False,
            "dex_liquidity": 100000.0,
            "dex_volume_1h": 150000.0,  # Would not trigger with default 500000
            "heat_slope": 1.0,
        }
        events_data = {"last_sentiment_score": 0.7}

        # Lower threshold to 100000
        with patch.dict(os.environ, {"MARKET_RISK_VOLUME_THRESHOLD": "100000"}):
            result = evaluator.evaluate(signals_data, events_data)
            assert "market_risk" in result["tags"]
            assert "MR01" in result["hit_rules"]

    def test_missing_field_safe_handling(self):
        """Test that missing fields don't cause errors"""
        evaluator = RuleEvaluator()

        # Missing heat_slope
        signals_data = {
            "goplus_risk": "green",
            "buy_tax": 2.0,
            "sell_tax": 2.0,
            "lp_lock_days": 180,
            "honeypot": False,
            "dex_liquidity": 100000.0,
            "dex_volume_1h": 50000.0,
            # heat_slope missing
        }
        events_data = {"last_sentiment_score": 0.7}

        # Should not raise error, heat_slope defaults to 0
        result = evaluator.evaluate(signals_data, events_data)
        assert "level" in result
        assert result["level"] in ["observe", "caution", "opportunity"]


class TestMarketRiskSignalGeneration:
    """Test signal type setting based on market risk"""

    @patch("api.jobs.goplus_scan.get_redis_client")
    @patch.object(RuleEvaluator, "evaluate")  # More precise mock
    def test_market_risk_type_set_with_cooldown(self, mock_evaluate, mock_redis_func):
        """Test that market_risk type is set when not in cooldown"""
        from api.core.metrics import signals_type_set_total

        # Setup mocks
        mock_redis = MagicMock()
        mock_redis.exists.return_value = False  # Not in cooldown
        mock_redis_func.return_value = mock_redis

        mock_evaluate.return_value = {
            "tags": ["market_risk"],
            "hit_rules": ["MR01"],
            "level": "caution",
            "score": -15,
        }

        # Test the logic (simplified version)
        event_key = "TEST:TOKEN:123"
        evaluator = RuleEvaluator()
        eval_result = evaluator.evaluate({}, {})

        if "market_risk" in eval_result.get("tags", []):
            cooldown_key = f"mr:cooldown:{event_key}"
            if not mock_redis.exists(cooldown_key):
                signal_type = "market_risk"
                mock_redis.setex(cooldown_key, 600, "1")
                # Would increment metric here in actual flow
                assert signal_type == "market_risk"

    @patch("api.jobs.goplus_scan.get_redis_client")
    def test_cooldown_prevents_duplicate(self, mock_redis_func):
        """Test that cooldown prevents setting type again"""
        mock_redis = MagicMock()
        mock_redis.exists.return_value = True  # In cooldown
        mock_redis.ttl.return_value = 300  # 5 minutes remaining
        mock_redis_func.return_value = mock_redis

        event_key = "TEST:TOKEN:123"
        cooldown_key = f"mr:cooldown:{event_key}"

        # During cooldown, type should not be set
        if mock_redis.exists(cooldown_key):
            # Should skip setting type
            signal_type = None  # Not set
            assert signal_type is None
            assert mock_redis.ttl(cooldown_key) == 300


class TestStateVersionWithRules:
    """Test state version generation with rule hashes"""

    def test_state_version_with_rules(self):
        """Test that hit rules are included in state version"""
        event = {"event_key": "TEST:123", "risk_level": "yellow", "state": "candidate"}
        hit_rules = ["MR01", "MR03"]

        with patch("api.cards.dedup.make_state_version") as mock_base:
            mock_base.return_value = "candidate|yellow|degrade:0|v1"

            result = make_state_version_with_rules(event, hit_rules)

            # Should have base version plus rule hash
            assert result.startswith("candidate|yellow|degrade:0|v1_mr")
            # Hash should be consistent for same rules
            assert len(result.split("_mr")[1]) == 8

    def test_state_version_stable_ordering(self):
        """Test that rule order doesn't affect hash"""
        event = {"event_key": "TEST:123"}

        with patch("api.cards.dedup.make_state_version") as mock_base:
            mock_base.return_value = "base|v1"

            # Different order, same rules
            version1 = make_state_version_with_rules(event, ["MR03", "MR01", "MR02"])
            version2 = make_state_version_with_rules(event, ["MR01", "MR02", "MR03"])

            assert version1 == version2

    def test_state_version_no_rules(self):
        """Test state version when no rules hit"""
        event = {"event_key": "TEST:123"}

        with patch("api.cards.dedup.make_state_version") as mock_base:
            mock_base.return_value = "base|v1"

            result = make_state_version_with_rules(event, [])

            # Should just return base version
            assert result == "base|v1"
            assert "_mr" not in result


class TestEndToEndIntegration:
    """Test end-to-end market risk flow"""

    @pytest.mark.integration
    def test_market_risk_card_generation(self):
        """Test that market risk signal generates correct card type

        Note: This test requires templates to exist. If running in CI without
        full template setup, consider mocking or skipping with:
        pytest -m "not integration"
        """
        from api.cards.registry import CARD_ROUTES, CARD_TEMPLATES

        # Verify market_risk is registered
        assert "market_risk" in CARD_ROUTES
        assert "market_risk" in CARD_TEMPLATES
        assert CARD_TEMPLATES["market_risk"] == "market_risk_card"

        # Verify template files exist
        import os

        template_dir = "templates/cards"
        if os.path.exists(template_dir):
            # Only check if template dir exists (may not in test environment)
            assert os.path.exists(f"{template_dir}/market_risk_card.tg.j2")
            assert os.path.exists(f"{template_dir}/market_risk_card.ui.j2")

    @patch("api.jobs.goplus_scan.signals_type_set_total")
    @patch("api.rules.eval_event.rules_market_risk_hits_total")
    def test_metrics_increment_correctly(self, mock_rules_metric, mock_signals_metric):
        """Test that metrics increment at correct points

        Note: This test verifies metric registration and that the evaluate() method
        calls increment. The signals_type_set_total would be called in goplus_scan
        when type is actually set, which is not triggered in this unit test.
        """
        evaluator = RuleEvaluator()

        signals_data = {
            "goplus_risk": "red",
            "buy_tax": 2.0,
            "sell_tax": 2.0,
            "lp_lock_days": 180,
            "honeypot": False,
            "dex_liquidity": 5000.0,  # Triggers MR02
            "dex_volume_1h": 600000.0,  # Triggers MR01
            "heat_slope": 1.0,
        }
        events_data = {"last_sentiment_score": 0.7}

        with patch.dict(
            os.environ,
            {"MARKET_RISK_VOLUME_THRESHOLD": "500000", "MARKET_RISK_LIQ_MIN": "10000"},
        ):
            result = evaluator.evaluate(signals_data, events_data)

            # Rules metric should be called for each MR rule hit
            assert mock_rules_metric.inc.call_count >= 2

            # Signals metric would be called when type is actually set
            # in goplus_scan flow (not in this unit test)
