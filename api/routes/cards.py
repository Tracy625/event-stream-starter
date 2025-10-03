"""
Day19 Card Preview Route - GET /cards/preview
"""

import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from api.cards.build import build_card

router = APIRouter(prefix="/cards", tags=["cards"])
logger = logging.getLogger("cards.preview")


@router.get("/preview", summary="Preview internal card")
async def preview_card(
    event_key: str = Query(
        ...,
        min_length=8,
        max_length=128,
        regex="^[A-Z0-9:_\\-\\.]{8,128}$",  # align with cards.schema.json
        description="Event key (8–128 chars, matches cards.schema.json)",
    ),
    render: int = Query(
        0, ge=0, le=1, description="Set to 1 to enable rendered output"
    ),
) -> dict:
    """
    Preview a card by event_key

    Returns a schema-compliant card object with optional rendering.

    Parameters:
    - event_key: Event identifier matching pattern ^[A-Z0-9:_\\-\\.]{8,128}$ (uppercase only)
    - render: 0 (default) or 1 to enable template rendering

    Returns:
    - 200: Schema-compliant card object
    - 404: Event key not found
    - 422: Invalid parameters
    - 500: Internal error

    Example response:
    ```json
    {
        "card_type": "primary",
        "event_key": "ETH:TOKEN:0X123",
        "data": {
            "goplus": {
                "risk": "yellow",
                "risk_source": "GoPlus@v1.0"
            },
            "dex": {
                "price_usd": 0.001234
            },
            "rules": {
                "level": "watch"
            }
        },
        "summary": "ETH | 价格≈$0.001234 | 规则判定watch",
        "risk_note": "合约体检yellow；关注税率/LP/交易限制",
        "meta": {
            "version": "cards@19.0",
            "data_as_of": "2025-09-12T10:00:00Z",
            "summary_backend": "template"
        }
    }
    ```
    """
    request_id = str(uuid.uuid4())
    status_code = 200

    try:
        # Build card
        card = build_card(event_key, render=bool(render))

        # Log successful request
        log_data = {
            "request_id": request_id,
            "event_key": event_key,
            "render": render,
            "status": 200,
        }
        logger.info(json.dumps(log_data, ensure_ascii=False))

        return card

    except ValueError as e:
        # Handle validation errors and "no usable sources"
        error_msg = str(e)
        status_code = 422

        # Log error
        log_data = {
            "request_id": request_id,
            "event_key": event_key,
            "render": render,
            "status": status_code,
            "error": error_msg,
        }
        logger.warning(json.dumps(log_data, ensure_ascii=False))

        raise HTTPException(status_code=status_code, detail=error_msg)

    except (KeyError, LookupError) as e:
        # Handle not found errors
        status_code = 404
        error_msg = f"Event key not found: {event_key}"

        # Log not found
        log_data = {
            "request_id": request_id,
            "event_key": event_key,
            "render": render,
            "status": status_code,
            "error": error_msg,
        }
        logger.warning(json.dumps(log_data, ensure_ascii=False))

        raise HTTPException(status_code=status_code, detail=error_msg)

    except Exception as e:
        # Handle unexpected errors
        status_code = 500
        error_msg = f"Internal server error: {str(e)}"

        # Log error
        log_data = {
            "request_id": request_id,
            "event_key": event_key,
            "render": render,
            "status": status_code,
            "error": str(e),
        }
        logger.error(json.dumps(log_data, ensure_ascii=False))

        raise HTTPException(status_code=status_code, detail="Internal server error")
