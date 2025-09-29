"""
Lightweight compaction job: raw_posts -> events (every 5 minutes)

Aggregates recent X posts (24h) by symbol/chain and upserts into events
via api.events.upsert_event().

Rules:
- Only process rows with is_candidate=true and (symbol or token_ca present)
- Detect chain from URLs if possible; if chain cannot be determined,
  set chain_id=None (we avoid chain-specific heat backfill later)
- Use EVENT_KEY_VERSION=v2 during this job to include chain dimension
"""

import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import text as sa_text

from worker.app import app
from api.database import with_db
from api.core.metrics_store import log_json


def _detect_chain_from_urls(urls: List[str], text: str = "") -> Optional[str]:
    """Best-effort chain detection from URLs or text clues.

    Returns canonical chain key: eth|bsc|base|arb|op|sol; None if unknown.
    """
    try:
        joined = " ".join((urls or [])) + " " + (text or "")
        j = joined.lower()
        # EVM scans
        if "etherscan.io" in j and "optimistic.etherscan.io" not in j:
            return "eth"
        if "bscscan.com" in j:
            return "bsc"
        if "arbiscan.io" in j:
            return "arb"
        if "optimistic.etherscan.io" in j or ":op:" in j:
            return "op"
        if "basescan.org" in j:
            return "base"
        # Solana
        if "solscan.io" in j or "solana.fm" in j or "solana.com" in j:
            return "sol"
    except Exception:
        pass
    return None


def _build_x_evidence(urls_field: Any, author: Optional[str], text: Optional[str], ts: datetime) -> Dict[str, Any]:
    """Build minimal x_data evidence payload for events.upsert_event()"""
    tweet_id = None
    urls: List[str] = []
    try:
        if isinstance(urls_field, dict):
            tweet_id = urls_field.get("tweet_id")
            raw_urls = urls_field.get("urls") or []
            if isinstance(raw_urls, list):
                urls = [str(u) for u in raw_urls if u]
        elif isinstance(urls_field, list):
            urls = [str(u) for u in urls_field if u]
    except Exception:
        pass
    ev = {"ts": ts.isoformat().replace("+00:00", "Z")}
    if author:
        ev["author"] = author
    if urls:
        u = urls[0]
        ev["url"] = u
        # evidence strength grading
        ul = (u or "").lower()
        if any(x in ul for x in ("etherscan.io", "bscscan.com", "arbiscan.io", "optimistic.etherscan.io", "basescan.org", "solscan.io")):
            ev["strength"] = "strong"
        elif any(x in ul for x in ("dexscreener.com", "geckoterminal.com")):
            ev["strength"] = "medium"
        else:
            ev["strength"] = "weak"
    if tweet_id:
        ev["tweet_id"] = tweet_id
    if text:
        ev["text"] = text[:180]
    return ev


def _with_event_key_v2():
    """Context manager to temporarily set EVENT_KEY_VERSION=v2 for this job."""
    class _Ctx:
        def __enter__(self):
            self.prev = os.environ.get("EVENT_KEY_VERSION")
            os.environ["EVENT_KEY_VERSION"] = "v2"
        def __exit__(self, exc_type, exc, tb):
            if self.prev is None:
                os.environ.pop("EVENT_KEY_VERSION", None)
            else:
                os.environ["EVENT_KEY_VERSION"] = self.prev
    return _Ctx()


def run_once(limit: int = 1000) -> Dict[str, int]:
    """Process recent raw_posts and upsert into events."""
    stats = {"scanned": 0, "upserted": 0, "skipped": 0, "errors": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    with with_db() as db, _with_event_key_v2():
        # Fetch candidates from raw_posts
        rows = db.execute(sa_text(
            """
            SELECT id, author, text, ts, urls, token_ca, symbol
              FROM raw_posts
             WHERE source = 'x'
               AND (is_candidate IS TRUE OR token_ca IS NOT NULL OR symbol IS NOT NULL)
               AND ts >= :cutoff
             ORDER BY ts DESC
             LIMIT :limit
            """
        ), {"cutoff": cutoff, "limit": limit}).mappings().fetchall()

        stats["scanned"] = len(rows)

        for r in rows:
            try:
                symbol = r.get("symbol")
                token_ca = r.get("token_ca")
                if not symbol and not token_ca:
                    stats["skipped"] += 1
                    continue

                # Extract URLs list for chain detection
                urls_field = r.get("urls")
                urls_list: List[str] = []
                if isinstance(urls_field, dict):
                    urls_list = [str(u) for u in (urls_field.get("urls") or []) if u]
                elif isinstance(urls_field, list):
                    urls_list = [str(u) for u in urls_field if u]

                chain = _detect_chain_from_urls(urls_list, r.get("text") or "")

                # Build post payload for upsert
                post: Dict[str, Any] = {
                    "type": "x",
                    "symbol": symbol,
                    "token_ca": token_ca,
                    "text": r.get("text") or "",
                    "created_ts": r.get("ts") or datetime.now(timezone.utc),
                }
                if chain:
                    post["chain_id"] = chain  # v2 identity uses this dimension

                x_data = _build_x_evidence(urls_field, r.get("author"), r.get("text"), r.get("ts"))

                # Use high-level API to insert/merge
                try:
                    from api.events import upsert_event as upsert
                    res = upsert(post, x_data=x_data)
                    stats["upserted"] += 1
                    log_json(stage="events.compact.upsert", event_key=res.get("event_key"), chain=chain, symbol=symbol, has_ca=bool(token_ca))
                except Exception as e:
                    stats["errors"] += 1
                    log_json(stage="events.compact.error", error=str(e)[:200])
            except Exception as e:
                stats["errors"] += 1
                log_json(stage="events.compact.row_error", error=str(e)[:200])

    log_json(stage="events.compact.done", **stats)
    return stats


@app.task(name="events.compact_5m")
def compact_task():
    return run_once()
