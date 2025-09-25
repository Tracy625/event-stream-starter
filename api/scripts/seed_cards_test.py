#!/usr/bin/env python
"""
Seed test data for all four card types
"""
import os
import sys
from datetime import datetime, timezone, timedelta

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.database import get_db_session
from api.models import Signal, Event
from api.utils.logging import log_json

def seed_test_cards():
    """Create test data for all card types"""

    now = datetime.now(timezone.utc)
    test_data = [
        {
            "event_key": "TEST:PRIMARY:001",
            "type": "primary",
            "risk_level": "yellow",
            "token_info": {"symbol": "PRIM", "chain": "eth", "ca_norm": "0x" + "1" * 40},
            "goplus_risk": "yellow",
            "risk_note": "Test primary risk"
        },
        {
            "event_key": "TEST:SECONDARY:001",
            "type": "secondary",
            "risk_level": "green",
            "token_info": {"symbol": "SEC", "chain": "eth", "ca_norm": "0x" + "2" * 40},
            "source": "verified",
            "features_snapshot": {"active_addrs": 100, "stale": False}
        },
        {
            "event_key": "TEST:TOPIC:001",
            "type": "topic",
            "token_info": {"symbol": "TOP", "chain": "eth"},
            "topic_id": "test-topic-1",
            "topic_entities": ["pepe", "meme"],
            "topic_mention_count": 42,
            "topic_confidence": 0.85
        },
        {
            "event_key": "TEST:MARKET:001",
            "type": "market_risk",
            "risk_level": "red",
            "token_info": {"symbol": "RISK", "chain": "eth", "ca_norm": "0x" + "4" * 40},
            "goplus_risk": "red",
            "honeypot": True,
            "risk_note": "Honeypot detected"
        }
    ]

    with get_db_session() as db:
        for data in test_data:
            # Create or update signal
            signal = db.query(Signal).filter_by(event_key=data["event_key"]).first()
            if not signal:
                signal = Signal(
                    event_key=data["event_key"],
                    type=data["type"],
                    state="candidate",
                    ts=now
                )
                db.add(signal)

            # Update signal fields
            for key, value in data.items():
                if hasattr(signal, key):
                    setattr(signal, key, value)

            db.commit()

            log_json(
                stage="seed.created",
                type=data["type"],
                event_key=data["event_key"]
            )

    print(f"✅ Seeded {len(test_data)} test cards")
    return len(test_data)

if __name__ == "__main__":
    count = seed_test_cards()
    sys.exit(0 if count == 4 else 1)