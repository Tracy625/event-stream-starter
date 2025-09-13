#!/usr/bin/env python
"""
Verification script for Task Card 18.2 - Rules API endpoint.

Tests:
1. GET /rules/eval endpoint with demo data
2. Response structure validation
3. Error handling (404, 500)
4. Concurrent request handling
"""

import os
import sys
import json
import time
import requests
import threading
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.database import build_engine_from_env, get_sessionmaker
from api.db import with_session
from sqlalchemy import text as sa_text
from api.metrics import log_json


def setup_demo_data(session):
    """Insert demo data into database for testing."""
    
    # DEMO1: Complete data (opportunity)
    session.execute(sa_text("""
        INSERT INTO events (event_key, start_ts, last_ts, last_sentiment_score)
        VALUES ('eth:DEMO1:2025-09-10T10:00:00Z', NOW(), NOW(), 0.8)
        ON CONFLICT (event_key) DO UPDATE
        SET last_sentiment_score = 0.8
    """))
    
    session.execute(sa_text("""
        INSERT INTO signals (event_key, goplus_risk, buy_tax, sell_tax, lp_lock_days,
                            dex_liquidity, dex_volume_1h, heat_slope)
        VALUES ('eth:DEMO1:2025-09-10T10:00:00Z', 'green', 2.0, 2.0, 200,
                600000.0, 150000.0, 1.5)
        ON CONFLICT DO NOTHING
    """))
    
    # DEMO2: Missing DEX data (observe)
    session.execute(sa_text("""
        INSERT INTO events (event_key, start_ts, last_ts, last_sentiment_score)
        VALUES ('eth:DEMO2:2025-09-10T11:00:00Z', NOW(), NOW(), 0.5)
        ON CONFLICT (event_key) DO UPDATE
        SET last_sentiment_score = 0.5
    """))
    
    session.execute(sa_text("""
        INSERT INTO signals (event_key, goplus_risk, buy_tax, sell_tax, lp_lock_days,
                            dex_liquidity, dex_volume_1h, heat_slope)
        VALUES ('eth:DEMO2:2025-09-10T11:00:00Z', 'yellow', 5.0, 5.0, 60,
                NULL, NULL, 0.5)
        ON CONFLICT DO NOTHING
    """))
    
    # DEMO3: Missing HF sentiment (caution)
    session.execute(sa_text("""
        INSERT INTO events (event_key, start_ts, last_ts, last_sentiment_score)
        VALUES ('eth:DEMO3:2025-09-10T12:00:00Z', NOW(), NOW(), NULL)
        ON CONFLICT (event_key) DO UPDATE
        SET last_sentiment_score = NULL
    """))
    
    session.execute(sa_text("""
        INSERT INTO signals (event_key, goplus_risk, buy_tax, sell_tax, lp_lock_days,
                            dex_liquidity, dex_volume_1h, heat_slope)
        VALUES ('eth:DEMO3:2025-09-10T12:00:00Z', 'red', 15.0, 15.0, 10,
                30000.0, 5000.0, -0.5)
        ON CONFLICT DO NOTHING
    """))
    
    session.commit()
    print("✅ Demo data inserted into database")


def test_endpoint(base_url: str = "http://localhost:8000"):
    """Test the /rules/eval endpoint."""
    
    print("\n" + "=" * 60)
    print("TESTING /rules/eval ENDPOINT")
    print("=" * 60)
    
    # Test DEMO1: Complete data (should be opportunity)
    print("\n1. Testing DEMO1 (complete data):")
    response = requests.get(f"{base_url}/rules/eval", 
                           params={"event_key": "eth:DEMO1:2025-09-10T10:00:00Z"})
    
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Level: {data['level']}")
        print(f"   Score: {data['score']}")
        print(f"   Reasons: {data['reasons']}")
        print(f"   Missing: {data['evidence']['missing']}")
        
        # Validate structure
        assert "event_key" in data
        assert "level" in data
        assert "score" in data
        assert "reasons" in data and isinstance(data["reasons"], list)
        assert len(data["reasons"]) <= 3
        assert "evidence" in data
        assert "signals" in data["evidence"]
        assert "events" in data["evidence"]
        assert "missing" in data["evidence"]
        assert "meta" in data
        assert "rules_version" in data["meta"]
        assert "hot_reloaded" in data["meta"]
        assert "refine_used" in data["meta"]
        
        assert data["level"] == "opportunity", f"Expected opportunity, got {data['level']}"
        print("   ✅ Structure and values validated")
    else:
        print(f"   ❌ Failed with status {response.status_code}: {response.text}")
        return False
    
    # Test DEMO2: Missing DEX (should be observe with missing=['dex'])
    print("\n2. Testing DEMO2 (missing DEX):")
    response = requests.get(f"{base_url}/rules/eval",
                           params={"event_key": "eth:DEMO2:2025-09-10T11:00:00Z"})
    
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Level: {data['level']}")
        print(f"   Score: {data['score']}")
        print(f"   Reasons: {data['reasons']}")
        print(f"   Missing: {data['evidence']['missing']}")
        
        assert "dex" in data["evidence"]["missing"], "Should detect missing DEX"
        assert any("DEX" in r for r in data["reasons"]), "Should include DEX missing reason"
        print("   ✅ Missing DEX detected correctly")
    else:
        print(f"   ❌ Failed with status {response.status_code}: {response.text}")
        return False
    
    # Test DEMO3: Missing HF (should be caution with missing=['hf'])
    print("\n3. Testing DEMO3 (missing HF):")
    response = requests.get(f"{base_url}/rules/eval",
                           params={"event_key": "eth:DEMO3:2025-09-10T12:00:00Z"})
    
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Level: {data['level']}")
        print(f"   Score: {data['score']}")
        print(f"   Reasons: {data['reasons']}")
        print(f"   Missing: {data['evidence']['missing']}")
        
        assert "hf" in data["evidence"]["missing"], "Should detect missing HF"
        assert data["level"] == "caution", f"Expected caution, got {data['level']}"
        print("   ✅ Missing HF detected, caution level correct")
    else:
        print(f"   ❌ Failed with status {response.status_code}: {response.text}")
        return False
    
    # Test 404: Non-existent event key
    print("\n4. Testing non-existent event key (404):")
    response = requests.get(f"{base_url}/rules/eval",
                           params={"event_key": "nonexistent:key:2025"})
    
    if response.status_code == 404:
        print(f"   Status: {response.status_code}")
        print("   ✅ Correctly returns 404 for non-existent key")
    else:
        print(f"   ❌ Expected 404, got {response.status_code}: {response.text}")
        return False
    
    # Test 422: Missing parameter
    print("\n5. Testing missing parameter (422):")
    response = requests.get(f"{base_url}/rules/eval")
    
    if response.status_code == 422:
        print(f"   Status: {response.status_code}")
        print("   ✅ Correctly returns 422 for missing parameter")
    else:
        print(f"   ❌ Expected 422, got {response.status_code}: {response.text}")
        return False
    
    return True


