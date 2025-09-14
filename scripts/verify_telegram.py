#!/usr/bin/env python3
"""
Telegram smoke test script with master switch control.
Honors TELEGRAM_PUSH_ENABLED environment variable.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any


def mask_sensitive(value: str, show_last: int = 4) -> str:
    """Mask sensitive data, showing only last N characters."""
    if not value or len(value) <= show_last:
        return "***"
    return "*" * (len(value) - show_last) + value[-show_last:]


def log(message: str) -> None:
    """Print log message with prefix."""
    print(f"[verify-telegram] {message}", flush=True)


def error(message: str) -> None:
    """Print error message with prefix to stderr."""
    print(f"[verify-telegram] ERROR: {message}", file=sys.stderr, flush=True)


def validate_boolean(value: str, var_name: str) -> bool:
    """Validate and normalize boolean environment variable."""
    normalized = value.lower()
    if normalized not in ["true", "false"]:
        error(f"{var_name} must be 'true' or 'false' (case-insensitive), got: '{value}'")
        error("Please update your environment to use 'true' or 'false' only")
        sys.exit(2)
    return normalized == "true"


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    thread_id: Optional[str] = None,
    api_base: str = "https://api.telegram.org",
    max_retries: int = 3,
    timeout: int = 6
) -> Dict[str, Any]:
    """
    Send a message via Telegram Bot API with retry logic.
    Returns the API response or raises an exception.
    """
    url = f"{api_base}/bot{bot_token}/sendMessage"

    # Prepare request body
    body = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True
    }
    if thread_id:
        body["message_thread_id"] = thread_id

    data = json.dumps(body).encode('utf-8')
    headers = {"Content-Type": "application/json"}

    # Retry logic with exponential backoff
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_data = response.read().decode('utf-8')
                result = json.loads(response_data)

                if result.get("ok") == True:
                    return result
                else:
                    # API returned ok=false
                    error_code = result.get("error_code", "unknown")
                    description = result.get("description", "no description")
                    raise Exception(f"API error {error_code}: {description}")

        except urllib.error.HTTPError as e:
            response_body = e.read().decode('utf-8', errors='ignore')
            try:
                error_data = json.loads(response_body)
                error_code = error_data.get("error_code", e.code)
                description = error_data.get("description", str(e))
            except:
                error_code = e.code
                description = str(e)

            # Check if we should retry (429 or 5xx)
            if e.code == 429 or (500 <= e.code < 600):
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    log(f"Retrying after {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue

            # Don't retry for client errors (4xx except 429)
            raise Exception(f"HTTP {error_code}: {description}")

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                log(f"Retrying after {wait_time}s due to: {str(e)}")
                time.sleep(wait_time)
                continue
            raise

    raise Exception(f"Failed after {max_retries} attempts")


def main() -> int:
    """Main entry point for the telegram verification script."""

    # Read environment variables
    push_enabled_raw = os.environ.get("TELEGRAM_PUSH_ENABLED", "false")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    thread_id = os.environ.get("TELEGRAM_THREAD_ID", "")
    api_base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")

    # Validate and normalize TELEGRAM_PUSH_ENABLED
    push_enabled = validate_boolean(push_enabled_raw, "TELEGRAM_PUSH_ENABLED")

    # Determine execution mode
    mode = "LIVE" if push_enabled else "DRY_RUN"
    log(f"Starting verification (mode={mode})")

    if not push_enabled:
        # Dry-run mode - no actual message sending
        log("TELEGRAM_PUSH_ENABLED=false, skipping actual send")
        log("DRY-RUN: smoke-ok")
        return 0

    # Live mode - validate required credentials
    log("TELEGRAM_PUSH_ENABLED=true, validating credentials...")

    # Check for missing or placeholder values
    if not bot_token or bot_token == "__FILL_ME__":
        error("TELEGRAM_BOT_TOKEN is missing or has placeholder value")
        error("Please set TELEGRAM_BOT_TOKEN in your environment")
        return 2

    if not chat_id or chat_id == "__FILL_ME__":
        error("TELEGRAM_CHAT_ID is missing or has placeholder value")
        error("Please set TELEGRAM_CHAT_ID in your environment")
        return 2

    # Log configuration (with masking)
    log(f"Bot token: {mask_sensitive(bot_token, 6)}")
    log(f"Chat ID: {mask_sensitive(chat_id, 4)}")
    if thread_id:
        log(f"Thread ID: {thread_id}")
    log(f"API base: {api_base}")

    # Send smoke test message
    try:
        log("Sending smoke test message...")
        result = send_telegram_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text="smoke-ok",
            thread_id=thread_id if thread_id else None,
            api_base=api_base
        )

        message_id = result.get("result", {}).get("message_id", "unknown")
        log(f"SUCCESS: Message sent (id={message_id})")
        return 0

    except Exception as e:
        error(f"Failed to send message: {str(e)}")
        error(f"Chat ID (masked): {mask_sensitive(chat_id, 4)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())