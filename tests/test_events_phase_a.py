import os
from datetime import datetime, timezone


def test_make_event_key_v2_symbol_normalization(monkeypatch):
    from api.events import make_event_key

    fixed_ts = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("EVENT_KEY_VERSION", "v2")
    monkeypatch.setenv("EVENT_KEY_SALT", "testsalt")
    monkeypatch.setenv("EVENT_TIME_BUCKET_SEC", "600")

    base = {
        "type": "market-update",
        "text": "Listing rumor for $PEPE",
        "created_ts": fixed_ts,
        "topic_hash": "t.hash123",
    }

    post1 = dict(base, symbol="PEPE")
    post2 = dict(base, symbol="$pepe")
    post3 = dict(base, symbol="PePe")

    k1 = make_event_key(post1)
    k2 = make_event_key(post2)
    k3 = make_event_key(post3)

    assert isinstance(k1, str) and len(k1) == 40
    assert k1 == k2 == k3


def test_merge_evidence_completion():
    from api.events import _build_evidence_item, merge_event_evidence

    fixed_ts = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    existing = [
        _build_evidence_item(
            source="x",
            ts=fixed_ts,
            ref={"tweet_id": "12345"},
            summary=None,
            weight=1.0,
        )
    ]
    incoming = [
        _build_evidence_item(
            source="x",
            ts=fixed_ts,
            ref={"url": "https://twitter.com/user/status/12345?utm_source=foo"},
            summary=None,
            weight=1.0,
        )
    ]

    res = merge_event_evidence("ek", incoming, existing)
    merged = res["merged_evidence"]
    assert len(merged) == 1
    ref = merged[0]["ref"]
    assert ref.get("tweet_id") == "12345"
    assert ref.get("url").startswith("https://twitter.com/")
