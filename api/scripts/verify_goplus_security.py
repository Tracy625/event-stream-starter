#!/usr/bin/env python
"""Verify GoPlus security checks work correctly in rules mode"""
import os
import sys

# Force rules mode if not set
if not os.getenv("SECURITY_BACKEND"):
    os.environ["SECURITY_BACKEND"] = "rules"

# Import after setting environment
from api.providers.goplus_provider import GoPlusProvider
from api.core.metrics_store import log_json

def main():
    """Run verification tests for GoPlus provider"""
    
    # Test samples - using addresses that match rules in risk_rules.example.yml
    samples = [
        {
            "chain_id": "1",
            "address": "0xbad0000000000000000000000000000000000000",  # Blacklisted in example rules
            "expected": "red",
            "reason": "blacklisted"
        },
        {
            "chain_id": "56", 
            "address": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",  # Another blacklisted
            "expected": "red",
            "reason": "blacklisted"
        },
        {
            "chain_id": "1",
            "address": "0x0000000000000000000000000000000000000000",  # Zero address blacklisted
            "expected": "red",
            "reason": "blacklisted"
        }
    ]
    
    provider = GoPlusProvider()
    all_passed = True
    
    print(f"Running GoPlus verification with {len(samples)} samples...")
    
    # First run - check risk labels
    print("\n=== First Run: Checking risk labels ===")
    first_run_results = []
    
    for i, sample in enumerate(samples, 1):
        try:
            result = provider.check_token(sample["chain_id"], sample["address"])
            first_run_results.append(result)
            
            if result.risk_label == sample["expected"]:
                print(f"✓ Sample {i}: {sample['address'][:10]}... = {result.risk_label} (expected: {sample['expected']}) - PASS")
                log_json(
                    stage="verify.sample",
                    sample=i,
                    address=sample["address"][:10],
                    risk=result.risk_label,
                    expected=sample["expected"],
                    cache=result.cache,
                    passed=True
                )
            else:
                print(f"✗ Sample {i}: {sample['address'][:10]}... = {result.risk_label} (expected: {sample['expected']}) - FAIL")
                log_json(
                    stage="verify.sample",
                    sample=i,
                    address=sample["address"][:10],
                    risk=result.risk_label,
                    expected=sample["expected"],
                    cache=result.cache,
                    passed=False
                )
                all_passed = False
                
        except Exception as e:
            print(f"✗ Sample {i}: Error - {str(e)}")
            log_json(stage="verify.error", sample=i, error=str(e))
            all_passed = False
    
    # Second run - check cache hits
    print("\n=== Second Run: Checking cache hits ===")
    cache_hits = 0
    
    for i, sample in enumerate(samples, 1):
        try:
            result = provider.check_token(sample["chain_id"], sample["address"])
            
            if result.cache:
                cache_hits += 1
                print(f"✓ Sample {i}: Cache hit = {result.cache}")
                log_json(
                    stage="verify.cache",
                    sample=i,
                    address=sample["address"][:10],
                    cache=result.cache,
                    passed=True
                )
            else:
                print(f"✗ Sample {i}: Cache hit = {result.cache} (expected: True)")
                log_json(
                    stage="verify.cache",
                    sample=i,
                    address=sample["address"][:10],
                    cache=result.cache,
                    passed=False
                )
                all_passed = False
                
        except Exception as e:
            print(f"✗ Sample {i}: Error - {str(e)}")
            log_json(stage="verify.error", sample=i, error=str(e))
            all_passed = False
    
    # Summary
    print(f"\n=== Summary ===")
    print(f"Cache hits: {cache_hits}/{len(samples)}")
    
    if all_passed:
        print("✓ All tests PASSED")
        log_json(stage="verify.pass", samples=len(samples), cache_hits=cache_hits)
        sys.exit(0)
    else:
        print("✗ Some tests FAILED")
        log_json(stage="verify.fail", reason="Some tests failed", cache_hits=cache_hits)
        sys.exit(1)

if __name__ == "__main__":
    main()