"""
Event aggregation module for D5.

Provides event key generation and upsert operations for event aggregation.
"""

import os
import re
import hashlib
import unicodedata
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set
from sqlalchemy import create_engine, Table, MetaData, func, text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from api.metrics import log_json, timeit

# Track if salt change warning has been shown
_salt_warning_shown = False


_events_tbl_cache = None


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
    engine = create_engine(postgres_url, echo=False, future=True)
    return engine.connect()


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


def _compute_candidate_score(post: Dict[str, Any], alpha: float = 0.6, beta: float = 0.4) -> float:
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
    text = unicodedata.normalize('NFC', text)
    
    # Remove URLs (http/https/bare domains with punctuation)
    text = re.sub(r'https?://[^\s]+', '', text)
    text = re.sub(r'www\.[^\s]+', '', text)
    text = re.sub(r'\b[a-zA-Z0-9][a-zA-Z0-9-]*\.(com|org|net|io|xyz|co|app|tech|ai|dev|finance|eth)[\s,\.!?;:]', ' ', text)
    
    # Remove @handles (but preserve #hashtags)
    text = re.sub(r'@\w+', '', text)
    
    # Collapse multiple spaces (last)
    text = re.sub(r'\s+', ' ', text)
    
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
    
    # Check for salt change warning (only log once)
    global _salt_warning_shown
    default_salt = "v1"
    if salt != default_salt and not _salt_warning_shown:
        log_json(
            stage="pipeline.event.key",
            event="salt_changed",
            current_salt=salt,
            default_salt=default_salt
        )
        _salt_warning_shown = True
    
    # Extract required fields (fail if missing critical fields)
    event_type = post.get("type")
    if not event_type:
        raise ValueError("Event type is required for key generation")
    
    # Normalize components
    type_norm = event_type.lower()
    
    # Symbol: strip edges then uppercase (preserves internal spaces)
    symbol = post.get("symbol", "")
    symbol_norm = symbol.strip().upper() if symbol else ""
    
    # Token CA: lowercase, validate 0x prefix and hex chars
    token_ca = post.get("token_ca", "")
    token_ca_norm = ""
    if token_ca:
        token_ca_lower = token_ca.lower()
        if not token_ca_lower.startswith("0x"):
            log_json(
                stage="pipeline.event.key",
                event="token_ca_warning",
                message="Token CA missing 0x prefix",
                token_ca=token_ca
            )
        elif not re.match(r'^0x[0-9a-f]+$', token_ca_lower):
            log_json(
                stage="pipeline.event.key",
                event="token_ca_warning",
                message="Token CA contains non-hex characters",
                token_ca=token_ca
            )
        token_ca_norm = token_ca_lower
    
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
    
    # Build preimage: type|symbol|token_ca|text_norm|bucket|salt
    preimage = f"{type_norm}|{symbol_norm}|{token_ca_norm}|{text_norm}|{bucket}|{salt}"
    
    # Generate SHA256 hash (40 hex chars to match Day5 - hardcoded length)
    hash_full = hashlib.sha256(preimage.encode()).hexdigest()
    event_key = hash_full[:40]  # Fixed at 40 hex chars per Day5 spec
    
    # Log the key generation
    log_json(
        stage="pipeline.event.key",
        event_key=event_key,
        type=type_norm,
        symbol=symbol_norm,
        token_ca=token_ca_norm,
        bucket=bucket,
        salt=salt
    )
    
    return event_key


def _make_evidence_dedup_key(evidence: Dict[str, Any]) -> str:
    """
    Generate deduplication key for evidence.
    
    Uses: sha1(source + sorted stable ref fields)
    """
    source = evidence.get("source", "")
    ref = evidence.get("ref", {})
    
    # Sort ref fields for stable hashing
    ref_sorted = json.dumps(ref, sort_keys=True)
    
    # Create dedup key
    content = f"{source}|{ref_sorted}"
    return hashlib.sha1(content.encode()).hexdigest()


def _build_evidence_item(source: str, ts: datetime, ref: Dict[str, Any], 
                         summary: Optional[str] = None, weight: Optional[float] = None) -> Dict[str, Any]:
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
        "ts": ts.isoformat() if hasattr(ts, 'isoformat') else ts,
        "ref": ref
    }
    
    if summary is not None:
        evidence["summary"] = summary
    if weight is not None:
        evidence["weight"] = weight
        
    return evidence


def merge_event_by_key(event_key: str, payload: Dict[str, Any], strict: Optional[bool] = None) -> Dict[str, Any]:
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
        would_change=would_change
    )
    
    return {
        "would_change": would_change,
        "delta_count": delta_evidence_count,
        "sources_candidate": list(sources_candidate)  # Convert set to list for consistent output
    }


def merge_event_evidence(event_key: str, new_evidence: List[Dict[str, Any]], 
                        existing_evidence: Optional[List[Dict[str, Any]]] = None,
                        current_source: Optional[str] = None) -> Dict[str, Any]:
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
    
    if not strict:
        # Loose mode: only keep evidence from current_source
        merged = []
        # Keep existing evidence from current source
        if current_source:
            merged = [e for e in existing if e.get("source") == current_source]
            # Add new evidence from current source
            merged.extend([e for e in new_evidence if e.get("source") == current_source])
        else:
            # No current source specified, just append new
            merged = existing + new_evidence
        
        after_count = len(merged)
        deduped = 0
    else:
        # Strict mode: merge and deduplicate across sources
        seen_keys = set()
        merged = []
        
        # Process existing evidence
        for item in existing:
            dedup_key = _make_evidence_dedup_key(item)
            if dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                merged.append(item)
        
        # Process new evidence
        for item in new_evidence:
            dedup_key = _make_evidence_dedup_key(item)
            if dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                merged.append(item)
        
        after_count = len(merged)
        deduped = (before_count + len(new_evidence)) - after_count
    
    # Extract sources for logging
    sources = set()
    for item in merged:
        if "source" in item:
            sources.add(item["source"])
    
    # Log the merge
    log_json(
        stage="pipeline.event.evidence.merge",
        event_key=event_key,
        source=list(sources),
        before_count=before_count,
        after_count=after_count,
        deduped=deduped,
        strict=strict,
        merge_scope=merge_scope
    )
    
    return {
        "merged_evidence": merged,
        "before_count": before_count,
        "after_count": after_count,
        "deduped": deduped
    }


