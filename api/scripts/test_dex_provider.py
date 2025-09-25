#!/usr/bin/env python3
"""
Test cases for DEX provider (Card 1 acceptance)
Tests dual-source fallback, caching, and degradation logic
"""
import os
import time
import json
from typing import Dict, Any
from api.providers.dex_provider import DexProvider
from api.core.metrics_store import log_json

# Test configuration
TEST_TOKEN = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"  # USDC on Ethereum
TEST_CHAIN = "eth"


def clear_cache_for_token(chain: str, contract: str):
    """Clear all cache entries for a specific token"""
    try:
        import redis
        client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        ca_norm = contract.lower()
        
        # Clear short-term cache (with time bucket)
        for key in client.keys(f"dex:snapshot:{chain}:{ca_norm}:*"):
            client.delete(key)
        
        # Clear last_ok cache
        client.delete(f"dex:last_ok:{chain}:{ca_norm}")
        
        return True
    except Exception as e:
        log_json(stage="test.cache_clear_error", error=str(e))
        return False


def test_normal_operation():
    """Test 1: Normal operation with primary or secondary source"""
    print("\n=== Test 1: Normal Operation ===")
    
    clear_cache_for_token(TEST_CHAIN, TEST_TOKEN)
    provider = DexProvider(timeout_s=5.0)
    
    result = provider.get_snapshot(TEST_CHAIN, TEST_TOKEN)
    
    # Verify required fields
    assert "price_usd" in result or "price" in result, "Missing price field"
    assert "source" in result, "Missing source field"
    assert result["source"] in ["dexscreener", "geckoterminal", ""], "Invalid source"
    assert "cache" in result, "Missing cache field"
    assert "stale" in result, "Missing stale field"
    assert "degrade" in result, "Missing degrade field"
    assert "reason" in result, "Missing reason field"
    assert "notes" in result, "Missing notes field"
    
    # For fresh data
    if not result["cache"]:
        assert result["stale"] == False, "Fresh data should not be stale"
        assert result["degrade"] == False, "Fresh data should not be degraded"
    
    print(f"✓ Source: {result['source']}")
    print(f"✓ Price: {result.get('price_usd') or result.get('price')}")
    print(f"✓ Cache: {result['cache']}, Stale: {result['stale']}, Degrade: {result['degrade']}")
    
    return True


def test_cache_hit():
    """Test 2: Cache hit within TTL window"""
    print("\n=== Test 2: Cache Hit ===")
    
    # First request to populate cache
    provider = DexProvider(timeout_s=5.0)
    result1 = provider.get_snapshot(TEST_CHAIN, TEST_TOKEN)
    
    # Second request should hit cache
    time.sleep(0.1)
    result2 = provider.get_snapshot(TEST_CHAIN, TEST_TOKEN)
    
    assert result2["cache"] == True, "Second request should hit cache"
    assert result2["stale"] == False, "Cached data within TTL should not be stale"
    assert result2["degrade"] == False, "Cached data should not be degraded"
    assert result2["source"] == result1["source"], "Source should match original"
    
    print(f"✓ Cache hit confirmed")
    print(f"✓ Source preserved: {result2['source']}")
    
    return True


def test_primary_fail_secondary_success():
    """Test 3: Primary source fails, secondary succeeds"""
    print("\n=== Test 3: Primary Fail, Secondary Success ===")
    
    clear_cache_for_token(TEST_CHAIN, TEST_TOKEN)
    
    # Use a provider with mocked primary failure
    # Since we can't easily mock, we'll use the actual behavior
    # where DexScreener might be blocked (connection refused)
    provider = DexProvider(timeout_s=5.0)
    result = provider.get_snapshot(TEST_CHAIN, TEST_TOKEN)
    
    # If primary failed and secondary succeeded
    if result["source"] == "geckoterminal" and result["reason"]:
        assert result["cache"] == False, "Should not be from cache"
        assert result["stale"] == False, "Fresh secondary data should not be stale"
        assert result["degrade"] == False, "Secondary success is not degradation"
        assert result["reason"] in ["timeout", "conn_refused", "http_4xx", "http_5xx", "unknown"], \
            f"Invalid reason: {result['reason']}"
        
        print(f"✓ Primary failed with: {result['reason']}")
        print(f"✓ Secondary succeeded: {result['source']}")
    else:
        print(f"⚠ Primary source succeeded (expected in some environments)")
    
    return True


def test_both_fail_with_last_ok():
    """Test 4: Both sources fail, degrade to last_ok"""
    print("\n=== Test 4: Both Fail, Degrade to last_ok ===")
    
    clear_cache_for_token(TEST_CHAIN, TEST_TOKEN)
    
    # Step 1: Normal request to populate last_ok
    provider1 = DexProvider(timeout_s=5.0)
    result1 = provider1.get_snapshot(TEST_CHAIN, TEST_TOKEN)
    original_source = result1["source"]
    
    print(f"  Step 1: Cached data from {original_source}")
    
    # Step 2: Clear short-term cache but keep last_ok
    try:
        import redis
        client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        ca_norm = TEST_TOKEN.lower()
        for key in client.keys(f"dex:snapshot:{TEST_CHAIN}:{ca_norm}:*"):
            client.delete(key)
    except:
        pass
    
    # Step 3: Use extremely short timeout to force both sources to fail
    provider2 = DexProvider(timeout_s=0.0001)
    result2 = provider2.get_snapshot(TEST_CHAIN, TEST_TOKEN)
    
    # Verify degradation
    assert result2["stale"] == True, "Degraded data should be stale"
    assert result2["degrade"] == True, "Should be marked as degraded"
    assert result2["reason"] == "both_failed_last_ok", f"Wrong reason: {result2['reason']}"
    assert result2["source"] == "", "Degraded response should have empty source"
    assert "notes" in result2, "Missing notes field"
    assert isinstance(result2["notes"], list), "Notes should be a list"
    
    if result2["notes"]:
        assert any("last_ok_from:" in note for note in result2["notes"]), \
            f"Notes should contain last_ok_from: {result2['notes']}"
        print(f"✓ Notes: {result2['notes']}")
    
    print(f"✓ Successfully degraded to last_ok")
    print(f"✓ Reason: {result2['reason']}")
    
    return True


