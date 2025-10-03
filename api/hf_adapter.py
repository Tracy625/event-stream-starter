# DEPRECATED: use api.services.hf_client.HfClient
"""
HuggingFace adapter for sentiment analysis.

This is now a thin wrapper around api.services.hf_client.HfClient.
Maintained for backward compatibility only.
"""

from typing import Tuple

# Singleton client instance
_client = None


def load_hf_model():
    """Load and cache HF model. Legacy function maintained for compatibility."""
    global _client
    if _client is None:
        from api.services.hf_client import HfClient

        _client = HfClient()
    # Return dummy values for compatibility (not actually used in analyze_hf)
    return None, None, None


def analyze_hf(text: str) -> Tuple[str, float]:
    """
    Analyze sentiment using HuggingFace model.

    Returns:
        (label, score) where label in {"pos", "neu", "neg"} and score in [-1, 1]
    """
    global _client
    if _client is None:
        from api.services.hf_client import HfClient

        _client = HfClient()

    result = _client.predict_sentiment_one(text)
    return result["label"], result["score"]
