from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime

class TopicSignalResponse(BaseModel):
    """Fixed output schema for topic signals"""
    type: Literal["topic"] = "topic"
    topic_id: str = Field(description="Topic identifier, format: t.{hash12}")
    topic_entities: List[str] = Field(description="Main entities for this topic")
    keywords: List[str] = Field(description="Extended keywords including entities")
    slope_10m: float = Field(description="10-minute window slope")
    slope_30m: float = Field(description="30-minute window slope")
    mention_count_24h: int = Field(description="Total mentions in 24 hours")
    confidence: float = Field(description="Confidence score 0-1")
    sources: List[str] = Field(description="Data sources used")
    evidence_links: List[str] = Field(description="1-3 original post links")
    calc_version: Literal["topic_v1"] = "topic_v1"
    ts: str = Field(description="ISO timestamp")
    degrade: bool = Field(description="Whether fallback was used")
    topic_merge_mode: str = Field(description="Merge mode: normal or fallback")

class TopicMergeConfig(BaseModel):
    """Topic merging configuration"""
    sim_threshold: float = Field(default=0.80)
    jaccard_fallback: float = Field(default=0.50)
    whitelist_boost: float = Field(default=0.05)
    window_hours: int = Field(default=24)
    slope_window_10m: int = Field(default=10)
    slope_window_30m: int = Field(default=30)