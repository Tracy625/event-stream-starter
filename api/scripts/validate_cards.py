#!/usr/bin/env python3
"""Pure schema validation for card structure"""
import json
import sys
from typing import Any, Dict, List

from jsonschema import Draft7Validator, ValidationError, validate


def log_json(stage: str, **kwargs):
    """Structured JSON logging"""
    log_entry = {"stage": stage, **kwargs}
    print(f"[JSON] {json.dumps(log_entry)}")


def validate_card_schema(card: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate card against pushcard.schema.json

    Returns:
        Dict with pass status and details
    """
    try:
        # Load schema
        with open("schemas/pushcard.schema.json", "r") as f:
            schema = json.load(f)

        # Validate schema itself
        Draft7Validator.check_schema(schema)

        # Remove rendered field if present (not part of schema)
        test_card = card.copy()
        test_card.pop("rendered", None)

        # Validate card
        validate(test_card, schema)

        return {
            "pass": True,
            "test": "schema_validation",
            "details": {
                "card_type": card.get("type"),
                "risk_level": card.get("risk_level"),
                "has_rendered": "rendered" in card,
            },
        }
    except ValidationError as e:
        return {
            "pass": False,
            "test": "schema_validation",
            "error": str(e),
            "details": {"path": list(e.path), "message": e.message},
        }
    except Exception as e:
        return {
            "pass": False,
            "test": "schema_validation",
            "error": str(e),
            "details": {},
        }


def main():
    """Run schema validation tests"""
    log_json(stage="verify.card.start", mode="schema_only")

    # Test data
    test_cards = [
        # Valid red card
        {
            "type": "primary",
            "risk_level": "red",
            "token_info": {
                "symbol": "SCAM",
                "ca_norm": "0x1234567890abcdef1234567890abcdef12345678",
                "chain": "eth",
            },
            "metrics": {
                "price_usd": 0.0001,
                "liquidity_usd": 1000.0,
                "fdv": 100000.0,
                "ohlc": {
                    "m5": {"o": -5.0, "h": 0.0002, "l": 0.0001, "c": 0.0001},
                    "h1": {"o": -10.0, "h": 0.0003, "l": 0.0001, "c": 0.0001},
                    "h24": {"o": -50.0, "h": 0.0005, "l": 0.0001, "c": 0.0001},
                },
            },
            "sources": {"security_source": "goplus", "dex_source": "dexscreener"},
            "states": {"cache": False, "degrade": False, "stale": False, "reason": ""},
            "evidence": {"goplus_raw": {"summary": "High risk token detected"}},
            "risk_note": "HONEYPOT DETECTED",
            "verify_path": "https://etherscan.io/token/0x1234567890abcdef1234567890abcdef12345678",
            "data_as_of": "2025-09-02T16:00:00Z",
            "rules_fired": ["Honeypot detected", "High tax"],
        },
        # Valid green card
        {
            "type": "primary",
            "risk_level": "green",
            "token_info": {
                "symbol": "USDC",
                "ca_norm": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                "chain": "eth",
            },
            "metrics": {
                "price_usd": 0.9998,
                "liquidity_usd": 50000000.0,
                "fdv": 47000000000.0,
                "ohlc": {
                    "m5": {"o": 0.01, "h": 1.0001, "l": 0.9997, "c": 0.9998},
                    "h1": {"o": 0.0, "h": 1.0002, "l": 0.9996, "c": 0.9998},
                    "h24": {"o": -0.02, "h": 1.0005, "l": 0.9995, "c": 0.9998},
                },
            },
            "sources": {"security_source": "goplus", "dex_source": "dexscreener"},
            "states": {"cache": True, "degrade": False, "stale": False, "reason": ""},
            "evidence": {"goplus_raw": {"summary": "Safe token"}},
            "risk_note": "Stable and safe",
            "verify_path": "https://etherscan.io/token/0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "data_as_of": "2025-09-02T16:00:00Z",
        },
        # Invalid card (missing required field)
        {
            "type": "primary",
            "risk_level": "yellow",
            "token_info": {"symbol": "BAD", "chain": "eth"},  # Missing ca_norm
            "metrics": {
                "price_usd": None,
                "liquidity_usd": None,
                "fdv": None,
                "ohlc": {
                    "m5": {"o": None, "h": None, "l": None, "c": None},
                    "h1": {"o": None, "h": None, "l": None, "c": None},
                    "h24": {"o": None, "h": None, "l": None, "c": None},
                },
            },
            "sources": {"security_source": "", "dex_source": ""},
            "states": {
                "cache": False,
                "degrade": True,
                "stale": True,
                "reason": "test_invalid",
            },
            "risk_note": "Invalid test",
            "verify_path": "/",
            "data_as_of": "2025-09-02T16:00:00Z",
        },
    ]

    results = []
    for i, card in enumerate(test_cards):
        result = validate_card_schema(card)
        result["card_index"] = i
        results.append(result)
        log_json(
            stage="verify.card.test",
            test="schema_validation",
            index=i,
            pass_status=result["pass"],
        )

    # Summary
    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    success = passed == 2  # Expect 2 valid, 1 invalid

    log_json(
        stage="verify.card.pass" if success else "verify.card.fail",
        passed=passed,
        total=total,
        expected_pass=2,
    )

    output = {
        "pass": success,
        "tests": results,
        "details": {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "expected_failures": 1,
        },
    }

    print(json.dumps(output, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
