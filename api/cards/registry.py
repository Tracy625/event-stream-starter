"""
Card routing registry - single source of truth for card types and templates
"""

from datetime import datetime
from typing import Any, Callable, Dict, Literal, cast, get_args

# Type definition with exhaustive checking
CardType = Literal["primary", "secondary", "topic", "market_risk"]


# Custom exception for unknown types
class UnknownCardTypeError(ValueError):
    """Raised when an unknown card type is encountered"""

    pass


def normalize_card_type(t: str) -> CardType:
    """
    Normalize and validate card type

    Args:
        t: Raw card type string

    Returns:
        Normalized CardType

    Raises:
        UnknownCardTypeError: If type is not recognized
    """
    if not t:
        raise UnknownCardTypeError("Card type cannot be empty")

    normalized = t.lower().strip()
    valid_types = get_args(CardType)

    if normalized not in valid_types:
        raise UnknownCardTypeError(f"Unknown card type: {t}")

    return cast(CardType, normalized)


# Forward declarations - actual implementations in generator.py
def generate_primary_card(signal: Dict[str, Any], *, now: datetime) -> "RenderPayload":
    from .generator import generate_primary_card as impl

    return impl(signal, now=now)


def generate_secondary_card(
    signal: Dict[str, Any], *, now: datetime
) -> "RenderPayload":
    from .generator import generate_secondary_card as impl

    return impl(signal, now=now)


def generate_topic_card(signal: Dict[str, Any], *, now: datetime) -> "RenderPayload":
    from .generator import generate_topic_card as impl

    return impl(signal, now=now)


def generate_market_risk_card(
    signal: Dict[str, Any], *, now: datetime
) -> "RenderPayload":
    from .generator import generate_market_risk_card as impl

    return impl(signal, now=now)


# Routing table - maps card type to generator function
CARD_ROUTES: Dict[CardType, Callable[[Dict[str, Any], datetime], "RenderPayload"]] = {
    "primary": generate_primary_card,
    "secondary": generate_secondary_card,
    "topic": generate_topic_card,
    "market_risk": generate_market_risk_card,
}

# Template registry - maps card type to template base name
CARD_TEMPLATES: Dict[CardType, str] = {
    "primary": "primary_card",
    "secondary": "secondary_card",
    "topic": "topic_card",
    "market_risk": "market_risk_card",
}

# RenderPayload structure
from typing import Optional, TypedDict


class CardMeta(TypedDict):
    """Required metadata fields for cards"""

    type: str  # Card type
    event_key: str  # Event identifier
    degrade: bool  # Whether card is degraded
    template_base: str  # Template base name
    latency_ms: Optional[int]  # Generation latency
    diagnostic_flags: Optional[Dict[str, bool]]  # Diagnostic info


class RenderPayload(TypedDict):
    """Unified return structure for card generators"""

    template_name: str  # Template base name (without .tg.j2/.ui.j2 suffix)
    context: Dict[str, Any]  # Rendering context
    meta: CardMeta  # Required metadata


# Export public API
__all__ = [
    "CARD_ROUTES",
    "CARD_TEMPLATES",
    "CardType",
    "normalize_card_type",
    "UnknownCardTypeError",
    "RenderPayload",
    "CardMeta",
]
