import os
import sys
import types
from datetime import datetime, timezone, timedelta


def _make_candidate(event_key: str, state: str = "candidate"):
    class C:
        pass
    c = C()
    c.event_key = event_key
    c.state = state
    c.time_col = datetime.now(timezone.utc) - timedelta(minutes=10)
    return c


class FakeRedis:
    def __init__(self, preset=None):
        self.store = dict(preset or {})
    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True
    def eval(self, lua, nkeys, key, token):
        cur = self.store.get(key)
        if cur == token:
            del self.store[key]
            return 1
        return 0
    def get(self, key):
        return self.store.get(key)


class FakeDB:
    def __init__(self, update_rowcount=1):
        self.update_rowcount = update_rowcount
        self.committed = False
        self.rolled_back = False
    def execute(self, stmt, params=None):
        class R:
            def __init__(self, rc=None):
                self.rowcount = rc if rc is not None else 1
            def fetchall(self):
                return []
            def scalar(self):
                return 1
        sql = str(stmt)
        if "UPDATE signals" in sql:
            return R(self.update_rowcount)
        return R()
    def commit(self):
        self.committed = True
    def rollback(self):
        self.rolled_back = True


def test_lock_acquire_fail_skips(monkeypatch):
    # Stub google cloud bigquery dependency
    # Stub BQ provider module to avoid importing google cloud
    stub_bq = types.ModuleType("api.providers.onchain.bq_provider")
    class _BQ:
        pass
    stub_bq.BQProvider = _BQ
    sys.modules.setdefault("api.providers.onchain.bq_provider", stub_bq)

    import worker.jobs.onchain.verify_signal as vs

    # Environment
    monkeypatch.setenv("ONCHAIN_LOCK_TTL_SEC", "60")
    monkeypatch.setenv("ONCHAIN_LOCK_MAX_RETRY", "0")
    monkeypatch.setenv("ONCHAIN_VERIFICATION_DELAY_SEC", "0")

    # Fake redis with pre-set key to force NX fail
    from worker.jobs.onchain.verify_signal import _lock_key
    fr = FakeRedis(preset={_lock_key("eth:0xabc"): "busy"})
    monkeypatch.setattr(vs, "get_redis_client", lambda: fr)

    # Bypass BQ and rules
    monkeypatch.setattr(vs, "fetch_onchain_features", lambda *a, **k: {"active_addr_pctl": 0.9, "growth_ratio": 2.0, "top10_share": 0.1, "self_loop_ratio": 0.01, "asof_ts": datetime.now(timezone.utc).isoformat()})
    class V: decision = "hold"; confidence = 0.5; note=None
    monkeypatch.setattr(vs, "evaluate", lambda *a, **k: V())

    db = FakeDB()
    cand = _make_candidate("eth:0xabc")
    res = vs.process_candidate(db, cand, rules=None, redis_client=fr)
    assert res == "skipped"


def test_release_mismatch(monkeypatch):
    stub_bq = types.ModuleType("api.providers.onchain.bq_provider")
    class _BQ:
        pass
    stub_bq.BQProvider = _BQ
    sys.modules.setdefault("api.providers.onchain.bq_provider", stub_bq)

    import worker.jobs.onchain.verify_signal as vs
    fr = FakeRedis(preset={vs._lock_key("eth:0xabc"): "other"})
    status = vs.release_lock(fr, "eth:0xabc", token="mine")
    assert status in ("mismatch", "expired")


def test_cas_conflict(monkeypatch):
    stub_bq = types.ModuleType("api.providers.onchain.bq_provider")
    class _BQ:
        pass
    stub_bq.BQProvider = _BQ
    sys.modules.setdefault("api.providers.onchain.bq_provider", stub_bq)

    import worker.jobs.onchain.verify_signal as vs
    fr = FakeRedis()  # will acquire
    monkeypatch.setattr(vs, "get_redis_client", lambda: fr)
    monkeypatch.setenv("ONCHAIN_LOCK_MAX_RETRY", "0")
    monkeypatch.setenv("ONCHAIN_VERIFICATION_DELAY_SEC", "0")

    # Features and rules
    monkeypatch.setattr(vs, "fetch_onchain_features", lambda *a, **k: {"active_addr_pctl": 0.9, "growth_ratio": 2.0, "top10_share": 0.1, "self_loop_ratio": 0.01, "asof_ts": datetime.now(timezone.utc).isoformat()})
    class V: decision = "upgrade"; confidence = 0.8; note=None
    monkeypatch.setattr(vs, "evaluate", lambda *a, **k: V())

    # DB that returns rowcount=0 on UPDATE (CAS miss)
    db = FakeDB(update_rowcount=0)
    cand = _make_candidate("eth:0xabc")
    res = vs.process_candidate(db, cand, rules=None, redis_client=fr)
    assert res == "skipped"
