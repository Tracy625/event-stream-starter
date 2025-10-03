import json
from typing import Tuple

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.hf_sentiment import analyze_with_fallback


class _SentimentIn(BaseModel):
    text: str


router = APIRouter(prefix="/sentiment", tags=["sentiment"])


@router.get("")
def sentiment_get(text: str):
    """Back-compat: GET /sentiment?text=..."""
    payload, status = analyze_with_fallback(text, path_label="get")
    return JSONResponse(content=payload, status_code=status)


@router.post("/analyze")
def sentiment_post(body: _SentimentIn):
    """
    JSON body: {"text": "..."}
    """
    payload, status = analyze_with_fallback(body.text, path_label="post")
    return JSONResponse(content=payload, status_code=status)


def log_json(stage: str, **kv) -> None:
    kv["stage"] = stage
    print(f"[JSON] {json.dumps(kv)}")


def analyze(text: str) -> Tuple[str, float]:
    payload, _ = analyze_with_fallback(text, path_label="script")
    return payload.get("label", "neu"), float(payload.get("score", 0.0))


__all__ = ["analyze", "router"]
