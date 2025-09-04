#!/usr/bin/env python3
"""Test card template rendering"""
import json
from jinja2 import Template, Environment, FileSystemLoader
import os

# Sample data that conforms to pushcard.schema.json
sample_red = {
    "type": "primary",
    "risk_level": "red",
    "token_info": {
        "symbol": "SCAM",
        "ca_norm": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "eth"
    },
    "metrics": {
        "price_usd": 0.0001,
        "liquidity_usd": 1000.0,
        "fdv": 100000.0,
        "ohlc": {
            "m5": {"o": -5.0, "h": 0.0002, "l": 0.0001, "c": 0.0001},
            "h1": {"o": -10.0, "h": 0.0003, "l": 0.0001, "c": 0.0001},
            "h24": {"o": -50.0, "h": 0.0005, "l": 0.0001, "c": 0.0001}
        }
    },
    "sources": {
        "security_source": "goplus",
        "dex_source": "dexscreener"
    },
    "states": {
        "cache": False,
        "degrade": False,
        "stale": False,
        "reason": ""
    },
    "evidence": {
        "goplus_raw": {
            "summary": "High risk token detected. Honeypot: YES, Buy Tax: 99%, Sell Tax: 99%, Ownership renounced: NO, LP locked: NO. This token shows multiple red flags including extremely high taxes and potential honeypot behavior. Exercise extreme caution."
        }
    },
    "risk_note": "HONEYPOT DETECTED - DO NOT BUY",
    "verify_path": "https://etherscan.io/token/0x1234567890abcdef1234567890abcdef12345678",
    "data_as_of": "2025-09-02T16:00:00Z",
    "rules_fired": [
        "Honeypot detected",
        "Buy tax > 10%",
        "Sell tax > 10%",
        "LP not locked"
    ],
    "legal_note": "This is not financial advice. DYOR."
}

sample_green = {
    "type": "primary",
    "risk_level": "green",
    "token_info": {
        "symbol": "USDC",
        "ca_norm": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "chain": "eth"
    },
    "metrics": {
        "price_usd": 0.9998,
        "liquidity_usd": 50000000.0,
        "fdv": 47000000000.0,
        "ohlc": {
            "m5": {"o": 0.01, "h": 1.0001, "l": 0.9997, "c": 0.9998},
            "h1": {"o": 0.0, "h": 1.0002, "l": 0.9996, "c": 0.9998},
            "h24": {"o": -0.02, "h": 1.0005, "l": 0.9995, "c": 0.9998}
        }
    },
    "sources": {
        "security_source": "goplus",
        "dex_source": "dexscreener"
    },
    "states": {
        "cache": True,
        "degrade": False,
        "stale": False,
        "reason": ""
    },
    "evidence": {
        "goplus_raw": {
            "summary": "Safe token. No security issues detected."
        }
    },
    "risk_note": "Stable and safe",
    "verify_path": "https://etherscan.io/token/0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "data_as_of": "2025-09-02T16:00:00Z"
}

sample_degraded = {
    "type": "primary",
    "risk_level": "yellow",
    "token_info": {
        "symbol": "UNKNOWN",
        "ca_norm": "0xffffffffffffffffffffffffffffffffffffffff",
        "chain": "eth"
    },
    "metrics": {
        "price_usd": None,
        "liquidity_usd": None,
        "fdv": None,
        "ohlc": {
            "m5": {"o": None, "h": None, "l": None, "c": None},
            "h1": {"o": None, "h": None, "l": None, "c": None},
            "h24": {"o": None, "h": None, "l": None, "c": None}
        }
    },
    "sources": {
        "security_source": "",
        "dex_source": ""
    },
    "states": {
        "cache": False,
        "degrade": True,
        "stale": True,
        "reason": "both_failed_no_cache"
    },
    "evidence": {},
    "risk_note": "Data unavailable",
    "verify_path": "/",
    "data_as_of": "2025-09-02T16:00:00Z"
}

def test_templates():
    """Test rendering both templates"""
    # Setup Jinja2 environment
    template_dir = os.path.join(os.path.dirname(__file__), '../../templates/cards')
    
    # Different environment for each template type
    # Telegram doesn't need autoescape
    tg_env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=False
    )
    
    # UI needs autoescape for HTML safety
    ui_env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=True
    )
    
    # Test Telegram template
    print("=" * 60)
    print("TELEGRAM TEMPLATE TESTS")
    print("=" * 60)
    
    tg_template = tg_env.get_template('primary_card.tg.j2')
    
    print("\n1. RED CARD (High Risk):")
    print("-" * 40)
    print(tg_template.render(card_data=sample_red))
    
    print("\n2. GREEN CARD (Safe):")
    print("-" * 40)
    print(tg_template.render(card_data=sample_green))
    
    print("\n3. DEGRADED CARD (No Data):")
    print("-" * 40)
    print(tg_template.render(card_data=sample_degraded))
    
    # Test UI template
    print("\n" + "=" * 60)
    print("UI TEMPLATE TEST (HTML snippet)")
    print("=" * 60)
    
    ui_template = ui_env.get_template('primary_card.ui.j2')
    
    # Just test that it renders without error
    html_output = ui_template.render(card_data=sample_red)
    print(f"✓ Red card HTML rendered: {len(html_output)} bytes")
    
    html_output = ui_template.render(card_data=sample_green)
    print(f"✓ Green card HTML rendered: {len(html_output)} bytes")
    
    html_output = ui_template.render(card_data=sample_degraded)
    print(f"✓ Degraded card HTML rendered: {len(html_output)} bytes")
    
    print("\n✅ All templates rendered successfully!")
    
    return True

if __name__ == "__main__":
    import sys
    try:
        success = test_templates()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Template error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)