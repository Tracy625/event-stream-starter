"""
Transform between internal card format and external pushcard format
"""
from typing import Dict, Any, Literal
from api.cards.registry import RenderPayload

def to_pushcard(payload: RenderPayload, rendered_text: str,
                channel: Literal["tg", "ui"]) -> Dict[str, Any]:
    """
    Transform internal card format (cards.schema.json) to pushcard format (pushcard.schema.json)

    Args:
        payload: Internal RenderPayload
        rendered_text: Rendered template text
        channel: Target channel

    Returns:
        Dict conforming to pushcard.schema.json
    """
    ctx = payload["context"]
    meta = payload["meta"]

    # Map to pushcard format (legacy compatibility)
    pushcard = {
        "type": meta["type"],
        "event_key": meta.get("event_key", ""),  # FIXED: Added event_key mapping
        "risk_level": ctx.get("risk_level", "yellow"),
        "token_info": ctx.get("token_info", {}),
        "metrics": {
            "price_usd": ctx.get("price_usd"),
            "liquidity_usd": ctx.get("liquidity_usd"),
            "fdv": ctx.get("fdv"),
            "ohlc": ctx.get("ohlc", {})
        },
        "sources": {
            "security_source": ctx.get("risk_source", ""),
            "dex_source": ctx.get("dex_source", "")
        },
        "states": {
            "cache": ctx.get("states", {}).get("cache", False),
            "degrade": meta["degrade"],
            "stale": ctx.get("states", {}).get("stale", False),
            "reason": ctx.get("states", {}).get("reason", "")
        },
        "evidence": {
            "goplus_raw": {
                "summary": ctx.get("goplus_summary", "")
            }
        },
        "risk_note": ctx.get("risk_note", ""),
        "verify_path": ctx.get("verify_path", "/"),
        "data_as_of": ctx.get("data_as_of"),
        "rendered": {}
    }

    # Add rendered content
    if channel == "tg":
        pushcard["rendered"]["tg"] = rendered_text
    else:
        pushcard["rendered"]["ui"] = rendered_text

    # Add optional fields if present
    if "rules_fired" in ctx:
        pushcard["rules_fired"] = ctx["rules_fired"]
    if "legal_note" in ctx:
        pushcard["legal_note"] = ctx["legal_note"]

    # Type-specific fields
    if meta["type"] == "secondary":
        pushcard["source_level"] = ctx.get("source_level", "rumor")
        pushcard["features_snapshot"] = ctx.get("features_snapshot", {})
    elif meta["type"] == "topic":
        pushcard["topic_id"] = ctx.get("topic_id")
        pushcard["topic_entities"] = ctx.get("topic_entities", [])
        pushcard["topic_mention_count"] = ctx.get("topic_mention_count")

    return pushcard

def from_pushcard(pushcard: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform pushcard format back to internal format (for testing)

    Args:
        pushcard: Dict conforming to pushcard.schema.json

    Returns:
        Dict conforming to cards.schema.json
    """
    # Reverse mapping for testing
    # Implementation details omitted for brevity
    return {
        "card_type": pushcard.get("type"),
        "event_key": pushcard.get("event_key", ""),
        # ... other mappings
    }