"""
Filtering module for crypto-related text processing.

This module provides:
- Keyword-based filtering with configurable terms
- Token symbol and contract address detection via regex
- Rule-based sentiment analysis (stub for HuggingFace integration)

Default keywords include crypto verbs (launch, mint, airdrop, deploy) and can be
overridden via KEYWORDS_CSV environment variable.

Sentiment analysis uses a simple lexicon-based approach:
- Positive words: solid, promising, bullish, moon, gem
- Negative words: rug, scam, dump, crash, fail
"""

import os
import re
from typing import List, Tuple, Optional

# Precompiled regex for symbols and contracts
# $TOKEN: 2–10 uppercase letters after a literal $
TOKEN_RE = re.compile(r"\$[A-Z]{2,10}\b")
# EVM contract: 0x + 40 hex chars
CA_RE = re.compile(r"0x[a-fA-F0-9]{40}\b")


def tokenize(text: str) -> List[str]:
    """Split text into lowercase tokens for analysis."""
    # Simple tokenization: split on whitespace and punctuation
    tokens = re.findall(r'\b\w+\b', text.lower())
    return tokens


def filters_text(text: str, keywords: Optional[List[str]] = None) -> bool:
    """
    Check if text contains crypto-relevant keywords or patterns.
    
    Returns True if text contains:
    - Any keyword from the list
    - Token symbols like $XYZ
    - Contract addresses (0x...)
    - Common crypto verbs
    """
    # normalize for keyword match; regex works on raw text
    raw = text or ""
    lowered = raw.casefold()
    
    if keywords is None:
        # Default keywords from env or fallback
        env_keywords = os.getenv('KEYWORDS_CSV', '')
        if env_keywords:
            keywords = [k.strip() for k in env_keywords.split(',')]
        else:
            keywords = ['launch', 'mint', 'airdrop', 'deploy', 'token', 'coin', 'crypto']
    
    kw = keywords
    if any(k in lowered for k in kw):
        return True
    
    # explicit crypto patterns
    if TOKEN_RE.search(raw) or CA_RE.search(raw):
        return True
    
    return False


def analyze_sentiment(text: str) -> Tuple[str, float]:
    """
    Analyze sentiment of text using configured backend (rules or HuggingFace).
    
    Returns:
        (label, score) where label in {"pos", "neu", "neg"} and score in [-1.0, 1.0]
    """
    from api.sentiment import router
    return router.analyze(text)


class FilterModule:
    """
    Wrapper class for filtering operations with configurable keywords.
    """
    
    def __init__(self, keywords: List[str], negations: Optional[List[str]] = None):
        """
        Initialize filter with custom keywords and optional negation terms.
        
        Args:
            keywords: List of terms to filter for
            negations: Optional list of terms to exclude (not implemented in stub)
        """
        self.keywords = keywords
        self.negations = negations or []
    
    def tokenize(self, text: str) -> List[str]:
        """Delegate to pure function."""
        return tokenize(text)
    
    def filters_text(self, text: str) -> bool:
        """Check if text passes filter using configured keywords."""
        # Apply negations if any
        if self.negations:
            text_lower = text.lower()
            for neg in self.negations:
                if neg.lower() in text_lower:
                    return False
        
        return filters_text(text, self.keywords)
    
    def analyze_sentiment(self, text: str) -> Tuple[str, float]:
        """Delegate to pure function."""
        return analyze_sentiment(text)