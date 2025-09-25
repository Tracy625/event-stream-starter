#!/usr/bin/env python3
"""
Demo script showing idempotency module usage in business scenarios.

Usage:
    python api/scripts/demo_idempotency.py
"""

import sys
import os
import time
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from api.core.idempotency import (
    seen, mark, seen_batch, mark_batch, stats
)


def demo_tweet_deduplication():
    """Demo: X/Twitter tweet deduplication"""
    print("\n=== Demo: Tweet Deduplication ===")

    # Simulate incoming tweets
    tweets = [
        {"id": "tweet_123", "author": "elonmusk", "text": "To the moon!"},
        {"id": "tweet_456", "author": "whale_alert", "text": "Large transfer detected"},
        {"id": "tweet_123", "author": "elonmusk", "text": "To the moon!"},  # Duplicate
        {"id": "tweet_789", "author": "cryptocom", "text": "New listing"},
    ]

    processed_count = 0
    duplicate_count = 0

    for tweet in tweets:
        tweet_key = f"tweet:{tweet['id']}"

        if seen(tweet_key):
            duplicate_count += 1
            print(f"  ⚠️  Duplicate tweet skipped: {tweet['id']} from @{tweet['author']}")
        else:
            # Process the tweet
            print(f"  ✓ Processing tweet: {tweet['id']} from @{tweet['author']}")
            print(f"     Content: '{tweet['text']}'")

            # Mark as processed
            mark(tweet_key, ttl_seconds=14 * 24 * 3600)  # 14 days TTL
            processed_count += 1

    print(f"\nSummary: {processed_count} processed, {duplicate_count} duplicates skipped")


def demo_webhook_idempotency():
    """Demo: Webhook idempotency handling"""
    print("\n=== Demo: Webhook Idempotency ===")

    def handle_webhook(webhook_id: str, payload: dict) -> dict:
        """Simulated webhook handler with idempotency"""

        # Check if we've already processed this webhook
        if seen(f"webhook:{webhook_id}"):
            print(f"  ⚠️  Webhook {webhook_id} already processed")
            return {"status": "already_processed", "webhook_id": webhook_id}

        # Process the webhook
        print(f"  ✓ Processing webhook {webhook_id}")
        print(f"     Payload: {json.dumps(payload, indent=2)}")

        # Simulate processing time
        time.sleep(0.1)

        # Mark as processed
        mark(f"webhook:{webhook_id}", ttl_seconds=7 * 24 * 3600)  # 7 days TTL

        return {"status": "success", "webhook_id": webhook_id, "processed_at": datetime.now().isoformat()}

    # Simulate webhook calls (including retries)
    webhooks = [
        {"id": "wh_001", "payload": {"event": "payment.success", "amount": 100}},
        {"id": "wh_002", "payload": {"event": "user.signup", "user_id": "u123"}},
        {"id": "wh_001", "payload": {"event": "payment.success", "amount": 100}},  # Retry
        {"id": "wh_003", "payload": {"event": "token.transfer", "from": "0x123", "to": "0x456"}},
    ]

    for webhook in webhooks:
        result = handle_webhook(webhook["id"], webhook["payload"])
        print(f"     Result: {result['status']}")


def demo_batch_event_processing():
    """Demo: Batch event processing with deduplication"""
    print("\n=== Demo: Batch Event Processing ===")

    # Simulate batch of events
    events = [
        "event_001", "event_002", "event_003", "event_004", "event_005",
        "event_002", "event_003",  # Duplicates
        "event_006", "event_007", "event_008"
    ]

    print(f"  Received {len(events)} events")

    # Check which events are new
    event_keys = [f"evt:{e}" for e in events]
    seen_results = seen_batch(event_keys)

    new_events = [evt for evt, key in zip(events, event_keys) if not seen_results[key]]
    duplicate_events = [evt for evt, key in zip(events, event_keys) if seen_results[key]]

    print(f"  📊 New events: {len(new_events)}")
    print(f"  📊 Duplicate events: {len(duplicate_events)}")

    if duplicate_events:
        print(f"     Duplicates: {', '.join(duplicate_events)}")

    # Process new events
    if new_events:
        print(f"\n  Processing {len(new_events)} new events...")

        # Mark all new events as processed in batch
        new_event_keys = [f"evt:{e}" for e in new_events]
        mark_batch(new_event_keys, ttl_seconds=24 * 3600)  # 24 hours TTL

        for event in new_events[:3]:  # Show first 3 for brevity
            print(f"     ✓ Processed: {event}")

        if len(new_events) > 3:
            print(f"     ... and {len(new_events) - 3} more")


def demo_card_send_deduplication():
    """Demo: Prevent duplicate Telegram card sends"""
    print("\n=== Demo: Card Send Deduplication ===")

    def send_card(event_key: str, channel_id: int, template: str = "v1"):
        """Simulate card send with deduplication"""

        # Create idempotency key
        idemp_key = f"card:{event_key}:{channel_id}:{template}"

        if seen(idemp_key):
            print(f"  ⚠️  Card already sent for event '{event_key}' to channel {channel_id}")
            return {"dedup": True, "sent": 0}

        # Send the card
        print(f"  ✓ Sending card for event '{event_key}' to channel {channel_id}")
        print(f"     Template: {template}")

        # Mark as sent
        mark(idemp_key, ttl_seconds=3600)  # 1 hour TTL

        return {"dedup": False, "sent": 1, "message_id": f"msg_{int(time.time())}"}

    # Simulate multiple send attempts
    attempts = [
        ("hot_token_alert", -1003006310940, "v1"),
        ("whale_movement", -1003006310940, "v1"),
        ("hot_token_alert", -1003006310940, "v1"),  # Duplicate
        ("hot_token_alert", -1003006310940, "v2"),  # Different template
        ("whale_movement", -1003006310940, "v1"),  # Duplicate
    ]

    for event_key, channel_id, template in attempts:
        result = send_card(event_key, channel_id, template)
        if result["dedup"]:
            print(f"     Result: Deduplicated")
        else:
            print(f"     Result: Sent (message_id: {result.get('message_id')})")


def show_statistics():
    """Show final statistics"""
    print("\n=== Final Statistics ===")

    final_stats = stats()

    print(f"  📊 Backend: {final_stats['backend']}")
    print(f"  📊 Total operations:")
    print(f"     - Hits: {final_stats['hits']}")
    print(f"     - Misses: {final_stats['misses']}")
    print(f"     - Marks: {final_stats['marks']}")
    print(f"  📊 Hit rate: {final_stats['hit_rate']:.1f}%")

    if final_stats['backend'] == 'redis':
        print(f"  📊 Redis available: {final_stats.get('redis_available', False)}")
    else:
        print(f"  📊 Memory keys: {final_stats.get('memory_keys', 0)}")


def main():
    """Run all demos"""
    print("=" * 60)
    print("Idempotency Module Business Demos")
    print("=" * 60)

    # Run demos
    demo_tweet_deduplication()
    demo_webhook_idempotency()
    demo_batch_event_processing()
    demo_card_send_deduplication()

    # Show statistics
    show_statistics()

    print("\n" + "=" * 60)
    print("✅ All demos completed!")


if __name__ == "__main__":
    main()