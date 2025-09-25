import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.core import metrics
from api.db.models.push_outbox import PushOutbox, PushOutboxDLQ, OutboxStatus
from worker.jobs.outbox_dlq_recover import recover_batch


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    pytest.skip("DATABASE_URL is required for DLQ recovery tests", allow_module_level=True)
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


@pytest.mark.parametrize("max_age", [5])
def test_dlq_recover_and_discard(max_age):
    metrics._registry.clear()

    now = datetime.now(timezone.utc)
    fresh_snapshot = {"text": "fresh"}
    stale_snapshot = {"text": "stale"}

    fresh_id = stale_id = skipped_id = None

    with Session() as session:
        # Fresh DLQ entry - should be recovered
        fresh = PushOutbox(
            channel_id=-1,
            thread_id=None,
            event_key="fresh",
            payload_json={"text": "old"},
            status=OutboxStatus.DLQ,
        )
        session.add(fresh)
        session.flush()
        fresh_id = fresh.id
        session.add(
            PushOutboxDLQ(
                ref_id=fresh_id,
                snapshot=fresh_snapshot,
                failed_at=now,
            )
        )

        # Stale DLQ entry - should be discarded
        stale = PushOutbox(
            channel_id=-2,
            thread_id=None,
            event_key="stale",
            payload_json={"text": "old"},
            status=OutboxStatus.DLQ,
        )
        session.add(stale)
        session.flush()
        stale_id = stale.id
        session.add(
            PushOutboxDLQ(
                ref_id=stale_id,
                snapshot=stale_snapshot,
                failed_at=now - timedelta(seconds=max_age + 5),
            )
        )

        # Already recovered entry - DLQ row should be skipped and deleted
        skipped = PushOutbox(
            channel_id=-3,
            thread_id=None,
            event_key="skipped",
            payload_json={"text": "ok"},
            status=OutboxStatus.PENDING,
        )
        session.add(skipped)
        session.flush()
        skipped_id = skipped.id
        session.add(
            PushOutboxDLQ(
                ref_id=skipped_id,
                snapshot={"text": "skipped"},
                failed_at=now,
            )
        )

        session.commit()

        result = recover_batch(session, limit=10, max_age_seconds=max_age)

        assert result["recovered"] == 1
        assert result["discarded"] == 1
        assert result["skipped"] == 1

        fresh_row = session.get(PushOutbox, fresh_id)
        assert fresh_row.status == OutboxStatus.RETRY
        assert fresh_row.payload_json == fresh_snapshot

        stale_row = session.get(PushOutbox, stale_id)
        assert stale_row.status == OutboxStatus.DLQ

        assert session.query(PushOutboxDLQ).filter_by(ref_id=fresh_id).first() is None
        assert session.query(PushOutboxDLQ).filter_by(ref_id=stale_id).first() is None
        assert session.query(PushOutboxDLQ).filter_by(ref_id=skipped_id).first() is None

        recovered_counter = metrics.counter(
            "dlq_recovered_count",
            "Number of DLQ entries successfully recovered",
        )
        discarded_counter = metrics.counter(
            "dlq_discarded_count",
            "Number of DLQ entries discarded due to staleness or missing source",
        )

        assert recovered_counter.values.get("", 0) >= 1
        assert discarded_counter.values.get("", 0) >= 1

    # Cleanup inserted rows to avoid polluting shared DB
    with Session() as cleanup:
        cleanup.query(PushOutboxDLQ).filter(
            PushOutboxDLQ.ref_id.in_([fresh_id, stale_id, skipped_id])
        ).delete(synchronize_session=False)
        cleanup.query(PushOutbox).filter(
            PushOutbox.id.in_([fresh_id, stale_id, skipped_id])
        ).delete(synchronize_session=False)
        cleanup.commit()
