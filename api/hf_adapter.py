"""
HuggingFace adapter for sentiment analysis.

Provides proper label mapping and score calculation for HF models.
"""

import os
import logging
from typing import Tuple
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

LOGGER = logging.getLogger(__name__)

# Configuration from environment
HF_MODEL = os.getenv("HF_MODEL", "cardiffnlp/twitter-roberta-base-sentiment-latest")
DEVICE = "cuda" if (os.getenv("HF_DEVICE", "cpu") == "cuda" and torch.cuda.is_available()) else "cpu"

# Global cache for model
_MODEL_CACHE = {"tokenizer": None, "model": None, "label_map": None}


def load_hf_model():
    """Load and cache HF model."""
    if _MODEL_CACHE["model"] is None:
        LOGGER.info(f"Loading HF model {HF_MODEL} on {DEVICE}")
        
        tokenizer = AutoTokenizer.from_pretrained(HF_MODEL)
        model = AutoModelForSequenceClassification.from_pretrained(HF_MODEL).to(DEVICE).eval()
        
        # Freeze parameters for inference
        for p in model.parameters():
            p.requires_grad = False
        
        # Extract label mapping from config
        ID2LABEL = {int(k): v.upper() for k, v in model.config.id2label.items()}
        
        # Map to standard labels
        LABEL_MAP = {}
        for i, name in ID2LABEL.items():
            if "NEG" in name:
                LABEL_MAP["neg"] = i
            elif "NEU" in name:
                LABEL_MAP["neu"] = i
            elif "POS" in name:
                LABEL_MAP["pos"] = i
        
        # Fallback for models with numeric labels
        if len(LABEL_MAP) != 3:
            LABEL_MAP = {"neg": 0, "neu": 1, "pos": 2}
        
        _MODEL_CACHE["tokenizer"] = tokenizer
        _MODEL_CACHE["model"] = model
        _MODEL_CACHE["label_map"] = LABEL_MAP
    
    return _MODEL_CACHE["tokenizer"], _MODEL_CACHE["model"], _MODEL_CACHE["label_map"]


def analyze_hf(text: str) -> Tuple[str, float]:
    """
    Analyze sentiment using HuggingFace model.
    
    Returns:
        (label, score) where label in {"pos", "neu", "neg"} and score in [-1, 1]
    """
    tokenizer, model, label_map = load_hf_model()
    
    # Tokenize and encode
    enc = tokenizer(text, return_tensors="pt", truncation=True, max_length=256).to(DEVICE)
    
    # Run inference
    with torch.no_grad():
        logits = model(**enc).logits[0].float()
    
    # Calculate probabilities
    probs = torch.softmax(logits, dim=-1)
    
    # Get label from highest probability
    idx = int(torch.argmax(probs).item())
    inv_map = {v: k for k, v in label_map.items()}
    label = inv_map[idx]  # 'pos' | 'neu' | 'neg'
    
    # Calculate score as difference between positive and negative probabilities
    # This gives a continuous score in [-1, 1]
    score = float(probs[label_map["pos"]] - probs[label_map["neg"]])
    
    # Clamp to valid range
    return label, max(-1.0, min(1.0, score))