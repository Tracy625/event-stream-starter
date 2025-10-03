"""
Event aggregation module for D5.

Provides event key generation and upsert operations for event aggregation.
"""

import hashlib
import json
import os
import random
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import MetaData, Table, create_engine, func
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.core.metrics import (deadlock_retries_total,
                              events_key_conflict_total, events_upsert_tx_ms,
                              evidence_completion_rate, evidence_dedup_total,
                              evidence_merge_ops_total,
                              insert_conflict_fallback_total)
from api.core.metrics_store import log_json, timeit

# Track if salt change warning has been shown
_salt_warning_shown = False


_events_tbl_cache = None
_columns_filter_warned = False
_unique_index_checked = False

# Optional high-performance JSON
try:  # pragma: no cover - optional
    import orjson as _orjson  # type: ignore
except Exception:  # pragma: no cover - optional
    _orjson = None


def _events_table(engine):
    """Reflect the events table and cache the Table object."""
    global _events_tbl_cache
    if _events_tbl_cache is not None:
        return _events_tbl_cache
    md = MetaData()
    _events_tbl_cache = Table("events", md, autoload_with=engine)
    return _events_tbl_cache


def _get_db_connection():
    """Get database connection from environment at call time."""
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        raise ValueError("POSTGRES_URL environment variable not set")
    # Ensure READ COMMITTED to avoid stale snapshots with concurrent upserts
    engine = create_engine(
        postgres_url,
        echo=False,
        future=True,
        isolation_level=os.getenv("DB_ISOLATION_LEVEL", "READ COMMITTED"),
    )
    return engine.connect()


