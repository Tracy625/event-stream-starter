"""
Event aggregation module for D5.

Provides event key generation and upsert operations for event aggregation.
"""

import os
import re
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy import create_engine, Table, MetaData, func, text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from api.metrics import log_json, timeit


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


@timeit("events.make_key")
def make_event_key(post: Dict[str, Any]) -> str:
    """
    Generate deterministic event key from post.
    
    Format: {id_part}:{topic_hash}:{time_bucket}
    
    Args:
        post: Post dictionary with required fields:
            - token_ca: Optional contract address
            - symbol: Optional token symbol
            - keywords: List of keywords
            - created_ts: Post timestamp (datetime)
    
    Returns:
        Event key string
    """
    # Read environment variables at call time
    bucket_sec = int(os.getenv("EVENT_TIME_BUCKET_SEC", "600"))
    topk = int(os.getenv("EVENT_TOPIC_TOPK", "3"))
    hash_algo = os.getenv("EVENT_HASH_ALGO", "blake2s")
    
    # Extract ID part
    id_part = _extract_id_part(post)
    
    # Extract and hash topic keywords
    keywords_norm = _extract_topic_keywords(post, topk)
    topic_hash = _compute_topic_hash(keywords_norm, hash_algo)
    
    # Calculate time bucket
    created_ts = post.get("created_ts")
    if not created_ts:
        created_ts = datetime.now(timezone.utc)
    elif isinstance(created_ts, str):
        # Parse if string
        created_ts = datetime.fromisoformat(created_ts.replace("Z", "+00:00"))
    
    # Convert to timestamp and bucket
    ts_epoch = int(created_ts.timestamp())
    bucket_start = (ts_epoch // bucket_sec) * bucket_sec
    
    # Build event key
    event_key = f"{id_part}:{topic_hash}:{bucket_start}"
    
    # Log the key generation
    log_json(
        "events.make_key",
        event_key=event_key,
        id_part=id_part,
        topic_hash=topic_hash,
        bucket_start=bucket_start,
        keywords_count=len(keywords_norm)
    )
    
    return event_key


@timeit("events.upsert")
def upsert_event(post: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upsert event to database based on post data.
    
    Creates new event or updates existing one based on event_key.
    
    Args:
        post: Post dictionary with required fields:
            - All fields required by make_event_key
            - sentiment_label: Sentiment classification
            - sentiment_score: Sentiment score [-1, 1]
    
    Returns:
        Dictionary with:
            - event_key: Generated event key
            - evidence_count: Current evidence count
            - candidate_score: Computed candidate score
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
    
    # Get engine and reflect table
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        raise ValueError("POSTGRES_URL environment variable not set")
    engine = create_engine(postgres_url, echo=False, future=True)
    
    events = _events_table(engine)
    
    # Build insert statement
    ins = pg_insert(events).values(
        event_key=event_key,
        symbol=symbol,
        token_ca=token_ca,
        topic_hash=topic_hash,
        time_bucket_start=time_bucket_start,
        start_ts=created_ts,
        last_ts=created_ts,
        evidence_count=1,
        candidate_score=candidate_score,
        keywords_norm=keywords_jsonb,
        version=version,
        last_sentiment=last_sentiment,
        last_sentiment_score=last_sentiment_score
    )
    
    # Build upsert statement with ON CONFLICT
    stmt = ins.on_conflict_do_update(
        index_elements=[events.c.event_key],
        set_={
            "last_ts": func.greatest(events.c.last_ts, ins.excluded.last_ts),
            "evidence_count": events.c.evidence_count + 1,
            "last_sentiment": ins.excluded.last_sentiment,
            "last_sentiment_score": ins.excluded.last_sentiment_score,
            "candidate_score": ins.excluded.candidate_score
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