import os
from typing import Tuple, Optional


_model = None
_tokenizer = None


def _load_model():
    """Lazy load the HuggingFace model and tokenizer."""
    global _model, _tokenizer
    
    if _model is not None:
        return _model, _tokenizer
    
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    
    model_name = os.getenv("HF_MODEL", "cardiffnlp/twitter-roberta-base-sentiment-latest")
    device_str = os.getenv("HF_DEVICE", "cpu")
    
    # Check CUDA availability
    if device_str == "cuda" and torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")
    
    _tokenizer = AutoTokenizer.from_pretrained(model_name)
    _model = AutoModelForSequenceClassification.from_pretrained(model_name)
    _model = _model.to(device)
    _model.eval()
    
    return _model, _tokenizer


def analyze_hf(text: str) -> Tuple[str, float]:
    """
    Analyze sentiment using HuggingFace model.
    
    Returns:
        (label, score) where:
        - label in {"pos", "neu", "neg"}
        - score = P(pos) - P(neg), clamped to [-1.0, 1.0]
    """
    import torch
    
    model, tokenizer = _load_model()
    
    # Tokenize and prepare input
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    
    # Move to same device as model
    device = next(model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}
    
    # Get predictions
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        probs = torch.softmax(logits, dim=-1)
    
    # Get id2label mapping from config
    id2label = model.config.id2label
    
    # Map labels to our standard format
    label_map = {}
    for idx, label in id2label.items():
        lower = label.lower()
        if "pos" in lower:
            label_map[idx] = "pos"
        elif "neg" in lower:
            label_map[idx] = "neg"
        else:
            label_map[idx] = "neu"
    
    # Get argmax label
    predicted_id = torch.argmax(probs, dim=-1).item()
    label = label_map.get(predicted_id, "neu")
    
    # Calculate score = P(pos) - P(neg)
    pos_prob = 0.0
    neg_prob = 0.0
    
    for idx, prob in enumerate(probs[0].cpu().numpy()):
        mapped = label_map.get(idx, "neu")
        if mapped == "pos":
            pos_prob += prob
        elif mapped == "neg":
            neg_prob += prob
    
    score = float(pos_prob - neg_prob)
    score = max(-1.0, min(1.0, score))
    
    return (label, score)


__all__ = ["analyze_hf"]