"""DEX API routes for snapshot data"""
from typing import Optional, Dict, Any
import re
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse
from api.providers.dex_provider import DexProvider
from api.core.metrics_store import log_json

router = APIRouter(prefix="/dex", tags=["dex"])

# Supported chains
SUPPORTED_CHAINS = {"eth", "bsc", "base", "arb", "op", "sol"}

# EVM address regex pattern
EVM_ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")


@router.get("/snapshot")
async def get_dex_snapshot(
    chain: Optional[str] = Query(None, description="Blockchain network"),
    contract: Optional[str] = Query(None, description="Token contract address"),
) -> JSONResponse:
    """
    Get DEX snapshot data for a token.
    
    Returns price, liquidity, and other DEX metrics with fallback support.
    """
    # Parameter validation
    if not chain or not contract:
        log_json(stage="dex.api.error", status=400, reason="missing_params", 
                chain=chain, contract=contract)
        raise HTTPException(status_code=400, detail="missing params")
    
    if chain.lower() not in SUPPORTED_CHAINS:
        log_json(stage="dex.api.error", status=400, reason="invalid_chain", 
                chain=chain)
        raise HTTPException(status_code=400, detail="invalid chain")
    
    if not EVM_ADDRESS_PATTERN.match(contract):
        log_json(stage="dex.api.error", status=400, reason="invalid_contract", 
                contract=contract)
        raise HTTPException(status_code=400, detail="invalid contract")
    
    # Normalize contract to lowercase
    chain_norm = chain.lower()
    contract_norm = contract.lower()
    
    log_json(stage="dex.api.request", chain=chain_norm, contract=contract_norm)
    
    try:
        # Get snapshot from provider
        data: Dict[str, Any] = DexProvider().get_snapshot(chain_norm, contract_norm)
    except Exception as e:
        # Don't expose internal exceptions
        log_json(stage="dex.api.error", chain=chain_norm, contract=contract_norm, 
                error=str(e)[:120])
        # Return 503 with degraded response
        return JSONResponse(
            status_code=503,
            content={
                "price_usd": None, 
                "liquidity_usd": None, 
                "fdv": None,
                "ohlc": {"m5": None, "h1": None, "h24": None},
                "source": "", 
                "cache": False, 
                "stale": True, 
                "degrade": True,
                "reason": "provider_error"
            },
        )
    
    # Determine status code: 503 if no data available, else 200
    status = 503 if (data.get("reason") == "both_failed_no_cache") else 200
    
    log_json(stage="dex.api.response", chain=chain_norm, contract=contract_norm,
             status=status, source=data.get("source"), degrade=data.get("degrade"),
             stale=data.get("stale"), cache=data.get("cache"))
    
    # Ensure all required fields are present in response
    response = {
        "price_usd": data.get("price_usd"),
        "liquidity_usd": data.get("liquidity_usd"),
        "fdv": data.get("fdv"),
        "ohlc": data.get("ohlc", {"m5": None, "h1": None, "h24": None}),
        "source": data.get("source", ""),
        "cache": data.get("cache", False),
        "stale": data.get("stale", False),
        "degrade": data.get("degrade", False),
        "reason": data.get("reason", "")
    }
    
    return JSONResponse(status_code=status, content=response)