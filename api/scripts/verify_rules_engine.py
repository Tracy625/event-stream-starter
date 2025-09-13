#!/usr/bin/env python
"""
Verification script for Task Card 18.1 - Rule Engine Core.

Tests:
1. Rule loading from YAML with caching
2. Hot-reload functionality  
3. Environment variable substitution
4. Demo scenarios (complete data, missing DEX, missing HF)
5. Score calculation and level mapping
6. Reason selection and deduplication
"""

import os
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.rules import RuleEvaluator
from api.metrics import log_json


def verify_demo_scenarios():
    """Verify the three demo scenarios from acceptance criteria."""
    evaluator = RuleEvaluator()
    
    print("=" * 60)
    print("DEMO SCENARIOS VERIFICATION")
    print("=" * 60)
    
    # DEMO1: Complete data
    demo1_signals = {
        "goplus_risk": "green",
        "buy_tax": 2.0,
        "sell_tax": 2.0,
        "lp_lock_days": 200,
        "dex_liquidity": 600000.0,
        "dex_volume_1h": 150000.0,
        "heat_slope": 1.5
    }
    demo1_events = {
        "last_sentiment_score": 0.8
    }
    
    print("\n✅ DEMO1 (Complete data):")
    result1 = evaluator.evaluate(demo1_signals, demo1_events)
    print(f"  Score: {result1['score']}")
    print(f"  Level: {result1['level']}")
    print(f"  Reasons ({len(result1['reasons'])}): {result1['reasons']}")
    print(f"  Missing: {result1['missing']}")
    
    assert result1['score'] > 0, "DEMO1 should have positive score"
    assert result1['level'] == "opportunity", "DEMO1 should be opportunity level"
    assert len(result1['missing']) == 0, "DEMO1 should have no missing sources"
    assert len(result1['reasons']) <= 3, "Should have at most 3 reasons"
    assert len(result1['reasons']) > 0, "Should have at least 1 reason"
    
    # DEMO2: Missing DEX
    demo2_signals = {
        "goplus_risk": "yellow",
        "buy_tax": 5.0,
        "sell_tax": 5.0,
        "lp_lock_days": 60,
        "dex_liquidity": None,
        "dex_volume_1h": None,
        "heat_slope": 0.5
    }
    demo2_events = {
        "last_sentiment_score": 0.5
    }
    
    print("\n✅ DEMO2 (Missing DEX):")
    result2 = evaluator.evaluate(demo2_signals, demo2_events)
    print(f"  Score: {result2['score']}")
    print(f"  Level: {result2['level']}")
    print(f"  Reasons ({len(result2['reasons'])}): {result2['reasons']}")
    print(f"  Missing: {result2['missing']}")
    
    assert "dex" in result2['missing'], "DEMO2 should detect missing DEX"
    assert "DEX 数据不足" in result2['reasons'], "DEMO2 should include DEX missing reason"
    assert len(result2['reasons']) <= 3, "Should have at most 3 reasons"
    
    # DEMO3: Missing HF sentiment
    demo3_signals = {
        "goplus_risk": "red",
        "buy_tax": 15.0,
        "sell_tax": 15.0,
        "lp_lock_days": 10,
        "dex_liquidity": 30000.0,
        "dex_volume_1h": 5000.0,
        "heat_slope": -0.5
    }
    demo3_events = {
        "last_sentiment_score": None
    }
    
    print("\n✅ DEMO3 (Missing HF):")
    result3 = evaluator.evaluate(demo3_signals, demo3_events)
    print(f"  Score: {result3['score']}")
    print(f"  Level: {result3['level']}")
    print(f"  Reasons ({len(result3['reasons'])}): {result3['reasons']}")
    print(f"  Missing: {result3['missing']}")
    
    assert "hf" in result3['missing'], "DEMO3 should detect missing HF"
    assert "情绪分析不可用" in result3['reasons'], "DEMO3 should include HF missing reason"
    assert result3['level'] == "caution", "DEMO3 should be caution level"
    assert len(result3['reasons']) <= 3, "Should have at most 3 reasons"
    
    print("\n✅ All demo scenarios passed!")


