"""Cards send route with tracing and metrics"""
import time
import json
import re
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Query, Header, Depends
from sqlalchemy.orm import Session

from api.core import metrics
from api.core import tracing
from api.core.cache_keys import dedup_key, idemp_key, DEDUP_TTL
from api.cache import get_redis_client
from api.services.telegram import TelegramNotifier
from api.db.repositories import outbox_repo
from api.database import get_sessionmaker, build_engine_from_env
from api.core.config import TelegramConfig

router = APIRouter()
logger = logging.getLogger(__name__)

# Pipeline latency histogram
pipeline_hist = metrics.histogram(
    "pipeline_latency_ms", 
    "End-to-end pipeline latency",
    [50, 100, 200, 500, 1000, 2000, 5000]
)

# Register a module-level singleton counter so export_text() can see it
DEGRADE_COUNTER = metrics.counter(
    "cards_degrade_count", "cards degrade batches"
)

# External error counters
EXTERNAL_ERR_429 = metrics.counter("external_error_total_429", "external errors: 429")
EXTERNAL_ERR_5XX = metrics.counter("external_error_total_5xx", "external errors: 5xx")
EXTERNAL_ERR_NET = metrics.counter("external_error_total_net", "external errors: network/timeouts")


def sanitize(name: str) -> str:
    """Sanitize string keeping only [A-Za-z0-9_-]"""
    return re.sub(r'[^A-Za-z0-9_-]', '_', name)


