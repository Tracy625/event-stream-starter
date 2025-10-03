import os
from datetime import datetime, timezone


def test_upsert_insert_conflict_fallback(monkeypatch):
    """Simulate lock failure leading to fallback path and ensure metrics increment."""
    os.environ.setdefault("POSTGRES_URL", "postgresql://stub")
    os.environ.setdefault("EVENT_DEADLOCK_MAX_RETRY", "0")  # immediate fallback

    from sqlalchemy import Column, Float, Integer, MetaData, Table, Text

    try:
        from sqlalchemy.dialects.postgresql import JSONB
    except Exception:
        from sqlalchemy import JSON as JSONB  # type: ignore

    from api import events as ev
    from api.core import metrics as mc

    # Build table schema minimal
    md = MetaData()
    events_tbl = Table(
        "events",
        md,
        Column("event_key", Text, primary_key=True),
        Column("symbol", Text),
        Column("token_ca", Text),
        Column("topic_hash", Text),
        Column("evidence_count", Integer),
        Column("candidate_score", Float),
        Column("evidence", JSONB),
        Column("last_ts", Text),
        Column("start_ts", Text),
        Column("time_bucket_start", Text),
        Column("keywords_norm", JSONB),
        Column("version", Text),
    )

    ev._events_tbl_cache = events_tbl

    # Fake connection/engine that raises on NOWAIT select once
    class FakeConn:
        def __init__(self):
            self.lock_attempts = 0
            self.last_insert_values = None

        def execute(self, stmt, params=None):
            # Detect NOWAIT select by string
            if isinstance(stmt, str):
                sql = stmt
            else:
                try:
                    sql = str(stmt)
                except Exception:
                    sql = ""
            if "FOR UPDATE NOWAIT" in sql and self.lock_attempts == 0:
                self.lock_attempts += 1
                raise Exception("could not obtain lock")

            # Capture insert values from fake insert
            if hasattr(stmt, "_insert_values"):
                self.last_insert_values = dict(stmt._insert_values)

            class _R:
                def fetchone(self_inner):
                    # Return minimal tuple: evidence_count, candidate_score, last_ts
                    return (1, 0.5, datetime.now(timezone.utc))

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
    monkeypatch.setattr(ev, "create_engine", lambda *_args, **_kwargs: fake_engine)

    # Fake insert builder to avoid dialect dependencies
    class FakeInsert:
        def __init__(self, table):
            self.table = table
            self._insert_values = {}
            self.excluded = type("Excluded", (), {})()  # mimic attribute presence

        def values(self, **kwargs):
            self._insert_values = dict(kwargs)
            return self

        def on_conflict_do_update(self, **kwargs):
            return self

    monkeypatch.setattr(ev, "pg_insert", lambda table: FakeInsert(table))

    # Snapshot metrics before
    before_fallback = mc.insert_conflict_fallback_total.values.copy()

    post = {
        "type": "market-update",
        "text": "$PEPE to moon",
        "created_ts": datetime.now(timezone.utc),
    }
    ev.upsert_event(post)

    # Ensure fallback counter increments when exceeding retry threshold
    assert mc.insert_conflict_fallback_total.values != before_fallback
