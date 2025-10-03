#!/usr/bin/env python3
"""
Day19 Card E - Verification script for /cards/preview endpoint
Validates that the response conforms to schemas/cards.schema.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

import jsonschema
import requests


def load_env_file(env_path=".env"):
    """Simple .env file loader (without external dependencies)"""
    if not os.path.exists(env_path):
        return

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                # Only set if not already in environment
                if key not in os.environ:
                    os.environ[key] = value.strip('"').strip("'")


def load_schema():
    """Load the cards schema for validation with resolver for external $refs"""
    schema_dir = Path(__file__).parent.parent / "schemas"
    schema_path = schema_dir / "cards.schema.json"

    if not schema_path.exists():
        print(
            json.dumps(
                {"pass": False, "reason": f"Schema file not found: {schema_path}"}
            )
        )
        sys.exit(1)

    with open(schema_path) as f:
        schema = json.load(f)

    # Load common schema for $ref resolution
    common_path = schema_dir / "common.schema.json"
    if common_path.exists():
        with open(common_path) as f:
            common_schema = json.load(f)

        from jsonschema import RefResolver

        resolver = RefResolver(
            base_uri=f"file://{schema_dir}/",
            referrer=schema,
            store={"common.schema.json": common_schema},
        )
        return schema, resolver

    return schema, None


def verify_card_preview(
    event_key: str, base_url: str = "http://localhost:8000"
) -> dict:
    """
    Verify the /cards/preview endpoint response

    Args:
        event_key: Event key to test
        base_url: API base URL

    Returns:
        Verification result dict
    """
    # Build request URL
    url = f"{base_url}/cards/preview"
    params = {"event_key": event_key, "render": 1}  # Always test with render enabled

    try:
        # Make request
        response = requests.get(url, params=params, timeout=10)

        # Check HTTP status
        if response.status_code != 200:
            return {
                "pass": False,
                "reason": f"HTTP {response.status_code}: {response.text}",
            }

        # Parse JSON response
        try:
            card_data = response.json()
        except json.JSONDecodeError as e:
            return {"pass": False, "reason": f"Invalid JSON response: {e}"}

        # Load schema and validate
        schema_and_resolver = load_schema()
        schema, resolver = (
            schema_and_resolver
            if isinstance(schema_and_resolver, tuple)
            else (schema_and_resolver, None)
        )
        try:
            if resolver:
                jsonschema.validate(card_data, schema, resolver=resolver)
            else:
                jsonschema.validate(card_data, schema)
        except jsonschema.ValidationError as e:
            return {"pass": False, "reason": f"Schema validation failed: {e.message}"}

        # Extract verification details
        result = {
            "pass": True,
            "summary_backend": card_data.get("meta", {}).get(
                "summary_backend", "unknown"
            ),
            "has_goplus": "goplus" in card_data.get("data", {}),
            "has_dex": "dex" in card_data.get("data", {}),
        }

        # Additional checks
        if "summary" not in card_data or not card_data["summary"]:
            result["pass"] = False
            result["reason"] = "Missing or empty summary field"

        if "risk_note" not in card_data or not card_data["risk_note"]:
            result["pass"] = False
            result["reason"] = "Missing or empty risk_note field"

        # Check length constraints
        if result["pass"]:
            summary_len = len(card_data.get("summary", ""))
            risk_note_len = len(card_data.get("risk_note", ""))

            max_summary = int(os.environ.get("CARDS_SUMMARY_MAX_CHARS", "280"))
            max_risk_note = int(os.environ.get("CARDS_RISKNOTE_MAX_CHARS", "160"))

            if summary_len > max_summary:
                result["pass"] = False
                result["reason"] = f"Summary too long: {summary_len} > {max_summary}"
            elif risk_note_len > max_risk_note:
                result["pass"] = False
                result["reason"] = (
                    f"Risk note too long: {risk_note_len} > {max_risk_note}"
                )

        # Check for degrade flag if timeout is very low
        timeout_ms = int(os.environ.get("CARDS_SUMMARY_TIMEOUT_MS", "1200"))
        if timeout_ms <= 1:
            # With very low timeout, should degrade to template
            if result.get("summary_backend") != "template":
                result["timeout_degrade_check"] = (
                    "Expected template backend with low timeout"
                )

        return result

    except requests.RequestException as e:
        return {"pass": False, "reason": f"Request failed: {e}"}
    except Exception as e:
        return {"pass": False, "reason": f"Unexpected error: {e}"}


def main():
    """Main entry point"""
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Verify /cards/preview endpoint response against schema",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/verify_cards_preview.py --event-key ETH:TOKEN:0X123456
  EVENT_KEY=TEST_BAD make verify_cards
  CARDS_SUMMARY_TIMEOUT_MS=1 make verify_cards
        """,
    )
    parser.add_argument(
        "--event-key",
        required=True,
        help="Event key to test (e.g., ETH:TOKEN:0X123456)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    # Load environment variables
    load_env_file()

    # Run verification
    result = verify_card_preview(args.event_key, args.base_url)

    # Output result as JSON
    print(json.dumps(result, indent=2))

    # Exit with appropriate code
    if not result.get("pass", False):
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
