#!/usr/bin/env python3
"""
Test script for Card C builder validation
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Mock the providers since they don't exist yet
class MockProviders:
    @staticmethod
    def mock_goplus_data():
        return {
            "risk": "yellow",
            "source": "GoPlus@v1.2",
            "buy_tax": 0.05,
            "sell_tax": 0.10,
            "lp_locked": True,
            "is_honeypot": False,
            "as_of": datetime.now(timezone.utc).isoformat() + "Z",
        }

    @staticmethod
    def mock_dex_data():
        return {
            "price_usd": 0.001234,
            "liquidity_usd": 125000.0,
            "fdv": 5000000.0,
            "m5": {
                "open": 0.001200,
                "high": 0.001250,
                "low": 0.001180,
                "close": 0.001234,
                "ts": datetime.now(timezone.utc).isoformat() + "Z",
            },
            "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
        }

    @staticmethod
    def mock_rules_data():
        return {
            "level": "watch",
            "score": 65,
            "reasons": ["High sell tax", "Moderate liquidity"],
            "all_reasons": [
                "High sell tax detected",
                "Moderate liquidity concerns",
                "Recent price volatility",
                "New token warning",
            ],
        }

    @staticmethod
    def mock_evidence_data():
        return [
            {
                "type": "price_alert",
                "desc": "Price increased 50% in 1 hour",
                "url": "https://example.com/alert1",
            },
            {
                "type": "whale_activity",
                "description": "Large wallet accumulated 5% of supply",
            },
        ]


# Monkey-patch the imports in build.py
import api.cards.build as build_module

original_get_goplus = build_module._get_goplus_data
original_get_dex = build_module._get_dex_data
original_get_rules = build_module._get_rules_data
original_get_evidence = build_module._get_evidence_data


def load_schema():
    """Load the cards schema for validation"""
    schema_path = Path(__file__).parent / "schemas" / "cards.schema.json"
    with open(schema_path) as f:
        return json.load(f)


def test_successful_build():
    """Test building a card with all data sources available"""
    print("Test 1 - Successful build with all sources:")

    # Mock all providers to return data
    build_module._get_goplus_data = lambda x: MockProviders.mock_goplus_data()
    build_module._get_dex_data = lambda x: MockProviders.mock_dex_data()
    build_module._get_rules_data = lambda x: MockProviders.mock_rules_data()
    build_module._get_evidence_data = lambda x: MockProviders.mock_evidence_data()

    try:
        from api.cards.build import build_card

        card = build_card("ETH:TOKEN:0x1234567890ABCDEF")

        print(f"  Card type: {card['card_type']}")
        print(f"  Summary: {card['summary']}")
        print(f"  Risk note: {card['risk_note']}")
        print(f"  Has GoPlus: {'goplus' in card['data']}")
        print(f"  Has DEX: {'dex' in card['data']}")
        print(f"  Has rules: {'rules' in card['data']}")
        print(f"  Has evidence: {'evidence' in card}")
        print(f"  Meta version: {card['meta']['version']}")
        print(f"  Degraded: {card['meta'].get('degrade', False)}")

        # Validate against schema
        schema = load_schema()
        jsonschema.validate(card, schema)
        print("  ✓ Schema validation passed\n")

    except Exception as e:
        print(f"  ✗ Failed: {e}\n")
        return False

    return True


def test_missing_goplus():
    """Test building with missing GoPlus data"""
    print("Test 2 - Missing GoPlus data (degraded):")

    # Mock providers with GoPlus returning None
    build_module._get_goplus_data = lambda x: None
    build_module._get_dex_data = lambda x: MockProviders.mock_dex_data()
    build_module._get_rules_data = lambda x: MockProviders.mock_rules_data()
    build_module._get_evidence_data = lambda x: None

    try:
        from api.cards.build import build_card

        card = build_card("SOL:TOKEN:ABC123")

        print(f"  Has GoPlus: {'goplus' in card['data']}")
        print(f"  GoPlus risk: {card['data']['goplus'].get('risk', 'N/A')}")
        print(f"  Has DEX: {'dex' in card['data']}")
        print(f"  Degraded: {card['meta'].get('degrade', False)}")
        print(f"  Rules reasons: {card['data']['rules'].get('reasons', [])}")

        assert card["data"]["goplus"]["risk"] == "gray", "GoPlus should have gray risk"
        assert (
            card["data"]["goplus"]["risk_source"] == "unavailable"
        ), "GoPlus should be unavailable"
        assert card["meta"].get("degrade") == True, "Should be degraded"
        assert "missing goplus" in card["data"]["rules"].get(
            "reasons", []
        ), "Should have degrade reason"

        # Validate against schema
        schema = load_schema()
        jsonschema.validate(card, schema)
        print("  ✓ Passed with degradation\n")

    except Exception as e:
        print(f"  ✗ Failed: {e}\n")
        return False

    return True


def test_no_sources():
    """Test building with no data sources (should fail)"""
    print("Test 3 - No data sources (should fail):")

    # All providers return None
    build_module._get_goplus_data = lambda x: None
    build_module._get_dex_data = lambda x: None
    build_module._get_rules_data = lambda x: None
    build_module._get_evidence_data = lambda x: None

    try:
        from api.cards.build import build_card

        card = build_card("BSC:TOKEN:XYZ789")
        print(f"  ✗ Should have failed but returned: {card}\n")
        return False

    except ValueError as e:
        if "no usable sources" in str(e):
            print(f"  ✓ Correctly failed: {e}\n")
            return True
        else:
            print(f"  ✗ Wrong error: {e}\n")
            return False
    except Exception as e:
        print(f"  ✗ Unexpected error: {e}\n")
        return False


def test_invalid_event_key():
    """Test with invalid event_key format"""
    print("Test 4 - Invalid event_key:")

    try:
        from api.cards.build import build_card

        card = build_card("bad!")
        print(f"  ✗ Should have failed but returned: {card}\n")
        return False

    except ValueError as e:
        if "invalid event_key" in str(e):
            print(f"  ✓ Correctly rejected: {e}\n")
            return True
        else:
            print(f"  ✗ Wrong error: {e}\n")
            return False
    except Exception as e:
        print(f"  ✗ Unexpected error: {e}\n")
        return False


def test_partial_data():
    """Test with DEX data only"""
    print("Test 5 - Partial data (DEX only):")

    # Only DEX returns data
    build_module._get_goplus_data = lambda x: None
    build_module._get_dex_data = lambda x: MockProviders.mock_dex_data()
    build_module._get_rules_data = lambda x: None
    build_module._get_evidence_data = lambda x: None

    try:
        from api.cards.build import build_card

        card = build_card("ETH:MEME:PEPE2025")

        print(f"  Has DEX: {'dex' in card['data']}")
        print(f"  Price: ${card['data']['dex'].get('price_usd', 'N/A')}")
        print(f"  Rules level: {card['data']['rules']['level']}")
        print(f"  Degraded: {card['meta'].get('degrade', False)}")
        print(f"  Summary: {card['summary']}")

        # Validate against schema
        schema = load_schema()
        jsonschema.validate(card, schema)
        print("  ✓ Schema validation passed\n")

    except Exception as e:
        print(f"  ✗ Failed: {e}\n")
        return False

    return True


if __name__ == "__main__":
    print("Running Card C builder tests...\n")

    # Ensure template mode for predictable testing
    os.environ["CARDS_SUMMARY_BACKEND"] = "template"

    results = []
    results.append(test_successful_build())
    results.append(test_missing_goplus())
    results.append(test_no_sources())
    results.append(test_invalid_event_key())
    results.append(test_partial_data())

    # Restore original functions
    build_module._get_goplus_data = original_get_goplus
    build_module._get_dex_data = original_get_dex
    build_module._get_rules_data = original_get_rules
    build_module._get_evidence_data = original_get_evidence

    passed = sum(results)
    failed = len(results) - passed

    print(f"{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed > 0:
        print("\n❌ Some tests failed")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)
