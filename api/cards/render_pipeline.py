"""
Card rendering and push pipeline with unified degradation and error handling
"""
import json
import time
from pathlib import Path
from typing import Dict, Any, Literal, Optional, Tuple
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from jsonschema import validate, ValidationError, Draft7Validator

from api.cards.registry import (
    CARD_ROUTES, CARD_TEMPLATES, CardType,
    normalize_card_type, UnknownCardTypeError,
    RenderPayload
)
from api.cards.dedup import should_emit, mark_emitted
from api.cards.transformers import to_pushcard
from api.utils.logging import log_json
from api.services.telegram import TelegramNotifier
# Note: Outbox repository helpers are imported in worker/jobs/push_cards.py.
# render_pipeline itself does not depend on them; avoid importing here to
# keep API-side usage lightweight and prevent import errors in minimal envs.
# Avoid importing DB session helpers here; pipeline does not persist state directly.

# Import metrics from centralized registry - no new registrations here!
from api.core.metrics import (
    cards_generated_total,
    cards_render_fail_total,
    cards_push_total,
    cards_push_fail_total,
    cards_pipeline_latency_ms,
    cards_unknown_type_count
)

# Reusable Jinja2 environments (module-level singletons)
_env_tg = Environment(
    loader=FileSystemLoader("templates/cards"),
    autoescape=False
)
_env_ui = Environment(
    loader=FileSystemLoader("templates/cards"),
    autoescape=True
)

def check_template_exists(template_base: str, channel: Literal["tg", "ui"],
                         env: Optional[Environment] = None) -> bool:
    """
    Check if template exists using Jinja2 loader

    Args:
        template_base: Base template name without suffix
        channel: Target channel (tg or ui)
        env: Jinja2 environment (created if not provided)

    Returns:
        True if template exists, False otherwise
    """
    if env is None:
        # Use module-level singleton
        env = _env_ui if channel == "ui" else _env_tg

    template_name = f"{template_base}.{channel}.j2"
    try:
        env.loader.get_source(env, template_name)
        return True
    except TemplateNotFound:
        return False

def render_template(payload: RenderPayload, channel: Literal["tg", "ui"]) -> Tuple[str, bool]:
    """
    Render template with degradation on failure

    Args:
        payload: RenderPayload with template_name and context
        channel: Target channel

    Returns:
        Tuple of (rendered_text, is_degraded)
    """
    start_time = time.time()
    template_base = payload["template_name"]
    card_type = payload["meta"]["type"]

    try:
        # Use module-level singleton
        env = _env_ui if channel == "ui" else _env_tg

        # Check template exists
        if not check_template_exists(template_base, channel, env):
            log_json(
                stage="cards.template_missing",
                template=f"{template_base}.{channel}.j2",
                type=card_type
            )
            cards_render_fail_total.inc({"type": card_type, "reason": "template_missing"})

            # Degraded fallback
            return _render_degraded(payload, channel), True

        # Load and render template
        template_name = f"{template_base}.{channel}.j2"
        template = env.get_template(template_name)
        rendered = template.render(card_data=payload["context"])

        latency_ms = int((time.time() - start_time) * 1000)
        log_json(
            stage="cards.rendered",
            template=template_name,
            type=card_type,
            latency_ms=latency_ms
        )

        return rendered, False

    except Exception as e:
        log_json(
            stage="cards.render_error",
            error=str(e),
            template=template_base,
            type=card_type
        )
        cards_render_fail_total.inc({"type": card_type, "reason": "render_error"})
        return _render_degraded(payload, channel), True

def _render_degraded(payload: RenderPayload, channel: Literal["tg", "ui"]) -> str:
    """Generate degraded text output when template fails"""
    ctx = payload["context"]
    card_type = payload["meta"]["type"]

    if channel == "tg":
        # Minimal Markdown for Telegram
        lines = [
            f"⚫ **{card_type.upper()} 卡片** (降级模式)",
            "",
            f"代币: {ctx.get('token_info', {}).get('symbol', 'UNKNOWN')}",
            f"风险: {ctx.get('risk_level', 'unknown')}",
            f"时间: {ctx.get('data_as_of', 'N/A')}",
            "",
            "_服务降级，显示简化内容_"
        ]
        return "\n".join(lines)
    else:
        # Plain text for UI
        return f"{card_type} Card (Degraded)\nSymbol: {ctx.get('token_info', {}).get('symbol', 'UNKNOWN')}\nRisk: {ctx.get('risk_level', 'unknown')}"

