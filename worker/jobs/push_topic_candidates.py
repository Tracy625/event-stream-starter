import os
import json
from datetime import datetime, timezone
from typing import Dict, Any

from celery import Celery
from api.cache import get_redis_client
from api.core.metrics_store import log_json, timeit
from api.services.telegram import TelegramNotifier

app = Celery('worker')
app.config_from_object('celeryconfig')

@app.task
@timeit
def push_topic_to_telegram(topic_id: str):
    """Push topic candidate to Telegram"""
    
    redis = get_redis_client()
    notifier = TelegramNotifier()
    
    try:
        # Get candidate data from Redis
        push_key = f"topic:push:candidate:{topic_id}"
        
        if not redis:
            log_json(stage="push.topic.error", error="Redis not available")
            return {"success": False, "error": "Redis not available"}
        
        candidate_data = redis.get(push_key)
        
        if not candidate_data:
            log_json(
                stage="push.topic.missing",
                topic_id=topic_id
            )
            return {"success": False, "error": "Candidate not found"}
        
        candidate = json.loads(candidate_data)
        
        # Format message
        message = format_topic_message(candidate)
        
        # Send to Telegram
        chat_id = os.getenv("TELEGRAM_SANDBOX_CHAT_ID")
        
        if not chat_id:
            log_json(
                stage="push.topic.error",
                error="TELEGRAM_SANDBOX_CHAT_ID not configured"
            )
            return {"success": False, "error": "Telegram not configured"}
        
        result = notifier.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown"
        )
        
        if result.get("success"):
            log_json(
                stage="push.topic.sent",
                topic_id=topic_id,
                entities=candidate.get("entities"),
                mention_count=candidate.get("mention_count")
            )
            
            # Mark as pushed
            redis.delete(push_key)
            
            return {
                "success": True,
                "topic_id": topic_id,
                "message_id": result.get("message_id")
            }
        else:
            log_json(
                stage="push.topic.failed",
                topic_id=topic_id,
                error=result.get("error")
            )
            return {"success": False, "error": result.get("error")}
            
    except Exception as e:
        log_json(
            stage="push.topic.error",
            topic_id=topic_id,
            error=str(e)
        )
        return {"success": False, "error": str(e)}

def format_topic_message(c: Dict[str, Any]) -> str:
    """Format topic candidate into Telegram message - minimal version"""
    ents = c.get("entities") or []
    ents_show = ", ".join(ents[:5]) if ents else "(无)"
    latest_iso = (c.get("latest_ts") or "").isoformat() if hasattr(c.get("latest_ts"), "isoformat") else str(c.get("latest_ts", ""))
    # 最小文案 + 风险提示（避免引导交易与仿冒）
    return (
        f"🔥 热点话题：{ents_show}\n"
        f"📊 24h 提及：{c.get('mention_count', 0)}\n"
        f"🏷️ 实体：{ents_show}\n"
        f"🕒 最新：{latest_iso}\n"
        f"⚠️ 未落地为币，谨防仿冒"
    )

def push_to_telegram(text: str) -> Dict[str, Any]:
    """Direct push to Telegram using existing notifier"""
    notifier = TelegramNotifier()
    chat_id = os.getenv("TELEGRAM_TOPIC_CHAT_ID") or os.getenv("TELEGRAM_SANDBOX_CHAT_ID")

    if not chat_id:
        raise ValueError("TELEGRAM_TOPIC_CHAT_ID not configured")

    result = notifier.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML"
    )

    if not result.get("success"):
        raise Exception(f"Telegram send failed: {result.get('error')}")

    return result

@app.task
def push_topic_digest():
    """Push daily topic digest to Telegram"""
    
    redis = get_redis_client()
    notifier = TelegramNotifier()
    
    try:
        # Get today's digest
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        digest_key = f"topic:digest:{today}"
        
        if not redis:
            return {"success": False, "error": "Redis not available"}
        
        digest_data = redis.get(digest_key)
        
        if not digest_data:
            log_json(
                stage="push.digest.empty",
                date=today
            )
            return {"success": False, "error": "No digest for today"}
        
        digest = json.loads(digest_data)
        
        # Format digest message
        lines = [
            "📋 *Daily Topic Digest*",
            f"📅 {today}",
            "",
            "Top topics beyond daily cap:",
            ""
        ]
        
        for i, topic in enumerate(digest[:10], 1):
            entities = topic.get("entities", [])
            count = topic.get("mention_count", 0)
            lines.append(f"{i}. {', '.join(entities)} ({count} mentions)")
        
        lines.extend([
            "",
            f"Total overflow topics: {len(digest)}",
            "",
            "_Daily cap reached. These topics were aggregated._"
        ])
        
        message = "\n".join(lines)
        
        # Send digest
        chat_id = os.getenv("TELEGRAM_SANDBOX_CHAT_ID")
        
        result = notifier.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown"
        )
        
        if result.get("success"):
            log_json(
                stage="push.digest.sent",
                date=today,
                topic_count=len(digest)
            )
            return {"success": True, "date": today}
        else:
            log_json(
                stage="push.digest.failed",
                date=today,
                error=result.get("error")
            )
            return {"success": False, "error": result.get("error")}
            
    except Exception as e:
        log_json(
            stage="push.digest.error",
            error=str(e)
        )
        return {"success": False, "error": str(e)}
