"""
Unified card push worker for all card types
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from api.cache import get_redis_client
from api.cards.render_pipeline import render_and_push

# Import metrics from centralized registry (no new registration here!)
from api.core.metrics import cards_push_fail_total
from api.database import with_db
from api.db.models.push_outbox import OutboxStatus, PushOutbox
from api.utils.logging import log_json

# Use same app instance as other workers
from worker.app import app


class CardPushTask(Task):
    """Custom task with exponential backoff"""

    autoretry_for = (Exception,)
    max_retries = 5
    default_retry_delay = 2  # Start with 2 seconds
    retry_backoff = True  # Enable exponential backoff
    retry_backoff_max = 300  # Max 5 minutes
    retry_jitter = True  # Add jitter to prevent thundering herd


@app.task(base=CardPushTask, bind=True, queue="cards")
def process_card(self, signal: Dict[str, Any], channel_id: str) -> Dict[str, Any]:
    """
    Process and push card with retry logic

    Args:
        signal: Signal data with type field
        channel_id: Target channel ID

    Returns:
        Result dict with success status
    """
    try:
        # Add retry attempt to signal for tracking
        signal["attempt"] = self.request.retries + 1

        log_json(
            stage="cards.worker.start",
            type=signal.get("type"),
            event_key=signal.get("event_key"),
            attempt=signal["attempt"],
        )

        # Call unified pipeline
        result = render_and_push(signal=signal, channel_id=channel_id, channel="tg")

        if result.get("success"):
            log_json(
                stage="cards.worker.success",
                type=signal.get("type"),
                event_key=signal.get("event_key"),
                message_id=result.get("message_id"),
            )
            return result

        # Handle specific error codes
        error_code = result.get("error_code") or result.get("status_code")

        if error_code == 429:
            # Rate limit - retry with backoff
            retry_after = result.get("retry_after", 60)
            log_json(
                stage="cards.worker.rate_limited",
                retry_after=retry_after,
                attempt=signal["attempt"],
            )
            raise self.retry(countdown=retry_after)

        elif error_code and 400 <= error_code < 500:
            # Client error - send to DLQ, don't retry
            log_json(
                stage="cards.worker.client_error",
                error_code=error_code,
                error=result.get("error"),
            )
            cards_push_fail_total.inc(
                {"type": signal.get("type", "unknown"), "code": "4xx"}
            )
            _send_to_dlq(signal, result)
            return result

        elif error_code and error_code >= 500:
            # Server error - retry with backoff
            log_json(
                stage="cards.worker.server_error",
                error_code=error_code,
                attempt=signal["attempt"],
            )
            cards_push_fail_total.inc(
                {"type": signal.get("type", "unknown"), "code": "5xx"}
            )
            raise self.retry()

        else:
            # Network or unknown error - retry
            log_json(
                stage="cards.worker.network_error",
                error=result.get("error"),
                attempt=signal["attempt"],
            )
            cards_push_fail_total.inc(
                {"type": signal.get("type", "unknown"), "code": "net"}
            )
            raise self.retry()

    except MaxRetriesExceededError:
        # Max retries reached - send to DLQ
        log_json(
            stage="cards.worker.max_retries",
            type=signal.get("type"),
            event_key=signal.get("event_key"),
        )
        cards_push_fail_total.inc(
            {"type": signal.get("type", "unknown"), "code": "max_retries"}
        )
        _send_to_dlq(signal, {"error": "Max retries exceeded"})
        return {"success": False, "error": "Max retries exceeded"}

    except Exception as e:
        log_json(
            stage="cards.worker.error", error=str(e), attempt=self.request.retries + 1
        )
        raise


def _send_to_dlq(signal: Dict[str, Any], result: Dict[str, Any]):
    """
    Send failed card to dead letter queue (outbox with special status)

    Args:
        signal: Original signal
        result: Failure result
    """
    try:
        with with_db() as db:
            # Create outbox entry with DLQ status
            row = PushOutbox(
                channel_id=int(signal.get("channel_id") or 0),
                thread_id=None,
                event_key=signal.get("event_key", ""),
                payload_json=signal,
                status=OutboxStatus.DLQ.value,
                attempt=int(signal.get("attempt", 0)),
                last_error=json.dumps(result),
            )
            db.add(row)
            db.flush()

            log_json(
                stage="cards.dlq.saved",
                event_key=signal.get("event_key"),
                outbox_id=row.id,
            )
    except Exception as e:
        log_json(stage="cards.dlq.error", error=str(e))