def test_concurrent_requests(base_url: str = "http://localhost:8000"):
    """Test concurrent request handling."""
    print("\n" + "=" * 60)
    print("TESTING CONCURRENT REQUESTS")
    print("=" * 60)
    
    results = []
    errors = []
    
    def make_request(event_key: str, index: int):
        try:
            start = time.time()
            response = requests.get(f"{base_url}/rules/eval",
                                   params={"event_key": event_key})
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                results.append({
                    "index": index,
                    "event_key": event_key,
                    "latency_ms": latency,
                    "level": response.json()["level"]
                })
            else:
                errors.append({
                    "index": index,
                    "event_key": event_key,
                    "status": response.status_code
                })
        except Exception as e:
            errors.append({
                "index": index,
                "event_key": event_key,
                "error": str(e)
            })
    
    # Create threads for concurrent requests
    threads = []
    event_keys = [
        "eth:DEMO1:2025-09-10T10:00:00Z",
        "eth:DEMO2:2025-09-10T11:00:00Z",
        "eth:DEMO3:2025-09-10T12:00:00Z"
    ]
    
    print("\nSending 9 concurrent requests (3 per demo)...")
    for i in range(9):
        event_key = event_keys[i % 3]
        t = threading.Thread(target=make_request, args=(event_key, i))
        threads.append(t)
        t.start()
    
    # Wait for all threads to complete
    for t in threads:
        t.join()
    
    print(f"\nResults: {len(results)} successful, {len(errors)} errors")
    
    if results:
        avg_latency = sum(r["latency_ms"] for r in results) / len(results)
        print(f"Average latency: {avg_latency:.1f}ms")
        
        # Check that all requests succeeded
        for result in results[:3]:  # Show first 3
            print(f"  Request {result['index']}: {result['event_key'][:20]}... -> {result['level']} ({result['latency_ms']:.1f}ms)")
    
    if errors:
        print("\nErrors encountered:")
        for error in errors:
            print(f"  Request {error['index']}: {error}")
        return False
    
    print("\n✅ All concurrent requests handled successfully")
    return True


def main():
    """Run all verification tests."""
    print("\n" + "=" * 60)
    print("RULES API VERIFICATION SCRIPT")
    print("Task Card 18.2 - API Route")
    print("=" * 60)
    
    # Check if running in Docker or local
    api_url = os.getenv("API_URL", "http://localhost:8000")
    
    # Setup demo data if database is available
    try:
        engine = build_engine_from_env()
        SessionClass = get_sessionmaker(engine)
        
        with with_session(SessionClass) as session:
            setup_demo_data(session)
    except Exception as e:
        print(f"⚠️  Could not setup demo data: {e}")
        print("   Assuming data already exists in database")
    
    # Run tests
    try:
        if not test_endpoint(api_url):
            print("\n❌ Endpoint tests failed")
            return 1
        
        if not test_concurrent_requests(api_url):
            print("\n❌ Concurrent request tests failed")
            return 1
        
        print("\n" + "=" * 60)
        print("✅ ALL API TESTS PASSED!")
        print("=" * 60)
        return 0
        
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Could not connect to API at {api_url}")
        print("   Make sure the API server is running:")
        print("   docker compose up api")
        print("   or: uvicorn api.main:app --reload")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())