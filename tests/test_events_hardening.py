import os
from datetime import datetime, timezone

import pytest


def test_make_event_key_requires_type():
    from api.events import make_event_key

    # Missing type should raise
    with pytest.raises(ValueError):
        make_event_key({"text": "foo"})

    # With type should pass and return a 40-hex key
    key = make_event_key({"type": "market-update", "text": "foo"})
    assert isinstance(key, str)
    assert len(key) == 40


def test_upsert_topic_fields_persist(monkeypatch):
    """
    Verify that when topic_hash/topic_entities are provided and columns exist,
    the insert payload includes them. Uses a mocked engine and insert builder.
    """
    import types
    from api import events as ev
    from sqlalchemy import MetaData, Table, Column, Text, Integer, Float
    try:
        from sqlalchemy.dialects.postgresql import JSONB
    except Exception:
        # Fallback if JSONB not available in environment
        from sqlalchemy import JSON as JSONB  # type: ignore

    # Ensure POSTGRES_URL present (value unused by fake engine)
    os.environ.setdefault("POSTGRES_URL", "postgresql://stub")

    # Build a mock events table with needed columns
    md = MetaData()
    events_tbl = Table(
        "events", md,
        Column("event_key", Text, primary_key=True),
        Column("symbol", Text),
        Column("token_ca", Text),
        Column("topic_hash", Text),
        Column("time_bucket_start", Text),  # type not critical for test
        Column("start_ts", Text),
        Column("last_ts", Text),
        Column("evidence_count", Integer),
        Column("candidate_score", Float),
        Column("keywords_norm", JSONB),
        Column("version", Text),
        Column("last_sentiment", Text),
        Column("last_sentiment_score", Float),
        Column("topic_entities", Text),  # store as text for simplicity in test
        Column("evidence", JSONB),
    )

    # Patch the cached table so reflection is skipped
    prev_cache = getattr(ev, "_events_tbl_cache", None)
    ev._events_tbl_cache = events_tbl

    # Fake engine/connection that captures the insert values
    class FakeConn:
        def __init__(self):
            self.last_insert_values = None

        def execute(self, stmt, params=None):
            # Capture insert values from our fake statement
            if hasattr(stmt, "_insert_values"):
                self.last_insert_values = dict(stmt._insert_values)

            class _R:
                def fetchone(self_inner):
                    # Return minimal tuple: evidence_count, candidate_score, last_ts
                    return (1, 0.38, datetime.now(timezone.utc))

            return _R()

    class FakeEngine:
        def __init__(self):
            self.conn = FakeConn()

        def begin(self):
            engine = self

            class Ctx:
                def __enter__(self_inner):
                    return engine.conn

                def __exit__(self_inner, exc_type, exc, tb):
                    return False

            return Ctx()

    fake_engine = FakeEngine()

    # Patch create_engine to return our fake engine
    monkeypatch.setattr(ev, "create_engine", lambda *_args, **_kwargs: fake_engine)

    # Patch pg_insert to a fake that records values
    class FakeInsert:
        def __init__(self, table):
            self.table = table
            self._insert_values = {}

        def values(self, **kwargs):
            self._insert_values = dict(kwargs)
            return self

        def on_conflict_do_update(self, **kwargs):
            # Return self as a stand-in statement
            return self

    monkeypatch.setattr(ev, "pg_insert", lambda table: FakeInsert(table))

    # Build post with topic fields
    post = {
        "type": "market-update",
        "text": "Listing rumor for $PEPE",
        "symbol": "PEPE",
        "keywords": ["$PEPE"],
        "created_ts": datetime.now(timezone.utc),
        "sentiment_label": "neu",
        "sentiment_score": 0.0,
        "topic_hash": "t.test123",
        "topic_entities": ["pepe", "gem"],
    }

    # Execute upsert (will use fakes, not touching real DB)
    result = ev.upsert_event(post)
    assert isinstance(result, dict)

    # Validate that topic fields were included in insert payload
    assert fake_engine.conn.last_insert_values is not None
    assert fake_engine.conn.last_insert_values.get("topic_hash") == post["topic_hash"]
    # topic_entities was declared as Text in the test table; ensure value serialized
    assert "topic_entities" in fake_engine.conn.last_insert_values
