import time

from api.core import metrics
from api.tasks import beat
from scripts import beat_healthcheck


class DummyRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)


def test_beat_heartbeat_increments(monkeypatch):
    metrics._registry.clear()

    dummy = DummyRedis()
    monkeypatch.setenv("BEAT_HEARTBEAT_KEY", "test:heartbeat")
    monkeypatch.setattr(beat, "get_redis_client", lambda: dummy)

    beat.heartbeat()
    beat.heartbeat()

    counter = metrics.counter("beat_heartbeat", "Celery beat heartbeat count")
    assert counter.values.get("", 0) == 2

    last = beat.get_last_heartbeat()
    assert last is not None
    assert abs(last - float(dummy.store["test:heartbeat"])) < 1e-6


def test_beat_healthcheck(monkeypatch):
    now = time.time()

    monkeypatch.setattr(beat_healthcheck, "get_last_heartbeat", lambda: now)
    assert beat_healthcheck.main() == 0

    monkeypatch.setattr(beat_healthcheck, "get_last_heartbeat", lambda: now - 20)
    monkeypatch.setenv("BEAT_MAX_LAG_SEC", "10")
    assert beat_healthcheck.main() == 1

    monkeypatch.delenv("BEAT_MAX_LAG_SEC", raising=False)
