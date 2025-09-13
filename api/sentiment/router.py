import os
import json
from typing import Tuple

# === FastAPI router (added for HTTP exposure) ===
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/sentiment", tags=["sentiment"])

class _SentimentIn(BaseModel):
    text: str

@router.get("")
def sentiment_get(text: str):
    """
    Back-compat: GET /sentiment?text=...
    """
    label, score = analyze(text)  # 使用你现有的 analyze()
    return {"label": label, "score": score}

@router.post("/analyze")
def sentiment_post(body: _SentimentIn):
    """
    JSON body: {"text": "..."}
    """
    label, score = analyze(body.text)
    return {"label": label, "score": score}

def log_json(stage: str, **kv) -> None:
    kv["stage"] = stage
    print(f"[JSON] {json.dumps(kv)}")


def analyze(text: str) -> Tuple[str, float]:
    backend = os.getenv("SENTIMENT_BACKEND", "rules")
    strict = os.getenv("SENTIMENT_STRICT", "0") == "1"
    
    if backend == "hf":
        try:
            from api.hf_sentiment import analyze_hf
            return analyze_hf(text)
        except Exception as e:
            if strict:
                raise
            log_json(
                "sentiment.downgrade",
                backend="hf",
                reason=str(e),
                downgrade=True
            )
            from api.rules_sentiment import analyze_rules
            return analyze_rules(text)
    else:
        from api.rules_sentiment import analyze_rules
        return analyze_rules(text)


__all__ = ["analyze", "router"]