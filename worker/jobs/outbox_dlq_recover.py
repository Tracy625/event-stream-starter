"""DLQ recovery job for push outbox entries."""

import os
from datetime import datetime, timedelta, timezone
from typing import Dict

from sqlalchemy.orm import Session

from api.core import metrics
from api.database import build_engine_from_env, get_sessionmaker
from api.db.models.push_outbox import OutboxStatus, PushOutbox, PushOutboxDLQ

_DEFAULT_LIMIT = int(os.getenv("OUTBOX_DLQ_RECOVER_LIMIT", "50"))
_DEFAULT_MAX_AGE = int(os.getenv("OUTBOX_DLQ_MAX_AGE_SEC", str(3600)))  # 1 hour


def _get_counters() -> Dict[str, metrics.Counter]:
    recovered_counter = metrics.counter(
        "dlq_recovered_count", "Number of DLQ entries successfully recovered"
    )
    discarded_counter = metrics.counter(
        "dlq_discarded_count",
        "Number of DLQ entries discarded due to staleness or missing source",
    )
    return {
        "recovered": recovered_counter,
        "discarded": discarded_counter,
    }


def recover_batch(
    session: Session, *, limit: int | None = None, max_age_seconds: int | None = None
) -> Dict[str, int]:
    """Recover a batch of DLQ entries back into the main outbox table."""
    limit = limit or _DEFAULT_LIMIT
    max_age_seconds = max_age_seconds or _DEFAULT_MAX_AGE

    counters = _get_counters()
    now = datetime.now(timezone.utc)
    expiry_cutoff = now - timedelta(seconds=max_age_seconds)

    # push_outbox_dlq 没有 updated_at 字段，使用 failed_at 近似排序
    dlq_rows = (
        session.query(PushOutboxDLQ)
        .order_by(PushOutboxDLQ.failed_at.asc())
        .limit(limit)
        .all()
    )

    recovered = discarded = skipped = 0

    for dlq_row in dlq_rows:
        # 丢弃超出保留期的记录
        if dlq_row.failed_at and dlq_row.failed_at < expiry_cutoff:
            session.delete(dlq_row)
            discarded += 1
            continue

        outbox_row = session.get(PushOutbox, dlq_row.ref_id)
        if outbox_row is None:
            session.delete(dlq_row)
            discarded += 1
            continue

        if outbox_row.status != OutboxStatus.DLQ:
            # 已经被其他流程恢复，删除 DLQ 快照避免重复
            session.delete(dlq_row)
            skipped += 1
            continue

        # 恢复：重置状态/重试时间，写回最新快照
        outbox_row.status = OutboxStatus.RETRY
        outbox_row.next_try_at = now
        outbox_row.last_error = None
        outbox_row.attempt = 0
        outbox_row.payload_json = dlq_row.snapshot

        session.delete(dlq_row)
        recovered += 1

    session.commit()

    if recovered:
        counters["recovered"].inc(value=recovered)
    if discarded:
        counters["discarded"].inc(value=discarded)

    return {
        "scanned": len(dlq_rows),
        "recovered": recovered,
        "discarded": discarded,
        "skipped": skipped,
    }


def recover_once(
    *, limit: int | None = None, max_age_seconds: int | None = None
) -> Dict[str, int]:
    """Standalone helper to run recovery with its own session."""
    engine = build_engine_from_env()
    SessionLocal = get_sessionmaker(engine)
    session = SessionLocal()
    try:
        return recover_batch(session, limit=limit, max_age_seconds=max_age_seconds)
    finally:
        session.close()
