#!/usr/bin/env python3
"""Verify topic push to Telegram"""

import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/Users/tracy-mac/Desktop/GUIDS")

from api.cache import get_redis_client
from api.core.metrics_store import log_json
from api.services.telegram import TelegramNotifier
from worker.jobs.push_topic_candidates import format_topic_message


def verify_topic_push():
    """Verify Telegram push functionality"""

    redis = get_redis_client()
    notifier = TelegramNotifier()
    mock_mode = os.getenv("TELEGRAM_MODE", "").lower() == "mock"

    results = {"pass": False, "checks": [], "details": {}}

    try:
        # Test 1: Check Telegram bot configuration
        print("\n1. Testing Telegram bot connection...")

        if mock_mode:
            results["checks"].append({"test": "bot_token", "pass": True, "mock": True})
            print("  ✓ Skipped bot connection in mock mode")
        else:
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            if not token:
                results["checks"].append(
                    {
                        "test": "bot_token",
                        "pass": False,
                        "error": "TELEGRAM_BOT_TOKEN not set",
                    }
                )
                print("  ✗ TELEGRAM_BOT_TOKEN not configured")
            else:
                # Test bot connection
                bot_info = notifier.test_connection()

                if bot_info.get("success"):
                    results["checks"].append(
                        {
                            "test": "bot_token",
                            "pass": True,
                            "bot_username": bot_info.get("bot_username"),
                        }
                    )
                    print(f"  ✓ Bot connected: @{bot_info.get('bot_username')}")
                else:
                    results["checks"].append(
                        {
                            "test": "bot_token",
                            "pass": False,
                            "error": bot_info.get("error"),
                        }
                    )
                    print(f"  ✗ Bot connection failed: {bot_info.get('error')}")

        # Test 2: Check sandbox chat configuration
        print("\n2. Checking sandbox chat configuration...")

        chat_id = os.getenv("TELEGRAM_SANDBOX_CHAT_ID")

        if mock_mode:
            results["checks"].append(
                {"test": "chat_config", "pass": True, "mock": True}
            )
            chat_id = chat_id or "0"
            results["details"]["chat_id"] = chat_id
            print("  ✓ Skipped chat config in mock mode")
        elif not chat_id:
            results["checks"].append(
                {
                    "test": "chat_config",
                    "pass": False,
                    "error": "TELEGRAM_SANDBOX_CHAT_ID not set",
                }
            )
            print("  ✗ TELEGRAM_SANDBOX_CHAT_ID not configured")
        else:
            results["checks"].append(
                {"test": "chat_config", "pass": True, "chat_id": chat_id}
            )
            results["details"]["chat_id"] = chat_id
            print(f"  ✓ Chat ID configured: {chat_id}")

        # Test 3: Create mock topic candidate
        print("\n3. Creating mock topic candidate...")

        mock_candidate = {
            "topic_id": "t.mocktest123",
            "entities": ["pepe", "meme", "frog"],
            "mention_count": 137,
            "evidence_links": [
                "https://x.com/example/status/1",
                "https://x.com/example/status/2",
            ],
        }

        if redis:
            # Store in Redis
            push_key = f"topic:push:candidate:{mock_candidate['topic_id']}"
            redis.setex(push_key, 300, json.dumps(mock_candidate))  # 5 min TTL

            results["checks"].append(
                {
                    "test": "mock_candidate",
                    "pass": True,
                    "topic_id": mock_candidate["topic_id"],
                }
            )
            print(f"  ✓ Mock candidate created: {mock_candidate['topic_id']}")
        else:
            results["checks"].append(
                {
                    "test": "mock_candidate",
                    "pass": False,
                    "error": "Redis not available",
                }
            )
            print("  ✗ Redis not available")

        # Test 4: Format message
        print("\n4. Testing message formatting...")

        message = format_topic_message(mock_candidate)

        # Check message contains required elements
        required_elements = [
            "Trending Topic Alert",
            "pepe",
            "137",  # mention count
            "Disclaimer",
            "未落地为币，谨防仿冒",  # Chinese warning
        ]

        missing = [e for e in required_elements if e not in message]

        if not missing:
            results["checks"].append(
                {"test": "message_format", "pass": True, "length": len(message)}
            )
            print(f"  ✓ Message formatted correctly ({len(message)} chars)")
            print(f"\n--- Message Preview ---")
            print(message[:500] + ("..." if len(message) > 500 else ""))
            print(f"--- End Preview ---\n")
        else:
            results["checks"].append(
                {"test": "message_format", "pass": False, "missing": missing}
            )
            print(f"  ✗ Missing elements: {missing}")

        # Test 5: Send test message (if configured or in mock mode)
        if (chat_id and os.getenv("TELEGRAM_BOT_TOKEN")) or mock_mode:
            print("\n5. Sending test message to Telegram...")

            send_result = notifier.send_message(
                chat_id=chat_id, text=message, parse_mode="Markdown"
            )

            if send_result.get("success"):
                results["checks"].append(
                    {
                        "test": "send_message",
                        "pass": True,
                        "message_id": send_result.get("message_id"),
                    }
                )
                print(f"  ✓ Message sent! ID: {send_result.get('message_id')}")
                print(f"  Check your Telegram sandbox channel")

                # Log for audit
                log_json(
                    stage="verify.push.sent",
                    chat_id=chat_id,
                    message_id=send_result.get("message_id"),
                    topic_id=mock_candidate["topic_id"],
                )
            else:
                results["checks"].append(
                    {
                        "test": "send_message",
                        "pass": False,
                        "error": send_result.get("error"),
                    }
                )
                print(f"  ✗ Send failed: {send_result.get('error')}")
        else:
            results["checks"].append(
                {
                    "test": "send_message",
                    "pass": False,
                    "reason": "Telegram not configured",
                }
            )
            print("  ⚠ Skipped (Telegram not configured)")

        # Calculate overall pass/fail
        passed_checks = sum(1 for c in results["checks"] if c.get("pass"))
        total_checks = len(results["checks"])

        # For push verification, we need at least message formatting to work
        results["pass"] = passed_checks >= 2 and any(  # At least 2 checks pass
            c["test"] == "message_format" and c["pass"] for c in results["checks"]
        )

        results["summary"] = {
            "passed": passed_checks,
            "total": total_checks,
            "rate": f"{passed_checks}/{total_checks}",
            "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        }

        # Log results
        log_json(
            stage="verify.push.done",
            pass_rate=f"{passed_checks}/{total_checks}",
            overall_pass=results["pass"],
        )

    except Exception as e:
        results["error"] = str(e)
        log_json(stage="verify.push.error", error=str(e))
        print(f"\n✗ Error: {e}")

    # Output results
    print("\n" + "=" * 50)
    print("VERIFICATION RESULTS")
    print("=" * 50)
    print(json.dumps(results, indent=2))

    if mock_mode:
        print("\n✓ Running in MOCK mode - messages written to file")
        print(
            f"  Check: {os.getenv('TELEGRAM_MOCK_PATH', '/tmp/telegram_sandbox.jsonl')}"
        )
    elif not os.getenv("TELEGRAM_BOT_TOKEN"):
        print("\n⚠ Note: Set TELEGRAM_BOT_TOKEN and TELEGRAM_SANDBOX_CHAT_ID")
        print("  to enable full Telegram push testing")
        print("  Or set TELEGRAM_MODE=mock for local testing")

    return results["pass"]


def main():
    """Main entry point"""
    return verify_topic_push()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
