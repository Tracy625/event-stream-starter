"""GoPlus batch scan job for signals table"""
import os
import time
import json
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import create_engine, text as sa_text
from api.providers.goplus_provider import GoPlusProvider
from api.metrics import log_json


def goplus_scan(batch: Optional[int] = None) -> Dict[str, int]:
    """
    Batch scan signals for GoPlus security assessment.
    
    Args:
        batch: Override batch size (default from GOPLUS_SCAN_BATCH env var)
    
    Returns:
        Dict with processed, success, failed counts
    """
    # Check if scanning is enabled
    if os.getenv("ENABLE_GOPLUS_SCAN", "false").lower() != "true":
        log_json(stage="goplus.scan.disabled", reason="ENABLE_GOPLUS_SCAN not true")
        return {"processed": 0, "success": 0, "failed": 0}
    
    # Configuration
    batch_size = batch or int(os.getenv("GOPLUS_SCAN_BATCH", "50"))
    interval_s = int(os.getenv("GOPLUS_SCAN_INTERVAL_S", "10"))
    
    # Database connection
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        log_json(stage="goplus.scan.error", error="POSTGRES_URL not set")
        return {"processed": 0, "success": 0, "failed": 0}
    
    # Normalize DSN format
    postgres_url = postgres_url.replace("postgresql+psycopg2://", "postgresql://")
    
    engine = create_engine(postgres_url)
    provider = GoPlusProvider()
    
    # Counters
    processed = 0
    success = 0
    failed = 0
    
    log_json(stage="goplus.scan.start", batch_size=batch_size)
    start_time = time.monotonic()
    
    try:
        with engine.begin() as conn:
            # Fetch signals needing scan (goplus_risk IS NULL)
            result = conn.execute(
                sa_text("""
                    SELECT id, symbol, token_ca, evidence
                    FROM signals
                    WHERE goplus_risk IS NULL
                    LIMIT :batch_size
                """),
                {"batch_size": batch_size}
            ).fetchall()
            
            for row in result:
                signal_id, symbol, token_ca, evidence = row
                processed += 1
                
                # Skip if no token_ca
                if not token_ca:
                    log_json(stage="goplus.scan.skip", signal_id=signal_id, reason="no_token_ca")
                    continue
                
                # Default chain_id to 1 (Ethereum) if not specified
                chain_id = "1"
                
                try:
                    # Check token security via provider
                    security_result = provider.check_token(chain_id, token_ca)
                    
                    # Prepare evidence update - handle various evidence types
                    if evidence is None:
                        evidence_data = {}
                    elif isinstance(evidence, dict):
                        evidence_data = evidence.copy()
                    elif isinstance(evidence, str):
                        try:
                            evidence_data = json.loads(evidence)
                        except json.JSONDecodeError:
                            evidence_data = {}
                    else:
                        evidence_data = {}
                    
                    evidence_data["goplus_raw"] = {
                        "risk_label": security_result.risk_label,
                        "buy_tax": security_result.buy_tax,
                        "sell_tax": security_result.sell_tax,
                        "lp_lock_days": security_result.lp_lock_days,
                        "honeypot": security_result.honeypot,
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "cache": security_result.cache,
                        "degrade": security_result.degrade
                    }
                    
                    # Update signal with GoPlus results
                    conn.execute(
                        sa_text("""
                            UPDATE signals
                            SET goplus_risk = :risk,
                                buy_tax = :buy_tax,
                                sell_tax = :sell_tax,
                                lp_lock_days = :lp_lock_days,
                                honeypot = :honeypot,
                                evidence = :evidence,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = :id
                        """),
                        {
                            "id": signal_id,
                            "risk": security_result.risk_label,
                            "buy_tax": security_result.buy_tax,
                            "sell_tax": security_result.sell_tax,
                            "lp_lock_days": security_result.lp_lock_days,
                            "honeypot": security_result.honeypot,
                            "evidence": json.dumps(evidence_data)
                        }
                    )
                    
                    success += 1
                    log_json(
                        stage="goplus.scan.item",
                        signal_id=signal_id,
                        symbol=symbol,
                        risk=security_result.risk_label,
                        cache=security_result.cache
                    )
                    
                except Exception as e:
                    failed += 1
                    log_json(
                        stage="goplus.scan.item_error",
                        signal_id=signal_id,
                        error=str(e)
                    )
                
                # Progress log every 10 items
                if processed % 10 == 0:
                    log_json(
                        stage="goplus.scan.progress",
                        processed=processed,
                        success=success,
                        failed=failed
                    )
            
            # Sleep between batches
            if processed > 0 and processed < batch_size:
                time.sleep(interval_s)
    
    except Exception as e:
        log_json(stage="goplus.scan.error", error=str(e))
    
    finally:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        log_json(
            stage="goplus.scan.complete",
            success=success,
            failed=failed,
            processed=processed,
            duration_ms=duration_ms
        )
    
    return {"processed": processed, "success": success, "failed": failed}