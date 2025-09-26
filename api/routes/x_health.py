"""Health and simple read-only routes for X backends."""

import os
from typing import Any, Dict
from fastapi import APIRouter, Query
from api.clients.x_client import get_x_health, get_x_client_from_env
from api.core.metrics_store import log_json

router = APIRouter()


@router.get("/health/x")
def x_health() -> Dict[str, Any]:
    """Return configured X backends and last known status."""
    data = get_x_health()
    if not data.get("backends"):
        # ensure backends reflected if not initialized yet
        be = os.getenv("X_BACKENDS") or os.getenv("X_BACKEND", "graphql")
        data["backends"] = [b.strip() for b in be.split(",") if b.strip()]
    return data


@router.get("/x/tweets")
def get_user_tweets(handle: str, limit: int = Query(5, ge=1, le=50)) -> Dict[str, Any]:
    """Minimal read-only endpoint to fetch tweets via multi-source client."""
    client = get_x_client_from_env()
    tweets = client.fetch_user_tweets(handle, since_id=None, limit=limit)
    # diagnostic stale flag may be present only for profile; keep structure minimal here.
    log_json(stage="x.api.tweets", handle=handle, count=len(tweets))
    return {"handle": handle, "count": len(tweets), "items": tweets[:limit]}


@router.get("/x/user")
def get_user_profile(handle: str) -> Dict[str, Any]:
    client = get_x_client_from_env()
    profile = client.fetch_user_profile(handle) or {}
    # Add OpenAPI-visible diagnostic in response
    log_json(stage="x.api.user", handle=handle, ok=bool(profile))
    return {"ok": bool(profile), "profile": profile}
