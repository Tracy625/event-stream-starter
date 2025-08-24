"""
Deprecated shim. Do NOT use `api.refine` directly.
This module re-exports from `api.refiner` to avoid dual-implementation drift.
"""
from .refiner import *  # noqa: F401,F403