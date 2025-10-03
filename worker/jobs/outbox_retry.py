"""Outbox retry job for processing pending messages"""

import random
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from api.core import metrics, tracing
from api.core.metrics_store import log_json
from api.database import build_engine_from_env, get_sessionmaker
from api.db.repositories import outbox_repo
from api.services.telegram import TelegramNotifier


def process_outbox_batch(session: Session, limit: int = 50) -> int:
    """
    Process a batch of outbox messages with proper retry logic

    This function:
    1. Fetches due messages with row locking
    2. Processes each message
    3. Updates status based on result
    4. Commits transaction

    Args:
        session: Database session
        limit: Maximum number of messages to process

    Returns:
        Number of messages processed
    """

    # Get metrics instances
    backlog_gauge = metrics.gauge("outbox_backlog", "Number of pending outbox messages")
    processed_counter = metrics.counter("outbox_processed", "Outbox messages processed")
    dlq_counter = metrics.counter("outbox_dlq", "Messages moved to DLQ")

    # Get trace ID for this batch
    trace_id = tracing.get_trace_id()

    # Update backlog count before processing
    backlog_count = outbox_repo.count_backlog(session)
    backlog_gauge.set(backlog_count)
    log_json(
        stage="outbox.batch.start",
        trace_id=trace_id,
        backlog_before=backlog_count,
        limit=limit,
    )

    # Fetch messages that are due for processing (with row locking)
    messages = outbox_repo.fetch_due(session, limit=limit)

    if not messages:
        log_json(stage="outbox.batch.empty", trace_id=trace_id)
        return 0

    log_json(stage="outbox.batch.fetched", trace_id=trace_id, count=len(messages))

    # Initialize notifier once for the batch
    notifier = TelegramNotifier()

    processed = 0
    succeeded = 0
    retried = 0
    dlq_moved = 0

    for msg in messages:
        try:
            # Extract text from payload
            text = ""
            if isinstance(msg.payload_json, dict):
                text = msg.payload_json.get("text", "")
                if not text:
                    # Try other common fields
                    text = msg.payload_json.get("message", "")
                    if not text:
                        text = str(msg.payload_json)
            else:
                text = str(msg.payload_json)

            # Log processing attempt
            log_json(
                stage="outbox.message.processing",
                trace_id=trace_id,
                row_id=msg.id,
                event_key=msg.event_key,
                attempt=msg.attempt + 1,
            )

            # Send message
            res = notifier.send_message(
                chat_id=str(msg.channel_id or ""),
                text=text,
                parse_mode="HTML",
                disable_notification=False,
                event_key=msg.event_key,
                attempt=(msg.attempt or 0) + 1,
            )

            if res.get("success"):
                # Success - mark as done
                outbox_repo.mark_done(session, row_id=msg.id)
                succeeded += 1
                processed_counter.inc({"result": "success"})

                log_json(
                    stage="outbox.message.sent",
                    trace_id=trace_id,
                    row_id=msg.id,
                    event_key=msg.event_key,
                    message_id=res.get("message_id"),
                )

            else:
                # Handle failure based on error type
                error_code = res.get("error_code")
                status_code = res.get("status_code", 0)
                retry_after = res.get("retry_after")
                error_msg = res.get("error", "Unknown error")

                # Calculate next retry time based on error type
                next_try_at = calculate_next_retry(
                    attempt=msg.attempt + 1,
                    status_code=status_code,
                    error_code=error_code,
                    retry_after=retry_after,
                )

                # Determine if this is a permanent error
                is_permanent = is_permanent_error(status_code, error_code)

                if is_permanent or msg.attempt >= outbox_repo.MAX_RETRY_ATTEMPTS - 1:
                    # Move to DLQ for permanent errors or max attempts reached
                    snapshot = (
                        msg.payload_json
                        if isinstance(msg.payload_json, dict)
                        else {"text": text}
                    )
                    outbox_repo.move_to_dlq(
                        session, row_id=msg.id, last_error=error_msg, snapshot=snapshot
                    )
                    dlq_moved += 1
                    dlq_counter.inc()
                    processed_counter.inc({"result": "dlq"})

                    log_json(
                        stage="outbox.message.dlq",
                        trace_id=trace_id,
                        row_id=msg.id,
                        event_key=msg.event_key,
                        reason="permanent_error" if is_permanent else "max_retries",
                        error=error_msg,
                    )

                else:
                    # Retry with calculated delay
                    success = outbox_repo.mark_retry(
                        session,
                        row_id=msg.id,
                        next_try_at=next_try_at,
                        last_error=error_msg,
                        attempt_inc=1,
                    )

                    if success:
                        retried += 1
                        processed_counter.inc({"result": "retry"})

                        log_json(
                            stage="outbox.message.retry",
                            trace_id=trace_id,
                            row_id=msg.id,
                            event_key=msg.event_key,
                            next_attempt=msg.attempt + 1,
                            next_try_at=next_try_at.isoformat(),
                            error=error_msg,
                        )

            processed += 1

            # Commit after each message to avoid long transactions
            session.commit()

        except Exception as e:
            # Handle unexpected errors
            log_json(
                stage="outbox.message.error",
                trace_id=trace_id,
                row_id=msg.id,
                event_key=msg.event_key,
                error=str(e),
            )

            # Rollback this message's transaction
            session.rollback()

            # Try to mark for retry
            try:
                attempt = (msg.attempt or 0) + 1
                next_try_at = calculate_next_retry(attempt=attempt)

                success = outbox_repo.mark_retry(
                    session,
                    row_id=msg.id,
                    next_try_at=next_try_at,
                    last_error=f"Processing error: {str(e)}",
                    attempt_inc=1,
                )

                if success:
                    retried += 1
                    session.commit()
                else:
                    # Moved to DLQ
                    dlq_moved += 1
                    session.commit()

            except Exception as inner_e:
                log_json(
                    stage="outbox.message.fatal",
                    trace_id=trace_id,
                    row_id=msg.id,
                    error=str(inner_e),
                )
                session.rollback()

    # Update backlog count after processing
    backlog_count = outbox_repo.count_backlog(session)
    backlog_gauge.set(backlog_count)

    log_json(
        stage="outbox.batch.complete",
        trace_id=trace_id,
        processed=processed,
        succeeded=succeeded,
        retried=retried,
        dlq_moved=dlq_moved,
        backlog_after=backlog_count,
    )

    return processed


