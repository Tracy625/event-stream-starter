#!/usr/bin/env python3
"""
Test script for configuration hot reload functionality.

Usage:
    python api/scripts/test_hotreload.py
"""

import hashlib
import os
import sys
import time
from pathlib import Path

# Add api directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.config.hotreload import get_registry
from api.core.metrics_store import log_json


def main():
    """Test configuration hot reload."""
    print("[hotreload] Testing configuration hot reload...")

    # Initialize registry
    registry = get_registry()
    print(f"[hotreload] Registry initialized, version: {registry.snapshot_version()}")
    print(f"[hotreload] Hot reload enabled: {registry._enabled}")

    # Test 1: Get namespace
    print("\n[Test 1] Testing namespace access...")
    risk_rules = registry.get_ns("risk_rules")
    print(f"  risk_rules namespace has {len(risk_rules)} keys")

    onchain_rules = registry.get_ns("onchain")
    print(f"  onchain namespace has {len(onchain_rules)} keys")

    # Test 2: Get dotted path
    print("\n[Test 2] Testing dotted path access...")

    # Try to get a value from risk_rules
    honeypot_red = registry.get_path("risk_rules.HONEYPOT_RED", None)
    print(f"  risk_rules.HONEYPOT_RED = {honeypot_red}")

    # Try to get a value from onchain
    windows = registry.get_path("onchain.windows", [])
    print(f"  onchain.windows = {windows}")

    # Test 3: Check reload
    print("\n[Test 3] Testing reload check (no changes expected)...")
    reloaded = registry.reload_if_stale()
    print(f"  Reloaded: {reloaded}")

    # Test 4: Metrics
    print("\n[Test 4] Getting metrics...")
    metrics = registry.get_metrics()
    for key, value in metrics.items():
        print(f"  {key}: {value}")

    # Test 5: Force reload
    print("\n[Test 5] Testing force reload...")
    reloaded = registry.reload_if_stale(force=True)
    print(f"  Force reloaded: {reloaded}")
    print(f"  New version: {registry.snapshot_version()}")

    print("\n[hotreload] All tests completed successfully!")


if __name__ == "__main__":
    main()