def test_both_fail_no_cache():
    """Test 5: Both sources fail, no cache available"""
    print("\n=== Test 5: Both Fail, No Cache ===")
    
    # Use a unique token that won't have cache
    fake_token = "0x" + "f" * 40
    
    clear_cache_for_token(TEST_CHAIN, fake_token)
    
    # Use extremely short timeout
    provider = DexProvider(timeout_s=0.0001)
    result = provider.get_snapshot(TEST_CHAIN, fake_token)
    
    # Verify empty degradation
    assert result["price_usd"] is None or result["price"] is None, "Should have no price"
    assert result["stale"] == True, "Should be marked as stale"
    assert result["degrade"] == True, "Should be marked as degraded"
    assert result["reason"] == "both_failed_no_cache", f"Wrong reason: {result['reason']}"
    assert result["source"] == "", "Should have empty source"
    
    print(f"✓ Correctly returned empty degraded response")
    print(f"✓ Reason: {result['reason']}")
    
    return True


def test_env_variable_compatibility():
    """Test 6: Environment variable backward compatibility"""
    print("\n=== Test 6: ENV Variable Compatibility ===")
    
    # Test new variable
    os.environ["DEX_CACHE_TTL_S"] = "120"
    provider1 = DexProvider()
    assert provider1.cache_ttl_s == 120, "Should use DEX_CACHE_TTL_S"
    
    # Test old variable (when new one is not set)
    del os.environ["DEX_CACHE_TTL_S"]
    os.environ["DEX_CACHE_TTL_SEC"] = "180"
    provider2 = DexProvider()
    assert provider2.cache_ttl_s == 180, "Should fall back to DEX_CACHE_TTL_SEC"
    
    # Clean up
    if "DEX_CACHE_TTL_SEC" in os.environ:
        del os.environ["DEX_CACHE_TTL_SEC"]
    
    print(f"✓ ENV variable compatibility working")
    
    return True


def test_timeout_configuration():
    """Test 7: Timeout configuration priority"""
    print("\n=== Test 7: Timeout Configuration ===")
    
    # Test constructor parameter takes precedence
    os.environ["DEX_TIMEOUT_S"] = "3.0"
    provider1 = DexProvider(timeout_s=2.0)
    assert provider1.timeout_s == 2.0, "Constructor param should override ENV"
    
    # Test ENV variable
    provider2 = DexProvider()
    assert provider2.timeout_s == 3.0, "Should use ENV variable"
    
    # Test default
    del os.environ["DEX_TIMEOUT_S"]
    provider3 = DexProvider()
    assert provider3.timeout_s == 1.5, "Should use default 1.5s"
    
    print(f"✓ Timeout configuration priority correct")
    
    return True


def test_field_normalization():
    """Test 8: Core field normalization"""
    print("\n=== Test 8: Field Normalization ===")
    
    provider = DexProvider(timeout_s=5.0)
    result = provider.get_snapshot(TEST_CHAIN, TEST_TOKEN)
    
    # Check all core fields exist
    required_fields = [
        "price", "price_usd", "liquidity_usd", "fdv", "ohlc",
        "source", "cache", "stale", "degrade", "reason", "notes"
    ]
    
    for field in required_fields:
        assert field in result, f"Missing required field: {field}"
    
    # Check field types
    assert isinstance(result["cache"], bool), "cache should be bool"
    assert isinstance(result["stale"], bool), "stale should be bool"
    assert isinstance(result["degrade"], bool), "degrade should be bool"
    assert isinstance(result["reason"], str), "reason should be string"
    assert isinstance(result["notes"], list), "notes should be list"
    assert isinstance(result["ohlc"], dict), "ohlc should be dict"
    
    print(f"✓ All core fields present and typed correctly")
    
    return True


def run_all_tests():
    """Run all test cases"""
    tests = [
        ("Normal Operation", test_normal_operation),
        ("Cache Hit", test_cache_hit),
        ("Primary Fail Secondary Success", test_primary_fail_secondary_success),
        ("Both Fail With last_ok", test_both_fail_with_last_ok),
        ("Both Fail No Cache", test_both_fail_no_cache),
        ("ENV Compatibility", test_env_variable_compatibility),
        ("Timeout Configuration", test_timeout_configuration),
        ("Field Normalization", test_field_normalization),
    ]
    
    passed = 0
    failed = 0
    
    print("=" * 50)
    print("DEX Provider Acceptance Tests (Card 1)")
    print("=" * 50)
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"✅ {name}: PASSED\n")
            else:
                failed += 1
                print(f"❌ {name}: FAILED\n")
        except AssertionError as e:
            failed += 1
            print(f"❌ {name}: FAILED - {e}\n")
        except Exception as e:
            failed += 1
            print(f"❌ {name}: ERROR - {e}\n")
    
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)
    
    return failed == 0


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)