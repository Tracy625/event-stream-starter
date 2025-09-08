"""Unit tests for on-chain rules engine."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from api.onchain.dto import OnchainFeature, Rules, Verdict
from api.onchain.rules_engine import evaluate, load_rules


class TestRulesEngine:
    """Test suite for rules engine functionality."""
    
    @pytest.fixture
    def valid_rules_yaml(self):
        """Create a valid rules YAML configuration."""
        return {
            'windows': [30, 60, 180],
            'thresholds': {
                'active_addr_pctl': {'high': 0.95, 'mid': 0.80},
                'growth_ratio': {'fast': 2.0, 'slow': 1.2},
                'top10_share': {'high_risk': 0.70, 'mid_risk': 0.40},
                'self_loop_ratio': {'suspicious': 0.20, 'watch': 0.10}
            },
            'verdict': {
                'upgrade_if': ['active_addr_pctl>=high', 'growth_ratio>=fast'],
                'downgrade_if': ['top10_share>=high_risk', 'self_loop_ratio>=suspicious']
            }
        }
    
    @pytest.fixture
    def valid_rules(self, valid_rules_yaml):
        """Create a valid Rules object."""
        return Rules(**valid_rules_yaml)
    
    def test_upgrade(self, valid_rules):
        """Test upgrade verdict when all upgrade conditions are met."""
        features = OnchainFeature(
            active_addr_pctl=0.96,  # >= 0.95 (high)
            growth_ratio=2.5,        # >= 2.0 (fast)
            top10_share=0.3,         # < 0.70 (not high_risk)
            self_loop_ratio=0.05,    # < 0.20 (not suspicious)
            asof_ts=datetime.now(),
            window_min=60
        )
        
        verdict = evaluate(features, valid_rules)
        
        assert verdict.decision == "upgrade"
        assert verdict.confidence == 1.0
        assert verdict.note is None
    
    def test_downgrade_priority(self, valid_rules):
        """Test that downgrade has priority when both conditions are met."""
        features = OnchainFeature(
            active_addr_pctl=0.96,  # >= 0.95 (high) - upgrade condition
            growth_ratio=2.5,        # >= 2.0 (fast) - upgrade condition
            top10_share=0.75,        # >= 0.70 (high_risk) - downgrade condition
            self_loop_ratio=0.25,    # >= 0.20 (suspicious) - downgrade condition
            asof_ts=datetime.now(),
            window_min=60
        )
        
        verdict = evaluate(features, valid_rules)
        
        assert verdict.decision == "downgrade"
        assert verdict.confidence == 1.0
        assert verdict.note is None
    
    def test_hold(self, valid_rules):
        """Test hold verdict when no conditions are fully met."""
        features = OnchainFeature(
            active_addr_pctl=0.85,  # < 0.95 (not high)
            growth_ratio=1.5,        # < 2.0 (not fast)
            top10_share=0.3,         # < 0.70 (not high_risk)
            self_loop_ratio=0.05,    # < 0.20 (not suspicious)
            asof_ts=datetime.now(),
            window_min=60
        )
        
        verdict = evaluate(features, valid_rules)
        
        assert verdict.decision == "hold"
        assert verdict.confidence == 0.5
        assert verdict.note is None
    
    def test_insufficient_window(self, valid_rules):
        """Test insufficient verdict when window is not supported."""
        features = OnchainFeature(
            active_addr_pctl=0.85,
            growth_ratio=1.5,
            top10_share=0.3,
            self_loop_ratio=0.05,
            asof_ts=datetime.now(),
            window_min=90  # Not in [30, 60, 180]
        )
        
        verdict = evaluate(features, valid_rules)
        
        assert verdict.decision == "insufficient"
        assert verdict.confidence == 0.0
        assert verdict.note == "window_unsupported"
    
    def test_threshold_missing(self):
        """Test insufficient verdict when threshold label is missing."""
        # Create rules with missing threshold label
        rules = Rules(
            windows=[30, 60, 180],
            thresholds={
                'active_addr_pctl': {'mid': 0.80},  # Missing 'high'
                'growth_ratio': {'fast': 2.0, 'slow': 1.2},
                'top10_share': {'high_risk': 0.70, 'mid_risk': 0.40},
                'self_loop_ratio': {'suspicious': 0.20, 'watch': 0.10}
            },
            verdict={
                'upgrade_if': ['active_addr_pctl>=high'],  # References missing 'high'
                'downgrade_if': ['top10_share>=high_risk']
            }
        )
        
        features = OnchainFeature(
            active_addr_pctl=0.96,
            growth_ratio=1.5,
            top10_share=0.3,
            self_loop_ratio=0.05,
            asof_ts=datetime.now(),
            window_min=60
        )
        
        verdict = evaluate(features, rules)
        
        assert verdict.decision == "insufficient"
        assert verdict.confidence == 0.0
        assert verdict.note == "threshold_label_missing"
    
    def test_feature_out_of_range(self, valid_rules):
        """Test insufficient verdict when feature values are out of range."""
        features = OnchainFeature(
            active_addr_pctl=0.85,
            growth_ratio=1.5,
            top10_share=1.5,  # > 1.0, invalid
            self_loop_ratio=0.05,
            asof_ts=datetime.now(),
            window_min=60
        )
        
        verdict = evaluate(features, valid_rules)
        
        assert verdict.decision == "insufficient"
        assert verdict.confidence == 0.0
        assert verdict.note == "feature_out_of_range"
    
    def test_yaml_invalid(self):
        """Test that invalid YAML structure triggers proper error handling."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            # Write invalid YAML with extra keys
            yaml.dump({
                'windows': [30, 60],
                'thresholds': {'active_addr_pctl': {'high': 0.95}},
                'verdict': {'upgrade_if': ['active_addr_pctl>=high']},
                'invalid_key': 'should_not_exist'  # Invalid extra key
            }, f)
            temp_path = f.name
        
        try:
            # Should raise ValueError
            with pytest.raises(ValueError, match="Invalid keys"):
                load_rules(temp_path)
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    def test_load_rules_missing_file(self):
        """Test that missing file is handled properly."""
        with pytest.raises(ValueError, match="Failed to load rules file"):
            load_rules('/nonexistent/path/rules.yml')
    
    def test_load_rules_valid(self, valid_rules_yaml):
        """Test successful loading of valid rules."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(valid_rules_yaml, f)
            temp_path = f.name
        
        try:
            rules = load_rules(temp_path)
            assert rules.windows == [30, 60, 180]
            assert 'active_addr_pctl' in rules.thresholds
            assert 'upgrade_if' in rules.verdict
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    def test_negative_growth_ratio(self, valid_rules):
        """Test that negative growth_ratio triggers insufficient verdict."""
        features = OnchainFeature(
            active_addr_pctl=0.85,
            growth_ratio=-0.5,  # Negative, invalid
            top10_share=0.3,
            self_loop_ratio=0.05,
            asof_ts=datetime.now(),
            window_min=60
        )
        
        verdict = evaluate(features, valid_rules)
        
        assert verdict.decision == "insufficient"
        assert verdict.confidence == 0.0
        assert verdict.note == "feature_out_of_range"
    
    def test_partial_upgrade_conditions(self, valid_rules):
        """Test hold when only some upgrade conditions are met."""
        features = OnchainFeature(
            active_addr_pctl=0.96,  # >= 0.95 (high) - meets condition
            growth_ratio=1.5,        # < 2.0 (not fast) - doesn't meet condition
            top10_share=0.3,
            self_loop_ratio=0.05,
            asof_ts=datetime.now(),
            window_min=60
        )
        
        verdict = evaluate(features, valid_rules)
        
        assert verdict.decision == "hold"
        assert verdict.confidence == 0.5
        assert verdict.note is None
    
    def test_partial_downgrade_conditions(self, valid_rules):
        """Test hold when only some downgrade conditions are met."""
        features = OnchainFeature(
            active_addr_pctl=0.85,
            growth_ratio=1.5,
            top10_share=0.75,     # >= 0.70 (high_risk) - meets condition
            self_loop_ratio=0.05, # < 0.20 (not suspicious) - doesn't meet condition
            asof_ts=datetime.now(),
            window_min=60
        )
        
        verdict = evaluate(features, valid_rules)
        
        assert verdict.decision == "hold"
        assert verdict.confidence == 0.5
        assert verdict.note is None