def _check_event_key_unique(conn) -> None:
    """One-time check that events.event_key has UNIQUE/PRIMARY constraint (Postgres).

    Logs a warning metric if missing. Does not raise.
    """
    global _unique_index_checked
    if _unique_index_checked:
        return
    try:
        # Only attempt on Postgres urls
        url = os.getenv("POSTGRES_URL", "")
        if not url or "postgres" not in url:
            _unique_index_checked = True
            return
        sql = sa_text(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
            WHERE t.relname = 'events'
              AND c.contype IN ('p','u')
              AND a.attname = 'event_key'
            LIMIT 1
            """
        )
        row = conn.execute(sql).fetchone()
        if not row:
            log_json(
                stage="events.unique_index_missing",
                table="events",
                column="event_key",
                message="events.event_key lacks UNIQUE/PK; insert-conflict fallback will not work",
            )
        _unique_index_checked = True
    except Exception:
        # Silent best-effort
        _unique_index_checked = True


def _jitter_sleep(base_min_ms: int, base_max_ms: int, attempt: int) -> None:
    """Sleep with exponential backoff and jitter for lock retries."""
    # Attempt grows the window exponentially
    scale = 2**attempt
    low = base_min_ms * scale
    high = base_max_ms * scale
    delay_ms = random.randint(low, high)
    time.sleep(delay_ms / 1000.0)


def _normalize_url(url: Optional[str]) -> Optional[str]:
    """
    Normalize URL for deduplication:
    - Lowercase scheme/host; http/https treated as equivalent (normalize to https)
    - Convert IDN host to punycode
    - Remove fragment; collapse trailing slash
    - Remove common tracking params (utm_*, ref, ref_src)
    - Sort remaining query params for stability
    """
    if not url or not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        scheme = (
            "https" if parts.scheme in ("http", "https", "") else parts.scheme.lower()
        )
        host = parts.hostname or ""
        try:
            host_puny = host.encode("idna").decode("ascii") if host else host
        except Exception:
            host_puny = host.lower()
        # Normalize port (drop default ports)
        port = parts.port
        netloc = host_puny
        if port and not (
            (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        ):
            netloc = f"{host_puny}:{port}"

        # Filter query params
        q = []
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            kl = (k or "").lower()
            if kl.startswith("utm_") or kl in ("ref", "ref_src"):
                continue
            q.append((kl, v))
        q.sort()
        query = urlencode(q, doseq=True)

        # Drop fragment
        fragment = ""
        # Normalize path: collapse trailing slash except root
        path = parts.path or "/"
        if path != "/":
            path = re.sub(r"/+$", "", path)

        normalized = urlunsplit((scheme, netloc, path, query, fragment))
        return normalized
    except Exception:
        return url


def _ts_bucket(ts: Any, bucket_sec: int) -> int:
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            ts = datetime.now(timezone.utc)
    if not hasattr(ts, "timestamp"):
        ts = datetime.now(timezone.utc)
    epoch = int(ts.timestamp())
    return (epoch // bucket_sec) * bucket_sec


def _normalize_token_symbol(symbol: Optional[str]) -> str:
    """
    Normalize token symbol for event key generation.

    Args:
        symbol: Raw symbol from post

    Returns:
        Normalized symbol with $ prefix, lowercase
    """
    if not symbol:
        return ""

    # Remove whitespace and convert to lowercase
    clean = symbol.strip().lower()

    # Ensure $ prefix
    if not clean.startswith("$"):
        clean = "$" + clean

    return clean


def _extract_id_part(post: Dict[str, Any]) -> str:
    """
    Extract ID part for event key from post.

    Priority:
    1. token_ca if matches ^0x[0-9a-f]{40}$ (lowercase)
    2. normalized symbol with $ prefix
    3. "na" as fallback

    Args:
        post: Post dictionary with token_ca and/or symbol

    Returns:
        ID part for event key
    """
    # Check token_ca first
    token_ca = post.get("token_ca")
    if token_ca and isinstance(token_ca, str):
        # Convert to lowercase and check pattern
        token_ca_lower = token_ca.lower()
        if re.match(r"^0x[0-9a-f]{40}$", token_ca_lower):
            return token_ca_lower

    # Check symbol second
    symbol = post.get("symbol")
    if symbol:
        normalized = _normalize_token_symbol(symbol)
        if normalized:
            return normalized

    # Fallback
    return "na"


def _extract_topic_keywords(post: Dict[str, Any], topk: int) -> List[str]:
    """
    Extract and normalize top-K keywords for topic hash.

    Priority: $token symbols, then 2-3 char words.

    Args:
        post: Post dictionary with keywords field
        topk: Number of top keywords to extract

    Returns:
        List of normalized, deduplicated, sorted keywords
    """
    keywords = post.get("keywords", [])
    if not keywords:
        return []

    # Normalize: lowercase, deduplicate
    normalized = []
    seen = set()

    # First pass: prioritize $token symbols
    for kw in keywords:
        if not kw:
            continue
        kw_lower = kw.lower().strip()

        # Check if it's a token symbol
        if kw_lower.startswith("$") and kw_lower not in seen:
            normalized.append(kw_lower)
            seen.add(kw_lower)
            if len(normalized) >= topk:
                break

    # Second pass: add 2-3 char words if needed
    if len(normalized) < topk:
        for kw in keywords:
            if not kw:
                continue
            kw_lower = kw.lower().strip()

            # Skip if already added or is a token
            if kw_lower in seen or kw_lower.startswith("$"):
                continue

            # Check length (2-3 chars preferred for short keywords)
            if 2 <= len(kw_lower) <= 3:
                normalized.append(kw_lower)
                seen.add(kw_lower)
                if len(normalized) >= topk:
                    break

    # Third pass: add any remaining keywords if still under topk
    if len(normalized) < topk:
        for kw in keywords:
            if not kw:
                continue
            kw_lower = kw.lower().strip()

            if kw_lower not in seen:
                normalized.append(kw_lower)
                seen.add(kw_lower)
                if len(normalized) >= topk:
                    break

    # Sort for deterministic output
    return sorted(normalized[:topk])


def _compute_topic_hash(keywords: List[str], algo: str) -> str:
    """
    Compute topic hash from normalized keywords.

    Args:
        keywords: List of normalized keywords
        algo: Hash algorithm (blake2s, sha256, etc)

    Returns:
        First 12 hex characters of hash
    """
    if not keywords:
        # Hash "none" if no keywords
        content = "none"
    else:
        # Join keywords with '||' separator
        content = "||".join(keywords)

    # Select hash algorithm
    if algo == "blake2s":
        h = hashlib.blake2s(content.encode()).hexdigest()
    elif algo == "sha256":
        h = hashlib.sha256(content.encode()).hexdigest()
    else:
        # Default to blake2s
        h = hashlib.blake2s(content.encode()).hexdigest()

    # Return first 12 hex characters
    return h[:12]


def _compute_candidate_score(
    post: Dict[str, Any], alpha: float = 0.6, beta: float = 0.4
) -> float:
    """
    Compute candidate score from sentiment and keyword hits.

    Formula: α * sentiment_score + β * keyword_hits_normalized

    Args:
        post: Post dictionary with sentiment_score and keywords
        alpha: Weight for sentiment score (default 0.6)
        beta: Weight for keyword hits (default 0.4)

    Returns:
        Candidate score in range [0, 1]
    """
    # Get sentiment score (already in [-1, 1], normalize to [0, 1])
    sentiment_score = post.get("sentiment_score", 0.0)
    if sentiment_score is None:
        sentiment_score = 0.0

    # Normalize sentiment from [-1, 1] to [0, 1]
    sentiment_norm = (sentiment_score + 1.0) / 2.0

    # Count keyword hits (normalize by capping at 5)
    keywords = post.get("keywords", [])
    keyword_hits = len(keywords) if keywords else 0
    keyword_norm = min(keyword_hits / 5.0, 1.0)

    # Compute weighted score
    score = alpha * sentiment_norm + beta * keyword_norm

    # Clamp to [0, 1]
    return max(0.0, min(1.0, score))


def _normalize_text(text: str) -> str:
    """
    Normalize text for event key generation.

    Order: Unicode NFC → Remove URLs/@handles → Collapse spaces
    Preserves #hashtags
    """
    if not text:
        return ""

    # Lowercase
    text = text.lower()

    # Unicode NFC normalization (first)
    text = unicodedata.normalize("NFC", text)

    # Remove URLs (http/https/bare domains with punctuation)
    text = re.sub(r"https?://[^\s]+", "", text)
    text = re.sub(r"www\.[^\s]+", "", text)
    text = re.sub(
        r"\b[a-zA-Z0-9][a-zA-Z0-9-]*\.(com|org|net|io|xyz|co|app|tech|ai|dev|finance|eth)[\s,\.!?;:]",
        " ",
        text,
    )

    # Remove @handles (but preserve #hashtags)
    text = re.sub(r"@\w+", "", text)

    # Collapse multiple spaces (last)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


@timeit("events.make_key")
def make_event_key(post: Dict[str, Any]) -> str:
    """
    Generate deterministic event key from post.

    Pure function that only depends on input and EVENT_KEY_SALT.
    Format: sha256(type|symbol|token_ca|text_norm|bucket|salt)

    Args:
        post: Post dictionary with required fields:
            - type: Event type (required)
            - token_ca: Optional contract address
            - symbol: Optional token symbol
            - text: Optional text content
            - created_ts: Post timestamp (datetime)

    Returns:
        Event key string (40 hex chars)
    """
    # Read environment variables
    salt = os.getenv("EVENT_KEY_SALT", "v1")
    bucket_sec = int(os.getenv("EVENT_TIME_BUCKET_SEC", "600"))
    key_version = os.getenv("EVENT_KEY_VERSION", "v1").strip() or "v1"

    # Check for salt change warning (only log once)
    global _salt_warning_shown
    default_salt = "v1"
    if salt != default_salt and not _salt_warning_shown:
        log_json(
            stage="pipeline.event.key",
            event="salt_changed",
            current_salt=salt,
            default_salt=default_salt,
        )
        _salt_warning_shown = True

    # Extract required fields (fail if missing critical fields)
    event_type = post.get("type")
    if not event_type:
        raise ValueError("Event type is required for key generation")

    # Normalize components
    type_norm = (event_type or "").lower()

    # Token CA: lowercase, validate 0x prefix and hex chars
    token_ca = post.get("token_ca", "")
    token_ca_norm = ""
    if token_ca:
        token_ca_lower = str(token_ca).lower()
        if not token_ca_lower.startswith("0x"):
            log_json(
                stage="pipeline.event.key",
                event="token_ca_warning",
                message="Token CA missing 0x prefix",
                token_ca=token_ca,
            )
        elif not re.match(r"^0x[0-9a-f]{40}$", token_ca_lower):
            log_json(
                stage="pipeline.event.key",
                event="token_ca_warning",
                message="Token CA format invalid",
                token_ca=token_ca,
            )
        token_ca_norm = token_ca_lower

    # Symbol normalized consistently with storage path (with $ and lowercase)
    symbol_norm = _normalize_token_symbol(post.get("symbol"))
    chain_id = post.get("chain_id") or "na"

    # Text normalization
    text = post.get("text", "")
    text_norm = _normalize_text(text)

    # Calculate time bucket
    created_ts = post.get("created_ts")
    if not created_ts:
        created_ts = datetime.now(timezone.utc)
    elif isinstance(created_ts, str):
        created_ts = datetime.fromisoformat(created_ts.replace("Z", "+00:00"))

    # Convert to timestamp and bucket
    ts_epoch = int(created_ts.timestamp())
    bucket = (ts_epoch // bucket_sec) * bucket_sec

    if key_version == "v1":
        # Legacy v1 behavior (compat): sha256(type|symbol|token_ca|text_norm|bucket|salt) → 40 hex
        preimage = f"{type_norm}|{symbol_norm.upper() if symbol_norm else ''}|{token_ca_norm}|{text_norm}|{bucket}|{salt}"
        hash_full = hashlib.sha256(preimage.encode()).hexdigest()
        event_key = hash_full[:40]
    else:
        # v2: identity prefers token_ca else (symbol_norm|chain); include topic_hash and text signature
        identity = token_ca_norm or f"{symbol_norm}|{chain_id}"
        topic_hash = post.get("topic_hash") or ""
        # lightweight text signature (n-gram blake2s)
        text_sig = hashlib.blake2s(text_norm.encode("utf-8")).hexdigest()[:16]
        preimage = f"v2|{type_norm}|{identity}|{topic_hash}|{bucket}|{text_sig}"
        # blake2s keyed with salt for stability and salt rotation
        h = hashlib.blake2s(
            preimage.encode("utf-8"), key=str(salt).encode("utf-8")
        ).hexdigest()
        event_key = h[:40]

    # Log the key generation
    log_json(
        stage="pipeline.event.key",
        event_key=event_key,
        type=type_norm,
        symbol=symbol_norm,
        token_ca=token_ca_norm,
        bucket=bucket,
        salt=salt,
        key_version=key_version,
    )

    return event_key


def _make_evidence_dedup_key(evidence: Dict[str, Any]) -> str:
    """
    Generate a stable deduplication key per source with source-specific rules.

    Rules:
      - x: prefer tweet_id; else normalized url
      - dex: prefer tx; else (chain_id,pool,ts_bucket)
      - goplus: (goplus_endpoint|endpoint, chain_id, address)
      - default: sha1(source + sorted stable ref fields)
    """
    source = (evidence.get("source") or "").lower()
    ref = evidence.get("ref", {}) or {}
    ts = evidence.get("ts")
    bucket_sec = int(os.getenv("EVENT_TIME_BUCKET_SEC", "600"))

    if source == "x":
        tid = ref.get("tweet_id")
        if tid:
            return f"x:{tid}"
        url = _normalize_url(ref.get("url"))
        if url:
            # Try extract tweet id from canonical URL: /status/<id>(...)
            m = re.search(r"/status(?:es)?/(\d+)", url)
            if m:
                return f"x:{m.group(1)}"
            return f"x:{url}"
    elif source == "dex":
        tx = ref.get("tx")
        if tx:
            return f"dex:{tx}"
        chain_id = ref.get("chain_id", "na")
        pool = ref.get("pool", "na")
        tb = _ts_bucket(ts or datetime.now(timezone.utc), bucket_sec)
        return f"dex:{chain_id}:{pool}:{tb}"
    elif source == "goplus":
        endpoint = ref.get("goplus_endpoint") or ref.get("endpoint") or "na"
        chain_id = ref.get("chain_id", "na")
        address = ref.get("address", "na")
        return f"gp:{endpoint}|{chain_id}|{address}"

    # Default: stable dump of ref with normalized URLs where possible
    ref_norm = {}
    for k, v in ref.items():
        if k.lower() == "url":
            ref_norm[k] = _normalize_url(v)
        else:
            ref_norm[k] = v
    if _orjson is not None:
        try:
            ref_sorted = _orjson.dumps(ref_norm, option=_orjson.OPT_SORT_KEYS).decode()
        except Exception:
            ref_sorted = json.dumps(ref_norm, sort_keys=True, separators=(",", ":"))
    else:
        ref_sorted = json.dumps(ref_norm, sort_keys=True, separators=(",", ":"))
    content = f"{source}|{ref_sorted}"
    return hashlib.sha1(content.encode()).hexdigest()


def _build_evidence_item(
    source: str,
    ts: datetime,
    ref: Dict[str, Any],
    summary: Optional[str] = None,
    weight: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Build a standardized evidence item.

    Schema:
    {
        "source": "x|dex|goplus",
        "ts": "2025-09-10T08:22:11Z",
        "ref": {tweet_id, url, chain_id, pool, tx, goplus_endpoint, key},
        "summary": str|None,
        "weight": float|None
    }
    """
    evidence = {
        "source": source,
        "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
        "ref": ref,
    }

    if summary is not None:
        evidence["summary"] = summary
    if weight is not None:
        evidence["weight"] = weight

    return evidence


def merge_event_by_key(
    event_key: str, payload: Dict[str, Any], strict: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Dry-run merge for event by key (no DB writes).

    Args:
        event_key: Event key to merge into
        payload: New data to merge
        strict: Whether to enforce strict mode (from ENV if not provided)

    Returns:
        Dictionary with:
            - would_change: Whether merge would change the event
            - delta_count: Number of new evidence items
            - sources_candidate: Set of unique sources that would be merged
    """
    if strict is None:
        # Parse EVENT_MERGE_STRICT as boolean (case insensitive)
        strict_env = os.getenv("EVENT_MERGE_STRICT", "true").lower()
        strict = strict_env in ("true", "1", "yes", "on")

    # Extract sources from payload
    sources_candidate = set()
    if "source" in payload:
        sources_candidate.add(payload["source"])
    if "sources" in payload and isinstance(payload["sources"], list):
        sources_candidate.update(payload["sources"])

    # Count evidence items
    delta_evidence_count = 0
    if "evidence" in payload:
        if isinstance(payload["evidence"], list):
            delta_evidence_count = len(payload["evidence"])
        elif isinstance(payload["evidence"], dict):
            delta_evidence_count = 1

    # Determine if changes would occur (simplified for dry-run)
    would_change = delta_evidence_count > 0 or len(sources_candidate) > 0

    # Log the merge attempt
    log_json(
        stage="pipeline.event.merge",
        event_key=event_key,
        strict=strict,
        sources_candidate=list(sources_candidate),
        delta_evidence_count=delta_evidence_count,
        dry_run=True,
        would_change=would_change,
    )

    return {
        "would_change": would_change,
        "delta_count": delta_evidence_count,
        "sources_candidate": list(
            sources_candidate
        ),  # Convert set to list for consistent output
    }


def merge_event_evidence(
    event_key: str,
    new_evidence: List[Dict[str, Any]],
    existing_evidence: Optional[List[Dict[str, Any]]] = None,
    current_source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Merge and deduplicate evidence for an event.

    Args:
        event_key: Event key
        new_evidence: New evidence items to merge
        existing_evidence: Existing evidence from DB
        current_source: Current source to filter on when strict=false

    Returns:
        Dictionary with:
            - merged_evidence: Deduplicated merged evidence list
            - before_count: Count before merge
            - after_count: Count after merge
            - deduped: Number of duplicates removed
    """
    # Parse strict mode
    strict_env = os.getenv("EVENT_MERGE_STRICT", "true").lower()
    strict = strict_env in ("true", "1", "yes", "on")

    existing = existing_evidence or []
    before_count = len(existing)

    # Determine current source if not provided
    if not current_source and new_evidence:
        sources_in_new = set(e.get("source") for e in new_evidence if e.get("source"))
        if len(sources_in_new) == 1:
            current_source = sources_in_new.pop()

    merge_scope = "cross_source" if strict else "single_source"

    def _norm_all(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for it in items or []:
            it2 = dict(it)
            ref = dict(it2.get("ref", {}) or {})
            # Normalize URL fields if present
            if "url" in ref:
                ref["url"] = _normalize_url(ref.get("url"))
            it2["ref"] = ref
            out.append(it2)
        return out

    def _merge_fields(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
        # Merge refs (union of keys; prefer non-empty)
        ref_a = dict(a.get("ref", {}) or {})
        ref_b = dict(b.get("ref", {}) or {})
        ref_m = dict(ref_a)
        for k, v in ref_b.items():
            if ref_m.get(k) in (None, "") and v not in (None, ""):
                ref_m[k] = v
        # Merge ts: keep earliest
        ts_a = a.get("ts")
        ts_b = b.get("ts")
        ts_keep = ts_a
        try:
            da = (
                datetime.fromisoformat(ts_a.replace("Z", "+00:00"))
                if isinstance(ts_a, str)
                else ts_a
            )
            db = (
                datetime.fromisoformat(ts_b.replace("Z", "+00:00"))
                if isinstance(ts_b, str)
                else ts_b
            )
            if hasattr(da, "timestamp") and hasattr(db, "timestamp"):
                ts_keep = da if da <= db else db
        except Exception:
            ts_keep = ts_a or ts_b
        # Merge weight and summary
        wa = a.get("weight")
        wb = b.get("weight")
        weight = None
        try:
            weight = max(w for w in [wa, wb] if isinstance(w, (int, float)))
        except ValueError:
            weight = wa or wb
        sa = a.get("summary") or ""
        sb = b.get("summary") or ""
        summary = sa if len(sa) >= len(sb) else sb
        merged = dict(a)
        merged["ref"] = ref_m
        if ts_keep is not None:
            # Ensure JSON-serializable timestamp in evidence
            try:
                if hasattr(ts_keep, "isoformat"):
                    # Normalize to Z suffix for UTC when applicable
                    ts_str = ts_keep.isoformat()
                    if ts_str.endswith("+00:00"):
                        ts_str = ts_str.replace("+00:00", "Z")
                    merged["ts"] = ts_str
                elif isinstance(ts_keep, str):
                    merged["ts"] = ts_keep
                else:
                    # Fallback to current UTC time in ISO string
                    merged["ts"] = (
                        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    )
            except Exception:
                merged["ts"] = (
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                )
        if weight is not None:
            merged["weight"] = weight
        if summary:
            merged["summary"] = summary
        return merged

    # Normalize inputs
    existing_n = _norm_all(existing)
    new_n = _norm_all(new_evidence)

    if not strict:
        # Loose mode: only keep evidence from current_source (still dedup within source)
        merged_map = {}
        for item in existing_n + new_n:
            if current_source and item.get("source") != current_source:
                continue
            k = _make_evidence_dedup_key(item)
            if k in merged_map:
                merged_map[k] = _merge_fields(merged_map[k], item)
            else:
                merged_map[k] = item
        merged = list(merged_map.values())
        after_count = len(merged)
        deduped = (before_count + len(new_n)) - after_count
    else:
        # Strict mode: dedup across sources with field completion
        merged_map = {}
        for item in existing_n:
            k = _make_evidence_dedup_key(item)
            merged_map[k] = item
        for item in new_n:
            k = _make_evidence_dedup_key(item)
            if k in merged_map:
                merged_map[k] = _merge_fields(merged_map[k], item)
            else:
                merged_map[k] = item
        merged = list(merged_map.values())
        after_count = len(merged)
        deduped = (before_count + len(new_n)) - after_count

    # Extract sources for logging
    sources = set()
    for item in merged:
        if "source" in item:
            sources.add(item["source"])

    # Metrics
    evidence_merge_ops_total.inc({"scope": merge_scope})
    for item in new_n:
        src = (item.get("source") or "").lower()
        evidence_dedup_total.inc({"source": src})

    # Completion rate (tweet_id+url if any present)
    comp_numer = 0
    comp_denom = 0
    for item in merged:
        if (item.get("source") or "").lower() == "x":
            r = item.get("ref", {}) or {}
            has_tid = bool(r.get("tweet_id"))
            has_url = bool(r.get("url"))
            if has_tid or has_url:
                comp_denom += 1
                if has_tid and has_url:
                    comp_numer += 1
    if comp_denom:
        evidence_completion_rate.set(comp_numer / comp_denom)

    # Log the merge
    log_json(
        stage="pipeline.event.evidence.merge",
        event_key=event_key,
        source=list(sources),
        before_count=before_count,
        after_count=after_count,
        deduped=deduped,
        strict=strict,
        merge_scope=merge_scope,
    )

    return {
        "merged_evidence": merged,
        "before_count": before_count,
        "after_count": after_count,
        "deduped": deduped,
    }


def upsert_event_with_evidence(
    *,
    event: Dict[str, Any],
    evidence: List[Dict[str, Any]],
    strict: Optional[bool] = None,
    current_source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    New entry point for upserting events with evidence.

    Args:
        event: Event data dictionary
        evidence: List of evidence items
        strict: Override strict mode (None = use ENV)
        current_source: Current source for single-source mode

    Returns:
        Dictionary with event_key, evidence_count, candidate_score
    """
    # Generate event key
    event_key = make_event_key(event)

    # TODO: Implement actual DB upsert with evidence merge
    # For now, just return mock result
    merge_result = merge_event_evidence(
        event_key=event_key,
        new_evidence=evidence,
        existing_evidence=[],
        current_source=current_source,
    )

    return {
        "event_key": event_key,
        "evidence_count": merge_result["after_count"],
        "candidate_score": 0.5,  # Mock score
    }


@timeit("events.upsert")
def upsert_event(
    post: Dict[str, Any],
    goplus_data: Optional[Dict[str, Any]] = None,
    dex_data: Optional[Dict[str, Any]] = None,
    x_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Backward-compatible upsert event function.

    Legacy signature maintained for compatibility. New code should use upsert_event_with_evidence.

    Args:
        post: Post dictionary with required fields
        goplus_data: Optional GoPlus security data
        dex_data: Optional DEX data
        x_data: Optional X/Twitter data

    Returns:
        Dictionary with event_key, evidence_count, candidate_score
    """
    # Generate event key
    event_key = make_event_key(post)

    # Read environment variables
    bucket_sec = int(os.getenv("EVENT_TIME_BUCKET_SEC", "600"))
    topk = int(os.getenv("EVENT_TOPIC_TOPK", "3"))
    hash_algo = os.getenv("EVENT_HASH_ALGO", "blake2s")
    version = os.getenv("EVENT_KEY_VERSION", "v1")

    # Extract fields
    keywords_norm = _extract_topic_keywords(post, topk)
    # Use provided topic_hash if available, otherwise compute from keywords
    topic_hash = post.get("topic_hash") or _compute_topic_hash(keywords_norm, hash_algo)
    # Get topic_entities if provided
    topic_entities = post.get("topic_entities", None)

    # Get timestamps
    created_ts = post.get("created_ts")
    if not created_ts:
        created_ts = datetime.now(timezone.utc)
    elif isinstance(created_ts, str):
        created_ts = datetime.fromisoformat(created_ts.replace("Z", "+00:00"))

    # Calculate time bucket as datetime
    ts_epoch = int(created_ts.timestamp())
    bucket_start_epoch = (ts_epoch // bucket_sec) * bucket_sec
    time_bucket_start = datetime.fromtimestamp(bucket_start_epoch)

    # Extract symbol and token_ca
    symbol = post.get("symbol")
    if symbol:
        symbol = _normalize_token_symbol(symbol)

    token_ca = post.get("token_ca")
    if token_ca:
        token_ca = token_ca.lower()

    # Compute candidate score
    candidate_score = _compute_candidate_score(post)

    # Get sentiment fields
    last_sentiment = post.get("sentiment_label")
    last_sentiment_score = post.get("sentiment_score")

    # Prepare keywords for JSONB
    keywords_jsonb = keywords_norm if keywords_norm else None

    # Build evidence items from various sources
    new_evidence = []
    current_ts = datetime.now(timezone.utc)

    # X/Twitter evidence
    if x_data:
        x_ref = {}
        if "tweet_id" in x_data:
            x_ref["tweet_id"] = x_data["tweet_id"]
        if "url" in x_data:
            # Prefer expanded_url if provided, then normalize
            raw_url = x_data.get("expanded_url") or x_data.get("url")
            x_ref["url"] = _normalize_url(raw_url)
        if "author" in x_data:
            x_ref["author"] = x_data["author"]

        x_evidence = _build_evidence_item(
            source="x",
            ts=x_data.get("ts", current_ts),
            ref=x_ref,
            summary=x_data.get("text", "")[:100] if "text" in x_data else None,
            weight=x_data.get("weight", 1.0),
        )
        new_evidence.append(x_evidence)

    # DEX evidence
    if dex_data:
        dex_ref = {}
        if "chain_id" in dex_data:
            dex_ref["chain_id"] = dex_data["chain_id"]
        if "pool" in dex_data:
            dex_ref["pool"] = dex_data["pool"]
        if "tx" in dex_data:
            dex_ref["tx"] = dex_data["tx"]

        dex_evidence = _build_evidence_item(
            source="dex",
            ts=dex_data.get("ts", current_ts),
            ref=dex_ref,
            summary=(
                f"Price: ${dex_data.get('price_usd', 0):.4f}"
                if "price_usd" in dex_data
                else None
            ),
            weight=dex_data.get("weight", 1.0),
        )
        new_evidence.append(dex_evidence)

    # GoPlus evidence
    goplus_risk = None
    buy_tax = None
    sell_tax = None
    lp_lock_days = None
    honeypot = None

    if goplus_data:
        # Extract GoPlus fields for columns
        goplus_risk = goplus_data.get("risk_label")
        buy_tax = goplus_data.get("buy_tax")
        sell_tax = goplus_data.get("sell_tax")
        lp_lock_days = goplus_data.get("lp_lock_days")
        honeypot = goplus_data.get("honeypot")

        # Build evidence item
        goplus_ref = {}
        if "goplus_endpoint" in goplus_data:
            goplus_ref["goplus_endpoint"] = goplus_data["goplus_endpoint"]
        if "chain_id" in goplus_data:
            goplus_ref["chain_id"] = goplus_data["chain_id"]
        if token_ca:
            goplus_ref["address"] = token_ca

        goplus_evidence = _build_evidence_item(
            source="goplus",
            ts=goplus_data.get("ts", current_ts),
            ref=goplus_ref,
            summary=f"Risk: {goplus_risk}" if goplus_risk else None,
            weight=goplus_data.get("weight", 1.0),
        )
        new_evidence.append(goplus_evidence)

    # Prepare evidence JSONB (now as array)
    evidence_jsonb = new_evidence if new_evidence else None

    # Get engine and reflect table
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        raise ValueError("POSTGRES_URL environment variable not set")
    engine = create_engine(
        postgres_url,
        echo=False,
        future=True,
        isolation_level=os.getenv("DB_ISOLATION_LEVEL", "READ COMMITTED"),
    )

    events = _events_table(engine)

    # Build insert statement values (will filter by actual table columns below)
    insert_values = {
        "event_key": event_key,
        "symbol": symbol,
        "token_ca": token_ca,
        "topic_hash": topic_hash,
        "time_bucket_start": time_bucket_start,
        "start_ts": created_ts,
        "last_ts": created_ts,
        "evidence_count": len(new_evidence) if new_evidence else 1,
        "candidate_score": candidate_score,
        "keywords_norm": keywords_jsonb,
        "version": version,
        "last_sentiment": last_sentiment,
        "last_sentiment_score": last_sentiment_score,
        "goplus_risk": goplus_risk,
        "buy_tax": buy_tax,
        "sell_tax": sell_tax,
        "lp_lock_days": lp_lock_days,
        "honeypot": honeypot,
        "evidence": evidence_jsonb,
    }

    # Determine existing columns to avoid referencing non-existent fields
    existing_cols = {c.name for c in events.columns}

    # Keep a snapshot of intended insert keys for diagnostics
    intended_insert_keys = set(insert_values.keys())

    # Add topic_entities only if provided and column exists
    if topic_entities is not None and "topic_entities" in existing_cols:
        insert_values["topic_entities"] = topic_entities

    # Keep only keys that exist in the table
    filtered_insert_values = {
        k: v for k, v in insert_values.items() if k in existing_cols
    }

    # One-time warning if any intended columns were filtered out (schema drift)
    global _columns_filter_warned
    missing_insert_cols = sorted(list(intended_insert_keys - existing_cols))
    if missing_insert_cols and not _columns_filter_warned:
        log_json(
            stage="events.upsert.columns.filtered",
            missing_insert=missing_insert_cols,
            existing_cols_count=len(existing_cols),
        )
        _columns_filter_warned = True

    # Use filtered values for insert
    insert_values = filtered_insert_values

    # Try to detect-and-merge on conflict with lock retries
    max_retry = int(os.getenv("EVENT_DEADLOCK_MAX_RETRY", "3"))
    backoff_min = int(os.getenv("EVENT_DEADLOCK_BACKOFF_MS_MIN", "20"))
    backoff_max = int(os.getenv("EVENT_DEADLOCK_BACKOFF_MS_MAX", "40"))

    t0 = time.perf_counter()
    with engine.begin() as conn:
        # One-time unique index check
        try:
            _check_event_key_unique(conn)
        except Exception:
            pass
        merged_for_update: Optional[List[Dict[str, Any]]] = None
        # Attempt to lock the row if it exists and merge evidence first
        for attempt in range(max_retry + 1):
            try:
                sel = sa_text(
                    "SELECT event_key, symbol, token_ca, topic_hash, evidence "
                    "FROM events WHERE event_key = :k FOR UPDATE NOWAIT"
                )
                row = conn.execute(sel, {"k": event_key}).fetchone()
                if row is not None and hasattr(row, "_mapping"):
                    mapping = row._mapping
                    existing_ev = mapping.get("evidence") or []
                    # Conflict detection on identity dimensions (best-effort)
                    row_symbol = mapping.get("symbol")
                    row_token_ca = mapping.get("token_ca")
                    row_topic_hash = mapping.get("topic_hash")
                    identity_new = token_ca or f"{symbol}|na"
                    identity_old = (
                        row_token_ca or row_token_ca
                    ) or f"{_normalize_token_symbol(row_symbol)}|na"
                    if (str(identity_new) != str(identity_old)) or (
                        row_topic_hash and row_topic_hash != topic_hash
                    ):
                        events_key_conflict_total.inc({"reason": "identity_mismatch"})
                        log_json(
                            stage="events.key_conflict",
                            event_key=event_key,
                            identity_new=str(identity_new),
                            identity_old=str(identity_old),
                            topic_hash_new=topic_hash,
                            topic_hash_old=row_topic_hash,
                        )
                    merge_res = merge_event_evidence(
                        event_key=event_key,
                        new_evidence=new_evidence,
                        existing_evidence=existing_ev,
                        current_source=None,
                    )
                    merged_for_update = merge_res["merged_evidence"]
                break  # Either locked and handled, or row missing; proceed
            except Exception:
                if attempt >= max_retry:
                    # Enqueue for background compaction (hotspot)
                    from api.core.metrics import evidence_compact_enqueue_total

                    insert_conflict_fallback_total.inc()
                    evidence_compact_enqueue_total.inc()
                    break
                deadlock_retries_total.inc()
                _jitter_sleep(backoff_min, backoff_max, attempt)

        # Prepare insert payload (use merged evidence if available)
        if merged_for_update is not None:
            insert_values["evidence"] = merged_for_update
            insert_values["evidence_count"] = len(merged_for_update)

        ins = pg_insert(events).values(**insert_values)

        # Upsert: update replaces evidence with excluded (already merged if lock path)
        update_set = {}
        has_excluded = hasattr(ins, "excluded")
        if (
            has_excluded
            and "last_ts" in existing_cols
            and hasattr(ins.excluded, "last_ts")
        ):
            update_set["last_ts"] = func.greatest(
                events.c.last_ts, ins.excluded.last_ts
            )
        if (
            has_excluded
            and "evidence_count" in existing_cols
            and hasattr(ins.excluded, "evidence")
        ):
            update_set["evidence_count"] = sa_text(
                "CASE WHEN excluded.evidence IS NULL THEN events.evidence_count "
                "ELSE jsonb_array_length(excluded.evidence) END"
            )
        if has_excluded:
            for col in [
                "last_sentiment",
                "last_sentiment_score",
                "candidate_score",
                "goplus_risk",
                "buy_tax",
                "sell_tax",
                "lp_lock_days",
                "honeypot",
            ]:
                if col in existing_cols and hasattr(ins.excluded, col):
                    update_set[col] = getattr(ins.excluded, col)
            if "evidence" in existing_cols and hasattr(ins.excluded, "evidence"):
                update_set["evidence"] = sa_text(
                    "CASE WHEN excluded.evidence IS NULL THEN events.evidence ELSE excluded.evidence END"
                )

        stmt = ins.on_conflict_do_update(
            index_elements=[events.c.event_key], set_=update_set
        )
        conn.execute(stmt)

        # Fetch the final values
        row = conn.execute(
            sa_text(
                "SELECT evidence_count, candidate_score, last_ts "
                "FROM events WHERE event_key = :k"
            ),
            {"k": event_key},
        ).fetchone()

    t1 = time.perf_counter()
    events_upsert_tx_ms.observe(int(round((t1 - t0) * 1000)))

    # Build return dictionary
    result_dict = {
        "event_key": event_key,
        "evidence_count": int(row[0]),
        "candidate_score": float(row[1]),
        "last_ts": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
    }

    # Log the upsert
    log_json(
        "events.upsert",
        event_key=event_key,
        evidence_count=result_dict["evidence_count"],
        candidate_score=result_dict["candidate_score"],
        symbol=symbol,
        token_ca=token_ca,
        last_ts=result_dict["last_ts"],
    )

    # Return without last_ts for compatibility
    return {
        "event_key": result_dict["event_key"],
        "evidence_count": result_dict["evidence_count"],
        "candidate_score": result_dict["candidate_score"],
    }
