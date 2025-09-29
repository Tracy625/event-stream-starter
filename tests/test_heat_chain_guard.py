def test_heat_persist_symbol_fallback_disabled(monkeypatch):
    """Ensure heat persist does not fallback to symbol when chain is unknown and fallback is disabled."""
    from api.signals.heat import persist_heat

    class DummyDB:
        def execute(self, *args, **kwargs):
            class R:
                def fetchone(self_inner):
                    return None
            return R()

    # Disable symbol fallback explicitly
    monkeypatch.setenv("HEAT_ALLOW_SYMBOL_FALLBACK", "false")
    # Enable persist path
    monkeypatch.setenv("HEAT_ENABLE_PERSIST", "true")

    db = DummyDB()
    # token has symbol but no CA; expect False due to disabled fallback
    ok = persist_heat(db, token="PEPE", token_ca=None, heat={"cnt_10m": 1, "cnt_30m": 2}, upsert=True, strict_match=False)
    assert ok is False

