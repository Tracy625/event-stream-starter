"""Verify onchain features table and basic functionality"""
import os
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import create_engine, text as sa_text

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from api.utils.logging import log_json
except ImportError:
    def log_json(stage, **kwargs):
        print(f"[{stage}] {kwargs}")

from api.jobs.onchain.enrich_features import enrich_onchain_features


DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/guids")
engine = create_engine(DATABASE_URL)


def verify_onchain_features():
    """Verify onchain features functionality"""
    # Enable stub data
    os.environ["ENABLE_STUB_DATA"] = "true"
    
    chain = "eth"
    address = "0x0000000000000000000000000000000000000000"
    
    # Clean up any existing test data
    with engine.connect() as conn:
        conn.execute(sa_text("""
            DELETE FROM onchain_features 
            WHERE chain = :chain AND address = :address
        """), {"chain": chain, "address": address})
        conn.commit()
    
    # First run with T1
    t1 = datetime(2025, 1, 6, 12, 0, 0, tzinfo=timezone.utc)
    log_json(stage="verify.run1", as_of_ts=t1.isoformat())
    stats1 = enrich_onchain_features(chain, address, as_of_ts=t1)
    log_json(stage="verify.stats1", **stats1)
    assert stats1["written"] == 3, f"Expected 3 written, got {stats1['written']}"
    
    # Second run with T2 (10 minutes later)
    t2 = t1 + timedelta(minutes=11)
    log_json(stage="verify.run2", as_of_ts=t2.isoformat())
    stats2 = enrich_onchain_features(chain, address, as_of_ts=t2)
    log_json(stage="verify.stats2", **stats2)
    assert stats2["written"] == 3, f"Expected 3 written, got {stats2['written']}"
    
    # Verify growth_ratio for window=30
    with engine.connect() as conn:
        result = conn.execute(sa_text("""
            SELECT as_of_ts, addr_active, growth_ratio
            FROM onchain_features
            WHERE chain = :chain AND address = :address AND window_minutes = 30
            ORDER BY as_of_ts
        """), {"chain": chain, "address": address})
        
        rows = list(result)
        assert len(rows) == 2, f"Expected 2 rows for window=30, got {len(rows)}"
        
        # First row should have NULL growth_ratio
        assert rows[0][2] is None, "First row should have NULL growth_ratio"
        
        # Second row should have calculated growth_ratio
        assert rows[1][2] is not None, "Second row growth_ratio should not be NULL"
        prev_active = rows[0][1]
        curr_active = rows[1][1]
        expected_growth = Decimal(curr_active - prev_active) / Decimal(prev_active)
        actual_growth = Decimal(str(rows[1][2]))
        assert abs(actual_growth - expected_growth) < Decimal("1e-8"), f"growth_ratio mismatch: expected {expected_growth}, got {actual_growth}"
        log_json(stage="verify.growth", prev=prev_active, curr=curr_active, expected=float(expected_growth), actual=float(actual_growth))
    
    # Third run with same T2 (idempotency check)
    log_json(stage="verify.run3", as_of_ts=t2.isoformat())
    stats3 = enrich_onchain_features(chain, address, as_of_ts=t2)
    log_json(stage="verify.stats3", **stats3)
    assert stats3["written"] == 0, f"Expected 0 written (idempotent), got {stats3['written']}"
    assert stats3["updated"] == 3, f"Expected 3 updated (idempotent), got {stats3['updated']}"
    
    # Print summary for manual inspection
    with engine.connect() as conn:
        result = conn.execute(sa_text("""
            SELECT window_minutes, COUNT(*) as cnt, MAX(growth_ratio) as latest_growth
            FROM onchain_features
            WHERE chain = :chain AND address = :address
            GROUP BY window_minutes
            ORDER BY window_minutes
        """), {"chain": chain, "address": address})
        
        for row in result:
            log_json(stage="verify.summary", window=row[0], count=row[1], 
                    latest_growth=float(row[2]) if row[2] else None)
    
    log_json(stage="verify", status="success")


if __name__ == "__main__":
    verify_onchain_features()