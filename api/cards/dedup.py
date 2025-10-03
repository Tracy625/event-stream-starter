"""State-based deduplication for card generation"""

import os
from typing import Tuple

from api.cache import get_redis_client
from api.core.metrics_store import log_json


def make_state_version(event: dict) -> str:
    """
    Generate state version string from event

    Format: {state}|{risk_level}|degrade:{0|1}|{EVENT_KEY_VERSION}
    """
    state = event.get("state", "candidate")
    risk_level = event.get("risk_level", "unknown")

    # Extract degrade flag from states dict
    states = event.get("states", {})
    # Degrade if explicitly set OR if risk_level is gray
    degrade = states.get("degrade", False) or (risk_level == "gray")
    degrade_flag = "1" if degrade else "0"

    # Use EVENT_KEY_VERSION for better governance during key version gray rollout
    key_ver = os.environ.get("EVENT_KEY_VERSION", "v1").strip() or "v1"
    state_version = f"{state}|{risk_level}|degrade:{degrade_flag}|{key_ver}"

    # Log version creation
    log_json(
        stage="dedup.make_version",
        event_key=event.get("event_key", ""),
        state=state,
        risk_level=risk_level,
        degrade=degrade,  # boolean, not string
        state_version=state_version,
    )

    return state_version


def should_emit(event_key: str, state_version: str) -> Tuple[bool, str]:
    """
    Check if event should be emitted based on state change

    Returns:
        (should_emit, reason)
    """
    if not event_key:
        return True, "no_event_key"

    try:
        redis_client = get_redis_client()
        if not redis_client:
            return True, "redis_unavailable"

        # Check stored version
        redis_key = f"dedup:{event_key}"
        stored_version = redis_client.get(redis_key)

        # Handle both bytes and string returns from Redis
        if stored_version is not None and isinstance(stored_version, bytes):
            stored_version = stored_version.decode("utf-8")

        if stored_version is None:
            # First time seeing this event_key
            decision = True
            reason = "first_seen"
        elif stored_version == state_version:
            # Same state, skip
            decision = False
            reason = "state_unchanged"
        else:
            # State changed, allow
            decision = True
            reason = "state_changed"

        # Log decision
        log_json(
            stage="dedup.check",
            event_key=event_key,
            stored=stored_version,
            incoming=state_version,
            decision="emit" if decision else "skip",
            reason=reason,
        )

        return decision, reason

    except Exception as e:
        # On error, allow emission
        log_json(stage="dedup.check", event_key=event_key, error=str(e))
        return True, "check_error"


def mark_emitted(event_key: str, state_version: str) -> None:
    """Mark event as emitted with state version"""
    try:
        redis_client = get_redis_client()
        if redis_client:
            redis_key = f"dedup:{event_key}"
            ttl = int(os.environ.get("DEDUP_TTL_SEC", "3600"))
            redis_client.setex(redis_key, ttl, state_version)
            log_json(
                stage="dedup.store",
                event_key=event_key,
                state_version=state_version,
                ttl=ttl,
            )
    except Exception as e:
        log_json(stage="dedup.store", event_key=event_key, error=str(e))


def make_state_version_with_rules(event: dict, hit_rules: list) -> str:
    """Generate state version with rule hit hash

    Args:
        event: Event data dict
        hit_rules: List of rule IDs that were hit

    Returns:
        State version string with rule hash appended
    """
    base_version = make_state_version(event)
    if hit_rules:
        import hashlib

        rules_str = ",".join(sorted(hit_rules))
        rules_hash = hashlib.md5(rules_str.encode()).hexdigest()[:8]
        return f"{base_version}_mr{rules_hash}"
    return base_version
