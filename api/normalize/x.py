"""
X (Twitter) tweet normalization module.

Standardizes raw tweets from X clients into unified format with light parsing.
"""

import os
import re
from typing import Dict, Any, Optional
from api.metrics import log_json


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
    
    # Optional URL expansion (disabled by default for MVP)
    if os.getenv("X_ENABLE_LINK_EXPAND", "false").lower() == "true":
        # URL expansion with 2s timeout would go here
        # For MVP, skip expansion
        pass
    
    # Extract contract address (EVM format)
    token_ca = None
    ca_pattern = r'\b0x[a-fA-F0-9]{40}\b'
    ca_match = re.search(ca_pattern, text)
    if ca_match:
        token_ca = ca_match.group(0)
    
    # Extract symbol ($TOKEN format)
    symbol = None
    symbol_pattern = r'(?<![A-Za-z0-9_])\$[A-Za-z][A-Za-z0-9]{1,9}\b'
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
        "is_candidate": is_candidate
    }
    
    # Log success
    log_json(stage="x.normalize.ok", 
            has_ca=bool(token_ca), 
            has_symbol=bool(symbol))
    
    return normalized