def test_healthz_ok():
    from api.routes.health import healthz

    resp = healthz()
    assert isinstance(resp, dict)
    assert resp.get("status") == "healthy"


def test_readyz_db_fail(monkeypatch):
    import types

    import api.routes.health as h

    def bad_with_db():
        class _Ctx:
            def __enter__(self):
                raise RuntimeError("db down")

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Ctx()

    monkeypatch.setattr(h, "with_db", bad_with_db)
    resp = h.readyz()
    # Should be a Response with 503
    from starlette.responses import Response

    assert isinstance(resp, Response)
    assert resp.status_code == 503


def test_readyz_redis_fail(monkeypatch):
    import api.routes.health as h

    class BadRedis:
        def ping(self):
            raise RuntimeError("redis down")

    # Stub DB to succeed
    class GoodCtx:
        def __enter__(self):
            class _DB:
                def execute(self, *a, **k):
                    class _R:
                        def scalar(self_inner):
                            return 1

                    return _R()

            return _DB()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(h, "with_db", lambda: GoodCtx())
    monkeypatch.setattr(h, "get_redis_client", lambda: BadRedis())

    resp = h.readyz()
    from starlette.responses import Response

    assert isinstance(resp, Response)
    assert resp.status_code == 503
