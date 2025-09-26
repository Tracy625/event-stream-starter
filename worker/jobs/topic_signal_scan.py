"""
Scan events with topic data and create corresponding signals.
This job identifies events that have topic_hash but no corresponding signal entry.
"""

import os
from datetime import datetime, timezone, timedelta

from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError

from worker.app import app
from api.database import build_engine_from_env, get_sessionmaker
from api.core.metrics_store import log_json


def get_db_session():
    """Get database session consistent with other worker jobs"""
    engine = build_engine_from_env()
    SessionLocal = get_sessionmaker(engine)
    return SessionLocal()


@app.task
def scan_topic_signals():
    """
    Scan for events with topic data that don't have corresponding signals.
    Creates new signal entries for topic-based events.
    """
    import time
    start_time_perf = time.perf_counter()

    batch_size = int(os.getenv("TOPIC_SIGNAL_BATCH_SIZE", "100"))
    scan_window_hours = int(os.getenv("TOPIC_SIGNAL_SCAN_WINDOW_HOURS", "24"))

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=scan_window_hours)

    log_json(
        stage="topic.signal.scan.start",
        batch_size=batch_size,
        window_hours=scan_window_hours
    )

    created_count = 0
    updated_count = 0
    skipped_non_topic = 0
    error_count = 0

    session = get_db_session()

    try:
        # Find events with topic data but no topic-type signal
        # Note: LEFT JOIN with market_type filter to only check for topic signals
        query = sa_text("""
            SELECT
                e.event_key,
                e.topic_hash as topic_id,
                e.topic_entities,
                e.candidate_score as topic_confidence,
                e.last_ts
            FROM events e
            LEFT JOIN signals s ON e.event_key = s.event_key AND s.market_type = 'topic'
            WHERE e.topic_hash IS NOT NULL
                AND e.last_ts >= :start_time
                AND s.id IS NULL
            ORDER BY e.last_ts DESC
            LIMIT :batch_size
        """)

        results = session.execute(query, {
            "start_time": start_time,
            "batch_size": batch_size
        }).mappings().fetchall()

        for row in results:
            try:
                # First check if any signal exists for this event_key
                check_query = sa_text("""
                    SELECT id, market_type
                    FROM signals
                    WHERE event_key = :event_key
                """)

                existing = session.execute(check_query, {
                    "event_key": row["event_key"]
                }).mappings().fetchone()

                if existing:
                    if existing["market_type"] == 'topic':
                        # Update existing topic signal
                        update_query = sa_text("""
                            UPDATE signals SET
                                topic_id = :topic_id,
                                topic_entities = :topic_entities,
                                topic_confidence = :topic_confidence,
                                ts = :ts
                            WHERE event_key = :event_key AND market_type = 'topic'
                        """)

                        result = session.execute(update_query, {
                            "event_key": row["event_key"],
                            "topic_id": row["topic_id"],
                            "topic_entities": row["topic_entities"],
                            "topic_confidence": float(row["topic_confidence"]) if row["topic_confidence"] else 0.0,
                            "ts": row["last_ts"]
                        })

                        if result.rowcount > 0:
                            updated_count += 1
                    else:
                        # Skip non-topic signal
                        skipped_non_topic += 1
                        log_json(
                            stage="topic.signal.scan.skip_non_topic",
                            event_key=row["event_key"],
                            existing_type=existing["market_type"]
                        )
                else:
                    # Insert new topic signal
                    insert_query = sa_text("""
                        INSERT INTO signals (
                            event_key,
                            market_type,
                            topic_id,
                            topic_entities,
                            topic_confidence,
                            ts
                        ) VALUES (
                            :event_key,
                            'topic',
                            :topic_id,
                            :topic_entities,
                            :topic_confidence,
                            :ts
                        )
                    """)

                    result = session.execute(insert_query, {
                        "event_key": row["event_key"],
                        "topic_id": row["topic_id"],
                        "topic_entities": row["topic_entities"] if row["topic_entities"] else None,
                        "topic_confidence": float(row["topic_confidence"]) if row["topic_confidence"] else 0.0,
                        "ts": row["last_ts"]
                    })

                    if result.rowcount > 0:
                        created_count += 1

            except Exception as e:
                error_count += 1
                log_json(
                    stage="topic.signal.scan.error",
                    event_key=row["event_key"],
                    error=str(e)
                )

        session.commit()

        log_json(
            stage="topic.signal.scan.done",
            created=created_count,
            updated=updated_count,
            skipped_non_topic=skipped_non_topic,
            errors=error_count,
            total=len(results)
        )

        # Log execution time
        elapsed_ms = int((time.perf_counter() - start_time_perf) * 1000)
        log_json(stage="topic.signal.scan.timing", elapsed_ms=elapsed_ms)

        return {
            "success": True,
            "created": created_count,
            "updated": updated_count,
            "skipped_non_topic": skipped_non_topic,
            "errors": error_count,
            "total": len(results)
        }

    except SQLAlchemyError as e:
        session.rollback()
        log_json(
            stage="topic.signal.scan.failed",
            error=str(e)
        )

        # Log execution time even on failure
        elapsed_ms = int((time.perf_counter() - start_time_perf) * 1000)
        log_json(stage="topic.signal.scan.timing", elapsed_ms=elapsed_ms)

        return {
            "success": False,
            "error": str(e)
        }
    finally:
        session.close()