import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from api.cache import get_redis_client
from api.core import metrics, tracing
from api.core.metrics_store import log_json, timeit


class TelegramNotifier:
    """Minimal Telegram notification service"""

    def __init__(self):
        # Try both TG_BOT_TOKEN and TELEGRAM_BOT_TOKEN
        self.bot_token = os.getenv("TG_BOT_TOKEN", "") or os.getenv(
            "TELEGRAM_BOT_TOKEN", ""
        )
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.redis = get_redis_client()
        self.timeout = int(os.getenv("TG_TIMEOUT_SECS", "6") or 6)

    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "Markdown",
        disable_notification: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Send message to Telegram chat
        Returns: {"success": bool, "message_id": str, "error": str}
        """

        mode = (os.getenv("TELEGRAM_MODE", "mock") or "mock").strip().lower()
        force_429 = (os.getenv("TELEGRAM_FORCE_429", "") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "y",
            "on",
        )

        # Get metrics
        error_counter = metrics.counter(
            "telegram_error_code_count", "Telegram error codes"
        )
        latency_hist = metrics.histogram(
            "telegram_send_latency_ms",
            "Telegram send latency",
            [50, 100, 200, 500, 1000, 2000, 5000],
        )

        # Start timing
        start_time = time.time()
        event_key = kwargs.get("event_key")
        attempt = kwargs.get("attempt")
        trace_id = tracing.get_trace_id()

        # Fallback: if no token from init, try getting from config
        if not self.bot_token:
            try:
                from api.core.config import TelegramConfig

                cfg = TelegramConfig.from_env()
                self.bot_token = cfg.bot_token or ""
                self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
            except Exception:
                pass

        # Apply sandbox override if enabled
        from api.core.config import TelegramConfig

        cfg = TelegramConfig.from_env()
        if cfg.sandbox and cfg.sandbox_channel_id:
            chat_id = str(cfg.effective_channel_id())

        if mode != "mock" and not self.bot_token:
            log_json(stage="telegram.error", error="TELEGRAM_BOT_TOKEN not configured")
            return {"success": False, "error": "Bot token not configured"}

        try:
            # Use new rate limiter with 1s window
            from api.core.rate_limiter import allow_or_wait

            # Get effective channel ID as int
            effective_channel = int(chat_id) if chat_id.lstrip("-").isdigit() else None

            # Check rate limit before sending; block until allowed instead of synthesizing 429
            wait_start = time.time()
            ok = allow_or_wait(effective_channel, max_wait_ms=5000)
            while not ok:
                # short sleep to avoid tight loop; allow_or_wait enforces window
                time.sleep(0.05)
                ok = allow_or_wait(effective_channel, max_wait_ms=5000)
            # Optional visibility: how long we waited locally (does not count as 429)
            waited_ms = int((time.time() - wait_start) * 1000)
            if waited_ms > 0:
                log_json(
                    stage="telegram.ratelimit_wait",
                    chat_id=chat_id,
                    waited_ms=waited_ms,
                )

            if mode == "mock":
                latency_ms = (time.time() - start_time) * 1000
                latency_hist.observe(latency_ms)

                if force_429:
                    log_entry = {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "evt": "telegram.send",
                        "channel_id": chat_id,
                        "event_key": event_key,
                        "ok": False,
                        "code": "429",
                        "error_code": 429,
                        "reason": "forced_429",
                        "latency_ms": int(latency_ms),
                        "attempt": attempt,
                        "trace_id": trace_id,
                    }
                    print(json.dumps(log_entry))
                    log_json(
                        stage="telegram.mock_429",
                        chat_id=chat_id,
                        error="forced_429",
                        error_code=429,
                    )
                    error_counter.inc({"code": "429"})
                    return {
                        "success": False,
                        "error": "forced_429",
                        "error_code": 429,
                        "status_code": 429,
                        "retry_after": 1,
                    }

                record = _push_mock(text)
                message_id = f"mock-{int(timestamp := (time.time() * 1000))}"
                error_counter.inc({"code": "200"})
                log_entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "evt": "telegram.send",
                    "channel_id": chat_id,
                    "event_key": event_key,
                    "ok": True,
                    "code": "200",
                    "latency_ms": int(latency_ms),
                    "attempt": attempt,
                    "trace_id": trace_id,
                    "mock_path": str(MOCK_PATH),
                    "message_id": message_id,
                }
                print(json.dumps(log_entry))
                log_json(
                    stage="telegram.mock_sent",
                    chat_id=chat_id,
                    text_length=len(text),
                    mock_path=str(MOCK_PATH),
                )
                return {
                    "success": True,
                    "message_id": message_id,
                    "status_code": 200,
                    "mock_record": record,
                }

            # Prepare request
            url = f"{self.base_url}/sendMessage"

            payload = {
                "chat_id": chat_id,
                "text": text[:4096],  # Telegram message limit
                "parse_mode": parse_mode,
                "disable_notification": disable_notification,
            }

            # Add thread ID if sandbox mode specifies it
            if cfg.sandbox and cfg.sandbox_thread_id:
                payload["message_thread_id"] = cfg.sandbox_thread_id

            # Send request
            response = requests.post(url, json=payload, timeout=self.timeout)

            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            latency_hist.observe(latency_ms)

            # Parse response
            data = response.json()
            status_code = response.status_code

            if data.get("ok"):
                message_id = data["result"]["message_id"]

                # Record success
                error_counter.inc({"code": "200"})

                # Structured log
                log_entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "evt": "telegram.send",
                    "channel_id": chat_id,
                    "event_key": event_key,
                    "ok": True,
                    "code": "200",
                    "latency_ms": int(latency_ms),
                    "attempt": attempt,
                    "trace_id": trace_id,
                }
                print(json.dumps(log_entry))

                log_json(
                    stage="telegram.sent",
                    chat_id=chat_id,
                    message_id=message_id,
                    text_length=len(text),
                )

                return {"success": True, "message_id": str(message_id)}
            else:
                error = data.get("description", "Unknown error")
                error_code = data.get("error_code")

                # Classify error code
                if status_code == 429 or error_code == 429:
                    code_label = "429"
                elif 400 <= status_code < 500:
                    code_label = "4xx"
                elif status_code >= 500:
                    code_label = "5xx"
                else:
                    code_label = "unknown"

                error_counter.inc({"code": code_label})

                # Structured log
                log_entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "evt": "telegram.send",
                    "channel_id": chat_id,
                    "event_key": event_key,
                    "ok": False,
                    "code": code_label,
                    "latency_ms": int(latency_ms),
                    "attempt": attempt,
                    "trace_id": trace_id,
                }
                print(json.dumps(log_entry))

                log_json(
                    stage="telegram.api_error",
                    chat_id=chat_id,
                    error=error,
                    error_code=error_code,
                )

                # Extract retry_after if present
                retry_after = None
                if data.get("parameters"):
                    retry_after = data["parameters"].get("retry_after")

                return {
                    "success": False,
                    "error": error,
                    "error_code": error_code,
                    "status_code": status_code,
                    "retry_after": retry_after,
                }

        except requests.exceptions.Timeout:
            latency_ms = (time.time() - start_time) * 1000
            latency_hist.observe(latency_ms)
            error_counter.inc({"code": "net"})

            # Structured log
            log_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "evt": "telegram.send",
                "channel_id": chat_id,
                "event_key": event_key,
                "ok": False,
                "code": "net",
                "latency_ms": int(latency_ms),
                "attempt": attempt,
                "trace_id": trace_id,
            }
            print(json.dumps(log_entry))

            log_json(stage="telegram.timeout", chat_id=chat_id)
            return {
                "success": False,
                "error": "Request timeout",
                "error_code": None,
                "status_code": 0,
                "retry_after": None,
            }

        except requests.exceptions.RequestException as e:
            latency_ms = (time.time() - start_time) * 1000
            latency_hist.observe(latency_ms)
            error_counter.inc({"code": "net"})

            # Structured log
            log_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "evt": "telegram.send",
                "channel_id": chat_id,
                "event_key": event_key,
                "ok": False,
                "code": "net",
                "latency_ms": int(latency_ms),
                "attempt": attempt,
                "trace_id": trace_id,
            }
            print(json.dumps(log_entry))

            log_json(stage="telegram.request_error", chat_id=chat_id, error=str(e))
            return {
                "success": False,
                "error": f"Request failed: {str(e)}",
                "error_code": None,
                "status_code": 0,
                "retry_after": None,
            }

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            latency_hist.observe(latency_ms)
            error_counter.inc({"code": "net"})

            # Structured log
            log_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "evt": "telegram.send",
                "channel_id": chat_id,
                "event_key": event_key,
                "ok": False,
                "code": "net",
                "latency_ms": int(latency_ms),
                "attempt": attempt,
                "trace_id": trace_id,
            }
            print(json.dumps(log_entry))

            log_json(stage="telegram.error", chat_id=chat_id, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "error_code": None,
                "status_code": 0,
                "retry_after": None,
            }

    def get_updates(self, offset: Optional[int] = None) -> Dict[str, Any]:
        """Get updates from Telegram (for testing)"""

        if not self.bot_token:
            return {"success": False, "error": "Bot token not configured"}

        try:
            url = f"{self.base_url}/getUpdates"

            params = {}
            if offset:
                params["offset"] = offset

            response = requests.get(url, params=params, timeout=self.timeout)

            data = response.json()

            if data.get("ok"):
                return {"success": True, "updates": data.get("result", [])}
            else:
                return {
                    "success": False,
                    "error": data.get("description", "Unknown error"),
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def test_connection(self) -> Dict[str, Any]:
        """Test bot connection"""

        if not self.bot_token:
            return {"success": False, "error": "Bot token not configured"}

        try:
            url = f"{self.base_url}/getMe"

            response = requests.get(url, timeout=self.timeout)
            data = response.json()

            if data.get("ok"):
                bot_info = data.get("result", {})

                log_json(
                    stage="telegram.connected",
                    bot_username=bot_info.get("username"),
                    bot_id=bot_info.get("id"),
                )

                return {
                    "success": True,
                    "bot_username": bot_info.get("username"),
                    "bot_id": bot_info.get("id"),
                }
            else:
                return {
                    "success": False,
                    "error": data.get("description", "Unknown error"),
                }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Module-level convenience functions for Day9.1 verification
MODE = (os.getenv("TELEGRAM_MODE", "mock") or "mock").strip().lower()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_SANDBOX_CHAT_ID")
MOCK_PATH = Path(os.getenv("TELEGRAM_MOCK_PATH", "/tmp/telegram_sandbox.jsonl"))


def _now_iso() -> str:
    """Get current ISO timestamp"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _push_mock(text: str) -> Dict:
    """Push to mock file for testing"""
    rec = {"ok": True, "mock": True, "text": text, "ts": _now_iso()}
    MOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MOCK_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log_json(stage="telegram.mock", path=str(MOCK_PATH), text_len=len(text))
    return rec


def _push_real(text: str) -> Dict:
    """Push to real Telegram"""
    if not BOT_TOKEN or not CHAT_ID:
        return {
            "ok": False,
            "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_SANDBOX_CHAT_ID not set",
        }

    notifier = TelegramNotifier()
    result = notifier.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")

    return {
        "ok": result.get("success", False),
        "message_id": result.get("message_id"),
        "error": result.get("error"),
    }


def push_topic_card(text: str) -> Dict:
    """
    Minimal adapter for Day9.1 verification.
    Respect TELEGRAM_MODE: mock | real.
    """
    if MODE == "real":
        return _push_real(text)
    return _push_mock(text)
