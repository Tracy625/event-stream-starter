import re
from typing import List, Tuple


def tokenize(text: str) -> List[str]:
    """Split text into lowercase tokens for analysis."""
    tokens = re.findall(r'\b\w+\b', text.lower())
    return tokens


def analyze_rules(text: str) -> Tuple[str, float]:
    """
    Analyze sentiment using rule-based heuristics.
    
    Returns:
        (label, score) where label in {"pos", "neu", "neg"} and score in [-1.0, 1.0]
    """
    positive_words = {
        'good', 'great', 'solid', 'promising', 'bullish', 'moon', 'gem',
        'pump', 'profit', 'gains', 'strong', 'amazing', 'excellent',
        'opportunity', 'potential', 'winner', 'rocket', 'fire'
    }
    
    negative_words = {
        'bad', 'rug', 'scam', 'dump', 'crash', 'fail', 'loss', 'bear',
        'fake', 'warning', 'avoid', 'danger', 'risk', 'weak', 'poor',
        'terrible', 'horrible', 'trash', 'ponzi', 'fraud'
    }
    
    tokens = tokenize(text)
    
    pos_count = sum(1 for token in tokens if token in positive_words)
    neg_count = sum(1 for token in tokens if token in negative_words)
    
    # Calculate score
    total_sentiment_words = pos_count + neg_count
    if total_sentiment_words == 0:
        return ("neu", 0.0)
    
    # Score calculation: difference normalized by total
    score = (pos_count - neg_count) / max(len(tokens), 1)
    score = max(-1.0, min(1.0, score * 3))  # Scale and clamp to [-1, 1]
    
    # Determine label
    if score > 0.1:
        label = "pos"
    elif score < -0.1:
        label = "neg"
    else:
        label = "neu"
    
    return (label, score)


__all__ = ["analyze_rules"]