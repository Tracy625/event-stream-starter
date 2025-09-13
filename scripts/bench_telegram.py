#!/usr/bin/env python3
"""Telegram benchmark script for testing message sending"""
import os
import sys
import time
import json
import argparse
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("Error: requests module not available")
    sys.exit(1)


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Benchmark Telegram bot message sending")
    parser.add_argument("-n", "--n", type=int, default=5, help="Number of messages to send")
    parser.add_argument("--text", default="bench from scripts/bench_telegram.py", help="Message text")
    parser.add_argument("--event-prefix", default="bench", help="Event key prefix")
    parser.add_argument("--interval-ms", type=int, default=200, help="Interval between messages in ms")
    return parser.parse_args()


def get_config():
    """Get configuration from environment"""
    config = {
        "bot_token": os.getenv("TG_BOT_TOKEN", ""),
        "channel_id": os.getenv("TG_CHANNEL_ID", ""),
        "thread_id": os.getenv("TG_THREAD_ID", ""),
        "sandbox": os.getenv("TG_SANDBOX", "").lower() in ("1", "true", "yes"),
        "sandbox_channel_id": os.getenv("TG_SANDBOX_CHANNEL_ID", ""),
        "sandbox_thread_id": os.getenv("TG_SANDBOX_THREAD_ID", ""),
        "timeout_secs": int(os.getenv("TG_TIMEOUT_SECS", "6"))
    }
    
    # Parse channel IDs
    try:
        config["channel_id"] = int(config["channel_id"]) if config["channel_id"] else None
    except ValueError:
        config["channel_id"] = None
    
    try:
        config["thread_id"] = int(config["thread_id"]) if config["thread_id"] else None
    except ValueError:
        config["thread_id"] = None
        
    try:
        config["sandbox_channel_id"] = int(config["sandbox_channel_id"]) if config["sandbox_channel_id"] else None
    except ValueError:
        config["sandbox_channel_id"] = None
        
    try:
        config["sandbox_thread_id"] = int(config["sandbox_thread_id"]) if config["sandbox_thread_id"] else None
    except ValueError:
        config["sandbox_thread_id"] = None
    
    return config


def get_effective_target(config):
    """Get effective chat_id and thread_id considering sandbox mode"""
    if config["sandbox"] and config["sandbox_channel_id"]:
        chat_id = config["sandbox_channel_id"]
        thread_id = config["sandbox_thread_id"]
    else:
        chat_id = config["channel_id"]
        thread_id = config["thread_id"]
    
    return chat_id, thread_id


def build_link(chat_id, message_id):
    """Build Telegram message link if possible"""
    if chat_id and str(chat_id).startswith("-100"):
        channel_num = str(chat_id)[4:]
        return f"https://t.me/c/{channel_num}/{message_id}"
    return None


def send_message(bot_token, chat_id, thread_id, text, timeout_secs):
    """Send a single message to Telegram"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    if thread_id:
        payload["message_thread_id"] = thread_id
    
    start_time = time.time()
    
    try:
        response = requests.post(url, json=payload, timeout=timeout_secs)
        latency_ms = (time.time() - start_time) * 1000
        
        data = response.json()
        
        if data.get("ok"):
            return {
                "ok": True,
                "code": "200",
                "message_id": data["result"]["message_id"],
                "latency_ms": int(latency_ms)
            }
        else:
            return {
                "ok": False,
                "code": str(response.status_code),
                "error": data.get("description", "Unknown error"),
                "latency_ms": int(latency_ms)
            }
            
    except requests.exceptions.Timeout:
        latency_ms = (time.time() - start_time) * 1000
        return {
            "ok": False,
            "code": "timeout",
            "error": "Request timeout",
            "latency_ms": int(latency_ms)
        }
        
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return {
            "ok": False,
            "code": "error",
            "error": str(e),
            "latency_ms": int(latency_ms)
        }


def main():
    """Main benchmark function"""
    args = parse_args()
    config = get_config()
    
    if not config["bot_token"]:
        print("Error: TG_BOT_TOKEN not set")
        sys.exit(1)
    
    chat_id, thread_id = get_effective_target(config)
    
    if not chat_id:
        print("Error: No effective channel_id available")
        sys.exit(1)
    
    # Create output file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"/tmp/bench_telegram_{timestamp}.jsonl"
    
    print(f"Sending {args.n} messages to chat_id={chat_id}, thread_id={thread_id}")
    print(f"Output file: {output_file}")
    
    sent = 0
    ok_count = 0
    err_count = 0
    
    with open(output_file, "w") as f:
        for i in range(args.n):
            event_key = f"{args.event_prefix}_{i}_{int(time.time())}"
            
            result = send_message(
                config["bot_token"],
                chat_id,
                thread_id,
                args.text,
                config["timeout_secs"]
            )
            
            # Build record
            record = {
                "ts_iso": datetime.now(timezone.utc).isoformat(),
                "ok": result["ok"],
                "code": result["code"],
                "message_id": result.get("message_id"),
                "link": build_link(chat_id, result.get("message_id")) if result.get("message_id") else None,
                "chat_id": chat_id,
                "thread_id": thread_id,
                "event_key": event_key,
                "text_len": len(args.text),
                "latency_ms": result["latency_ms"],
                "error": result.get("error")
            }
            
            # Write to file
            f.write(json.dumps(record) + "\n")
            f.flush()
            
            sent += 1
            
            if result["ok"]:
                ok_count += 1
                link = record["link"]
                print(f"OK link={link if link else 'N/A'}")
            else:
                err_count += 1
                print(f"ERR code={result['code']} desc={result.get('error', 'Unknown')}")
            
            # Sleep between messages
            if i < args.n - 1:
                time.sleep(args.interval_ms / 1000.0)
    
    # Print summary
    print(f"\nsent={sent} ok={ok_count} err={err_count} file={output_file}")


if __name__ == "__main__":
    main()