"""Onchain features API endpoints"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import create_engine
from sqlalchemy import text as sa_text
from sqlalchemy.orm import sessionmaker

from api.providers.onchain.bq_provider import BQProvider
from api.schemas.onchain import OnchainFeaturesResponse, WindowFeatures

try:
    from api.utils.cache import cache_get, cache_set
except ImportError:

    def cache_get(key: str) -> Optional[str]:
        return None

    def cache_set(key: str, value: str, ttl: int) -> None:
        pass


try:
    from api.utils.logging import log_json
except ImportError:

    def log_json(stage, **kwargs):
        print(f"[{stage}] {kwargs}")


router = APIRouter(prefix="/onchain", tags=["onchain"])

# Initialize provider
provider = BQProvider()

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv(
    "POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/guids"
)
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


@router.get("/features", response_model=OnchainFeaturesResponse)
async def get_onchain_features(
    chain: str = Query(..., description="Blockchain network"),
    address: str = Query(..., description="Contract address"),
) -> OnchainFeaturesResponse:
    """Get latest onchain features for an address across time windows"""

    # Validate chain
    if chain.lower() != "eth":
        raise HTTPException(
            status_code=400, detail="Only 'eth' chain is currently supported"
        )

    # Validate address (0x + 40 hex chars)
    if not re.match(r"^0x[a-fA-F0-9]{40}$", address):
        raise HTTPException(
            status_code=400,
            detail="Invalid address format (must be 0x + 40 hex characters)",
        )

    # Normalize
    chain = chain.lower()
    address = address.lower()

    # Check cache
    cache_key = f"onf:{chain}:{address}"
    cached = cache_get(cache_key)
    if cached:
        log_json(stage="onchain_features.cache_hit", chain=chain, address=address)
        response = json.loads(cached)
        response["cache"] = True
        return OnchainFeaturesResponse(**response)

    session = Session()
    try:
        windows_data = {}
        all_as_of_ts = []
        latest_calc_version = None

        # Query for each window
        for window in [30, 60, 180]:
            query = sa_text(
                """
                SELECT addr_active, tx_count, growth_ratio, top10_share, 
                       self_loop_ratio, calc_version, as_of_ts
                FROM onchain_features
                WHERE chain = :chain AND address = :address AND window_minutes = :window
                ORDER BY as_of_ts DESC
                LIMIT 1
            """
            )

            result = session.execute(
                query, {"chain": chain, "address": address, "window": window}
            ).first()

            if result:
                windows_data[str(window)] = WindowFeatures(
                    addr_active=result[0],
                    tx_count=result[1],
                    growth_ratio=float(result[2]) if result[2] else None,
                    top10_share=float(result[3]) if result[3] else None,
                    self_loop_ratio=float(result[4]) if result[4] else None,
                    calc_version=result[5],
                    as_of_ts=result[6],
                )
                all_as_of_ts.append(result[6])
                if result[6] == max(all_as_of_ts):
                    latest_calc_version = result[5]
            else:
                windows_data[str(window)] = None

        # Determine data_as_of and stale status
        data_as_of = max(all_as_of_ts) if all_as_of_ts else None
        stale = all(v is None for v in windows_data.values())

        response = OnchainFeaturesResponse(
            chain=chain,
            address=address,
            data_as_of=data_as_of,
            calc_version=latest_calc_version,
            windows=windows_data,
            stale=stale,
            degrade=None,
            cache=False,
        )

        # Cache the response (Pydantic v1/v2 compatible)
        try:
            cache_payload = response.model_dump_json()
        except AttributeError:
            cache_payload = response.json()
        cache_set(cache_key, cache_payload, ttl=60)

        return response

    except Exception as e:
        log_json(stage="onchain_features.error", error=str(e))
        return OnchainFeaturesResponse(
            chain=chain,
            address=address,
            data_as_of=None,
            calc_version=None,
            windows={"30": None, "60": None, "180": None},
            stale=True,
            degrade="query_error",
            cache=False,
        )
    finally:
        session.close()


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
async def get_freshness(
    chain: str = Query(..., description="Blockchain identifier (e.g., eth, polygon)")
):
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


@router.get("/query")
async def query_template(
    template: Literal[
        "active_addrs_window", "token_transfers_window", "top_holders_snapshot"
    ] = Query(..., description="Template name"),
    address: str = Query(..., description="Contract address"),
    from_ts: Optional[int] = Query(None, description="Start timestamp (unix seconds)"),
    to_ts: Optional[int] = Query(None, description="End timestamp (unix seconds)"),
    window_minutes: Optional[int] = Query(None, description="Time window in minutes"),
    top_n: Optional[int] = Query(
        20, description="Number of top holders (for top_holders_snapshot)"
    ),
):
    """
    Execute SQL template with guards and caching.

    Args:
        template: Template to execute
        address: Contract address to query
        from_ts: Start timestamp (unix seconds)
        to_ts: End timestamp (unix seconds)
        window_minutes: Alternative to from_ts/to_ts
        top_n: Number of top holders (default 20)

    Returns:
        Query results with metadata
    """
    log_json(
        stage="onchain.query",
        method="GET",
        template=template,
        address=address,
        window_minutes=window_minutes,
        from_ts=from_ts,
        to_ts=to_ts,
    )

    try:
        # Normalize parameters
        params = {"address": address}

        # Handle time window parameters
        if template != "top_holders_snapshot":
            # Time window is required for non-snapshot templates
            if window_minutes is not None:
                # Derive from window_minutes
                if not to_ts:
                    to_ts = int(time.time())
                if not from_ts:
                    from_ts = to_ts - (window_minutes * 60)
                params["window_minutes"] = window_minutes

            if from_ts and to_ts:
                # Validate bounds
                if from_ts >= to_ts:
                    return {
                        "stale": True,
                        "degrade": "invalid_params",
                        "reason": "from_ts must be less than to_ts",
                        "template": template,
                    }
                params["from_ts"] = from_ts
                params["to_ts"] = to_ts
                if not params.get("window_minutes"):
                    params["window_minutes"] = (to_ts - from_ts) // 60
            elif template in ["active_addrs_window", "token_transfers_window"]:
                # These templates require time window
                return {
                    "stale": True,
                    "degrade": "missing_params",
                    "reason": "time window required (provide from_ts/to_ts or window_minutes)",
                    "template": template,
                }

        if template == "top_holders_snapshot":
            params["top_n"] = top_n

        # Execute template with all guards
        result = provider.execute_template(template, params)
        return result

    except Exception as e:
        log_json(stage="onchain.query", error=str(e), template=template)
        return {"degrade": "internal_error", "template": template, "cache_hit": False}
