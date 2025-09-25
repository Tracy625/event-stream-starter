"""
Refiner adapter for rule engine reasons.

Provides optional refinement of rule reasons through the existing refiner module,
with environment-controlled activation and timeout enforcement.
"""

import os
import asyncio
from typing import List, Tuple
from api.core.metrics_store import log_json


def maybe_refine_reasons(reasons: List[str]) -> Tuple[List[str], bool]:
    """
    Optionally refine rule reasons using the refiner module.
    
    Args:
        reasons: List of reason strings to potentially refine
        
    Returns:
        Tuple of (refined_reasons, refine_used)
        - refined_reasons: Either refined or original reasons
        - refine_used: True if refinement was successful, False otherwise
    """
    # Check if refinement is enabled
    if os.getenv("RULES_REFINER", "off").lower() != "on":
        return reasons, False
    
    if not reasons:
        return reasons, False
    
    try:
        # Enforce 800ms cap on timeout
        global_timeout = int(os.getenv("REFINE_TIMEOUT_MS", "3000"))
        timeout_ms = min(global_timeout, 800)
        
        # Try to get or create event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            # No event loop in current thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Call refine_evidence synchronously with timeout
        # Since refine_evidence is sync, we run it in executor with timeout
        async def _refine_with_timeout():
            return await asyncio.wait_for(
                loop.run_in_executor(
                    None, 
                    refine_evidence, 
                    reasons, 
                    {"hint": "rules.reasons"}
                ),
                timeout=timeout_ms / 1000.0
            )
        
        # Run the async function
        if loop.is_running():
            # If loop is already running (e.g., in FastAPI), create task
            future = asyncio.ensure_future(_refine_with_timeout())
            # Wait synchronously (blocking) - not ideal but maintains sync interface
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = executor.submit(asyncio.run, _refine_with_timeout()).result(timeout=timeout_ms/1000)
        else:
            # Run in the loop
            result = loop.run_until_complete(_refine_with_timeout())
        
        # Extract refined reasons from result
        if isinstance(result, dict):
            refined = result.get("reasons", reasons)
            if refined and isinstance(refined, list):
                # Ensure we don't change the number of reasons
                # Just refine the text content
                if len(refined) == len(reasons):
                    return refined, True
                else:
                    # If counts don't match, use original
                    log_json(
                        stage="rules.refine_degrade",
                        reason="count_mismatch",
                        original_count=len(reasons),
                        refined_count=len(refined)
                    )
                    return reasons, False
        
        # If result structure unexpected, use original
        return reasons, False
        
    except asyncio.TimeoutError:
        log_json(
            stage="rules.refine_degrade",
            reason="timeout",
            timeout_ms=timeout_ms
        )
        return reasons, False
        
    except Exception as e:
        log_json(
            stage="rules.refine_degrade",
            reason="exception",
            error=str(e)
        )
        return reasons, False


def maybe_refine_reasons_simple(reasons: List[str]) -> Tuple[List[str], bool]:
    """
    Simplified version without async complexity.
    
    Since refine_evidence is synchronous, we can call it directly
    with a simple timeout mechanism.
    """
    # Check if refinement is enabled
    if os.getenv("RULES_REFINER", "off").lower() != "on":
        return reasons, False
    
    if not reasons:
        return reasons, False
    
    try:
        # Import here to avoid import errors when refiner not available
        from api.refiner import refine_evidence
        
        # Call refine_evidence directly (it's synchronous)
        result = refine_evidence(reasons, hint="rules.reasons")
        
        # Extract refined reasons from result
        if isinstance(result, dict):
            refined = result.get("reasons", reasons)
            if refined and isinstance(refined, list):
                # Preserve the original number of reasons
                # Take same count from refined as we had originally
                refined = refined[:len(reasons)]
                # Pad with original if refined has fewer
                if len(refined) < len(reasons):
                    refined.extend(reasons[len(refined):])
                return refined, True
        
        return reasons, False
        
    except ImportError:
        log_json(
            stage="rules.refine_degrade",
            reason="import_error",
            error="Refiner module not available"
        )
        return reasons, False
    except Exception as e:
        log_json(
            stage="rules.refine_degrade",
            reason="exception",
            error=str(e)
        )
        return reasons, False


# Use the simple version as default since refine_evidence is sync
maybe_refine_reasons = maybe_refine_reasons_simple