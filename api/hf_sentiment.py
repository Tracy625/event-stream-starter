import os
from typing import Tuple, Optional
from api.services.hf_client import HfClient


_hf_client = None


def _get_client():
    """Get or create HfClient instance."""
    global _hf_client
    if _hf_client is None:
        _hf_client = HfClient()
    return _hf_client


def analyze_hf(text: str) -> Tuple[str, float]:
    """
    Analyze sentiment using HuggingFace model.
    
    Returns:
        (label, score) where:
        - label in {"pos", "neu", "neg"}
        - score = P(pos) - P(neg), clamped to [-1.0, 1.0]
    """
    client = _get_client()
    result = client.predict_sentiment_one(text)
    return (result["label"], result["score"])


__all__ = ["analyze_hf"]