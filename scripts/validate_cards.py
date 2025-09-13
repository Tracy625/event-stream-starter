#!/usr/bin/env python3
"""
Card schema validation script for Day19
Tests schemas/cards.schema.json with various test cases
"""

import json
import jsonschema
from pathlib import Path
import sys

def load_schema():
    """Load the cards schema with resolver for external $refs"""
    schema_dir = Path(__file__).parent.parent / "schemas"
    schema_path = schema_dir / "cards.schema.json"
    
    # Load main schema
    with open(schema_path) as f:
        schema = json.load(f)
    
    # Load common schema for $ref resolution
    common_path = schema_dir / "common.schema.json"
    if common_path.exists():
        with open(common_path) as f:
            common_schema = json.load(f)
        
        # Create a resolver that can handle the external reference
        from jsonschema import RefResolver
        resolver = RefResolver(
            base_uri=f"file://{schema_dir}/",
            referrer=schema,
            store={
                "common.schema.json": common_schema
            }
        )
        return schema, resolver
    
    return schema, None

def test_minimal_valid():
    """Test case 1: Minimal valid card with all required fields"""
    return {
        "card_type": "primary",
        "event_key": "ETH:TOKEN:0X1234567890",
        "data": {
            "goplus": {
                "risk": "green",
                "risk_source": "GoPlus@v1.0"
            },
            "dex": {
                "price_usd": 0.01
            },
            "rules": {
                "level": "none"
            }
        },
        "summary": "Test summary",
        "risk_note": "Test risk note",
        "meta": {
            "version": "cards@19.0",
            "data_as_of": "2025-09-12T10:00:00Z",
            "summary_backend": "template"
        }
    }

def test_without_optional():
    """Test case 2: Valid card without optional fields"""
    return {
        "card_type": "secondary",
        "event_key": "SOL:TOKEN:ABC123",
        "data": {
            "goplus": {
                "risk": "yellow",
                "risk_source": "GoPlus@v1.1"
            },
            "dex": {}
        },
        "summary": "Another test summary without optional fields",
        "risk_note": "Simple risk note",
        "meta": {
            "version": "cards@19.0",
            "data_as_of": "2025-09-12T11:00:00Z",
            "summary_backend": "llm"
        }
    }

def test_summary_too_long():
    """Test case 3: Invalid - summary exceeds maxLength"""
    card = test_minimal_valid()
    card["summary"] = "x" * 281  # Exceeds 280 char limit
    return card

def test_risk_note_too_long():
    """Test case 4: Invalid - risk_note exceeds maxLength"""
    card = test_minimal_valid()
    card["risk_note"] = "y" * 161  # Exceeds 160 char limit
    return card

def test_undefined_field():
    """Test case 5: Invalid - undefined field in object with additionalProperties:false"""
    card = test_minimal_valid()
    card["data"]["goplus"]["undefined_field"] = "should fail"
    return card

def test_invalid_enum():
    """Test case 6: Invalid - invalid enum value"""
    card = test_minimal_valid()
    card["data"]["goplus"]["risk"] = "purple"  # Not in enum
    return card

def test_complex_valid():
    """Test case 7: Complex valid card with many optional fields"""
    return {
        "card_type": "topic",
        "event_key": "ETH:MEME:PEPE:2025Q3",
        "data": {
            "goplus": {
                "risk": "red",
                "risk_source": "GoPlus@v2.0",
                "tax_buy": 0.15,
                "tax_sell": 0.25,
                "lp_locked": False,
                "honeypot": True,
                "diagnostic": {
                    "source": "cache",
                    "cache": True,
                    "stale": False,
                    "degrade": False
                }
            },
            "dex": {
                "price_usd": 0.0001234,
                "liquidity_usd": 50000.0,
                "fdv": 1234567.89,
                "ohlc": {
                    "m5": {
                        "open": 0.0001200,
                        "high": 0.0001250,
                        "low": 0.0001190,
                        "close": 0.0001234,
                        "ts": "2025-09-12T12:05:00Z"
                    }
                },
                "diagnostic": {
                    "source": "api",
                    "cache": False,
                    "stale": False,
                    "degrade": False
                }
            },
            "onchain": {
                "features_snapshot": {
                    "active_wallets": 1500,
                    "transactions_24h": 25000
                },
                "source_level": "confirmed"
            },
            "rules": {
                "level": "risk",
                "score": 95,
                "reasons": ["Honeypot detected", "High taxes", "Low liquidity"],
                "all_reasons": [
                    "Honeypot mechanism detected in contract",
                    "Buy tax exceeds 10% threshold",
                    "Sell tax exceeds 20% threshold",
                    "Liquidity below safety threshold",
                    "Suspicious contract patterns found"
                ]
            }
        },
        "summary": "High-risk meme token with honeypot mechanism and excessive taxes detected",
        "risk_note": "DO NOT BUY - Honeypot with 25% sell tax",
        "rendered": {
            "tg": "⚠️ HIGH RISK\nHoneypot detected\nTaxes: Buy 15% / Sell 25%",
            "ui": "<div class='alert-danger'>High Risk Token</div>"
        },
        "evidence": [
            {
                "type": "contract_analysis",
                "desc": "Honeypot mechanism found in transfer function",
                "url": "https://etherscan.io/address/0x123"
            },
            {
                "type": "tax_warning",
                "desc": "Excessive taxes detected"
            }
        ],
        "meta": {
            "version": "cards@19.0",
            "data_as_of": "2025-09-12T12:30:00Z",
            "summary_backend": "llm",
            "used_refiner": "gpt-4",
            "degrade": False
        }
    }

def validate_card(schema_and_resolver, card, test_name, should_pass=True):
    """Validate a card against the schema"""
    schema, resolver = schema_and_resolver
    try:
        if resolver:
            jsonschema.validate(card, schema, resolver=resolver)
        else:
            jsonschema.validate(card, schema)
        if should_pass:
            print(f"✅ {test_name}: PASSED (as expected)")
            return True
        else:
            print(f"❌ {test_name}: FAILED - Should have failed but passed")
            return False
    except jsonschema.ValidationError as e:
        if not should_pass:
            print(f"✅ {test_name}: FAILED (as expected) - {e.message}")
            return True
        else:
            print(f"❌ {test_name}: FAILED - {e.message}")
            print(f"   Path: {' > '.join(str(p) for p in e.path)}")
            return False

def main():
    """Run all validation tests"""
    print("Loading schema from schemas/cards.schema.json...")
    try:
        schema_and_resolver = load_schema()
        print("✓ Schema loaded successfully\n")
    except Exception as e:
        print(f"✗ Failed to load schema: {e}")
        return 1
    
    print("Running validation tests...\n")
    
    tests = [
        ("Minimal valid card", test_minimal_valid(), True),
        ("Without optional fields", test_without_optional(), True),
        ("Summary too long", test_summary_too_long(), False),
        ("Risk note too long", test_risk_note_too_long(), False),
        ("Undefined field", test_undefined_field(), False),
        ("Invalid enum value", test_invalid_enum(), False),
        ("Complex valid card", test_complex_valid(), True),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, card, should_pass in tests:
        if validate_card(schema_and_resolver, card, test_name, should_pass):
            passed += 1
        else:
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    
    if failed > 0:
        print("\n❌ Some tests failed")
        return 1
    else:
        print("\n✅ All tests passed!")
        return 0

if __name__ == "__main__":
    sys.exit(main())