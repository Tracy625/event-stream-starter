#!/usr/bin/env python3
"""End-to-end card generation and deduplication verification"""
import json
import sys
import os
import time
from typing import Dict, Any, List

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def log_json(stage: str, **kwargs):
    """Structured JSON logging"""
    log_entry = {"stage": stage, **kwargs}
    print(f"[JSON] {json.dumps(log_entry)}")

def test_card_generation() -> Dict[str, Any]:
    """Test card generation with templates"""
    try:
        from cards.generator import generate_card
        
        # Test data
        signals = {
            "dex_snapshot": {
                "price_usd": 1.5,
                "liquidity_usd": 5000.0,
                "fdv": 150000.0,
                "ohlc": {
                    "m5": {"o": 2.0, "h": 1.6, "l": 1.4, "c": 1.5},
                    "h1": {"o": -1.0, "h": 1.7, "l": 1.3, "c": 1.5},
                    "h24": {"o": 15.0, "h": 1.8, "l": 1.2, "c": 1.5}
                },
                "source": "dexscreener",
                "cache": False,
                "stale": False,
                "degrade": False,
                "reason": ""
            },
            "goplus_raw": {
                "summary": "Token security check passed"
            }
        }
        
        event = {
            "type": "primary",
            "risk_level": "green",
            "token_info": {
                "symbol": "TEST",
                "ca_norm": "0xabcdef1234567890abcdef1234567890abcdef12",
                "chain": "eth"
            },
            "risk_note": "Low risk token",
            "verify_path": "/tx/0xtest123",
            "data_as_of": "2025-09-02T18:00:00Z"
        }
        
        card = generate_card(event, signals)
        
        # Verify structure
        assert "type" in card
        assert "risk_level" in card
        assert "rendered" in card
        assert "tg" in card["rendered"]
        assert "ui" in card["rendered"]
        
        return {
            "pass": True,
            "test": "card_generation",
            "details": {
                "has_tg_template": len(card["rendered"]["tg"]) > 0,
                "has_ui_template": len(card["rendered"]["ui"]) > 0,
                "risk_level": card["risk_level"]
            }
        }
    except Exception as e:
        return {
            "pass": False,
            "test": "card_generation",
            "error": str(e),
            "details": {}
        }

def test_deduplication() -> Dict[str, Any]:
    """Test deduplication logic"""
    try:
        from cards.dedup import should_send
        import redis
        
        # Use test prefix to avoid pollution
        test_key = f"test:verify:{int(time.time())}"
        
        # Clear any existing key
        try:
            r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            r.delete(f"card:sent:{test_key}")
        except:
            pass
        
        # First call should return True
        first = should_send(test_key, ttl_s=5)  # Short TTL for testing
        
        # Second call should return False
        second = should_send(test_key, ttl_s=5)
        
        # Wait for expiry
        time.sleep(6)
        
        # Third call after expiry should return True
        third = should_send(test_key, ttl_s=5)
        
        success = (first == True and second == False and third == True)
        
        return {
            "pass": success,
            "test": "deduplication",
            "details": {
                "first_call": first,
                "second_call": second,
                "third_after_expiry": third
            }
        }
    except Exception as e:
        return {
            "pass": False,
            "test": "deduplication",
            "error": str(e),
            "details": {}
        }

def test_recheck_queue() -> Dict[str, Any]:
    """Test recheck queue functionality"""
    try:
        from cards.dedup import add_to_recheck
        import redis
        
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        
        # Clear queue
        r.delete("recheck:hot")
        
        # Add items with different priorities
        test_items = [
            ("test:high", 1),
            ("test:medium", 5),
            ("test:low", 10)
        ]
        
        for key, priority in test_items:
            add_to_recheck(key, priority)
        
        # Get items in priority order
        items = r.zrange("recheck:hot", 0, -1, withscores=True)
        
        # Verify order (lower score = higher priority)
        success = (
            len(items) == 3 and
            items[0][0].decode() == "test:high" and
            items[0][1] == 1.0 and
            items[1][0].decode() == "test:medium" and
            items[1][1] == 5.0 and
            items[2][0].decode() == "test:low" and
            items[2][1] == 10.0
        )
        
        return {
            "pass": success,
            "test": "recheck_queue",
            "details": {
                "items_added": len(test_items),
                "items_in_queue": len(items),
                "priority_order_correct": success
            }
        }
    except Exception as e:
        return {
            "pass": False,
            "test": "recheck_queue",
            "error": str(e),
            "details": {}
        }

def test_red_card_rules() -> Dict[str, Any]:
    """Test red card with rules_fired"""
    try:
        from cards.generator import generate_card
        
        signals = {
            "dex_snapshot": {
                "price_usd": 0.00001,
                "liquidity_usd": 100.0,
                "fdv": 10000.0,
                "ohlc": {
                    "m5": {"o": -90.0, "h": 0.00002, "l": 0.00001, "c": 0.00001},
                    "h1": {"o": -95.0, "h": 0.00003, "l": 0.00001, "c": 0.00001},
                    "h24": {"o": -99.0, "h": 0.00005, "l": 0.00001, "c": 0.00001}
                },
                "source": "dexscreener",
                "cache": False,
                "stale": False,
                "degrade": False,
                "reason": ""
            },
            "goplus_raw": {
                "summary": "DANGER: Honeypot detected! Buy tax: 99%, Sell tax: 99%"
            }
        }
        
        event = {
            "type": "primary",
            "risk_level": "red",
            "token_info": {
                "symbol": "SCAM",
                "ca_norm": "0x0000000000000000000000000000000000000001",
                "chain": "eth"
            },
            "risk_note": "HONEYPOT - DO NOT BUY",
            "verify_path": "/tx/0xscam",
            "data_as_of": "2025-09-02T18:00:00Z",
            "rules_fired": [
                "Honeypot detected",
                "Buy tax > 10%",
                "Sell tax > 10%",
                "Price drop > 90%"
            ]
        }
        
        card = generate_card(event, signals)
        
        # Verify red card specifics
        success = (
            card["risk_level"] == "red" and
            "rules_fired" in card and
            len(card["rules_fired"]) > 0 and
            "HONEYPOT" in card["risk_note"]
        )
        
        # Check that template contains warning
        tg_text = card["rendered"]["tg"]
        has_warning = "HIGH RISK" in tg_text and "Honeypot" in tg_text
        
        return {
            "pass": success and has_warning,
            "test": "red_card_rules",
            "details": {
                "risk_level": card["risk_level"],
                "rules_count": len(card.get("rules_fired", [])),
                "has_honeypot_warning": has_warning
            }
        }
    except Exception as e:
        return {
            "pass": False,
            "test": "red_card_rules",
            "error": str(e),
            "details": {}
        }

def main():
    """Run all verification tests"""
    log_json(stage="verify.card.start", mode="end_to_end")
    
    # Run all tests
    tests = [
        test_card_generation(),
        test_deduplication(),
        test_recheck_queue(),
        test_red_card_rules()
    ]
    
    # Log each test result
    for test in tests:
        log_json(
            stage="verify.card.test",
            test=test["test"],
            pass_status=test["pass"]
        )
    
    # Calculate summary
    passed = sum(1 for t in tests if t["pass"])
    total = len(tests)
    success = (passed == total)
    
    log_json(
        stage="verify.card.pass" if success else "verify.card.fail",
        passed=passed,
        total=total
    )
    
    # Output results
    output = {
        "pass": success,
        "tests": tests,
        "details": {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "test_names": [t["test"] for t in tests]
        }
    }
    
    print(json.dumps(output, indent=2))
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())