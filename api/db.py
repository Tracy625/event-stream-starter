"""
Database operations for raw posts and events.

Provides transaction-safe operations for inserting and upserting data.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from api.models import Event, RawPost


def now_utc() -> datetime:
    """Get current UTC timestamp with timezone."""
    return datetime.now(timezone.utc)


@contextmanager
def with_session(SessionClass) -> Generator[Session, None, None]:
    """
    Context manager for database sessions with automatic transaction handling.

    Commits on success, rolls back on exception.

    Args:
        SessionClass: sessionmaker class

    Yields:
        Session instance
    """
    session = SessionClass()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def insert_raw_post(
    session: Session, author: str, text: str, ts: datetime, urls: List[str]
) -> int:
    """
    Insert a raw post into the database.

    Args:
        session: Active database session
        author: Post author identifier
        text: Post content
        ts: Post timestamp
        urls: List of URLs found in post

    Returns:
        ID of inserted post
    """
    # Ensure urls is JSONB-friendly
    urls_jsonb = urls if urls else []

    post = RawPost(
        source="api", author=author, text=text, ts=ts, urls=urls_jsonb  # Default source
    )

    session.add(post)
    session.flush()  # Get the ID without committing

    return post.id


def upsert_event(
    session: Session,
    event_key: str,
    type: str,
    score: float,
    summary: str,
    evidence: Dict[str, Any],
    ts: datetime,
) -> None:
    """
    Insert or update an event in the database.

    If event_key exists, only updates: score, summary, evidence.
    Never updates: type, event_key, timestamps.

    Args:
        session: Active database session
        event_key: Unique event identifier
        type: Event type (token, airdrop, deploy, misc)
        score: Event score [0, 1]
        summary: Event summary text
        evidence: Evidence dictionary (JSONB)
        ts: Event timestamp
    """
    # Ensure evidence is JSONB-friendly
    evidence_jsonb = evidence if evidence else {}

    # Use PostgreSQL's ON CONFLICT for upsert
    stmt = insert(Event).values(
        event_key=event_key,
        type=type,
        score=score,
        summary=summary,
        evidence=evidence_jsonb,
        start_ts=ts,
        last_ts=ts,
    )

    # On conflict, only update allowed fields
    stmt = stmt.on_conflict_do_update(
        index_elements=["event_key"],
        set_={
            "score": stmt.excluded.score,
            "summary": stmt.excluded.summary,
            "evidence": stmt.excluded.evidence,
            "last_ts": stmt.excluded.last_ts,
        },
    )

    session.execute(stmt)
