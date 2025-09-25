"""HuggingFace sentiment helpers with online fallback and degradation metrics."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import httpx

from api.core.metrics import hf_degrade_count
from api.rules_sentiment import analyze_rules

TIMEOUT_S = float(os.getenv("SENTIMENT_TIMEOUT_S", "3"))
POS_THRESHOLD = float(os.getenv("SENTIMENT_POS_THRESH", "0.25"))
NEG_THRESHOLD = float(os.getenv("SENTIMENT_NEG_THRESH", "-0.25"))


def _resolve_timeout() -> float:
    """Fetch timeout on every invocation to honour updated environment values."""
    value = os.getenv("SENTIMENT_TIMEOUT_S")
    if not value:
        return TIMEOUT_S
    try:
        return float(value)
    except ValueError:
        return TIMEOUT_S


def _norm_probs(triples: List[Dict[str, Any]]) -> Dict[str, float]:
    """Normalize HuggingFace response triples into pos/neu/neg probabilities."""
    probs = {"pos": 0.0, "neu": 0.0, "neg": 0.0}

    for item in triples:
        label = str(item.get("label", "")).lower()
        score = float(item.get("score", 0.0))

        if "positive" in label or label == "pos":
            probs["pos"] = max(probs["pos"], score)
        elif "negative" in label or label == "neg":
            probs["neg"] = max(probs["neg"], score)
        elif "neutral" in label or label == "neu":
            probs["neu"] = max(probs["neu"], score)

    # Fallback to neutral if both pos/neg missing
    if probs["neu"] == 0.0 and probs["pos"] == 0.0 and probs["neg"] == 0.0:
        probs["neu"] = 1.0

    return probs


def _score_from_probs(probs: Dict[str, float]) -> Tuple[str, float]:
    """Derive label and sentiment score from probability map."""
    score = max(-1.0, min(1.0, probs["pos"] - probs["neg"]))

    if score >= POS_THRESHOLD:
        label = "pos"
    elif score <= NEG_THRESHOLD:
        label = "neg"
    else:
        label = "neu"

    return label, score


def _extract_triples(data: Any) -> List[Dict[str, Any]]:
    """Extract classification triples from inference response."""
    if isinstance(data, list):
        if data and isinstance(data[0], list):
            return [dict(item) for item in data[0] if isinstance(item, dict)]
        if data and isinstance(data[0], dict):
            return [dict(item) for item in data if isinstance(item, dict)]
    raise ValueError("invalid_response")


def _analyze_template(text: str) -> Dict[str, Any]:
    label, score = analyze_rules(text)
    return {"label": label, "score": score, "backend": "template"}


def _analyze_online(text: str) -> Dict[str, Any]:
    token = os.getenv("HUGGING_FACE_HUB_TOKEN") or os.getenv("HF_API_TOKEN") or ""
    model = os.getenv("HF_MODEL", "distilbert-base-uncased-finetuned-sst-2-english")
    base = os.getenv("HF_API_BASE", "https://api-inference.huggingface.co").rstrip("/")

    if not token:
        raise PermissionError("missing_token")

    url = f"{base}/models/{model}"
    headers = {"Authorization": f"Bearer {token}"}
    timeout = _resolve_timeout()

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json={"inputs": text}, headers=headers)
        response.raise_for_status()
        data = response.json()

    triples = _extract_triples(data)
    probs = _norm_probs(triples)
    label, score = _score_from_probs(probs)

    return {"label": label, "score": score, "backend": "hf", "probs": probs}


def _record_degrade(reason: str, path_label: str) -> None:
    hf_degrade_count.labels(reason, path_label).inc()


def analyze_with_fallback(text: str, path_label: str = "script") -> Tuple[Dict[str, Any], int]:
    """Attempt online inference, fall back to template on failure."""
    backend = (os.getenv("SENTIMENT_BACKEND") or "").lower()

    if backend not in {"api", "hf"}:
        payload = _analyze_template(text)
        payload["degrade"] = False
        return payload, 200

    try:
        payload = _analyze_online(text)
        payload["degrade"] = False
        return payload, 200

    except PermissionError:
        reason = "auth"
    except httpx.TimeoutException:
        reason = "timeout"
    except httpx.HTTPStatusError as exc:
        code = getattr(getattr(exc, "response", None), "status_code", 0)
        if code in (401, 403):
            reason = "auth"
        elif 400 <= code < 500:
            reason = "http_4xx"
        elif 500 <= code < 600:
            reason = "http_5xx"
        else:
            reason = "unknown"
    except ValueError:
        reason = "invalid"
    except httpx.RequestError:
        reason = "timeout"
    except Exception:
        reason = "unknown"

    _record_degrade(reason, path_label)
    fallback = _analyze_template(text)
    fallback.update({"degrade": True, "reason": reason})
    return fallback, 200


def analyze_hf(text: str) -> Tuple[str, float]:
    """Direct online inference helper used by legacy callers."""
    result = _analyze_online(text)
    return result["label"], result["score"]


__all__ = ["analyze_hf", "analyze_with_fallback"]
