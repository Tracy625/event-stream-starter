#!/usr/bin/env python3
"""Verify topic signal API functionality"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/Users/tracy-mac/Desktop/GUIDS')

from api.metrics import log_json

BASE = os.getenv("API_BASE", "http://localhost:8000")
TOPIC_ID = os.getenv("TEST_TOPIC_ID", "t.test")

REQUIRED_FIELDS = [
    "type","topic_id","topic_entities","keywords",
    "slope_10m","slope_30m","mention_count_24h",
    "confidence","sources","evidence_links",
    "calc_version","ts","degrade","topic_merge_mode"
]

def fail(msg, payload=None):
    print(f"[FAIL] {msg}")
    if payload is not None:
        try:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception:
            print(payload)
    sys.exit(1)

def main():
    """Verify /signals/topic endpoint"""
    
    url = f"{BASE}/signals/topic"
    
    try:
        # Test with entities parameter
        print("Testing /signals/topic with entities...")
        r = requests.get(url, params={"entities": "pepe,frog,meme"}, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        # Fallback to topic_id test
        try:
            print(f"Entities test failed: {e}")
            print(f"Testing /signals/topic with topic_id={TOPIC_ID}...")
            r = requests.get(url, params={"topic_id": TOPIC_ID}, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e2:
            fail(f"HTTP error: {e2}")

    # Check required fields
    for k in REQUIRED_FIELDS:
        if k not in data:
            fail(f"missing field: {k}", data)
    
    # Validate field types
    if data.get("type") != "topic":
        fail(f"type must be 'topic', got: {data.get('type')}", data)
    
    # Check slopes are numeric
    for k in ["slope_10m", "slope_30m"]:
        if not isinstance(data.get(k), (int, float)):
            fail(f"{k} must be number, got: {type(data.get(k))}", data)
    
    # Check confidence is numeric and in range
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)):
        fail(f"confidence must be number, got: {type(confidence)}", data)
    if not 0 <= confidence <= 1:
        fail(f"confidence must be 0-1, got: {confidence}", data)
    
    # Check arrays are arrays
    for k in ["topic_entities", "keywords", "sources", "evidence_links"]:
        if not isinstance(data.get(k), list):
            fail(f"{k} must be array, got: {type(data.get(k))}", data)
    
    # Optional: enforce slope difference for acceptance when requested
    if os.getenv("EXPECT_SLOPE_DIFF") == "1":
        if float(data.get("slope_10m", 0.0)) == float(data.get("slope_30m", 0.0)):
            fail("slope_10m equals slope_30m; expect difference within 24h window", data)
    
    print("[OK] verify_topic_signal passed")
    print(f"  Topic ID: {data.get('topic_id')}")
    print(f"  Entities: {data.get('topic_entities')}")
    print(f"  Slope 10m: {data.get('slope_10m')}")
    print(f"  Slope 30m: {data.get('slope_30m')}")
    print(f"  Confidence: {data.get('confidence')}")
    print(f"  Sources: {data.get('sources')}")
    return True

if __name__ == "__main__":
    main()