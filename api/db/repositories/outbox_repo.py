"""Repository layer for push outbox operations"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import and_, asc, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.sql import expression, func

from api.db.models.push_outbox import OutboxStatus, PushOutbox, PushOutboxDLQ

# Maximum retry attempts before moving to DLQ
MAX_RETRY_ATTEMPTS = 20


def enqueue(
    session: Session,
    *,
    channel_id: int,
    thread_id: Optional[int],
    event_key: str,
    payload_json: dict,
) -> int:
    """
    Enqueue a new push message to outbox

    Returns:
        Row ID of the created outbox entry
    """
    outbox = PushOutbox(
        channel_id=channel_id,
        thread_id=thread_id,
        event_key=event_key,
        payload_json=payload_json,
        status=OutboxStatus.PENDING,
        attempt=0,
        next_try_at=None,  # Immediate processing for new messages
    )
    session.add(outbox)
    session.flush()
    return outbox.id


def fetch_due(session: Session, *, limit: int = 50) -> List[PushOutbox]:
    """
    Fetch messages that are due for processing with row locking

    This function:
    1. Fetches messages with status in ('pending', 'retry')
    2. Ensures next_try_at is due (or NULL for immediate processing)
    3. Skips messages that exceeded max retry attempts
    4. Uses FOR UPDATE SKIP LOCKED to prevent concurrent processing
    5. Orders by priority: next_try_at NULLS FIRST, then created_at

    Returns:
        List of PushOutbox records ready for processing
    """
    now = func.now()

    # Build query with proper conditions
    query = (
        session.query(PushOutbox)
        .filter(
            and_(
                # Status must be pending or retry
                PushOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.RETRY]),
                # Due for processing: next_try_at is NULL or in the past
                or_(PushOutbox.next_try_at.is_(None), PushOutbox.next_try_at <= now),
                # Haven't exceeded max attempts
                PushOutbox.attempt < MAX_RETRY_ATTEMPTS,
            )
        )
        .order_by(
            # Process immediate messages first (NULL next_try_at)
            asc(func.coalesce(PushOutbox.next_try_at, now)).nullsfirst(),
            # Then by creation order
            asc(PushOutbox.created_at),
        )
        .with_for_update(skip_locked=True)  # Skip locked rows to prevent blocking
        .limit(limit)
    )

    return query.all()


def dequeue_batch(session: Session, *, limit: int = 50) -> List[PushOutbox]:
    """
    Dequeue batch of messages ready for processing

    DEPRECATED: Use fetch_due() instead for better concurrency control

    Returns:
        List of PushOutbox records ready for processing
    """
    # Redirect to the new method with proper locking
    return fetch_due(session, limit=limit)


def mark_done(session: Session, *, row_id: int) -> None:
    """
    Mark an outbox entry as done

    Updates status to DONE and sets updated_at timestamp
    """
    result = (
        session.query(PushOutbox)
        .filter(PushOutbox.id == row_id)
        .update(
            {"status": OutboxStatus.DONE, "updated_at": func.now()},
            synchronize_session=False,
        )
    )

    if result == 0:
        # Log warning if no row was updated
        from api.core.metrics_store import log_json

        log_json(stage="outbox.mark_done", warning="No row updated", row_id=row_id)


def mark_retry(
    session: Session,
    *,
    row_id: int,
    next_try_at: datetime,
    last_error: Optional[str],
    attempt_inc: int = 1,
) -> bool:
    """
    Mark an outbox entry for retry

    Args:
        session: Database session
        row_id: ID of the outbox entry
        next_try_at: When to retry next
        last_error: Error message to store
        attempt_inc: How much to increment attempt counter

    Returns:
        True if marked for retry, False if should go to DLQ
    """
    # First check current attempt count
    current = session.query(PushOutbox).filter(PushOutbox.id == row_id).first()

    if not current:
        return False

    new_attempt = current.attempt + attempt_inc

    # Check if we should move to DLQ instead
    if new_attempt >= MAX_RETRY_ATTEMPTS:
        # Move to DLQ instead of retrying
        move_to_dlq(
            session,
            row_id=row_id,
            last_error=f"Max retries ({MAX_RETRY_ATTEMPTS}) exceeded. Last error: {last_error}",
            snapshot=(
                current.payload_json
                if isinstance(current.payload_json, dict)
                else {"text": str(current.payload_json)}
            ),
        )
        return False

    # Update for retry
    result = (
        session.query(PushOutbox)
        .filter(PushOutbox.id == row_id)
        .update(
            {
                "status": OutboxStatus.RETRY,
                "next_try_at": next_try_at,
                "last_error": last_error,
                "attempt": new_attempt,
                "updated_at": func.now(),
            },
            synchronize_session=False,
        )
    )

    return result > 0


def move_to_dlq(
    session: Session,
    *,
    row_id: int,
    last_error: Optional[str],
    snapshot: Optional[dict] = None,
) -> None:
    """
    Move an outbox entry to DLQ

    If snapshot is provided, archives to push_outbox_dlq table
    """
    # Get the current row
    outbox = session.query(PushOutbox).filter(PushOutbox.id == row_id).first()

    if not outbox:
        return

    # Archive to DLQ table if snapshot provided or create from current
    if snapshot is None:
        snapshot = (
            outbox.payload_json
            if isinstance(outbox.payload_json, dict)
            else {"text": str(outbox.payload_json)}
        )

    dlq_entry = PushOutboxDLQ(ref_id=row_id, snapshot=snapshot)
    session.add(dlq_entry)

    # Update original row status to DLQ
    session.query(PushOutbox).filter(PushOutbox.id == row_id).update(
        {
            "status": OutboxStatus.DLQ,
            "last_error": last_error,
            "updated_at": func.now(),
        },
        synchronize_session=False,
    )

    # Log DLQ move
    from api.core.metrics_store import log_json

    log_json(
        stage="outbox.moved_to_dlq",
        row_id=row_id,
        event_key=outbox.event_key,
        attempts=outbox.attempt,
        last_error=last_error,
    )


def count_backlog(session: Session) -> int:
    """
    Count messages in pending or retry status

    Returns:
        Number of messages waiting to be processed
    """
    return (
        session.query(PushOutbox)
        .filter(
            and_(
                PushOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.RETRY]),
                PushOutbox.attempt < MAX_RETRY_ATTEMPTS,
            )
        )
        .count()
    )


def recover_from_dlq(session: Session, *, row_id: int) -> bool:
    """
    Recover a message from DLQ back to retry status

    Args:
        session: Database session
        row_id: ID of the outbox entry to recover

    Returns:
        True if recovered successfully
    """
    result = (
        session.query(PushOutbox)
        .filter(and_(PushOutbox.id == row_id, PushOutbox.status == OutboxStatus.DLQ))
        .update(
            {
                "status": OutboxStatus.RETRY,
                "attempt": 0,  # Reset attempt counter
                "next_try_at": func.now(),  # Retry immediately
                "last_error": None,
                "updated_at": func.now(),
            },
            synchronize_session=False,
        )
    )

    if result > 0:
        from api.core.metrics_store import log_json

        log_json(stage="outbox.recovered_from_dlq", row_id=row_id)

    return result > 0