def render_and_push(signal: Dict[str, Any],
                    channel_id: str,
                    channel: Literal["tg", "ui"] = "tg",
                    now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Complete pipeline: route → generate → render → validate → push

    Args:
        signal: Input signal with type field
        channel_id: Target channel ID
        channel: Rendering channel (tg or ui)
        now: Current time (for testing)

    Returns:
        Result dict with success, message_id, error, etc.
    """
    start_time = time.time()
    if now is None:
        now = datetime.now(timezone.utc)

    card_type = None  # Initialize for finally block

    try:
        # 1. Normalize and validate type
        raw_type = signal.get("type", "")
        try:
            card_type = normalize_card_type(raw_type)
        except UnknownCardTypeError as e:
            log_json(
                stage="cards.unknown_type",
                type=raw_type,
                error=str(e)
            )
            cards_unknown_type_count.inc({"type": raw_type})
            return {"success": False, "error": str(e)}

        # 2. Route to generator
        generator = CARD_ROUTES[card_type]

        # 3. Generate card context
        try:
            payload = generator(signal, now=now)
            cards_generated_total.inc({"type": card_type})
        except Exception as e:
            log_json(
                stage="cards.generate_error",
                type=card_type,
                error=str(e)
            )
            return {"success": False, "error": f"Generation failed: {str(e)}"}

        # 4. Check deduplication
        event_key = payload["meta"]["event_key"]
        if event_key:
            state_version = signal.get("state_version") or "v0"
            can_emit, reason = should_emit(event_key, state_version)
            if not can_emit:
                log_json(
                    stage="cards.dedup_skip",
                    event_key=event_key,
                    reason=reason
                )
                return {"success": False, "error": f"Dedup: {reason}", "dedup": True}

        # 5. Render template
        rendered_text, is_degraded = render_template(payload, channel)
        if is_degraded:
            payload["meta"]["degrade"] = True

        # 6. Transform to pushcard format
        pushcard = to_pushcard(payload, rendered_text, channel)

        # 7. Validate against schema
        schema_path = Path("schemas/pushcard.schema.json")
        if schema_path.exists():
            try:
                with open(schema_path) as f:
                    schema = json.load(f)
                try:
                    validate(pushcard, schema)
                except ValidationError as e:
                    log_json(
                        stage="cards.schema_error",
                        error=str(e),
                        type=card_type
                    )
                    # Mark as degraded but continue push
                    payload["meta"]["degrade"] = True
                    pushcard.setdefault("states", {})["degrade"] = True
                    cards_render_fail_total.inc({"type": card_type, "reason": "schema_invalid"})
                    # Continue
            except Exception as e:
                # Any schema loading/resolution error → log and continue (do not fail pipeline)
                log_json(
                    stage="cards.schema_error",
                    error=str(e),
                    type=card_type
                )
                payload["meta"]["degrade"] = True
                pushcard.setdefault("states", {})["degrade"] = True

        # 8. Push to channel
        if channel == "tg":
            notifier = TelegramNotifier()
            result = notifier.send_message(
                chat_id=channel_id,
                text=rendered_text,
                parse_mode="HTML",
                event_key=event_key
            )

            if result.get("success"):
                # Mark as emitted ONLY after successful send
                if event_key:
                    state_version = signal.get("state_version") or "v0"
                    mark_emitted(event_key, state_version)
                cards_push_total.inc({"type": card_type})
            else:
                error_code = _classify_error_code(result)
                cards_push_fail_total.inc({"type": card_type, "code": error_code})

            return result
        else:
            # UI channel - just return rendered content
            return {"success": True, "content": rendered_text}

    except Exception as e:
        log_json(
            stage="cards.pipeline_error",
            error=str(e)
        )
        return {"success": False, "error": str(e)}
    finally:
        latency_ms = int((time.time() - start_time) * 1000)
        if card_type:
            cards_pipeline_latency_ms.observe(latency_ms, {"type": card_type})

def _classify_error_code(result: Dict[str, Any]) -> str:
    """Classify error code for metrics"""
    status_code = result.get("status_code", 0)
    error_code = result.get("error_code")

    if status_code == 429 or error_code == 429:
        return "429"
    elif 400 <= status_code < 500:
        return "4xx"
    elif status_code >= 500:
        return "5xx"
    else:
        return "net"
