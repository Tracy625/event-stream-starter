"""
Re-export logging utilities from metrics module.

This module provides structured logging utilities with automatic trace context injection.
All logs are output as JSON with fixed fields for consistency:
- ts_iso: ISO8601 timestamp
- ts_epoch: Unix timestamp
- trace_id: Request trace ID (auto-injected from context)
- request_id: Request ID (auto-injected from context)
- level: Log level (default: info)
- stage: Event stage/category
- message: Human-readable message
- Additional fields as provided

Example:
    from api.utils.logging import log_json

    log_json("processing", status="started", count=100)
    # Output: [JSON] {"ts_iso":"2024-01-01T00:00:00Z","ts_epoch":1704067200,
    #                 "trace_id":"abc123","request_id":"def456","level":"info",
    #                 "stage":"processing","message":"Event: processing",
    #                 "status":"started","count":100}
"""

from api.core.metrics_store import (get_request_id, get_trace_id, log_json,
                                    set_trace_context, timeit)

__all__ = ["log_json", "timeit", "get_trace_id", "get_request_id", "set_trace_context"]
