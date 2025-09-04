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
            # 从 signals 关联 events 取需要的字段；token_ca/symbol 以 events 为准
            result = conn.execute(
                sa_text("""
                    SELECT s.id AS signal_id, s.event_key,
                           e.symbol, e.token_ca, e.evidence
                    FROM signals s
                    JOIN events e ON e.event_key = s.event_key
                    WHERE s.goplus_risk IS NULL
                    LIMIT :batch_size
                """),
                {"batch_size": batch_size}
            ).fetchall()
            
            for row in result:
                signal_id = row.signal_id
                event_key  = row.event_key
                symbol     = row.symbol
                token_ca   = row.token_ca
                evidence   = row.evidence
                processed += 1
                
                # Skip if no token_ca
                if not token_ca:
                    log_json(stage="goplus.scan.skip", signal_id=signal_id, reason="no_token_ca")
                    continue
                
                # 解析 evidence，支持 str / dict / list；chain_id 尝试从 evidence 里取
                chain_id = "1"
                ev_obj = None
                if isinstance(evidence, str):
                    try:
                        ev_obj = json.loads(evidence)
                    except Exception:
                        ev_obj = None
                else:
                    ev_obj = evidence

                if isinstance(ev_obj, dict):
                    chain_id = str(ev_obj.get("chain_id") or chain_id)
                    token_ca = token_ca or ev_obj.get("token_ca")
                elif isinstance(ev_obj, list):
                    for item in ev_obj:
                        if isinstance(item, dict):
                            if not token_ca:
                                token_ca = item.get("token_ca") or token_ca
                            if not chain_id and item.get("chain_id"):
                                chain_id = str(item.get("chain_id"))
                
                try:
                    # Check token security via provider
                    security_result = provider.check_token(chain_id, token_ca)
                    
                    # 生成 go+ 摘要（不破坏 evidence 结构：dict 则打键；list 则 append）
                    summary_text = (
                        (security_result.notes[0] if getattr(security_result, "notes", None) else None)
                        or ("evaluated by local rules" if security_result.degrade else "evaluated by goplus api")
                    )
                    goplus_summary = {
                        "summary": summary_text,
                        "risk_label": security_result.risk_label,
                        "buy_tax": security_result.buy_tax,
                        "sell_tax": security_result.sell_tax,
                        "lp_lock_days": security_result.lp_lock_days,
                        "honeypot": security_result.honeypot,
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "cache": security_result.cache,
                        "degrade": security_result.degrade
                    }
                    new_evidence = ev_obj
                    if isinstance(ev_obj, dict):
                        # 在 dict 顶层挂一个键，便于查阅
                        merged = dict(ev_obj)
                        merged["goplus_raw"] = goplus_summary
                        new_evidence = merged
                    elif isinstance(ev_obj, list):
                        # 追加一条结构化记录
                        new_evidence = list(ev_obj) + [{"source": "goplus", "goplus_raw": goplus_summary}]
                    else:
                        # 空或异常，兜底为单元素列表
                        new_evidence = [{"source": "goplus", "goplus_raw": goplus_summary}]
                    
                    # 回填 1：signals（风控字段）
                    conn.execute(
                        sa_text("""
                            UPDATE signals
                               SET goplus_risk = :risk,
                                   buy_tax = :buy_tax,
                                   sell_tax = :sell_tax,
                                   lp_lock_days = :lp_lock_days,
                                   honeypot = :honeypot
                             WHERE id = :id
                        """),
                        {
                            "id": signal_id,
                            "risk": security_result.risk_label,
                            "buy_tax": security_result.buy_tax,
                            "sell_tax": security_result.sell_tax,
                            "lp_lock_days": security_result.lp_lock_days,
                            "honeypot": security_result.honeypot,
                        },
                    )
                    # 回填 2：events（证据字段，JSONB）
                    conn.execute(
                        sa_text("""
                            UPDATE events
                               SET evidence = CAST(:evidence AS jsonb)
                             WHERE event_key = :event_key
                        """),
                        {
                            "event_key": event_key,
                            "evidence": json.dumps(new_evidence, ensure_ascii=False),
                        },
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
                
                # 每处理 10 条打点一次
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