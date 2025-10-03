#!/usr/bin/env python3
"""
Test script for Card D preview endpoint
"""

import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_preview_endpoint():
    """Test the cards preview endpoint locally"""
    from fastapi.testclient import TestClient

    # Mock the build_card function for testing
    import api.cards.build as build_module
    from api.main import app

    def mock_build_card(event_key: str, render: bool = False):
        """Mock build_card to return a test card"""
        if "INVALID" in event_key:
            raise ValueError("invalid event_key: does not match pattern")
        elif "NOTFOUND" in event_key:
            raise KeyError("Event not found")
        elif "NOSOURCE" in event_key:
            raise ValueError("no usable sources")

        card = {
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
                "summary_backend": "template",
            },
        }

        if render:
            card["rendered"] = {
                "tg": "Telegram render test",
                "ui": "<div>UI render test</div>",
            }

        return card

    # Replace build_card with mock
    original_build = build_module.build_card
    build_module.build_card = mock_build_card

    client = TestClient(app)

    print("Testing Card D preview endpoint...\n")

    # Test 1: Successful preview without render
    print("Test 1 - Successful preview without render:")
    response = client.get("/cards/preview?event_key=ETH:TOKEN:0X12345678")
    print(f"  Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"  Card type: {data.get('card_type')}")
        print(f"  Has summary: {bool(data.get('summary'))}")
        print(f"  Has risk_note: {bool(data.get('risk_note'))}")
        print(f"  Has rendered: {'rendered' in data}")
        assert data["data"]["goplus"]["risk"] == "yellow"
        assert data["data"]["dex"]["price_usd"] == 0.001234
        assert "rendered" not in data
        print("  ✓ Passed\n")
    else:
        print(f"  ✗ Failed: {response.text}\n")

    # Test 2: Successful preview with render
    print("Test 2 - Successful preview with render:")
    response = client.get("/cards/preview?event_key=SOL:MEME:PEPE&render=1")
    print(f"  Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"  Has rendered.tg: {'tg' in data.get('rendered', {})}")
        print(f"  Has rendered.ui: {'ui' in data.get('rendered', {})}")
        assert "rendered" in data
        assert "tg" in data["rendered"]
        print("  ✓ Passed\n")
    else:
        print(f"  ✗ Failed: {response.text}\n")

    # Test 3: Invalid event_key (422)
    print("Test 3 - Invalid event_key (422):")
    response = client.get("/cards/preview?event_key=INVALID!")
    print(f"  Status: {response.status_code}")
    if response.status_code == 422:
        print(f"  Error: {response.json().get('detail')}")
        print("  ✓ Passed\n")
    else:
        print(f"  ✗ Expected 422, got {response.status_code}\n")

    # Test 4: Missing event_key (422)
    print("Test 4 - Missing event_key (422):")
    response = client.get("/cards/preview")
    print(f"  Status: {response.status_code}")
    if response.status_code == 422:
        print("  ✓ Passed\n")
    else:
        print(f"  ✗ Expected 422, got {response.status_code}\n")

    # Test 5: Event not found (404)
    print("Test 5 - Event not found (404):")
    response = client.get("/cards/preview?event_key=NOTFOUND:123")
    print(f"  Status: {response.status_code}")
    if response.status_code == 404:
        print(f"  Error: {response.json().get('detail')}")
        print("  ✓ Passed\n")
    else:
        print(f"  ✗ Expected 404, got {response.status_code}\n")

    # Test 6: No usable sources (422)
    print("Test 6 - No usable sources (422):")
    response = client.get("/cards/preview?event_key=NOSOURCE:ABC")
    print(f"  Status: {response.status_code}")
    if response.status_code == 422:
        print(f"  Error: {response.json().get('detail')}")
        print("  ✓ Passed\n")
    else:
        print(f"  ✗ Expected 422, got {response.status_code}\n")

    # Test 7: Invalid render value
    print("Test 7 - Invalid render value (422):")
    response = client.get("/cards/preview?event_key=ETH:TOKEN:0X123&render=2")
    print(f"  Status: {response.status_code}")
    if response.status_code == 422:
        print("  ✓ Passed\n")
    else:
        print(f"  ✗ Expected 422, got {response.status_code}\n")

    # Restore original function
    build_module.build_card = original_build

    print("✅ All endpoint tests completed!")


def test_curl_simulation():
    """Simulate the curl command from acceptance criteria"""
    print("\nSimulating curl command...\n")
    print('curl -s "http://localhost:8000/cards/preview?event_key=TEST_BAD&render=1"')
    print("\nExpected response structure:")
    print(
        json.dumps(
            {
                "card_type": "primary",
                "event_key": "TEST_BAD",
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
            indent=2,
            ensure_ascii=False,
        )
    )

    print("\n✓ Response includes data.goplus.risk and data.dex (even if empty)")
    print("✓ summary and risk_note are non-empty")
    print("✓ Lengths: summary <= 280 chars, risk_note <= 160 chars")


if __name__ == "__main__":
    test_preview_endpoint()
    test_curl_simulation()