def write_snapshot(path: Path, payload_dict: Dict[str, Any]) -> None:
    """Write snapshot to file with error handling"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload_dict, f, ensure_ascii=False)
    except Exception:
        logger.warning("write snapshot failed", exc_info=True)


def get_db_session():
    """Get database session"""
    engine = build_engine_from_env()
    SessionLocal = get_sessionmaker(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.post("/cards/send")
async def send_card(
    event_key: str = Query(..., min_length=1, max_length=128),
    count: int = Query(1, ge=1, le=10),
    dry_run: int = Query(0, ge=0, le=1),
    template_v: str = Query("v1"),
    trace_id_hdr: Optional[str] = Header(None, alias="X-Trace-Id"),
    trace_id_q: Optional[str] = Query(None, alias="trace_id"),
    session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """Send cards with deduplication, batch support, and dry_run mode"""
    
    # Start timing
    start_time = time.time()
    
    # Set trace ID from header, query, or generate new one
    if trace_id_hdr:
        tracing.set_trace_id(trace_id_hdr)
    elif trace_id_q:
        tracing.set_trace_id(trace_id_q)
    tid = tracing.get_trace_id()
    
    # Check deduplication using Redis
    redis_client = get_redis_client()
    now = datetime.now(timezone.utc)
    dk = dedup_key(event_key, now)
    
    if redis_client:
        # Try to set the key with NX (only if not exists)
        if not redis_client.set(dk, "1", nx=True, ex=DEDUP_TTL):
            # Key already exists, deduplication hit
            pipeline_hist.observe((time.time() - start_time) * 1000)
            return {
                "dedup": True,
                "sent": 0,
                "failed": 0,
                "items": [],
                "trace_id": tid
            }
    
    # Resolve effective channel for idempotency check (before any send/outbox)
    cfg = TelegramConfig.from_env()
    eff_ch = cfg.effective_channel_id()
    channel_id = eff_ch if eff_ch else -1
    
    # Idempotency check: cards:idemp:{sha1(event|channel|template_v)}
    # Get redis client (may be None; do not fail hard)
    try:
        redis_client = get_redis_client()
    except Exception:
        redis_client = None
    
    if redis_client is not None:
        try:
            idem_key = idemp_key(event_key, channel_id, template_v)
            # Prefer atomic set with NX+EX
            ok = redis_client.set(idem_key, "1", nx=True, ex=DEDUP_TTL)
            if not ok:
                # hit: return immediately with dedup=true, no side effects
                logger.info(
                    "cards idempotent hit",
                    extra={"trace_id": tid, "event_key": event_key, "template_v": template_v, "channel_id": str(channel_id)},
                )
                pipeline_hist.observe((time.time() - start_time) * 1000)
                return {"dedup": True, "sent": 0, "failed": 0, "items": [], "trace_id": tid}
        except Exception as e:
            logger.warning(f"idempotency check failed: {e}")
    
    items: List[Dict[str, Any]] = []
    sent = 0
    failed = 0
    
    # Dry run mode - write to file without sending
    if dry_run == 1:
        out_dir = Path("/tmp/cards")
        out_dir.mkdir(parents=True, exist_ok=True)
        fpath = out_dir / f"{event_key}_{int(datetime.now().timestamp())}.json"
        
        dry_run_data = {
            "dry_run": True,
            "event_key": event_key,
            "count": count,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        fpath.write_text(json.dumps(dry_run_data))
        
        for i in range(count):
            items.append({
                "ok": False,
                "dry_run": True,
                "event_key": event_key,
                "attempt": 0
            })
            failed += 1
        
        pipeline_hist.observe((time.time() - start_time) * 1000)
        return {
            "dedup": False,
            "sent": sent,
            "failed": failed,
            "items": items,
            "trace_id": tid
        }
    
    # Real sending mode
    notifier = TelegramNotifier()
    any_failed = False
    
    # Use the already computed channel_id from idempotency check
    chat_id = str(channel_id)
    
    # Ensure snapshot directory exists
    snapshot_dir = Path("/tmp/cards")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    for i in range(count):
        # Prepare message text
        text = (
            f"<b>{event_key}</b> · Card #{i+1}/{count}\n"
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}"
        )
        
        # Send message with exception handling
        try:
            res = notifier.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_notification=False,
                event_key=event_key,
                attempt=1
            )
            success = res.get("success", False)
        except Exception as e:
            res = {"success": False, "error": str(e), "exc": True}
            success = False
        
        if success:
            sent += 1
            items.append({
                "ok": True,
                "message_id": res.get("message_id"),
                "event_key": event_key,
                "attempt": 1
            })
        else:
            failed += 1
            any_failed = True
            
            # Enqueue to outbox for retry
            row_id = outbox_repo.enqueue(
                session,
                channel_id=int(chat_id) if chat_id.lstrip("-").isdigit() else 0,
                thread_id=cfg.effective_thread_id(),
                event_key=event_key,
                payload_json={
                    "event_key": event_key,
                    "text": text,
                    "index": i + 1,
                    "total": count
                }
            )
            
            # Extract error code from response
            _err = (res.get("error") or "").lower()
            # 1) HTTP status code priority (multiple sources fallback)
            status_val = res.get("status_code") or res.get("code")
            if status_val is not None:
                error_code = str(status_val)
            # 2) Exception/network/timeout
            elif res.get("exc") or "timeout" in _err or "timed out" in _err:
                error_code = "NET"
            # 3) Structured error code from client
            elif res.get("error_code") is not None:
                error_code = str(res.get("error_code"))
            else:
                error_code = "ERR"
            
            # Extract error message
            error_msg = str(res.get("error", ""))[:300]
            
            # Increment external error counters based on error type
            status_code = res.get("status_code")
            if error_code == "429" or (isinstance(status_code, int) and status_code == 429):
                EXTERNAL_ERR_429.inc()
            elif isinstance(status_code, int) and 500 <= status_code <= 599:
                EXTERNAL_ERR_5XX.inc()
            elif error_code == "NET":
                EXTERNAL_ERR_NET.inc()
            
            # Write snapshot for failed item
            ts = int(time.time() * 1000)
            event_short = sanitize(event_key)[:16]
            trace8 = tid[:8]
            snapshot_filename = f"{ts}_{event_short}_{i+1}_{trace8}.json"
            snapshot_path = snapshot_dir / snapshot_filename
            
            snapshot_payload = {
                "event_key": event_key,
                "channel_id": chat_id,
                "text": text,
                "index": i + 1,
                "total": count,
                "trace_id": tid,
                "error_code": error_code,
                "error_msg": error_msg,
                "ts": ts
            }
            
            write_snapshot(snapshot_path, snapshot_payload)
            
            # Log failure with safe extra handling
            try:
                logger.info(
                    "telegram send failed",
                    extra={"trace_id": tid, "event_key": event_key, "error_code": error_code}
                )
            except Exception:
                # Avoid logging formatter not recognizing extra keys causing another error
                logger.info(f"telegram send failed trace_id={tid} event_key={event_key} error_code={error_code}")
            
            items.append({
                "ok": False,
                "error_code": error_code,
                "status_code": res.get("status_code"),
                "retry_after": res.get("retry_after"),
                "error": res.get("error"),
                "event_key": event_key,
                "attempt": 1,
                "outbox_id": row_id
            })
    
    # Commit outbox entries if any failures
    if failed > 0:
        session.commit()
    
    # Record pipeline latency
    pipeline_hist.observe((time.time() - start_time) * 1000)
    
    result = {
        "dedup": False,
        "sent": sent,
        "failed": failed,
        "items": items,
        "trace_id": tid
    }
    
    # Add degrade flag if any failures occurred
    if any_failed:
        result["degrade"] = True
    
    # Increment degrade counter once per degraded batch (singleton counter)
    if result.get("degrade"):
        DEGRADE_COUNTER.inc()
    
    return result