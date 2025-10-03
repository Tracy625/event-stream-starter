#!/usr/bin/env python3
"""
Test script for Card B summarizer validation
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.cards.summarizer import summarize_card


def test_minimal_payload():
    """Test with minimal payload (only price)"""
    payload = {"data": {"dex": {"price_usd": 0.00012345}}}
    summary, risk_note, meta = summarize_card(payload)
    print(f"Test 1 - Minimal payload:")
    print(f"  Summary: {summary}")
    print(f"  Risk note: {risk_note}")
    print(f"  Meta: {meta}")
    assert summary and "null" not in summary.lower()
    assert risk_note and "none" not in risk_note.lower()
    assert meta["summary_backend"] in ["llm", "template"]
    print("  ✓ Passed\n")


def test_with_rules_only():
    """Test with rules level only"""
    payload = {"data": {"rules": {"level": "caution"}}}
    summary, risk_note, meta = summarize_card(payload)
    print(f"Test 2 - Rules only:")
    print(f"  Summary: {summary}")
    print(f"  Risk note: {risk_note}")
    print(f"  Meta: {meta}")
    assert "caution" in summary.lower()
    assert len(summary) <= 280
    assert len(risk_note) <= 160
    print("  ✓ Passed\n")


def test_template_mode():
    """Test forced template mode"""
    os.environ["CARDS_SUMMARY_BACKEND"] = "template"
    payload = {
        "event_key": "ETH:TOKEN:0xABC123",
        "data": {
            "dex": {"price_usd": 1.234, "liquidity_usd": 50000},
            "goplus": {"risk": "yellow"},
            "rules": {"level": "watch"},
        },
    }
    summary, risk_note, meta = summarize_card(payload, timeout_ms=1)
    print(f"Test 3 - Template mode:")
    print(f"  Summary: {summary}")
    print(f"  Risk note: {risk_note}")
    print(f"  Meta: {meta}")
    assert meta["summary_backend"] == "template"
    assert "ETH" in summary
    assert "1.234" in summary
    assert "50000" in summary
    assert "watch" in summary
    assert "yellow" in risk_note
    print("  ✓ Passed\n")


def test_missing_fields():
    """Test with missing optional fields"""
    payload = {
        "event_key": "SOL:MEME:PEPE",
        "data": {"dex": {"price_usd": 0.0001}, "rules": {"level": "risk"}},
    }
    summary, risk_note, meta = summarize_card(payload)
    print(f"Test 4 - Missing fields:")
    print(f"  Summary: {summary}")
    print(f"  Risk note: {risk_note}")
    assert "SOL" in summary
    assert "流动性" not in summary  # No liquidity, should be omitted
    assert "unknown" in risk_note  # No goplus risk
    print("  ✓ Passed\n")


def test_long_numbers():
    """Test with very long numbers"""
    payload = {
        "data": {
            "dex": {"price_usd": 0.000000123456789, "liquidity_usd": 123456789012.345},
            "rules": {"level": "none"},
        }
    }
    summary, risk_note, meta = summarize_card(payload)
    print(f"Test 5 - Long numbers:")
    print(f"  Summary: {summary}")
    print(f"  Risk note: {risk_note}")
    # Check formatting works
    assert "$" in summary
    assert len(summary) <= 280
    print("  ✓ Passed\n")


def test_length_constraints():
    """Test that outputs respect length constraints"""
    os.environ["CARDS_SUMMARY_MAX_CHARS"] = "50"
    os.environ["CARDS_RISKNOTE_MAX_CHARS"] = "30"

    payload = {"data": {"dex": {"price_usd": 0.1}, "rules": {"level": "watch"}}}
    summary, risk_note, meta = summarize_card(payload)
    print(f"Test 6 - Length constraints:")
    print(f"  Summary ({len(summary)} chars): {summary}")
    print(f"  Risk note ({len(risk_note)} chars): {risk_note}")
    assert len(summary) <= 50
    assert len(risk_note) <= 30
    if len(summary) == 50:
        assert summary.endswith("…")
    print("  ✓ Passed\n")


if __name__ == "__main__":
    print("Running Card B summarizer tests...\n")

    # Set template mode for predictable testing
    os.environ["CARDS_SUMMARY_BACKEND"] = "template"

    test_minimal_payload()
    test_with_rules_only()
    test_template_mode()
    test_missing_fields()
    test_long_numbers()
    test_length_constraints()

    print("✅ All tests passed!")
