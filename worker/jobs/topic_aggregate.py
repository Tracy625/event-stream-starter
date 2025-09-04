import os
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from collections import defaultdict

from celery import Celery
from api.database import get_db
from api.cache import get_redis_client
from api.metrics import log_json, timeit
from api.services.topic_analyzer import TopicAnalyzer
from sqlalchemy import text as sa_text

app = Celery('worker')
app.config_from_object('celeryconfig')

@app.task
@timeit
def aggregate_topics():
    """Aggregate and merge topics over 24h window"""
    
    analyzer = TopicAnalyzer()
    redis = get_redis_client()
    
    window_hours = int(os.getenv("TOPIC_WINDOW_HOURS", "24"))
    daily_cap = int(os.getenv("DAILY_TOPIC_PUSH_CAP", "50"))
    
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=window_hours)
    
    log_json(stage="topic.aggregate.start", window_hours=window_hours)
    
    try:
        # Get all events with topics in window
        with get_db() as db:
            query = sa_text("""
                SELECT 
                    topic_hash,
                    topic_entities,
                    COUNT(*) as mention_count,
                    MAX(last_ts) as latest_ts,
                    array_agg(DISTINCT evidence_refs) as evidence_links
                FROM events
                WHERE last_ts >= :start_time
                    AND topic_hash IS NOT NULL
                GROUP BY topic_hash, topic_entities
                ORDER BY mention_count DESC
            """)
            
            results = db.execute(query, {"start_time": start_time}).fetchall()
            
            # Group topics for merging
            topic_groups = []
            merged_topics = set()
            
            for row in results:
                topic_id = row["topic_hash"]
                
                if topic_id in merged_topics:
                    continue
                
                # Parse entities
                entities = json.loads(row["topic_entities"]) if row["topic_entities"] else []
                
                if not entities:
                    continue
                
                # Check if should merge with existing group
                merged = False
                for group in topic_groups:
                    should_merge, merge_type = analyzer._check_similarity(
                        entities, 
                        group["entities"]
                    )
                    
                    if should_merge:
                        # Merge into group
                        group["mention_count"] += row["mention_count"]
                        group["topics"].append(topic_id)
                        group["latest_ts"] = max(group["latest_ts"], row["latest_ts"])
                        group["evidence_links"].extend(row["evidence_links"] or [])
                        merged_topics.add(topic_id)
                        merged = True
                        
                        log_json(
                            stage="topic.merge",
                            merge_type=merge_type,
                            topic_id=topic_id,
                            group_id=group["topic_id"]
                        )
                        break
                
                if not merged:
                    # Create new group
                    topic_groups.append({
                        "topic_id": topic_id,
                        "entities": entities,
                        "mention_count": row["mention_count"],
                        "topics": [topic_id],
                        "latest_ts": row["latest_ts"],
                        "evidence_links": row["evidence_links"] or []
                    })
            
            # Sort by mention count and apply daily cap
            topic_groups.sort(key=lambda x: x["mention_count"], reverse=True)
            
            # Store aggregated topics for push
            push_candidates = []
            
            for i, group in enumerate(topic_groups[:daily_cap]):
                # Check rate limit (1 hour per topic)
                rate_key = f"topic:pushed:{group['topic_id']}"
                
                if redis and redis.exists(rate_key):
                    log_json(
                        stage="topic.ratelimit",
                        topic_id=group["topic_id"],
                        skipped=True
                    )
                    continue
                
                push_candidates.append(group)
                
                # Set rate limit
                if redis:
                    redis.setex(rate_key, 3600, "1")  # 1 hour TTL
                
                # Store in Redis for push job
                if redis:
                    push_key = f"topic:push:candidate:{group['topic_id']}"
                    redis.setex(
                        push_key, 
                        3600,  # 1 hour TTL
                        json.dumps({
                            "topic_id": group["topic_id"],
                            "entities": group["entities"],
                            "mention_count": group["mention_count"],
                            "evidence_links": group["evidence_links"][:3]
                        })
                    )
            
            # Handle overflow (digest)
            if len(topic_groups) > daily_cap:
                digest_topics = topic_groups[daily_cap:]
                digest_key = f"topic:digest:{now.strftime('%Y%m%d')}"
                
                if redis:
                    redis.setex(
                        digest_key,
                        86400,  # 24 hour TTL
                        json.dumps([
                            {
                                "topic_id": g["topic_id"],
                                "entities": g["entities"],
                                "mention_count": g["mention_count"]
                            }
                            for g in digest_topics[:20]  # Limit digest to 20 items
                        ])
                    )
                
                log_json(
                    stage="topic.digest",
                    count=len(digest_topics),
                    date=now.strftime('%Y%m%d')
                )
            
            # Update topic mention time series in Redis
            for group in topic_groups:
                if redis:
                    ts_key = f"topic:mentions:{group['topic_id']}:{now.isoformat()}"
                    redis.setex(ts_key, 86400, str(group["mention_count"]))
            
            log_json(
                stage="topic.aggregate.done",
                total_topics=len(results),
                merged_groups=len(topic_groups),
                push_candidates=len(push_candidates),
                capped_at=daily_cap
            )
            
            # Trigger push job for candidates
            if push_candidates:
                from worker.jobs.push_topic_candidates import push_topic_to_telegram
                for candidate in push_candidates:
                    push_topic_to_telegram.delay(candidate["topic_id"])
            
            return {
                "success": True,
                "groups": len(topic_groups),
                "candidates": len(push_candidates)
            }
            
    except Exception as e:
        log_json(
            stage="topic.aggregate.error",
            error=str(e)
        )
        return {"success": False, "error": str(e)}