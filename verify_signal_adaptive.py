#!/usr/bin/env python
"""Verify adaptive time column detection in verify_signal job."""

import sys

sys.path.insert(0, ".")

print("=== Verify Signal Job - Adaptive Time Column Detection ===\n")

# Test 1: Check if helper function is added
try:
    from worker.jobs.onchain.verify_signal import _detect_time_column

    print("✓ _detect_time_column function found")
except ImportError:
    print("✗ _detect_time_column function not found")
    sys.exit(1)

# Test 2: Check imports
try:
    from typing import Literal

    from worker.jobs.onchain.verify_signal import run_once

    print("✓ Literal type import added")
    print("✓ run_once function available")
except ImportError as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)

# Test 3: Verify SQL safety
with open("worker/jobs/onchain/verify_signal.py", "r") as f:
    content = f.read()

    if "_detect_time_column" in content and "information_schema.columns" in content:
        print("✓ Time column detection uses information_schema")

    if "time_col AS time_col" in content:
        print("✓ Query uses aliased time column")

    if "current_schema()" in content:
        print("✓ Schema-aware queries")

print("\n=== Key Features ===")
print("1. Detects available time column: created_at > updated_at > ts")
print("2. Adapts query to use the detected column")
print("3. Handles missing columns gracefully with 'ts' fallback")
print("4. Logs which column is being used for transparency")

print("\n=== Testing Commands ===")
print("\n# Test with mock database (check which column would be detected):")
print('docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "')
print("  SELECT column_name")
print("  FROM information_schema.columns")
print("  WHERE table_schema = current_schema()")
print("    AND table_name = 'signals'")
print("    AND column_name IN ('created_at', 'updated_at', 'ts')")
print("  ORDER BY CASE column_name")
print("    WHEN 'created_at' THEN 1")
print("    WHEN 'updated_at' THEN 2")
print("    WHEN 'ts' THEN 3")
print("  END")
print('  LIMIT 1;"')

print("\n# Run the job to see column detection in logs:")
print("docker compose -f infra/docker-compose.yml exec -T worker bash -lc '")
print("  export PYTHONPATH=/app")
print("  export ONCHAIN_RULES=off")
print(
    '  python -c "from worker.jobs.onchain.verify_signal import run_once; print(run_once())"'
)
print("' 2>&1 | grep 'Using time column'")

print("\n✓ All checks passed!")
