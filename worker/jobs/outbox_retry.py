"""Outbox retry job for processing pending messages"""
import time
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from api.core import metrics
from api.db.repositories import outbox_repo
from api.services.telegram import TelegramNotifier
from api.database import build_engine_from_env, get_sessionmaker


def process_outbox_batch(session: Session, limit: int = 50) -> int:
    """Process a batch of outbox messages with retry logic"""
    
    # Get backlog gauge
    backlog_gauge = metrics.gauge("outbox_backlog", "Number of pending outbox messages")
    
    # Update backlog count before processing
    backlog_count = outbox_repo.count_backlog(session)
    backlog_gauge.set(backlog_count)
    
    # Get messages ready for processing
    messages = outbox_repo.dequeue_batch(session, limit=limit)
    processed = 0
    
    # Initialize notifier once
    notifier = TelegramNotifier()
    
    for msg in messages:
        try:
            # Extract text from payload
            text = ""
            if isinstance(msg.payload_json, dict):
                text = msg.payload_json.get("text", str(msg.payload_json))
            else:
                text = str(msg.payload_json)
            
            # Send message
            res = notifier.send_message(
                chat_id=str(msg.channel_id or ""),
                text=text,
                parse_mode="HTML",
                disable_notification=False,
                event_key=msg.event_key,
                attempt=(msg.attempt or 0) + 1
            )
            
            if res.get("success"):
                # Success - mark as done
                outbox_repo.mark_done(session, row_id=msg.id)
            else:
                # Handle different error scenarios
                error_code = res.get("error_code")
                status_code = res.get("status_code", 0)
                retry_after = res.get("retry_after")
                
                if error_code == 429 or status_code == 429:
                    # Rate limit - retry with specified delay or random backoff
                    if retry_after:
                        delay = retry_after
                    else:
                        delay = random.uniform(3, 5)  # 3-5 seconds random
                    
                    next_try = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    outbox_repo.mark_retry(
                        session,
                        row_id=msg.id,
                        next_try_at=next_try,
                        last_error=res.get("error", "Rate limited"),
                        attempt_inc=1
                    )
                
                elif status_code >= 500 or status_code == 0:
                    # 5xx or network error - exponential backoff with jitter
                    attempt = (msg.attempt or 0) + 1
                    base_delay = min(2 ** attempt * 2, 600)  # Cap at 10 minutes
                    jitter = random.uniform(0.7, 1.3)  # ±30% jitter
                    delay = base_delay * jitter
                    
                    next_try = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    outbox_repo.mark_retry(
                        session,
                        row_id=msg.id,
                        next_try_at=next_try,
                        last_error=res.get("error", "Server/network error"),
                        attempt_inc=1
                    )
                
                elif 400 <= status_code < 500 and status_code != 429:
                    # 4xx (non-429) - permanent error, move to DLQ
                    snapshot = msg.payload_json if isinstance(msg.payload_json, dict) else {"text": str(msg.payload_json)}
                    outbox_repo.move_to_dlq(
                        session,
                        row_id=msg.id,
                        last_error=res.get("error", f"Client error {status_code}"),
                        snapshot=snapshot
                    )
                
                else:
                    # Unknown error - treat as transient, retry with exponential backoff
                    attempt = (msg.attempt or 0) + 1
                    base_delay = min(2 ** attempt * 2, 600)
                    jitter = random.uniform(0.7, 1.3)
                    delay = base_delay * jitter
                    
                    next_try = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    outbox_repo.mark_retry(
                        session,
                        row_id=msg.id,
                        next_try_at=next_try,
                        last_error=res.get("error", "Unknown error"),
                        attempt_inc=1
                    )
            
            processed += 1
            
        except Exception as e:
            # Handle unexpected errors - retry with backoff
            attempt = (msg.attempt or 0) + 1
            base_delay = min(2 ** attempt * 2, 600)
            jitter = random.uniform(0.7, 1.3)
            delay = base_delay * jitter
            
            next_try = datetime.now(timezone.utc) + timedelta(seconds=delay)
            outbox_repo.mark_retry(
                session,
                row_id=msg.id,
                next_try_at=next_try,
                last_error=f"Processing error: {str(e)}",
                attempt_inc=1
            )
    
    # Commit all changes
    session.commit()
    
    # Update backlog count after processing
    backlog_count = outbox_repo.count_backlog(session)
    backlog_gauge.set(backlog_count)
    
    return processed


def scheduled_process() -> int:
    """Scheduled process that creates its own session"""
    engine = build_engine_from_env()
    SessionLocal = get_sessionmaker(engine)
    session = SessionLocal()
    
    try:
        return process_outbox_batch(session, limit=50)
    finally:
        session.close()