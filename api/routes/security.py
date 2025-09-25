"""Security check API routes"""
from typing import Dict, Any
from fastapi import APIRouter, Query, HTTPException
from api.schemas.security import SecurityResponse, SecuritySummary
from api.providers.goplus_provider import GoPlusProvider
from api.core.metrics_store import log_json

router = APIRouter(prefix="/security", tags=["security"])

def _to_response(result) -> SecurityResponse:
    """Convert provider result to response model with full pass-through of flags and raw data"""
    if result is None:
        # Return a default unknown response if result is None
        return SecurityResponse(
            degrade=True,
            cache=False,
            stale=False,
            summary=SecuritySummary(
                risk_label="unknown",
                buy_tax=None,
                sell_tax=None,
                lp_lock_days=None,
                honeypot=None,
                blacklist_flags=[],
            ),
            notes=["Error: No result from provider"],
            raw=None,
        )
    return SecurityResponse(
        degrade=bool(getattr(result, "degrade", False)),
        cache=bool(getattr(result, "cache", False)),
        stale=bool(getattr(result, "stale", False)),
        summary=SecuritySummary(
            risk_label=getattr(result, "risk_label", "unknown"),
            buy_tax=getattr(result, "buy_tax", None),
            sell_tax=getattr(result, "sell_tax", None),
            lp_lock_days=getattr(result, "lp_lock_days", None),
            honeypot=getattr(result, "honeypot", None),
            blacklist_flags=getattr(result, "blacklist_flags", []),
        ),
        notes=getattr(result, "notes", []),
        raw=getattr(result, "raw_response", None),
    )

@router.get("/token", response_model=SecurityResponse)
async def check_token_security(
    chain_id: str = Query(..., description="Blockchain chain ID"),
    address: str = Query(..., description="Token contract address"),
    raw: bool = Query(False, description="Include raw response data")
):
    """Check token security"""
    log_json(stage="security.api.request", endpoint="token", params={"chain_id": chain_id, "address": address, "raw": raw})
    try:
        provider = GoPlusProvider()
        result = provider.check_token(chain_id, address)
        response = _to_response(result)
        if not raw:
            response.raw = None
        log_json(stage="security.api.response", endpoint="token", status=200, cache=result.cache, degrade=result.degrade)
        return response
    except Exception as e:
        log_json(stage="security.api.error", endpoint="token", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/address", response_model=SecurityResponse)
async def check_address_security(
    address: str = Query(..., description="Wallet address to check"),
    raw: bool = Query(False, description="Include raw response data")
):
    """Check address security"""
    log_json(stage="security.api.request", endpoint="address", params={"address": address, "raw": raw})
    try:
        provider = GoPlusProvider()
        result = provider.check_address(address)
        response = _to_response(result)
        if not raw:
            response.raw = None
        log_json(stage="security.api.response", endpoint="address", status=200, cache=result.cache, degrade=result.degrade)
        return response
    except Exception as e:
        log_json(stage="security.api.error", endpoint="address", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/approval", response_model=SecurityResponse)
async def check_approval_security(
    chain_id: str = Query(..., description="Blockchain chain ID"),
    address: str = Query(..., description="Contract address"),
    type: str = Query("erc20", description="Token type", pattern=r"^(erc20|erc721|erc1155)$"),
    raw: bool = Query(False, description="Include raw response data")
):
    """Check approval security"""
    log_json(stage="security.api.request", endpoint="approval", params={"chain_id": chain_id, "address": address, "type": type, "raw": raw})
    try:
        provider = GoPlusProvider()
        result = provider.check_approval(chain_id, address, type=type)
        response = _to_response(result)
        if not raw:
            response.raw = None
        log_json(stage="security.api.response", endpoint="approval", status=200, cache=result.cache, degrade=result.degrade)
        return response
    except Exception as e:
        log_json(stage="security.api.error", endpoint="approval", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")