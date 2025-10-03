"""
Rules evaluation API endpoint.

Provides GET /rules/eval endpoint to evaluate signals and events
against the rule engine and return risk levels, scores, and reasons.
"""

import time
import traceback
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from api.core.metrics_store import log_json
from api.database import get_db
from api.rules import RuleEvaluator

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("/eval")
async def evaluate_rules(
    event_key: str = Query(..., description="Event key to evaluate"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Evaluate rules for a given event key.

    Reads signals and events data from database, evaluates against
    rule engine, and returns level, score, reasons, and evidence.

    Args:
        event_key: The event key to evaluate
        db: Database session

    Returns:
        JSON response with evaluation results

    Raises:
        404: If event_key not found in database
        422: If parameters are invalid
        500: If internal error occurs
    """
    start_time = time.time()
    request_id = str(uuid4())

    try:
        # Query signals table for required fields
        signals_query = sa_text(
            """
            SELECT 
                goplus_risk,
                buy_tax,
                sell_tax,
                lp_lock_days,
                dex_liquidity,
                dex_volume_1h,
                heat_slope
            FROM signals
            WHERE event_key = :event_key
            ORDER BY ts DESC
            LIMIT 1
        """
        )

        signals_result = db.execute(signals_query, {"event_key": event_key}).first()

        # Query events table for required fields
        events_query = sa_text(
            """
            SELECT 
                last_sentiment_score
            FROM events
            WHERE event_key = :event_key
        """
        )

        events_result = db.execute(events_query, {"event_key": event_key}).first()

        # Check if any data exists
        if not signals_result and not events_result:
            raise HTTPException(
                status_code=404, detail=f"Event key '{event_key}' not found in database"
            )

        # Build data dictionaries with None for missing values
        signals_data = {}
        if signals_result:
            signals_data = {
                "goplus_risk": signals_result.goplus_risk,
                "buy_tax": signals_result.buy_tax,
                "sell_tax": signals_result.sell_tax,
                "lp_lock_days": signals_result.lp_lock_days,
                "dex_liquidity": signals_result.dex_liquidity,
                "dex_volume_1h": signals_result.dex_volume_1h,
                "heat_slope": signals_result.heat_slope,
            }
        else:
            # All signals fields are None if no record
            signals_data = {
                "goplus_risk": None,
                "buy_tax": None,
                "sell_tax": None,
                "lp_lock_days": None,
                "dex_liquidity": None,
                "dex_volume_1h": None,
                "heat_slope": None,
            }

        events_data = {}
        if events_result:
            events_data = {"last_sentiment_score": events_result.last_sentiment_score}
        else:
            # Event field is None if no record
            events_data = {"last_sentiment_score": None}

        # Evaluate rules
        evaluator = RuleEvaluator()
        result = evaluator.evaluate(signals_data, events_data)

        # Normalize reasons/all_reasons and enforce prefix & length constraints
        all_reasons = result.get("all_reasons", result.get("reasons", [])) or []
        reasons = result.get("reasons", []) or []
        if not isinstance(all_reasons, list):
            all_reasons = [str(all_reasons)]
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        # Ensure reasons is always the prefix of all_reasons and max length 3
        if not all_reasons or reasons != all_reasons[: len(reasons)]:
            reasons = all_reasons[:3]
        if len(reasons) > 3:
            reasons = reasons[:3]
        # Normalize missing list
        missing = result.get("missing", []) or []
        if not isinstance(missing, list):
            missing = [str(missing)]

        # Calculate latency
        latency_ms = int((time.time() - start_time) * 1000)

        # Log successful evaluation
        log_json(
            stage="rules.eval",
            event_key=event_key,
            level=result["level"],
            score=result["score"],
            reasons=reasons[:3],  # Ensure max 3 for logging
            all_reasons_n=len(all_reasons),  # Only log count, not full list
            missing=missing,
            rules_version=result.get("rules_version"),
            hot_reloaded=result.get("hot_reloaded", False),
            latency_ms=latency_ms,
            refine_used=result.get("refine_used", False),
            request_id=request_id,
            module="api.routes.rules",
        )

        # Build response
        response = {
            "event_key": event_key,
            "level": result["level"],
            "score": result["score"],
            "reasons": reasons,
            "all_reasons": all_reasons,
            "evidence": {
                "signals": signals_data,
                "events": events_data,
                "missing": missing,
            },
            "meta": {
                "rules_version": result["rules_version"],
                "hot_reloaded": result["hot_reloaded"],
                "refine_used": result.get("refine_used", False),
            },
        }

        return response

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Get truncated traceback
        tb_str = traceback.format_exc()
        # Truncate to single line, max 500 chars
        tb_line = tb_str.replace("\n", " ")[:500]

        # Log error with full context
        log_json(
            stage="rules.eval_error",
            event_key=event_key,
            error=f"{type(e).__name__}: {str(e)}"[:200],
            traceback=tb_line,
            rules_version=result.get("rules_version") if "result" in locals() else None,
            request_id=request_id,
            module="api.routes.rules",
        )

        # Return 500 error
        raise HTTPException(
            status_code=500, detail=f"Internal error evaluating rules: {str(e)}"
        )
