#!/usr/bin/env python
"""
CARD B-verify — End-to-end test for candidate verification job
Run this inside the worker container to test the verification flow.
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone

# Add app to path
sys.path.insert(0, '/app')

def test_verification_job():
    """Test the verification job end-to-end."""
    
    print("=" * 60)
    print("CARD B-verify — Candidate Verification E2E Test")
    print("=" * 60)
    print()
    
    # Import required modules
    try:
        from api.database import get_db
        from sqlalchemy import text as sa_text
        from worker.jobs.onchain.verify_signal import run_once
        print("✓ Modules imported successfully")
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return 1
    
    # Test configuration
    test_event_key = f"demo_event_bverify_{int(datetime.now().timestamp())}"
    
    # Step 1: Create test candidate
    print("\n1. Creating test candidate...")
    print("-" * 40)
    
    try:
        with next(get_db()) as db:
            # Check if required columns exist
            columns_check = db.execute(sa_text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'signals' 
                  AND column_name IN ('event_key', 'state', 'ts', 'onchain_asof_ts', 'onchain_confidence')
                ORDER BY column_name
            """)).fetchall()
            
            print(f"Available columns: {[col[0] for col in columns_check]}")
            
            # Insert test candidate
            db.execute(sa_text("""
                INSERT INTO signals (event_key, state, ts)
                VALUES (:event_key, 'candidate', :ts)
                ON CONFLICT (event_key) DO UPDATE 
                SET state = 'candidate',
                    ts = :ts,
                    onchain_asof_ts = NULL,
                    onchain_confidence = NULL
            """), {
                'event_key': test_event_key,
                'ts': datetime.now(timezone.utc) - timedelta(minutes=5)
            })
            db.commit()
            
            print(f"✓ Created test candidate: {test_event_key}")
            
    except Exception as e:
        print(f"✗ Failed to create test candidate: {e}")
        return 1
    
    # Step 2: Check environment settings
    print("\n2. Environment Configuration")
    print("-" * 40)
    
    rules_setting = os.getenv('ONCHAIN_RULES', 'off')
    delay_sec = int(os.getenv('ONCHAIN_VERIFICATION_DELAY_SEC', '180'))
    bq_view = os.getenv('BQ_ONCHAIN_FEATURES_VIEW', '')
    
    print(f"ONCHAIN_RULES = {rules_setting}")
    print(f"ONCHAIN_VERIFICATION_DELAY_SEC = {delay_sec}")
    print(f"BQ_ONCHAIN_FEATURES_VIEW = {bq_view or '(not set)'}")
    
    # Set minimal config if not present
    if not bq_view:
        os.environ['BQ_ONCHAIN_FEATURES_VIEW'] = 'dummy.table'
        print("  → Set dummy BQ view for testing")
    
    # Step 3: Run verification job
    print("\n3. Running verification job...")
    print("-" * 40)
    
    try:
        result = run_once(limit=10)
        print(f"Job Result: {json.dumps(result, indent=2)}")
        
        if result.get('scanned', 0) > 0:
            print("✓ Successfully scanned candidates")
        else:
            print("⚠ No candidates scanned")
            print("  Possible reasons:")
            print("  - Candidate too recent (< delay threshold)")
            print("  - Missing 'state' column")
            print("  - No time column available")
            
    except Exception as e:
        print(f"✗ Job execution failed: {e}")
        import traceback
        traceback.print_exc()
        result = None
    
    # Step 4: Verify results
    print("\n4. Verifying database results...")
    print("-" * 40)
    
    try:
        with next(get_db()) as db:
            # Check signal state
            signal = db.execute(sa_text("""
                SELECT 
                    event_key,
                    state,
                    onchain_asof_ts,
                    onchain_confidence
                FROM signals
                WHERE event_key = :event_key
            """), {'event_key': test_event_key}).fetchone()
            
            if signal:
                print(f"Signal state:")
                print(f"  event_key: {signal[0]}")
                print(f"  state: {signal[1]}")
                print(f"  onchain_asof_ts: {signal[2] or 'NULL'}")
                print(f"  onchain_confidence: {signal[3] or 'NULL'}")
                
                # Validate expectations
                print("\nValidation:")
                if rules_setting == 'off':
                    if signal[1] == 'candidate':
                        print("  ✓ State remained 'candidate' (ONCHAIN_RULES=off)")
                    else:
                        print(f"  ✗ State changed to '{signal[1]}' (expected 'candidate')")
                else:
                    print(f"  → State is '{signal[1]}' (ONCHAIN_RULES=on)")
                    
            else:
                print("✗ Signal not found in database")
                
            # Check events
            events = db.execute(sa_text("""
                SELECT type, metadata, created_at
                FROM signal_events
                WHERE event_key = :event_key
                ORDER BY created_at DESC
                LIMIT 5
            """), {'event_key': test_event_key}).fetchall()
            
            if events:
                print(f"\nEvents recorded: {len(events)}")
                for evt in events:
                    print(f"  - {evt[0]} at {evt[2]}")
            else:
                print("\nNo events recorded")
                
    except Exception as e:
        print(f"✗ Failed to verify results: {e}")
    
    # Step 5: Cleanup
    print("\n5. Cleanup")
    print("-" * 40)
    
    cleanup = input("Delete test data? (y/n): ").strip().lower()
    if cleanup == 'y':
        try:
            with next(get_db()) as db:
                db.execute(sa_text("""
                    DELETE FROM signal_events WHERE event_key = :event_key
                """), {'event_key': test_event_key})
                
                db.execute(sa_text("""
                    DELETE FROM signals WHERE event_key = :event_key
                """), {'event_key': test_event_key})
                
                db.commit()
                print("✓ Test data cleaned up")
        except Exception as e:
            print(f"✗ Cleanup failed: {e}")
    else:
        print(f"Test data retained: {test_event_key}")
    
    print("\n" + "=" * 60)
    print("Test completed")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(test_verification_job())