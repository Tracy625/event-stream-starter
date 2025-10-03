import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError

from api.core.metrics_store import log_json
from api.database import build_engine_from_env, get_sessionmaker
from worker.app import app


def get_db_session():
    """Get database session consistent with other worker jobs"""
    engine = build_engine_from_env()
    SessionLocal = get_sessionmaker(engine)
    return SessionLocal()


@app.task
def aggregate_topics():
    """
    24h 窗口内对话题做聚合，输出候选
    """
    # Manual timing since @timeit is incompatible with @app.task
    start_time_perf = time.perf_counter()

    window_hours = int(os.getenv("TOPIC_AGG_WINDOW_HOURS", "24"))
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=window_hours)

    session = get_db_session()

    try:
        # Check database dialect for compatibility
        if session.bind.dialect.name == "sqlite":
            # SQLite-compatible query using GROUP_CONCAT
            query = sa_text(
                """
                SELECT
                    topic_hash,
                    GROUP_CONCAT(topic_entities, ',') AS all_entities,
                    COUNT(*) AS mention_count,
                    MAX(last_ts) AS latest_ts
                FROM events
                WHERE last_ts >= :start_time
                  AND topic_hash IS NOT NULL
                GROUP BY topic_hash
                ORDER BY mention_count DESC
            """
            )
        else:
            # PostgreSQL query using ARRAY_AGG
            query = sa_text(
                """
                SELECT
                    topic_hash,
                    ARRAY_AGG(DISTINCT topic_entities) FILTER (WHERE topic_entities IS NOT NULL) AS all_entities,
                    COUNT(*) AS mention_count,
                    MAX(last_ts) AS latest_ts
                FROM events
                WHERE last_ts >= :start_time
                  AND topic_hash IS NOT NULL
                GROUP BY topic_hash
                ORDER BY mention_count DESC
            """
            )

        # Must use .mappings() for dict-style access
        rows = session.execute(query, {"start_time": start_time}).mappings().fetchall()

        merged_topics = {}
        empty_entities_groups = 0

        for row in rows:
            topic_id = row["topic_hash"]
            if topic_id in merged_topics:
                continue

            entities = set()

            if session.bind.dialect.name == "sqlite":
                # SQLite: GROUP_CONCAT returns concatenated JSON arrays as string
                if row["all_entities"]:
                    import json

                    # GROUP_CONCAT joins with comma, but JSON arrays also have commas
                    # So we get something like: ["pepe","gem"],["pepe"]
                    # Need to split carefully
                    raw_str = row["all_entities"]

                    # Try to parse as single JSON array first
                    try:
                        parsed = json.loads(raw_str)
                        if isinstance(parsed, list):
                            for e in parsed:
                                if e:
                                    entities.add(str(e).strip())
                    except (json.JSONDecodeError, TypeError):
                        # If that fails, try splitting on ],[ boundaries
                        # Add brackets back to make valid JSON
                        parts = raw_str.replace("],[", "]|||[").split("|||")
                        for part in parts:
                            part = part.strip()
                            if not part:
                                continue
                            # Ensure it has brackets
                            if not part.startswith("["):
                                part = "[" + part
                            if not part.endswith("]"):
                                part = part + "]"
                            try:
                                parsed = json.loads(part)
                                if isinstance(parsed, list):
                                    for e in parsed:
                                        if e:
                                            entities.add(str(e).strip())
                            except (json.JSONDecodeError, TypeError):
                                # Last resort: treat as plain string
                                entities.add(part)
            else:
                # PostgreSQL: Process array of arrays
                raw_groups = row["all_entities"] or []
                for group in raw_groups:
                    if not group:
                        continue
                    # group is a list/tuple of entities
                    for ent in group:
                        if ent is not None:
                            s = str(ent).strip()
                            if s:
                                entities.add(s)

            # Convert set to sorted list
            entities = sorted(entities)

            if not entities:
                empty_entities_groups += 1
                continue

            merged_topics[topic_id] = {
                "topic_id": topic_id,
                "entities": entities,
                "mention_count": int(row["mention_count"]),
                "latest_ts": row["latest_ts"],
                # 下游如依赖该字段：给出空列表占位，避免 KeyError
                "evidence_links": [],
            }

        candidates = list(merged_topics.values())

        # Push high-quality topics to Telegram (强耦合上线版)
        from api.cache import get_redis_client
        from worker.jobs.push_topic_candidates import (format_topic_message,
                                                       push_to_telegram)

        push_enabled = os.getenv("TOPIC_PUSH_ENABLED", "true").lower() == "true"
        min_mentions = int(os.getenv("TOPIC_PUSH_MIN_MENTIONS", "3"))
        cooldown = int(os.getenv("TOPIC_PUSH_COOLDOWN_SEC", "3600"))
        redis = get_redis_client()

        if push_enabled and redis:
            for c in candidates:
                log_json(
                    stage="topic.push.consider",
                    topic_id=c["topic_id"],
                    mention_count=c["mention_count"],
                )

                if c["mention_count"] < min_mentions:
                    log_json(
                        stage="topic.push.skipped_threshold",
                        topic_id=c["topic_id"],
                        min_mentions=min_mentions,
                    )
                    continue

                dedup_key = f"topic:dedup:{c['topic_id']}"
                if redis.get(dedup_key):
                    log_json(stage="topic.push.skipped_dedup", topic_id=c["topic_id"])
                    continue

                # 先占坑再推送，避免并发双发
                try:
                    redis.setex(dedup_key, cooldown, "1")
                except Exception as e:
                    log_json(
                        stage="topic.push.redis.error",
                        topic_id=c["topic_id"],
                        error=str(e),
                    )
                    # 不阻断；继续尝试推送，但这会失去去重保护

                try:
                    text = format_topic_message(c)
                    push_to_telegram(text)  # 同步调用
                    log_json(stage="topic.push.sent", topic_id=c["topic_id"])
                except Exception as e:
                    log_json(
                        stage="topic.push.error", topic_id=c["topic_id"], error=str(e)
                    )
                    # 发送失败可考虑释放去重坑（可选）
                    try:
                        redis.delete(dedup_key)
                    except Exception:
                        pass

        result = {
            "success": True,
            "window_hours": window_hours,
            "groups": len(merged_topics),
            "empty_entities_groups": empty_entities_groups,
            "candidates": candidates,
        }

        # Log metrics (exclude candidates to avoid log bloat)
        log_json(
            stage="topic.aggregate.done",
            **{k: v for k, v in result.items() if k != "candidates"},
        )

        # Log execution time
        elapsed_ms = int((time.perf_counter() - start_time_perf) * 1000)
        log_json(stage="topic.aggregate.timing", elapsed_ms=elapsed_ms)

        return result

    except SQLAlchemyError as e:
        log_json(stage="topic.aggregate.error", error=str(e))

        # Log execution time even on failure
        elapsed_ms = int((time.perf_counter() - start_time_perf) * 1000)
        log_json(stage="topic.aggregate.timing", elapsed_ms=elapsed_ms)

        return {"success": False, "error": str(e)}
    finally:
        session.close()
