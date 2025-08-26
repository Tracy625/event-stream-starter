"""Security check schemas for GoPlus integration"""
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime


# Request schemas
class TokenSecurityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chain_id: str = Field(..., description="Blockchain chain ID")
    address: str = Field(..., description="Token contract address")
    raw: bool = Field(False, description="Include raw response data")


class AddressSecurityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(..., description="Wallet address to check")
    raw: bool = Field(False, description="Include raw response data")


class ApprovalSecurityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chain_id: str = Field(..., description="Blockchain chain ID")
    address: str = Field(..., description="Contract address")
    type: Literal["erc20", "erc721", "erc1155"] = Field("erc20", description="Token type")
    raw: bool = Field(False, description="Include raw response data")


# Response schemas
class SecuritySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_label: Literal["red", "yellow", "green", "unknown"] = Field(..., description="Risk assessment label")
    buy_tax: Optional[float] = Field(None, description="Buy tax percentage")
    sell_tax: Optional[float] = Field(None, description="Sell tax percentage")
    lp_lock_days: Optional[int] = Field(None, description="Liquidity pool lock days")
    honeypot: Optional[bool] = Field(None, description="Honeypot detection")
    blacklist_flags: List[str] = Field(default_factory=list, description="Blacklist indicators")


class SecurityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    degrade: bool = Field(False, description="Whether response is degraded/fallback")
    cache: bool = Field(False, description="Whether response is from cache")
    stale: bool = Field(False, description="Whether cached data is stale")
    summary: SecuritySummary = Field(..., description="Security check summary")
    notes: List[str] = Field(default_factory=list, description="Additional notes or warnings")
    raw: Optional[Dict[str, Any]] = Field(None, description="Raw API response if requested")


# Cache schemas
class GoPlusCacheEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str
    chain_id: Optional[str]
    key: str
    payload_hash: Optional[str]
    resp_json: Dict[str, Any]
    status: str
    fetched_at: datetime
    expires_at: datetime


# Provider result schema
class SecurityResult(BaseModel):
    """Internal security check result from provider"""
    model_config = ConfigDict(extra="forbid")
    risk_label: Literal["red", "yellow", "green", "unknown"]
    buy_tax: Optional[float] = None
    sell_tax: Optional[float] = None
    lp_lock_days: Optional[int] = None
    honeypot: Optional[bool] = None
    blacklist_flags: List[str] = Field(default_factory=list)
    degrade: bool = False
    cache: bool = False
    stale: bool = False
    raw_response: Optional[Dict[str, Any]] = None
    notes: List[str] = Field(default_factory=list)