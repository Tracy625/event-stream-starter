"""
CA Hunter (MVP): resolve contract addresses for recent symbol-only events.

Heuristics (v1.1):
- Extract candidate CAs from evidence URLs (etherscan/bscscan/...)
- Query DEX snapshot for LP; read pair_created_at if available
- Score = 0.6*time_proximity + 0.4*lp_gate (simple)
  - time_proximity: 1 at 0 min distance, 0 at >=90m
  - lp_gate: 1 if liquidity >= baseline (EVM 15k, SOL 8k), else 0
- Accept if top_score >= 0.6 and margin >= 0.15, otherwise log ambiguous

On accept: update events.token_ca (best-effort) and log.
No push side-effects in MVP; downstream jobs (goplus_scan, rules) consume.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import text as sa_text

from worker.app import app
from worker.jobs.push_cards import process_card as push_card_task
from api.database import with_db
from api.core.metrics_store import log_json
from api.core.metrics import ca_hunter_matched_total, ca_hunter_ambiguous_total
from api.providers.dex_provider import DexProvider


SCAN_WINDOW_MIN = 120
TIME_PROXIMITY_MAX_MIN = 90


def _iter_candidate_events(db) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=SCAN_WINDOW_MIN)
    rows = db.execute(sa_text(
        """
        SELECT event_key, summary, evidence, last_ts
          FROM events
         WHERE last_ts >= :cutoff
           AND (evidence IS NOT NULL)
           AND (summary IS NULL OR summary = '' OR summary IS NOT NULL)
        """
    ), {"cutoff": cutoff}).mappings().fetchall()
    out = []
    for r in rows:
        out.append({
            "event_key": r.get("event_key"),
            "evidence": r.get("evidence") or [],
            "last_ts": r.get("last_ts"),
        })
    return out


_HEX40 = re.compile(r"\b0x[a-fA-F0-9]{40}\b")


def _extract_candidates(ev_items: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """Return list of (chain, address) candidates from evidence list."""
    cands: List[Tuple[str, str]] = []
    for item in ev_items or []:
        ref = item.get("ref") or {}
        # URL-based
        url = ref.get("url") or ref.get("href")
        if isinstance(url, str):
            u = url.lower()
            if "etherscan.io/address/" in u:
                m = _HEX40.search(u)
                if m:
                    cands.append(("eth", m.group(0)))
            elif "bscscan.com/address/" in u:
                m = _HEX40.search(u)
                if m:
                    cands.append(("bsc", m.group(0)))
            elif "arbiscan.io/address/" in u:
                m = _HEX40.search(u)
                if m:
                    cands.append(("arb", m.group(0)))
            elif "basescan.org/address/" in u:
                m = _HEX40.search(u)
                if m:
                    cands.append(("base", m.group(0)))
            elif "optimistic.etherscan.io/address/" in u:
                m = _HEX40.search(u)
                if m:
                    cands.append(("op", m.group(0)))
        # Text-based (fallback)
        summary = item.get("summary") or ""
        if isinstance(summary, str):
            m = _HEX40.search(summary)
            if m:
                cands.append(("eth", m.group(0)))
    # Dedup
    uniq = []
    seen = set()
    for ch, ca in cands:
        key = f"{ch}:{ca.lower()}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append((ch, ca.lower()))
    return uniq


def _score_candidate(dp: DexProvider, chain: str, address: str, ev_ts: datetime) -> Tuple[float, Dict[str, Any]]:
    """Score candidate using LP and pair_created_at if available."""
    details: Dict[str, Any] = {}
    try:
        snap = dp.get_snapshot(chain, address)
        lp = (snap or {}).get("liquidity_usd") or 0
        created_at = (snap or {}).get("pair_created_at")  # epoch ms if present
        t_score = 0.0
        if isinstance(created_at, (int, float)):
            try:
                pair_dt = datetime.fromtimestamp(float(created_at) / 1000.0, tz=timezone.utc)
                minutes = abs((ev_ts - pair_dt).total_seconds()) / 60.0
                if minutes <= TIME_PROXIMITY_MAX_MIN:
                    t_score = max(0.0, 1.0 - (minutes / TIME_PROXIMITY_MAX_MIN))
            except Exception:
                t_score = 0.0
        # LP gate
        lp_gate = 0.0
        baseline = 15000.0 if chain != "sol" else 8000.0
        if lp is not None and lp >= baseline:
            lp_gate = 1.0
        score = 0.6 * t_score + 0.4 * lp_gate
        details.update({"lp": lp, "created_at": created_at, "t_score": t_score, "lp_gate": lp_gate})
        return score, details
    except Exception as e:
        details["error"] = str(e)
        return 0.0, details


def run_once(limit: int = 200) -> Dict[str, int]:
    stats = {"scanned": 0, "evaluated": 0, "assigned": 0, "ambiguous": 0, "errors": 0}
    dp = DexProvider()
    with with_db() as db:
        evs = _iter_candidate_events(db)
        stats["scanned"] = len(evs)
        for ev in evs[:limit]:
            try:
                ek = ev["event_key"]
                last_ts = ev.get("last_ts") or datetime.now(timezone.utc)
                evid = ev.get("evidence") or []
                cands = _extract_candidates(evid)
                if not cands:
                    continue
                stats["evaluated"] += 1
                scored: List[Tuple[Tuple[str,str], float, Dict[str,Any]]] = []
                for ch, ca in cands:
                    s, det = _score_candidate(dp, ch, ca, last_ts)
                    scored.append(((ch, ca), s, det))
                scored.sort(key=lambda x: x[1], reverse=True)
                top = scored[0]
                margin = top[1] - (scored[1][1] if len(scored) > 1 else 0.0)
                if top[1] >= 0.6 and margin >= 0.15:
                    # Accept and update events.token_ca (best-effort)
                    ch, ca = top[0]
                    try:
                        db.execute(sa_text("UPDATE events SET token_ca = :ca WHERE event_key = :ek"), {"ek": ek, "ca": ca})
                        stats["assigned"] += 1
                        log_json(stage="ca_hunter.match", event_key=ek, chain=ch, ca=ca, score=top[1], margin=margin, details=top[2])
                        try:
                            ca_hunter_matched_total.inc()
                        except Exception:
                            pass
                    except Exception as e:
                        stats["errors"] += 1
                        log_json(stage="ca_hunter.update_error", event_key=ek, error=str(e)[:200])
                else:
                    stats["ambiguous"] += 1
                    log_json(stage="ca_hunter.ambiguous", event_key=ek, top_score=top[1], margin=margin, candidates=len(scored))
                    try:
                        ca_hunter_ambiguous_total.inc()
                    except Exception:
                        pass
                    # Emit an ambiguous primary (degraded) card with top candidates for operator clarity
                    try:
                        # Build candidates payload (top 2-3)
                        cands_payload: List[Dict[str, Any]] = []
                        for (ch, ca), s, det in scored[:3]:
                            t_delta = None
                            created_at = det.get("created_at")
                            if isinstance(created_at, (int, float)):
                                try:
                                    t_delta = int(abs((last_ts - datetime.fromtimestamp(float(created_at)/1000.0, tz=timezone.utc)).total_seconds()) // 60)
                                except Exception:
                                    t_delta = None
                            cands_payload.append({
                                "chain": ch,
                                "ca": ca,
                                "pair_url": f"https://dexscreener.com/{ch}/{ca}",
                                "lp_usd": det.get("lp"),
                                "pair_created_at": det.get("created_at"),
                                "txns": (det.get("txns") or {}),
                                "score": round(s, 2),
                                "margin": round(margin, 2),
                                "evidence_strength": "medium",
                                "t_delta_min": t_delta,
                            })

                        signal = {
                            "type": "primary",
                            "risk_level": "yellow",
                            "is_degraded": True,
                            "event_key": ek,
                            "token_info": {
                                "symbol": "UNKNOWN",
                                "chain": scored[0][0][0] if scored else "eth",
                            },
                            "risk_note": "歧义：候选池待确认，暂不下可买结论",
                            "states": {"degrade": True},
                            "ambiguous_candidates": cands_payload,
                        }
                        # Determine channel
                        import os
                        channel_id = os.getenv("TELEGRAM_TOPIC_CHAT_ID") or os.getenv("TELEGRAM_SANDBOX_CHANNEL_ID") or os.getenv("TG_CHANNEL_ID")
                        if channel_id:
                            push_card_task.apply_async(args=[signal, str(channel_id)])
                    except Exception as e:
                        log_json(stage="ca_hunter.ambiguous_push_error", event_key=ek, error=str(e)[:200])
            except Exception as e:
                stats["errors"] += 1
                log_json(stage="ca_hunter.error", error=str(e)[:200])
    log_json(stage="ca_hunter.done", **stats)
    return stats


@app.task(name="ca_hunter.scan_5m")
def scan_task():
    return run_once()
