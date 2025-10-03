#!/usr/bin/env python3
"""Test card template rendering"""
import json
import os

from jinja2 import Environment, FileSystemLoader, Template

# Sample data that conforms to pushcard.schema.json
sample_red = {
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
        "LP not locked",
    ],
    "legal_note": "This is not financial advice. DYOR.",
}

sample_green = {
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
    "evidence": {"goplus_raw": {"summary": "Safe token. No security issues detected."}},
    "risk_note": "Stable and safe",
    "verify_path": "https://etherscan.io/token/0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "data_as_of": "2025-09-02T16:00:00Z",
}

sample_degraded = {
    "type": "primary",
    "risk_level": "yellow",
    "token_info": {
        "symbol": "UNKNOWN",
        "ca_norm": "0xffffffffffffffffffffffffffffffffffffffff",
        "chain": "eth",
    },
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
        "reason": "both_failed_no_cache",
    },
    "evidence": {},
    "risk_note": "Data unavailable",
    "verify_path": "/",
    "data_as_of": "2025-09-02T16:00:00Z",
}

# Topic card sample data
sample_topic = {
    "type": "topic",
    "token_info": {
        "symbol": "MEME",
        "ca_norm": "0x9999999999999999999999999999999999999999",
        "chain": "eth",
    },
    "topic_id": "pepe_trend_2025",
    "topic_entities": ["pepe", "frog", "meme_coin", "eth_chain", "degen"],
    "topic_keywords": ["test_keyword", "moon[shot]", "100x", "trending", "viral"],
    "topic_mention_count": 42,
    "topic_confidence": 0.85,
    "topic_sources": ["twitter", "telegram", "discord", "reddit", "4chan", "weibo"],
    "topic_evidence_links": [
        "https://twitter.com/example/status/123",
        "https://t.me/example/456",
        "https://discord.com/channels/789",
        "https://reddit.com/r/example/101112",
        "https://boards.4chan.org/biz/thread/131415",
    ],
    "states": {"degrade": False},
    "verify_path": "/topics/pepe_trend_2025",
    "data_as_of": "2025-09-02T16:00:00Z",
}

# Topic card with missing fields
sample_topic_degraded = {
    "type": "topic",
    "token_info": {},
    "states": {"degrade": True},
    "verify_path": "/",
    "data_as_of": "2025-09-02T16:00:00Z",
}

# Market risk card sample data
sample_market_risk = {
    "type": "market_risk",
    "risk_level": "red",
    "goplus_risk": "red",
    "token_info": {
        "symbol": "RISKY",
        "ca_norm": "0xbadbadbadbadbadbadbadbadbadbadbadbadbadb",
        "chain": "eth",
    },
    "buy_tax": 2.5,
    "sell_tax": 5.0,
    "lp_lock_days": 0,
    "honeypot": True,
    "risk_note": "极高风险 - 蜜罐代币",
    "sources": {"security_source": "GoPlus@v1.2"},
    "states": {"degrade": False},
    "verify_path": "https://gopluslabs.io/token-security/1/0xbadbadbadbadbadbadbadbadbadbadbadbadbadb",
    "data_as_of": "2025-09-02T16:00:00Z",
}

# Market risk card with missing fields
sample_market_risk_degraded = {
    "type": "market_risk",
    "token_info": {"symbol": "UNKNOWN", "chain": "eth"},
    "sources": {},
    "states": {"degrade": True},
    "verify_path": "/",
    "data_as_of": "2025-09-02T16:00:00Z",
}


def test_templates():
    """Test rendering both templates"""
    # Setup Jinja2 environment
    template_dir = os.path.join(os.path.dirname(__file__), "../../templates/cards")

    # Different environment for each template type
    # Telegram doesn't need autoescape
    tg_env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)

    # UI needs autoescape for HTML safety
    ui_env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)

    # Test Telegram template
    print("=" * 60)
    print("TELEGRAM TEMPLATE TESTS")
    print("=" * 60)

    tg_template = tg_env.get_template("primary_card.tg.j2")

    print("\n1. RED CARD (High Risk):")
    print("-" * 40)
    print(tg_template.render(card_data=sample_red))

    print("\n2. GREEN CARD (Safe):")
    print("-" * 40)
    print(tg_template.render(card_data=sample_green))

    print("\n3. DEGRADED CARD (No Data):")
    print("-" * 40)
    print(tg_template.render(card_data=sample_degraded))

    # Test Topic card templates
    print("\n" + "=" * 60)
    print("TOPIC CARD TESTS")
    print("=" * 60)

    if os.path.exists(os.path.join(template_dir, "topic_card.tg.j2")):
        topic_tg_template = tg_env.get_template("topic_card.tg.j2")

        print("\n1. TOPIC CARD (Complete):")
        print("-" * 40)
        print(topic_tg_template.render(card_data=sample_topic))

        print("\n2. TOPIC CARD (Degraded/Missing Fields):")
        print("-" * 40)
        print(topic_tg_template.render(card_data=sample_topic_degraded))

        # Test UI version
        topic_ui_template = ui_env.get_template("topic_card.ui.j2")
        html_output = topic_ui_template.render(card_data=sample_topic)
        print(f"\n✓ Topic card HTML rendered: {len(html_output)} bytes")
    else:
        print("\n⚠️  Topic card templates not found")

    # Test Market Risk card templates
    print("\n" + "=" * 60)
    print("MARKET RISK CARD TESTS")
    print("=" * 60)

    if os.path.exists(os.path.join(template_dir, "market_risk_card.tg.j2")):
        market_risk_tg_template = tg_env.get_template("market_risk_card.tg.j2")

        print("\n1. MARKET RISK CARD (Complete):")
        print("-" * 40)
        print(market_risk_tg_template.render(card_data=sample_market_risk))

        print("\n2. MARKET RISK CARD (Degraded/Missing Fields):")
        print("-" * 40)
        print(market_risk_tg_template.render(card_data=sample_market_risk_degraded))

        # Test UI version
        market_risk_ui_template = ui_env.get_template("market_risk_card.ui.j2")
        html_output = market_risk_ui_template.render(card_data=sample_market_risk)
        print(f"\n✓ Market Risk card HTML rendered: {len(html_output)} bytes")
    else:
        print("\n⚠️  Market Risk card templates not found")

    # Test UI template
    print("\n" + "=" * 60)
    print("UI TEMPLATE TEST (HTML snippet)")
    print("=" * 60)

    ui_template = ui_env.get_template("primary_card.ui.j2")

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
