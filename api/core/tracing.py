"""Trace ID management using contextvars"""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

# Context variable for trace ID
_trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def get_trace_id() -> str:
    """Get current trace ID or generate a new one"""
    trace_id = _trace_id_var.get()
    if not trace_id:
        trace_id = str(uuid.uuid4())
        _trace_id_var.set(trace_id)
    return trace_id


def set_trace_id(value: str) -> None:
    """Set the current trace ID"""
    _trace_id_var.set(value)


@contextmanager
def trace_ctx(trace_id: Optional[str] = None):
    """Context manager for trace ID"""
    if trace_id:
        token = _trace_id_var.set(trace_id)
    else:
        trace_id = str(uuid.uuid4())
        token = _trace_id_var.set(trace_id)

    try:
        yield trace_id
    finally:
        if trace_id:
            _trace_id_var.reset(token)
