import json
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from api.cache import get_redis_client
from api.core.metrics_store import log_json
from api.schemas.topic import TopicSignalResponse
from api.services.topic_analyzer import TopicAnalyzer, postprocess_topic_signal

router = APIRouter(prefix="/signals", tags=["signals"])
analyzer = TopicAnalyzer()


@router.get("/topic", response_model=TopicSignalResponse)
async def get_topic_signal(
    topic_id: Optional[str] = Query(None), entities: Optional[str] = Query(None)
):
    """Get topic signal with slope and confidence metrics"""

    if not topic_id and not entities:
        raise HTTPException(400, "Either topic_id or entities required")

    try:
        # Parse entities if provided
        entity_list = None
        if entities:
            entity_list = [e.strip() for e in entities.split(",") if e.strip()]

        # Get topic analysis
        result = await analyzer.analyze_topic(topic_id=topic_id, entities=entity_list)

        log_json(
            stage="topic.signal",
            topic_id=result.topic_id,
            entities=result.topic_entities,
            slope_10m=result.slope_10m,
            slope_30m=result.slope_30m,
            confidence=result.confidence,
        )

        return result

    except Exception as e:
        log_json(
            stage="topic.error", error=str(e), topic_id=topic_id, entities=entities
        )
        raise HTTPException(500, f"Topic analysis failed: {str(e)}")
