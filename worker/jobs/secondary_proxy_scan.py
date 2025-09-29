"""
Secondary proxy scan task (v1.1):

Uses proxy indicators before buyers/median are available.
- Window: 30 or 60 minutes (ENV SECONDARY_PROXY_WINDOW)
- Conditions (configurable):
  • txns_window >= SECONDARY_PROXY_TXNS_MIN
  • lp_usd >= SECONDARY_PROXY_LP_MIN_USD_EVM/SOL
  • quote_volume_window >= SECONDARY_PROXY_VOL30_MIN_USD (optional)

On trigger: emit a 'secondary' card (degraded), with cooldown.
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from sqlalchemy import text as sa_text

from worker.app import app
from api.database import with_db
from api.core.metrics_store import log_json
from api.providers.dex_provider import DexProvider
from api.cache import get_redis_client
from worker.jobs.push_cards import process_card as push_card_task


def _cfg_bool(key: str, default: str = "true") -> bool:
    return os.getenv(key, default).lower() in ("1", "true", "yes", "on")


def run_once(limit: int = 200) -> Dict[str, int]:
    stats = {"scanned": 0, "evaluated": 0, "triggered": 0, "skipped": 0, "errors": 0}
    if not _cfg_bool("SECONDARY_PROXY_ENABLED", "true"):
        return stats

    window = int(os.getenv("SECONDARY_PROXY_WINDOW", "30"))
    txns_min = int(os.getenv("SECONDARY_PROXY_TXNS_MIN", "40"))
    lp_min_evm = float(os.getenv("SECONDARY_PROXY_LP_MIN_USD_EVM", "15000"))
    lp_min_sol = float(os.getenv("SECONDARY_PROXY_LP_MIN_USD_SOL", "8000"))
    vol_min = float(os.getenv("SECONDARY_PROXY_VOL30_MIN_USD", "20000"))
    cooldown = int(os.getenv("SECONDARY_PROXY_COOLDOWN_SEC", "3600"))

    rc = get_redis_client()
    dp = DexProvider()

    with with_db() as db:
        # Select recent events with CA (from ca_hunter or upstream) in the last 2h
        rows = db.execute(sa_text(
            """
            SELECT event_key, token_ca, last_ts
              FROM events
             WHERE token_ca IS NOT NULL
               AND last_ts >= (NOW() - INTERVAL '2 hours')
             ORDER BY last_ts DESC
             LIMIT :limit
            """
        ), {"limit": limit}).mappings().fetchall()
        stats["scanned"] = len(rows)

        for r in rows:
            try:
                ek = r["event_key"]
                ca = r["token_ca"]
                # Cooldown per event key
                if rc and not rc.set(f"secprx:cd:{ek}", "1", nx=True, ex=cooldown):
                    stats["skipped"] += 1
                    continue

                # Try common EVM chains first (heuristic); fallback: eth
                chains = ["eth", "bsc", "base", "arb", "op", "sol"]
                triggered = False
                for ch in chains:
                    try:
                        snap = dp.get_snapshot(ch, ca)
                        if not snap:
                            continue
                        lp = (snap or {}).get("liquidity_usd") or 0.0
                        txns = (snap or {}).get("txns", {}) or {}
                        # Approximate window txns using h1 or h24 when window data unavailable
                        txns_window = int(txns.get("h1", {}).get("buys", 0) + txns.get("h1", {}).get("sells", 0)) if window == 60 else int(txns.get("h1", {}).get("buys", 0) + txns.get("h1", {}).get("sells", 0))
                        vol_window = float((snap or {}).get("volume_24h", 0)) * (window / 1440.0)

                        lp_min = lp_min_sol if ch == "sol" else lp_min_evm
                        conds = [txns_window >= txns_min, lp >= lp_min]
                        if os.getenv("SECONDARY_PROXY_VOL30_MIN_USD") is not None:
                            conds.append(vol_window >= vol_min)

                        if all(conds):
                            # Emit secondary card
                            signal = {
                                "type": "secondary",
                                "risk_level": "yellow",
                                "event_key": ek,
                                "token_info": {"symbol": "UNKNOWN", "chain": ch},
                                "states": {"degrade": True},
                                "risk_note": f"代理触发：{window}m txns≥{txns_min}, LP≥{int(lp_min)}",
                            }
                            channel_id = os.getenv("TELEGRAM_TOPIC_CHAT_ID") or os.getenv("TELEGRAM_SANDBOX_CHANNEL_ID") or os.getenv("TG_CHANNEL_ID")
                            if channel_id:
                                push_card_task.apply_async(args=[signal, str(channel_id)])
                                stats["triggered"] += 1
                                triggered = True
                                log_json(stage="secondary.proxy.trigger", event_key=ek, chain=ch, lp=lp, txns=txns_window)
                                break
                    except Exception:
                        continue
                if not triggered:
                    stats["skipped"] += 1
            except Exception as e:
                stats["errors"] += 1
                log_json(stage="secondary.proxy.error", error=str(e)[:200])

    log_json(stage="secondary.proxy.done", **stats)
    return stats


@app.task(name="secondary.proxy_scan_5m")
def scan_task():
    return run_once()

