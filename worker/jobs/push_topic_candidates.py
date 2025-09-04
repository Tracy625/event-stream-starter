import os
import json
from datetime import datetime, timezone
from typing import Dict, Any

from celery import Celery
from api.cache import get_redis_client
from api.metrics import log_json, timeit
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

def format_topic_message(candidate: Dict[str, Any]) -> str:
    """Format topic candidate as Telegram message"""
    
    entities = candidate.get("entities", [])
    mention_count = candidate.get("mention_count", 0)
    evidence_links = candidate.get("evidence_links", [])
    
    # Build message
    lines = [
        "🔥 *Trending Topic Alert*",
        "",
        f"📊 Topic: {', '.join(entities)}",
        f"📈 Mentions (24h): {mention_count}",
        ""
    ]
    
    # Add evidence links
    if evidence_links:
        lines.append("🔗 Recent Posts:")
        for i, link in enumerate(evidence_links[:3], 1):
            lines.append(f"  {i}. {link}")
        lines.append("")
    
    # Add warning
    lines.extend([
        "⚠️ *Disclaimer:*",
        "_This is a trending topic alert. Not financial advice._",
        "_未落地为币，谨防仿冒_",
        "",
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    ])
    
    return "\n".join(lines)

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