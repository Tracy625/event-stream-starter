"""Onchain feature schemas"""
from datetime import datetime
from typing import Optional, Dict, Union
from decimal import Decimal
from pydantic import BaseModel, Field


class WindowFeatures(BaseModel):
    """Features for a specific time window"""
    addr_active: Optional[int] = None
    tx_count: Optional[int] = None
    growth_ratio: Optional[Union[Decimal, float]] = None
    top10_share: Optional[Union[Decimal, float]] = None
    self_loop_ratio: Optional[Union[Decimal, float]] = None
    calc_version: int
    as_of_ts: datetime
    
    class Config:
        json_encoders = {
            Decimal: float
        }


class OnchainFeaturesResponse(BaseModel):
    """Response for onchain features endpoint"""
    chain: str
    address: str
    data_as_of: Optional[datetime] = None
    calc_version: Optional[int] = None
    windows: Dict[str, Optional[WindowFeatures]]
    stale: bool = False
    degrade: Optional[str] = None
    cache: bool = False