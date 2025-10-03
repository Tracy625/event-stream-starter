def test_metrics_core_export_contains_events_metrics():
    from api.core import metrics as mc

    # Touch counters/gauges/histograms
    mc.events_key_conflict_total.inc({"reason": "identity_mismatch"})
    mc.evidence_merge_ops_total.inc({"scope": "cross_source"})
    mc.evidence_dedup_total.inc({"source": "x"})
    mc.deadlock_retries_total.inc()
    mc.insert_conflict_fallback_total.inc()
    mc.evidence_compact_enqueue_total.inc()
    mc.events_upsert_tx_ms.observe(12)
    mc.evidence_completion_rate.set(0.9)

    text = mc.export_text()
    assert "events_key_conflict_total" in text
    assert "evidence_merge_ops_total" in text
    assert "evidence_dedup_total" in text
    assert "deadlock_retries_total" in text
    assert "insert_conflict_fallback_total" in text
    assert "evidence_compact_enqueue_total" in text
    assert "events_upsert_tx_ms_bucket" in text or "events_upsert_tx_ms_count" in text
    assert "evidence_completion_rate" in text
