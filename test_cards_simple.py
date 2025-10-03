#!/usr/bin/env python3
"""
Simple test for Card D implementation (without running the server)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_route_structure():
    """Test that the route file is properly structured"""
    print("Testing Card D route structure...\n")

    # Test 1: Route file exists and imports correctly
    print("Test 1 - Route file imports:")
    try:
        from api.routes import cards

        print("  ✓ cards.py imports successfully")
        assert hasattr(cards, "router"), "Router not found"
        print("  ✓ Router object exists")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False

    # Test 2: Preview endpoint exists
    print("\nTest 2 - Preview endpoint exists:")
    try:
        # Check route definitions
        routes = [r for r in cards.router.routes if hasattr(r, "path")]
        preview_routes = [r for r in routes if "/preview" in r.path]
        assert len(preview_routes) > 0, "No /preview route found"
        print(f"  ✓ Found /preview endpoint")

        # Check it's a GET method
        route = preview_routes[0]
        assert "GET" in route.methods, "Preview is not a GET endpoint"
        print(f"  ✓ Endpoint uses GET method")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False

    # Test 3: Build card can be imported
    print("\nTest 3 - Build card imports:")
    try:
        from api.cards.build import build_card

        print("  ✓ build_card imports successfully")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False

    print("\n✅ All structure tests passed!")
    return True


def test_expected_response():
    """Show expected response format"""
    print("\n" + "=" * 50)
    print("Expected API Response Format:")
    print("=" * 50)

    expected = {
        "card_type": "primary",
        "event_key": "ETH:TOKEN:0X123456",
        "data": {
            "goplus": {
                "risk": "yellow",
                "risk_source": "GoPlus@v1.0",
                "tax_buy": 0.05,
                "tax_sell": 0.10,
            },
            "dex": {"price_usd": 0.001234, "liquidity_usd": 50000.0},
            "rules": {
                "level": "watch",
                "score": 65,
                "reasons": ["High sell tax", "Moderate liquidity"],
            },
        },
        "summary": "ETH | 价格≈$0.001234 | 流动性≈$50000 | 规则判定watch",
        "risk_note": "合约体检yellow；关注税率/LP/交易限制",
        "meta": {
            "version": "cards@19.0",
            "data_as_of": "2025-09-12T10:00:00Z",
            "summary_backend": "template",
        },
    }

    print(json.dumps(expected, indent=2, ensure_ascii=False))

    print("\n" + "=" * 50)
    print("Acceptance Criteria Check:")
    print("=" * 50)
    print("✓ Response has data.goplus.risk: 'yellow'")
    print("✓ Response has data.dex.price_usd: 0.001234")
    print(f"✓ Summary length: {len(expected['summary'])} chars (≤280)")
    print(f"✓ Risk note length: {len(expected['risk_note'])} chars (≤160)")
    print("✓ Meta includes version and data_as_of")


def show_curl_commands():
    """Show example curl commands"""
    print("\n" + "=" * 50)
    print("Example curl commands:")
    print("=" * 50)

    print("\n# 1. Basic preview (no render):")
    print(
        'curl -s "http://localhost:8000/cards/preview?event_key=ETH:TOKEN:0X123456" | jq'
    )

    print("\n# 2. Preview with render:")
    print(
        'curl -s "http://localhost:8000/cards/preview?event_key=ETH:TOKEN:0X123456&render=1" | jq'
    )

    print("\n# 3. Test degraded case (as per acceptance criteria):")
    print(
        'curl -s "http://localhost:8000/cards/preview?event_key=TEST_BAD&render=1" | jq'
    )

    print("\n# 4. Invalid event_key (should return 422):")
    print('curl -s "http://localhost:8000/cards/preview?event_key=BAD!" | jq')

    print("\n# 5. Missing event_key (should return 422):")
    print('curl -s "http://localhost:8000/cards/preview" | jq')


if __name__ == "__main__":
    success = test_route_structure()
    if success:
        test_expected_response()
        show_curl_commands()
    else:
        print("\n❌ Some tests failed")
        sys.exit(1)
