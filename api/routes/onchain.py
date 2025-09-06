"""Onchain data routes with BigQuery backend."""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from api.providers.onchain.bq_provider import BQProvider
from api.utils.logging import log_json

router = APIRouter(prefix="/onchain", tags=["onchain"])

# Initialize provider
provider = BQProvider()


@router.get("/healthz")
async def health_check():
    """
    Health check endpoint with connectivity and dry-run probe.
    
    Returns:
        Health status including dry-run metrics
    """
    log_json(stage="onchain.healthz", method="GET")
    
    try:
        result = provider.healthz()
        
        # Always return 200, even for degraded responses
        return result
        
    except Exception as e:
        log_json(stage="onchain.healthz", error=str(e))
        # Return degraded response instead of raising
        return {"degrade": True, "reason": "internal_error"}


@router.get("/freshness")
async def get_freshness(chain: str = Query(..., description="Blockchain identifier (e.g., eth, polygon)")):
    """
    Get data freshness for a specific blockchain.
    
    Args:
        chain: Blockchain identifier
        
    Returns:
        Latest block number and data timestamp
    """
    log_json(stage="onchain.freshness", method="GET", chain=chain)
    
    try:
        result = provider.freshness(chain)
        
        # Always return 200, even for degraded responses
        return result
        
    except Exception as e:
        log_json(stage="onchain.freshness", error=str(e), chain=chain)
        # Return degraded response instead of raising
        return {"degrade": True, "reason": "internal_error", "chain": chain}