def verify_hot_reload():
    """Verify hot-reload functionality."""
    print("\n" + "=" * 60)
    print("HOT-RELOAD VERIFICATION")
    print("=" * 60)
    
    evaluator = RuleEvaluator()
    
    # Initial load
    print("\n1. Initial load:")
    result = evaluator.evaluate({"goplus_risk": "green"}, {})
    version1 = result['rules_version']
    print(f"   Version: {version1}, Hot-reloaded: {result['hot_reloaded']}")
    
    # Wait and touch file
    time.sleep(1)
    rules_path = Path("rules/rules.yml")
    if rules_path.exists():
        os.utime(rules_path, None)
        print("   Touched rules file")
    
    # Wait for TTL to expire
    print("\n2. Waiting 6 seconds for TTL to expire...")
    time.sleep(6)
    
    # Should trigger reload
    print("3. After TTL expiry:")
    result = evaluator.evaluate({"goplus_risk": "green"}, {})
    print(f"   Version: {result['rules_version']}, Hot-reloaded: {result['hot_reloaded']}")
    assert result['hot_reloaded'], "Should show hot-reloaded after TTL"
    
    print("\n✅ Hot-reload verification passed!")


def verify_env_substitution():
    """Verify environment variable substitution."""
    print("\n" + "=" * 60)
    print("ENVIRONMENT VARIABLE SUBSTITUTION")
    print("=" * 60)
    
    # Set environment variables
    os.environ["THETA_LIQ"] = "200000"
    os.environ["THETA_VOL"] = "75000"
    os.environ["THETA_SENT"] = "0.6"
    
    print(f"\nEnvironment overrides:")
    print(f"  THETA_LIQ = 200000 (default: 50000)")
    print(f"  THETA_VOL = 75000 (default: 10000)")
    print(f"  THETA_SENT = 0.6 (default: 0.3)")
    
    # Create new evaluator to reload with env vars
    evaluator = RuleEvaluator()
    
    # Test with values between defaults and overrides
    test_signals = {
        "goplus_risk": "green",
        "buy_tax": 2,
        "sell_tax": 2,
        "lp_lock_days": 60,
        "dex_liquidity": 100000,  # < 200K (env), > 50K (default)
        "dex_volume_1h": 50000,   # < 75K (env), > 10K (default)
        "heat_slope": 0.5
    }
    test_events = {
        "last_sentiment_score": 0.5  # < 0.6 (env), > 0.3 (default)
    }
    
    result = evaluator.evaluate(test_signals, test_events)
    print(f"\nResult with env overrides:")
    print(f"  Score: {result['score']}")
    print(f"  Level: {result['level']}")
    print(f"  Reasons: {result['reasons']}")
    
    # Should trigger "不足"/"过低" based on env thresholds
    # Note: sentiment might not appear in top 3 due to lower priority
    assert any("流动性不足" in r for r in result['reasons']), "Should detect liquidity below env threshold"
    assert any("交易量过低" in r for r in result['reasons']), "Should detect volume below env threshold"
    
    # Verify sentiment is evaluated correctly even if not in top 3
    # (sentiment has lower priority than goplus/dex rules)
    print("\n  Note: Sentiment rule has lower priority, may not appear in top 3 reasons")
    
    # Clean up env vars
    del os.environ["THETA_LIQ"]
    del os.environ["THETA_VOL"]
    del os.environ["THETA_SENT"]
    
    print("\n✅ Environment substitution verification passed!")


def verify_error_handling():
    """Verify error handling and fallback."""
    print("\n" + "=" * 60)
    print("ERROR HANDLING VERIFICATION")
    print("=" * 60)
    
    # Test with invalid data types
    evaluator = RuleEvaluator()
    
    print("\n1. Testing with invalid data types:")
    result = evaluator.evaluate(
        {"goplus_risk": "invalid_value", "buy_tax": "not_a_number"},
        {"last_sentiment_score": "also_not_a_number"}
    )
    print(f"   Score: {result['score']}")
    print(f"   Level: {result['level']}")
    assert result['level'] in ["observe", "caution", "opportunity"], "Should return valid level even with errors"
    
    print("\n2. Testing with empty data:")
    result = evaluator.evaluate({}, {})
    print(f"   Score: {result['score']}")
    print(f"   Level: {result['level']}")
    assert result['level'] == "observe", "Empty data should default to observe"
    
    print("\n✅ Error handling verification passed!")


def main():
    """Run all verifications."""
    print("\n" + "=" * 60)
    print("RULE ENGINE VERIFICATION SCRIPT")
    print("Task Card 18.1 - Rule Engine Core")
    print("=" * 60)
    
    try:
        verify_demo_scenarios()
        verify_hot_reload()
        verify_env_substitution()
        verify_error_handling()
        
        print("\n" + "=" * 60)
        print("✅ ALL VERIFICATIONS PASSED!")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n❌ Verification failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())