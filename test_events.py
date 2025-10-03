#!/usr/bin/env python3
"""
Quick test script for events module.
"""

import os
import sys
from datetime import datetime, timezone

# Add api to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import functions
from api.events import make_event_key, upsert_event

# Test data
post1 = {
    "symbol": "$ARB",
    "token_ca": None,
    "keywords": ["airdrop", "arb", "claim"],
    "created_ts": datetime.now(timezone.utc),
    "sentiment_score": 0.8,
    "sentiment_label": "pos",
}

post2 = {
    "symbol": None,
    "token_ca": "0x1234567890123456789012345678901234567890",
    "keywords": ["$pepe", "moon", "10x"],
    "created_ts": datetime.now(timezone.utc),
    "sentiment_score": 0.5,
    "sentiment_label": "pos",
}

# Test make_event_key
print("Testing make_event_key:")
key1 = make_event_key(post1)
print(f"  Post 1 key: {key1}")

key2 = make_event_key(post2)
print(f"  Post 2 key: {key2}")

# Test determinism
key1_again = make_event_key(post1)
print(f"  Post 1 key (again): {key1_again}")
print(f"  Deterministic: {key1 == key1_again}")

print("\nTesting upsert_event:")
try:
    result1 = upsert_event(post1)
    print(f"  Result 1: {result1}")

    # Upsert same event again (should increment evidence_count)
    result1_again = upsert_event(post1)
    print(f"  Result 1 (again): {result1_again}")

    result2 = upsert_event(post2)
    print(f"  Result 2: {result2}")
except Exception as e:
    print(f"  Error: {e}")
    print("  (Make sure database is running and migration 003 is applied)")
