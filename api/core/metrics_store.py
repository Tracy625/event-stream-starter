"""
Metrics module for timing and structured logging.

Provides:
- timeit: Decorator to measure function execution time in milliseconds
- log_json: Function to output structured JSON logs with [JSON] prefix
- get_trace_id: Function to get current trace ID from context
- get_request_id: Function to get current request ID from context

Usage:
    @timeit("my-stage", backend="rules")
    def process_data(text: str) -> dict:
        return {"result": text.upper()}

    log_json("event", status="success", count=42)
"""

import time
import json
import functools
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from contextvars import ContextVar

# Context variables for request tracing
trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)
request_id_var: ContextVar[Optional[str]] = ContextVar('request_id', default=None)


def get_trace_id() -> Optional[str]:
    """Get current trace ID from context."""
    return trace_id_var.get()


def get_request_id() -> Optional[str]:
    """Get current request ID from context."""
    return request_id_var.get()


def set_trace_context(trace_id: str, request_id: str) -> None:
    """Set trace context for current request.

    Args:
        trace_id: Trace ID for distributed tracing
        request_id: Unique request ID
    """
    trace_id_var.set(trace_id)
    request_id_var.set(request_id)


def log_json(stage: str, **kv) -> None:
    """
    Output structured JSON log with [JSON] prefix.

    Args:
        stage: Stage identifier for the log entry
        **kv: Additional key-value pairs to include

    Output format:
        [JSON] {"ts_iso":"<ISO8601>","ts_epoch":<epoch>,"trace_id":"<trace>",
                "request_id":"<req>","level":"info","stage":"<stage>",
                "message":"<msg>","<key>":"<value>",...}

    Auto-injects trace_id and request_id from context if not provided.
    """
    now = datetime.now(timezone.utc)

    # Build payload with fixed keys in order
    payload = {
        "ts_iso": now.isoformat(),
        "ts_epoch": int(now.timestamp()),
        "trace_id": kv.pop("trace_id", None) or get_trace_id() or "no-trace",
        "request_id": kv.pop("request_id", None) or get_request_id() or "no-request",
        "level": kv.pop("level", "info"),
        "stage": stage,
        "message": kv.pop("message", f"Event: {stage}")
    }

    # Add provided key-value pairs, skipping None values
    for key, value in kv.items():
        if value is not None:
            payload[key] = value

    # Output JSON with [JSON] prefix, compact format
    json_str = json.dumps(payload, separators=(",", ":"))
    print(f"[JSON] {json_str}", flush=True)


def timeit(stage: str, backend: Optional[str] = None) -> Callable:
    """
    Decorator to measure function execution time in milliseconds.
    
    Args:
        stage: Stage name for logging
        backend: Optional backend identifier (defaults to "n/a")
    
    Logs JSON with fields:
        - stage: Provided stage name
        - backend: Backend identifier or "n/a"
        - ms: Execution time in milliseconds (integer)
        - ok: true on success, false on exception
        - ts_iso: ISO8601 timestamp in UTC
    
    Example:
        @timeit("filter", backend="rules")
        def filter_text(text: str) -> bool:
            return "crypto" in text.lower()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Start timing
            t0 = time.perf_counter()
            
            try:
                # Execute wrapped function
                result = func(*args, **kwargs)
                
                # Calculate elapsed time in milliseconds
                t1 = time.perf_counter()
                elapsed_ms = int(round((t1 - t0) * 1000))
                
                # Log success
                log_json(
                    stage=stage,
                    backend=backend or "n/a",
                    ms=elapsed_ms,
                    ok=True
                )
                
                return result
                
            except Exception as e:
                # Calculate elapsed time on failure
                t1 = time.perf_counter()
                elapsed_ms = int(round((t1 - t0) * 1000))
                
                # Log failure
                log_json(
                    stage=stage,
                    backend=backend or "n/a",
                    ms=elapsed_ms,
                    ok=False
                )
                
                # Re-raise original exception
                raise
        
        return wrapper
    return decorator