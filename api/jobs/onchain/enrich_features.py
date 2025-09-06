"""Enrich onchain features for signals"""
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from decimal import Decimal

from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker

try:
    from api.utils.logging import log_json
except ImportError:
    def log_json(stage, **kwargs):
        print(f"[{stage}] {kwargs}")


# Database setup
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/guids")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


def get_upstream_features(chain: str, address: str, window_minutes: int, as_of_ts: datetime) -> Optional[Dict[str, Any]]:
    """Get features from upstream provider"""
    # Check if Day11 upstream module exists
    try:
        from api.providers.onchain.bq_provider import BigQueryProvider
        provider = BigQueryProvider()
        # Call Day11 provider if available
        result = provider.get_features(chain, address, window_minutes, as_of_ts)
        return result
    except ImportError:
        # Fallback stub for testing without Day11
        if os.getenv("ENABLE_STUB_DATA", "false").lower() == "true":
            log_json(stage="enrich_features.stub", chain=chain, address=address, window=window_minutes)
            # Return stub data that varies with as_of_ts
            minute_val = as_of_ts.minute if as_of_ts else 0
            return {
                "addr_active": 10 + (minute_val % 10),
                "tx_count": 100 + (minute_val % 20) * 5,
                "top10_share": Decimal("0.45"),
                "self_loop_ratio": Decimal("0.02")
            }
        return None


def compute_growth_ratio(session, chain: str, address: str, window_minutes: int, 
                         current_active: int, as_of_ts: datetime) -> Optional[Decimal]:
    """Compute growth ratio vs previous row in same (chain,address,window)"""
    query = sa_text("""
        SELECT addr_active 
        FROM onchain_features 
        WHERE chain = :chain 
          AND address = :address 
          AND window_minutes = :window_minutes
          AND as_of_ts < :as_of_ts
        ORDER BY as_of_ts DESC
        LIMIT 1
    """)
    
    result = session.execute(query, {
        "chain": chain,
        "address": address,
        "window_minutes": window_minutes,
        "as_of_ts": as_of_ts
    }).first()
    
    if result and result[0] and result[0] > 0:
        prev_active = result[0]
        growth = Decimal(current_active - prev_active) / Decimal(prev_active)
        log_json(stage="enrich_features.growth", chain=chain, address=address, 
                window=window_minutes, prev=prev_active, curr=current_active, growth=float(growth))
        return growth
    
    return None


def enrich_onchain_features(chain: str, address: str, windows: Tuple[int, ...] = (30, 60, 180),
                           calc_version: int = 1, limit_prev_lookback: int = 1,
                           as_of_ts: Optional[datetime] = None) -> dict:
    """Process features for all window sizes"""
    if not as_of_ts:
        as_of_ts = datetime.now(timezone.utc)
    elif not as_of_ts.tzinfo:
        # Make timezone-aware if naive
        as_of_ts = as_of_ts.replace(tzinfo=timezone.utc)
    
    stats = {"written": 0, "updated": 0, "skipped": 0}
    session = Session()
    
    try:
        for window_minutes in windows:
            log_json(stage="enrich_features.start", chain=chain, address=address, window=window_minutes)
            
            # Get upstream features
            features = get_upstream_features(chain, address, window_minutes, as_of_ts)
            if not features:
                log_json(stage="enrich_features.skip", chain=chain, address=address, 
                        window=window_minutes, reason="no_upstream_data")
                stats["skipped"] += 1
                continue
            
            # Compute growth ratio if we have addr_active
            growth_ratio = None
            if features.get("addr_active"):
                growth_ratio = compute_growth_ratio(session, chain, address, window_minutes, 
                                                   features["addr_active"], as_of_ts)
            
            # Check if row exists
            check_query = sa_text("""
                SELECT calc_version FROM onchain_features
                WHERE chain = :chain AND address = :address 
                  AND as_of_ts = :as_of_ts AND window_minutes = :window_minutes
            """)
            existing = session.execute(check_query, {
                "chain": chain,
                "address": address,
                "as_of_ts": as_of_ts,
                "window_minutes": window_minutes
            }).first()
            
            # Idempotent upsert
            upsert_query = sa_text("""
                INSERT INTO onchain_features (
                    chain, address, as_of_ts, window_minutes,
                    addr_active, tx_count, growth_ratio, top10_share, self_loop_ratio,
                    calc_version
                ) VALUES (
                    :chain, :address, :as_of_ts, :window_minutes,
                    :addr_active, :tx_count, :growth_ratio, :top10_share, :self_loop_ratio,
                    :calc_version
                )
                ON CONFLICT (chain, address, as_of_ts, window_minutes)
                DO UPDATE SET
                    addr_active = EXCLUDED.addr_active,
                    tx_count = EXCLUDED.tx_count,
                    growth_ratio = EXCLUDED.growth_ratio,
                    top10_share = EXCLUDED.top10_share,
                    self_loop_ratio = EXCLUDED.self_loop_ratio,
                    calc_version = EXCLUDED.calc_version
                WHERE EXCLUDED.calc_version >= onchain_features.calc_version
            """)
            
            session.execute(upsert_query, {
                "chain": chain,
                "address": address,
                "as_of_ts": as_of_ts,
                "window_minutes": window_minutes,
                "addr_active": features.get("addr_active"),
                "tx_count": features.get("tx_count"),
                "growth_ratio": growth_ratio,
                "top10_share": features.get("top10_share"),
                "self_loop_ratio": features.get("self_loop_ratio"),
                "calc_version": calc_version
            })
            
            stats["written" if not existing else "updated"] += 1
            log_json(stage="enrich_features.done", chain=chain, address=address, window=window_minutes)
        
        session.commit()
        return stats
    finally:
        session.close()