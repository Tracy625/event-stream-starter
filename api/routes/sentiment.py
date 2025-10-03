# DEPRECATED shim: unify import path for sentiment routes
# Robustly locate an APIRouter from legacy module by scanning attributes
# and common factory functions, instead of guessing a specific variable name.

from importlib import import_module
from typing import Any

try:
    mod = import_module("api.sentiment.router")
except Exception as e:
    raise ImportError("Cannot import legacy module api.sentiment.router") from e

# 1) Quick tries for common names
candidate = None
for name in ("router", "sentiment_router", "routes"):
    candidate = getattr(mod, name, None)
    if candidate is not None:
        break

# 2) Scan all attributes for an APIRouter instance
if candidate is None:
    try:
        from fastapi import APIRouter  # imported only for isinstance check

        for name in dir(mod):
            obj: Any = getattr(mod, name)
            if isinstance(obj, APIRouter):
                candidate = obj
                break
    except Exception:
        # fall through to function factories
        pass

# 3) Try common factory functions that return a router
if candidate is None:
    for fn_name in ("get_router", "build_router", "make_router", "create_router"):
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            obj = fn()
            # accept APIRouter or any object with a 'routes' attribute
            if getattr(obj, "routes", None) is not None:
                candidate = obj
                break

# Finalize
if candidate is None or getattr(candidate, "routes", None) is None:
    raise ImportError(
        "api.routes.sentiment shim could not locate an APIRouter in api.sentiment.router. "
        "Tried common names, attribute scan, and factory functions."
    )

router = candidate
__all__ = ["router"]
