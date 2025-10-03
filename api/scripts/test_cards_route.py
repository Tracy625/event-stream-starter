#!/usr/bin/env python
"""
Test card routing for all types
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.cards.registry import UnknownCardTypeError, normalize_card_type
from api.cards.render_pipeline import render_and_push
from api.database import get_db_session
from api.models import Signal
from api.utils.logging import log_json


def test_all_routes():
    """Test routing for all card types"""

    results = {}

    # Test known types
    test_signals = [
        {"event_key": "TEST:PRIMARY:001", "type": "primary"},
        {"event_key": "TEST:SECONDARY:001", "type": "secondary"},
        {"event_key": "TEST:TOPIC:001", "type": "topic"},
        {"event_key": "TEST:MARKET:001", "type": "market_risk"},
    ]

    with get_db_session() as db:
        for test_signal in test_signals:
            # Get full signal from DB
            signal = (
                db.query(Signal).filter_by(event_key=test_signal["event_key"]).first()
            )

            if not signal:
                print(f"❌ Signal not found: {test_signal['event_key']}")
                continue

            # Convert to dict
            signal_dict = {
                "type": signal.type,
                "event_key": signal.event_key,
                "risk_level": getattr(signal, "risk_level", "yellow"),
                "token_info": getattr(signal, "token_info", {}),
                "goplus_risk": getattr(signal, "goplus_risk", None),
                "risk_note": getattr(signal, "risk_note", ""),
            }

            # Test render and push (mock mode)
            result = render_and_push(
                signal=signal_dict,
                channel_id="-123456789",
                channel="tg",
                now=datetime.now(timezone.utc),
            )

            results[test_signal["type"]] = result

            if result.get("success") or result.get("dedup"):
                print(f"✅ {test_signal['type']}: Success")
            else:
                print(f"⚠️ {test_signal['type']}: {result.get('error')}")

    # Test unknown type
    try:
        normalize_card_type("invalid_type")
        print("❌ Unknown type should raise error")
    except UnknownCardTypeError as e:
        print(f"✅ Unknown type handled: {str(e)}")
        results["unknown_handling"] = True

    # Verify metrics endpoint
    import requests

    try:
        resp = requests.get("http://localhost:8000/metrics")
        if resp.status_code == 200:
            metrics_text = resp.text

            # Check for cards metrics
            has_metrics = all(
                [
                    "cards_generated_total" in metrics_text,
                    "cards_push_total" in metrics_text,
                    "cards_pipeline_latency_ms" in metrics_text,
                ]
            )

            if has_metrics:
                print("✅ Metrics registered correctly")
            else:
                print("⚠️ Some metrics missing")
    except Exception as e:
        print(f"⚠️ Metrics check failed: {e}")

    # Summary
    success_count = sum(
        1
        for r in results.values()
        if isinstance(r, dict) and (r.get("success") or r.get("dedup"))
    )

    print("\n" + "=" * 50)
    print(f"Results: {success_count}/{len(test_signals)} types routed successfully")

    if results.get("unknown_handling"):
        print("✅ Unknown type handling works")

    # Log summary
    log_json(
        stage="test.summary",
        total=len(test_signals),
        success=success_count,
        unknown_handled=results.get("unknown_handling", False),
    )

    return success_count == len(test_signals)


if __name__ == "__main__":
    # Set mock mode for testing
    os.environ["TELEGRAM_MODE"] = "mock"

    success = test_all_routes()

    if success:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed")
        sys.exit(1)
