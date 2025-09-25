"""
Signals API routes.
"""

import os
from datetime import datetime, timezone
from fastapi import APIRouter, Query, HTTPException, Depends
from typing import Optional
from sqlalchemy.orm import Session

try:
    from api.database import get_db
except Exception:
    from api.db import get_db

from api.signals.heat import normalize_token, normalize_token_ca, compute_heat, persist_heat
from api.core.metrics_store import log_json


router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/heat")
async def get_heat(
    token: Optional[str] = Query(None, description="Token symbol"),
    token_ca: Optional[str] = Query(None, description="Token contract address"),
    db: Session = Depends(get_db),
):
    """
    Get heat metrics for a token.
    
    Priority: token_ca > token
    Returns heat metrics including counts, slope, and trend.
    """
    # Validate parameters - exactly one required
    if not token and not token_ca:
        raise HTTPException(
            status_code=400, 
            detail={"degrade": True, "error": "Either token or token_ca required"}
        )
    
    if token and token_ca:
        raise HTTPException(
            status_code=400,
            detail={"degrade": True, "error": "Provide either token or token_ca, not both"}
        )
    
    # Normalize inputs
    normalized_token = None
    normalized_ca = None
    
    try:
        if token:
            normalized_token = normalize_token(token)
            if not normalized_token:
                raise HTTPException(
                    status_code=400,
                    detail={"degrade": True, "error": "Invalid token symbol"}
                )
        
        if token_ca:
            normalized_ca = normalize_token_ca(token_ca)
            if not normalized_ca:
                raise HTTPException(
                    status_code=400,
                    detail={"degrade": True, "error": "Invalid token contract address"}
                )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"degrade": True, "error": str(e)}
        )
    
    try:
        # Decide persistence upfront
        enable_persist = os.getenv("HEAT_ENABLE_PERSIST", "false").lower() in ("true", "1", "yes", "on")
        persisted = False

        # Compute and (optionally) persist within a single transaction
        with db.begin():
            heat = compute_heat(db, token=normalized_token, token_ca=normalized_ca)
            if enable_persist:
                persisted = persist_heat(
                    db,
                    token=normalized_token,
                    token_ca=normalized_ca,
                    heat=heat,
                    upsert=None,
                    strict_match=None,
                )

        # Build response with all heat fields
        response = {
            "token": normalized_token,
            "token_ca": normalized_ca,
            "cnt_10m": heat["cnt_10m"],
            "cnt_30m": heat["cnt_30m"],
            "slope": heat["slope"],
            "trend": heat["trend"],
            "window": heat["window"],
            "degrade": heat["degrade"],
            "persisted": persisted,
            "asof_ts": heat.get("asof_ts"),
            "from_cache": heat.get("from_cache", False)
        }

        # Add EMA fields if present
        if "slope_ema" in heat:
            response["slope_ema"] = heat["slope_ema"]
            response["trend_ema"] = heat["trend_ema"]

        return response
        
    except Exception as e:
        # Return degraded response on error
        log_json(
            stage="signals.heat.error",
            error=str(e),
            token=token,
            token_ca=token_ca
        )
        
        return {
            "token": normalized_token,
            "token_ca": normalized_ca,
            "cnt_10m": 0,
            "cnt_30m": 0,
            "slope": None,
            "trend": "flat",
            "window": {"ten": 600, "thirty": 1800},
            "degrade": True,
            "persisted": False,
            "asof_ts": datetime.now(timezone.utc).isoformat(),
            "from_cache": False
        }