"""Cards send route with tracing and metrics"""
import time
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Query, Header, Depends
from sqlalchemy.orm import Session

from api.core import metrics
from api.core import tracing
from api.core.cache_keys import dedup_key, DEDUP_TTL
from api.cache import get_redis_client
from api.services.telegram import TelegramNotifier
from api.db.repositories import outbox_repo
from api.database import get_sessionmaker, build_engine_from_env

router = APIRouter()

# Pipeline latency histogram
pipeline_hist = metrics.histogram(
    "pipeline_latency_ms", 
    "End-to-end pipeline latency",
    [50, 100, 200, 500, 1000, 2000, 5000]
)


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
    
    # Get effective channel from config
    from api.core.config import TelegramConfig
    cfg = TelegramConfig.from_env()
    eff_ch = cfg.effective_channel_id()
    chat_id = str(eff_ch) if eff_ch else "-1"
    
    for i in range(count):
        # Prepare message text
        text = (
            f"<b>{event_key}</b> · Card #{i+1}/{count}\n"
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}"
        )
        
        # Send message
        res = notifier.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_notification=False,
            event_key=event_key,
            attempt=1
        )
        
        if res.get("success"):
            sent += 1
            items.append({
                "ok": True,
                "message_id": res.get("message_id"),
                "event_key": event_key,
                "attempt": 1
            })
        else:
            failed += 1
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
            error_code = (str(res.get("error_code")) if res.get("error_code") is not None
                          else ("timeout" if "timeout" in _err else
                                ("429" if "rate limit" in _err else "error")))
            
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
    
    return {
        "dedup": False,
        "sent": sent,
        "failed": failed,
        "items": items,
        "trace_id": tid
    }