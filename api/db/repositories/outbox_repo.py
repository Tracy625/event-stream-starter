"""Repository layer for push outbox operations"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, asc
from sqlalchemy.sql import func

from api.db.models.push_outbox import PushOutbox, PushOutboxDLQ, OutboxStatus


def enqueue(
    session: Session, 
    *, 
    channel_id: int, 
    thread_id: Optional[int], 
    event_key: str, 
    payload_json: dict
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
        status=OutboxStatus.PENDING
    )
    session.add(outbox)
    session.flush()
    return outbox.id


def dequeue_batch(session: Session, *, limit: int = 50) -> list[PushOutbox]:
    """
    Dequeue batch of messages ready for processing
    
    Fetches messages with status in ('pending','retry') and 
    (next_try_at IS NULL OR next_try_at <= now())
    Ordered by next_try_at NULLS FIRST, created_at ASC
    
    Returns:
        List of PushOutbox records ready for processing
    """
    query = session.query(PushOutbox).filter(
        and_(
            PushOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.RETRY]),
            or_(
                PushOutbox.next_try_at.is_(None),
                PushOutbox.next_try_at <= func.now()
            )
        )
    ).order_by(
        asc(PushOutbox.next_try_at).nullsfirst(),
        asc(PushOutbox.created_at)
    ).limit(limit)
    
    return query.all()


def mark_done(session: Session, *, row_id: int) -> None:
    """
    Mark an outbox entry as done
    """
    session.query(PushOutbox).filter(
        PushOutbox.id == row_id
    ).update({
        'status': OutboxStatus.DONE,
        'updated_at': func.now()
    })


def mark_retry(
    session: Session, 
    *, 
    row_id: int, 
    next_try_at: datetime, 
    last_error: Optional[str], 
    attempt_inc: int = 1
) -> None:
    """
    Mark an outbox entry for retry
    """
    session.query(PushOutbox).filter(
        PushOutbox.id == row_id
    ).update({
        'status': OutboxStatus.RETRY,
        'next_try_at': next_try_at,
        'last_error': last_error,
        'attempt': PushOutbox.attempt + attempt_inc,
        'updated_at': func.now()
    })


def move_to_dlq(
    session: Session, 
    *, 
    row_id: int, 
    last_error: Optional[str], 
    snapshot: Optional[dict] = None
) -> None:
    """
    Move an outbox entry to DLQ
    
    If snapshot is provided, archives to push_outbox_dlq table
    """
    # Get the current row
    outbox = session.query(PushOutbox).filter(
        PushOutbox.id == row_id
    ).first()
    
    if not outbox:
        return
    
    # Archive to DLQ table if snapshot provided
    if snapshot:
        dlq_entry = PushOutboxDLQ(
            ref_id=row_id,
            snapshot=snapshot
        )
        session.add(dlq_entry)
    
    # Update original row status to DLQ
    session.query(PushOutbox).filter(
        PushOutbox.id == row_id
    ).update({
        'status': OutboxStatus.DLQ,
        'last_error': last_error,
        'updated_at': func.now()
    })


def count_backlog(session: Session) -> int:
    """
    Count messages in pending or retry status
    
    Returns:
        Number of messages waiting to be processed
    """
    return session.query(PushOutbox).filter(
        PushOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.RETRY])
    ).count()