def upsert_event_with_evidence(*, event: Dict[str, Any], evidence: List[Dict[str, Any]], 
                               strict: Optional[bool] = None, current_source: Optional[str] = None) -> Dict[str, Any]:
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
        current_source=current_source
    )
    
    return {
        "event_key": event_key,
        "evidence_count": merge_result["after_count"],
        "candidate_score": 0.5  # Mock score
    }


@timeit("events.upsert")
def upsert_event(post: Dict[str, Any], goplus_data: Optional[Dict[str, Any]] = None,
                 dex_data: Optional[Dict[str, Any]] = None, x_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
    topic_hash = _compute_topic_hash(keywords_norm, hash_algo)
    
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
            x_ref["url"] = x_data["url"]
        if "author" in x_data:
            x_ref["author"] = x_data["author"]
            
        x_evidence = _build_evidence_item(
            source="x",
            ts=x_data.get("ts", current_ts),
            ref=x_ref,
            summary=x_data.get("text", "")[:100] if "text" in x_data else None,
            weight=x_data.get("weight", 1.0)
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
            summary=f"Price: ${dex_data.get('price_usd', 0):.4f}" if "price_usd" in dex_data else None,
            weight=dex_data.get("weight", 1.0)
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
            weight=goplus_data.get("weight", 1.0)
        )
        new_evidence.append(goplus_evidence)
    
    # Prepare evidence JSONB (now as array)
    evidence_jsonb = new_evidence if new_evidence else None
    
    # Get engine and reflect table
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        raise ValueError("POSTGRES_URL environment variable not set")
    engine = create_engine(postgres_url, echo=False, future=True)
    
    events = _events_table(engine)
    
    # Build insert statement with evidence and GoPlus fields
    ins = pg_insert(events).values(
        event_key=event_key,
        symbol=symbol,
        token_ca=token_ca,
        topic_hash=topic_hash,
        time_bucket_start=time_bucket_start,
        start_ts=created_ts,
        last_ts=created_ts,
        evidence_count=len(new_evidence) if new_evidence else 1,
        candidate_score=candidate_score,
        keywords_norm=keywords_jsonb,
        version=version,
        last_sentiment=last_sentiment,
        last_sentiment_score=last_sentiment_score,
        goplus_risk=goplus_risk,
        buy_tax=buy_tax,
        sell_tax=sell_tax,
        lp_lock_days=lp_lock_days,
        honeypot=honeypot,
        evidence=evidence_jsonb
    )
    
    # Build upsert statement with ON CONFLICT - now handles evidence array merge
    # Note: This is a simplified version. In production, we'd need to fetch existing
    # evidence and use merge_event_evidence() for proper deduplication
    stmt = ins.on_conflict_do_update(
        index_elements=[events.c.event_key],
        set_={
            "last_ts": func.greatest(events.c.last_ts, ins.excluded.last_ts),
            "evidence_count": sa_text(
                "CASE WHEN events.evidence IS NULL THEN COALESCE(array_length(excluded.evidence::json[], 1), 1) "
                "ELSE events.evidence_count + COALESCE(array_length(excluded.evidence::json[], 1), 1) END"
            ),
            "last_sentiment": ins.excluded.last_sentiment,
            "last_sentiment_score": ins.excluded.last_sentiment_score,
            "candidate_score": ins.excluded.candidate_score,
            "goplus_risk": ins.excluded.goplus_risk,
            "buy_tax": ins.excluded.buy_tax,
            "sell_tax": ins.excluded.sell_tax,
            "lp_lock_days": ins.excluded.lp_lock_days,
            "honeypot": ins.excluded.honeypot,
            # Merge evidence arrays (concat, dedup happens in app layer)
            "evidence": sa_text(
                "CASE WHEN events.evidence IS NULL THEN excluded.evidence "
                "WHEN excluded.evidence IS NULL THEN events.evidence "
                "ELSE events.evidence || excluded.evidence END"
            )
        }
    )
    
    # Execute with transaction
    with engine.begin() as conn:
        conn.execute(stmt)
        
        # Fetch the final values
        row = conn.execute(
            sa_text(
                "SELECT evidence_count, candidate_score, last_ts "
                "FROM events WHERE event_key = :k"
            ),
            {"k": event_key}
        ).fetchone()
    
    # Build return dictionary
    result_dict = {
        "event_key": event_key,
        "evidence_count": int(row[0]),
        "candidate_score": float(row[1]),
        "last_ts": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2])
    }
    
    # Log the upsert
    log_json(
        "events.upsert",
        event_key=event_key,
        evidence_count=result_dict["evidence_count"],
        candidate_score=result_dict["candidate_score"],
        symbol=symbol,
        token_ca=token_ca,
        last_ts=result_dict["last_ts"]
    )
    
    # Return without last_ts for compatibility
    return {
        "event_key": result_dict["event_key"],
        "evidence_count": result_dict["evidence_count"],
        "candidate_score": result_dict["candidate_score"]
    }