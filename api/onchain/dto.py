"""Data Transfer Objects for on-chain rules engine."""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class OnchainFeature(BaseModel):
    """On-chain feature metrics for evaluation."""

    active_addr_pctl: float
    growth_ratio: float
    top10_share: float
    self_loop_ratio: float
    asof_ts: datetime
    window_min: int


class Verdict(BaseModel):
    """Evaluation verdict from rules engine."""

    decision: Literal["upgrade", "downgrade", "hold", "insufficient"]
    confidence: float
    note: Optional[str] = None


class Rules(BaseModel):
    """Parsed rules configuration."""

    windows: List[int]
    thresholds: Dict[str, Dict[str, float]]
    verdict: Dict[str, List[str]]
