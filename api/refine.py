"""
Mini-LLM refine module for normalizing posts into structured events.

Extracts event keys, types, and assets from crypto-related text.
Uses deterministic hashing for stable event_key generation.
"""

import hashlib
import re
from typing import Dict, List, Any

# Reuse regex patterns from filter module
TOKEN_RE = re.compile(r"\$[A-Z]{2,10}\b")
CA_RE = re.compile(r"0x[a-fA-F0-9]{40}\b")


def extract_symbols(text: str) -> List[str]:
    """Extract unique token symbols from text."""
    matches = TOKEN_RE.findall(text)
    # Remove $ prefix and deduplicate
    symbols = list(set(m[1:] for m in matches))
    return sorted(symbols)  # Sort for deterministic output


def extract_contracts(text: str) -> List[str]:
    """Extract unique contract addresses from text."""
    matches = CA_RE.findall(text)
    # Deduplicate and normalize to lowercase
    contracts = list(set(m.lower() for m in matches))
    return sorted(contracts)  # Sort for deterministic output


def classify_type(text: str) -> str:
    """Classify event type based on text content."""
    text_lower = text.lower()
    
    # Check for specific patterns
    if any(word in text_lower for word in ['airdrop', 'drop', 'claim']):
        return "airdrop"
    elif any(word in text_lower for word in ['deploy', 'deployed', 'contract']):
        return "deploy"
    elif any(word in text_lower for word in ['token', 'coin', 'launch', 'mint']):
        return "token"
    else:
        return "misc"


def calculate_score(text: str, symbols: List[str], contracts: List[str]) -> float:
    """Calculate event score based on heuristics."""
    score = 0.3  # Base score
    
    # Boost for having symbols
    if symbols:
        score += 0.2
    
    # Boost for having contracts
    if contracts:
        score += 0.3
    
    # Boost for certain keywords
    boost_words = ['bullish', 'moon', 'gem', 'pump', 'launch']
    text_lower = text.lower()
    if any(word in text_lower for word in boost_words):
        score += 0.2
    
    return min(1.0, score)  # Cap at 1.0


def generate_summary(text: str, max_length: int = 100) -> str:
    """Generate concise summary from text."""
    # Clean up text
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Truncate if too long
    if len(text) > max_length:
        return text[:max_length-3] + "..."
    
    return text


def generate_event_key(type_str: str, symbols: List[str], contracts: List[str], summary: str) -> str:
    """Generate stable event key using SHA1 hash."""
    # Create deterministic string representation
    components = [
        type_str,
        '|'.join(symbols),
        '|'.join(contracts),
        summary[:50]  # Use first 50 chars for stability
    ]
    
    canonical = '|'.join(components)
    
    # Generate SHA1 hash
    hash_obj = hashlib.sha1(canonical.encode('utf-8'))
    return hash_obj.hexdigest()[:16]  # Use first 16 chars for brevity


def refine_post(text: str) -> Dict[str, Any]:
    """
    Refine raw post text into structured event.
    
    Returns dict with keys:
    - event_key: stable hash identifier
    - type: one of {"token", "airdrop", "deploy", "misc"}
    - score: float in [0, 1]
    - summary: concise text summary
    - assets: dict with symbols and contracts lists
    """
    # Extract assets
    symbols = extract_symbols(text)
    contracts = extract_contracts(text)
    
    # Classify type
    event_type = classify_type(text)
    
    # Generate summary
    summary = generate_summary(text)
    
    # Calculate score
    score = calculate_score(text, symbols, contracts)
    
    # Generate stable event key
    event_key = generate_event_key(event_type, symbols, contracts, summary)
    
    return {
        "event_key": event_key,
        "type": event_type,
        "score": score,
        "summary": summary,
        "assets": {
            "symbols": symbols,
            "contracts": contracts
        }
    }