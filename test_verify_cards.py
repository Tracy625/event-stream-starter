#!/usr/bin/env python3
"""
Test the Card E verification script locally (without server)
"""

import json
import os
import sys
from pathlib import Path


# Mock the requests module for testing without server
class MockResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data) if json_data else ""

    def json(self):
        return self._json_data


def mock_get(url, params=None, timeout=None):
    """Mock requests.get for testing"""
    event_key = params.get("event_key", "") if params else ""

    # Simulate different responses based on event_key
    if event_key == "TEST_BAD":
        # Degraded but valid response
        return MockResponse(
            200,
            {
                "card_type": "primary",
                "event_key": event_key,
                "data": {
                    "goplus": {"risk": "gray", "risk_source": "unavailable"},
                    "dex": {},
                    "rules": {"level": "none"},
                },
                "summary": "Token | 规则判定none",
                "risk_note": "合约体检gray；关注税率/LP/交易限制",
                "meta": {
                    "version": "cards@19.0",
                    "data_as_of": "2025-09-12T10:00:00Z",
                    "summary_backend": "template",
                    "degrade": True,
                },
            },
        )
    elif event_key == "TEST_GOOD":
        # Full valid response
        return MockResponse(
            200,
            {
                "card_type": "primary",
                "event_key": event_key,
                "data": {
                    "goplus": {"risk": "yellow", "risk_source": "GoPlus@v1.0"},
                    "dex": {"price_usd": 0.001234, "liquidity_usd": 50000.0},
                    "rules": {"level": "watch", "score": 65},
                },
                "summary": "TEST | 价格≈$0.001234 | 流动性≈$50000 | 规则判定watch",
                "risk_note": "合约体检yellow；关注税率/LP/交易限制",
                "meta": {
                    "version": "cards@19.0",
                    "data_as_of": "2025-09-12T10:00:00Z",
                    "summary_backend": "llm",
                    "used_refiner": "mini-llm",
                },
            },
        )
    elif "INVALID" in event_key:
        return MockResponse(422, {"detail": "invalid event_key"})
    else:
        return MockResponse(404, {"detail": f"Event key not found: {event_key}"})


def test_verify_script():
    """Test the verification script with mock responses"""

    # Monkey-patch requests module in the script
    import scripts.verify_cards_preview as verify_module

    verify_module.requests = type(
        "MockRequests", (), {"get": mock_get, "RequestException": Exception}
    )

    print("Testing Card E verification script...\n")

    # Test 1: Degraded but valid (TEST_BAD)
    print("Test 1 - Degraded but valid (TEST_BAD):")
    result = verify_module.verify_card_preview("TEST_BAD")
    print(json.dumps(result, indent=2))
    assert result["pass"] == True
    assert result["summary_backend"] == "template"
    assert result["has_goplus"] == True
    assert result["has_dex"] == True
    print("✓ Passed\n")

    # Test 2: Full valid response (TEST_GOOD)
    print("Test 2 - Full valid response (TEST_GOOD):")
    result = verify_module.verify_card_preview("TEST_GOOD")
    print(json.dumps(result, indent=2))
    assert result["pass"] == True
    assert result["summary_backend"] == "llm"
    assert result["has_goplus"] == True
    assert result["has_dex"] == True
    print("✓ Passed\n")

    # Test 3: Invalid event key
    print("Test 3 - Invalid event key:")
    result = verify_module.verify_card_preview("INVALID_KEY")
    print(json.dumps(result, indent=2))
    assert result["pass"] == False
    assert "422" in result["reason"]
    print("✓ Passed\n")

    # Test 4: Not found
    print("Test 4 - Event not found:")
    result = verify_module.verify_card_preview("NOTFOUND")
    print(json.dumps(result, indent=2))
    assert result["pass"] == False
    assert "404" in result["reason"]
    print("✓ Passed\n")

    # Test 5: With low timeout environment
    print("Test 5 - Low timeout should use template:")
    os.environ["CARDS_SUMMARY_TIMEOUT_MS"] = "1"
    result = verify_module.verify_card_preview("TEST_BAD")
    print(json.dumps(result, indent=2))
    assert result["pass"] == True
    assert result["summary_backend"] == "template"
    print("✓ Passed\n")

    print("✅ All verification tests passed!")


def test_make_command():
    """Show how to use the make command"""
    print("\n" + "=" * 50)
    print("Example Make Commands:")
    print("=" * 50)

    print("\n# Test with degraded response:")
    print("EVENT_KEY=TEST_BAD make verify_cards")

    print("\n# Test with low timeout (forces template):")
    print("CARDS_SUMMARY_TIMEOUT_MS=1 EVENT_KEY=TEST_BAD make verify_cards")

    print("\n# Test with different event keys:")
    print("EVENT_KEY=ETH:TOKEN:0X123456 make verify_cards")
    print("EVENT_KEY=SOL:MEME:PEPE2025 make verify_cards")

    print("\n# Direct script usage:")
    print("python scripts/verify_cards_preview.py --event-key TEST_BAD")
    print(
        "python scripts/verify_cards_preview.py --event-key ETH:TOKEN:0X123 --base-url http://localhost:8000"
    )


if __name__ == "__main__":
    test_verify_script()
    test_make_command()
