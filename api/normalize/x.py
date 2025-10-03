"""
X (Twitter) tweet normalization module.

Standardizes raw tweets from X clients into unified format with light parsing.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests

from api.core.metrics_store import log_json


def normalize_tweet(raw_tweet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normalize raw tweet data into standardized format.

    Args:
        raw_tweet: Raw tweet dict with keys: id, author, text, created_at, urls

    Returns:
        Normalized dict with standard fields or None if invalid

    Standard fields:
        - source: Always "x"
        - author: Twitter handle
        - text: Tweet text
        - ts: ISO8601 timestamp
        - urls: List of URLs
        - token_ca: Contract address (if found)
        - symbol: Token symbol (if found)
        - is_candidate: True if has CA or symbol
    """

    # Validate required fields
    if not raw_tweet:
        log_json(stage="x.normalize.drop", reason="empty_input")
        return None

    # Extract and validate text
    text = raw_tweet.get("text", "")
    if isinstance(text, str):
        text = text.strip()
    if not text:
        log_json(stage="x.normalize.drop", reason="empty_text")
        return None

    # Extract and validate timestamp
    ts = raw_tweet.get("created_at")
    if not ts:
        log_json(stage="x.normalize.drop", reason="missing_ts")
        return None

    # Extract author
    author = raw_tweet.get("author", "")
    if not author:
        log_json(stage="x.normalize.drop", reason="missing_author")
        return None

    # Extract URLs (ensure list)
    urls = raw_tweet.get("urls", [])
    if not isinstance(urls, list):
        urls = [urls] if urls else []
    urls = [str(u) for u in urls if u]

    # Optional URL expansion (enabled by env)
    if os.getenv("X_ENABLE_LINK_EXPAND", "false").lower() == "true" and urls:
        urls = _expand_urls_with_budget(urls)

    # Extract contract address (EVM format)
    token_ca = None
    ca_pattern = r"\b0x[a-fA-F0-9]{40}\b"
    ca_match = re.search(ca_pattern, text)
    if ca_match:
        token_ca = ca_match.group(0)

    # Extract symbol ($TOKEN format)
    symbol = None
    symbol_pattern = r"(?<![A-Za-z0-9_])\$[A-Za-z][A-Za-z0-9]{1,9}\b"
    symbol_match = re.search(symbol_pattern, text)
    if symbol_match:
        symbol = symbol_match.group(0)

    # Determine if candidate
    is_candidate = bool(token_ca or symbol)

    # Build normalized output
    normalized = {
        "source": "x",
        "author": author,
        "text": text,
        "ts": ts,
        "urls": urls,
        "token_ca": token_ca,
        "symbol": symbol,
        "is_candidate": is_candidate,
    }

    # Log success
    log_json(stage="x.normalize.ok", has_ca=bool(token_ca), has_symbol=bool(symbol))

    return normalized


def _expand_urls_with_budget(urls: List[str]) -> List[str]:
    """Expand short URLs with per-URL and total budget constraints.

    - Per URL timeout: 2s (HEAD then GET fallback)
    - Total budget per tweet: 5s
    - Concurrency: 4
    - Failure-safe: return original URL on any error
    """
    per_url_timeout = float(os.getenv("X_URL_EXPAND_TIMEOUT_S", "2"))
    total_budget_s = float(os.getenv("X_URL_EXPAND_TOTAL_S", "5"))
    max_workers = int(os.getenv("X_URL_EXPAND_WORKERS", "4"))

    sess = requests.Session()

    def resolve(u: str) -> str:
        try:
            # Try HEAD first (fast)
            r = sess.head(u, allow_redirects=True, timeout=per_url_timeout)
            if r.url:
                return r.url
        except Exception:
            pass
        try:
            r = sess.get(u, allow_redirects=True, timeout=per_url_timeout)
            return r.url or u
        except Exception:
            return u

    out = list(urls)
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(resolve, u): i for i, u in enumerate(urls)}
            deadline = requests.utils.default_timer() + total_budget_s
            for fut in as_completed(futures, timeout=total_budget_s):
                i = futures[fut]
                try:
                    out[i] = fut.result(
                        timeout=max(0.0, deadline - requests.utils.default_timer())
                    )
                except Exception:
                    out[i] = urls[i]
    except Exception:
        # Budget exceeded or thread pool error: fall back to original
        return urls
    return out