def calculate_next_retry(
    attempt: int,
    status_code: Optional[int] = None,
    error_code: Optional[int] = None,
    retry_after: Optional[int] = None,
) -> datetime:
    """
    Calculate next retry time based on error type and attempt number

    Args:
        attempt: Current attempt number (1-based)
        status_code: HTTP status code if available
        error_code: Specific error code if available
        retry_after: Server-specified retry delay in seconds

    Returns:
        Datetime when the next retry should occur
    """
    now = datetime.now(timezone.utc)

    # Rate limiting - use server's suggestion or short random delay
    if error_code == 429 or status_code == 429:
        if retry_after and retry_after > 0:
            delay = retry_after
        else:
            # Random delay between 1-3 seconds for rate limits
            delay = random.uniform(1, 3)

    # Server errors or network issues - exponential backoff with jitter
    elif status_code >= 500 or status_code == 0:
        # Exponential backoff: 2, 4, 8, 16, 32, 64, 128, 256, 512, 600 (cap)
        base_delay = min(2**attempt, 600)
        # Add ±30% jitter to prevent thundering herd
        jitter = random.uniform(0.7, 1.3)
        delay = base_delay * jitter

    # Default case - moderate exponential backoff
    else:
        base_delay = min(2**attempt * 2, 300)  # Cap at 5 minutes
        jitter = random.uniform(0.8, 1.2)  # ±20% jitter
        delay = base_delay * jitter

    return now + timedelta(seconds=delay)


def is_permanent_error(status_code: Optional[int], error_code: Optional[int]) -> bool:
    """
    Determine if an error is permanent and should go to DLQ

    Args:
        status_code: HTTP status code
        error_code: Specific error code

    Returns:
        True if error is permanent and retrying won't help
    """
    if status_code is None:
        return False

    # 4xx errors (except rate limiting) are usually permanent
    if 400 <= status_code < 500 and status_code != 429:
        # Special cases that might be transient
        if status_code in [408, 423, 425]:  # Request Timeout, Locked, Too Early
            return False
        return True

    return False


def scheduled_process() -> int:
    """
    Scheduled process entry point that creates its own database session

    This is called by Celery beat scheduler

    Returns:
        Number of messages processed
    """
    engine = build_engine_from_env()
    SessionLocal = get_sessionmaker(engine)
    session = SessionLocal()

    try:
        return process_outbox_batch(session, limit=50)
    except Exception as e:
        log_json(stage="outbox.scheduled.error", error=str(e))
        raise
    finally:
        session.close()
