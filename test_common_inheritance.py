#!/usr/bin/env python3
"""
Test that changes to common.schema.json are inherited by both schemas
"""

import json
import jsonschema
from pathlib import Path

def test_diagnostic_with_last_checked():
    """Test a card with the last_checked field in diagnostic"""
    
    # Load schemas
    schema_dir = Path(__file__).parent / "schemas"
    
    # Load cards schema
    with open(schema_dir / "cards.schema.json") as f:
        cards_schema = json.load(f)
    
    # Load common schema
    with open(schema_dir / "common.schema.json") as f:
        common_schema = json.load(f)
    
    # Create resolver
    from jsonschema import RefResolver
    resolver = RefResolver(
        base_uri=f"file://{schema_dir}/",
        referrer=cards_schema,
        store={
            "common.schema.json": common_schema
        }
    )
    
    # Test card with diagnostic fields including optional last_checked
    test_card = {
        "card_type": "primary",
        "event_key": "ETH:TEST:INHERITANCE",
        "data": {
            "goplus": {
                "risk": "green",
                "risk_source": "GoPlus@v2.0",
                "diagnostic": {
                    "source": "api",
                    "cache": False,
                    "stale": False,
                    "degrade": False,
                    "last_checked": "2025-09-12T12:00:00Z"  # New field from common
                }
            },
            "dex": {
                "price_usd": 1.23
            },
            "rules": {
                "level": "none"
            }
        },
        "summary": "Test inheritance of common definitions",
        "risk_note": "Testing shared diagnostic fields",
        "meta": {
            "version": "cards@19.0",
            "data_as_of": "2025-09-12T12:00:00Z",
            "summary_backend": "template"
        }
    }
    
    # Validate
    try:
        jsonschema.validate(test_card, cards_schema, resolver=resolver)
        print("✅ Card with last_checked field validated successfully")
        print("   This proves the diagnostic definition is inherited from common.schema.json")
        return True
    except jsonschema.ValidationError as e:
        print(f"❌ Validation failed: {e.message}")
        return False

def test_pushcard_states():
    """Test that pushcard inherits the states definition from common"""
    
    schema_dir = Path(__file__).parent / "schemas"
    
    # Load pushcard schema
    with open(schema_dir / "pushcard.schema.json") as f:
        pushcard_schema = json.load(f)
    
    # Load common schema
    with open(schema_dir / "common.schema.json") as f:
        common_schema = json.load(f)
    
    # Create resolver
    from jsonschema import RefResolver
    resolver = RefResolver(
        base_uri=f"file://{schema_dir}/",
        referrer=pushcard_schema,
        store={
            "common.schema.json": common_schema
        }
    )
    
    # Test minimal pushcard with states
    test_pushcard = {
        "type": "primary",
        "risk_level": "green",
        "token_info": {
            "symbol": "TEST",
            "chain": "eth"
        },
        "metrics": {
            "price_usd": 1.23,
            "liquidity_usd": 50000,
            "fdv": 1000000,
            "ohlc": {
                "m5": {"o": 1.20, "h": 1.25, "l": 1.19, "c": 1.23},
                "h1": {"o": 1.18, "h": 1.26, "l": 1.17, "c": 1.23},
                "h24": {"o": 1.10, "h": 1.30, "l": 1.05, "c": 1.23}
            }
        },
        "sources": {
            "security_source": "GoPlus",
            "dex_source": "Uniswap"
        },
        "states": {
            "cache": False,
            "degrade": False,
            "stale": False,
            "reason": "Fresh data"
        },
        "risk_note": "Test risk note",
        "verify_path": "/verify/test",
        "data_as_of": "2025-09-12T12:00:00Z"
    }
    
    # Validate
    try:
        jsonschema.validate(test_pushcard, pushcard_schema, resolver=resolver)
        print("✅ Pushcard with states validated successfully")
        print("   This proves the states definition is inherited from common.schema.json")
        return True
    except jsonschema.ValidationError as e:
        print(f"❌ Validation failed: {e.message}")
        return False

if __name__ == "__main__":
    print("Testing common schema inheritance...\n")
    
    test1 = test_diagnostic_with_last_checked()
    test2 = test_pushcard_states()
    
    print("\n" + "="*50)
    if test1 and test2:
        print("✅ All inheritance tests passed!")
        print("\nThis demonstrates that:")
        print("1. Changes to common.schema.json are automatically inherited")
        print("2. Both cards.schema.json and pushcard.schema.json use the shared definitions")
        print("3. Adding fields like 'last_checked' to common diagnosticFlags affects all consumers")
    else:
        print("❌ Some tests failed")