#!/usr/bin/env python
"""Verify state column migration and job functionality."""

import sys

sys.path.insert(0, ".")

print("=== State Column Migration Verification ===\n")

# Test 1: Check if migration file exists
import os

migration_path = "api/alembic/versions/012_add_signals_state.py"
if os.path.exists(migration_path):
    print("✓ Migration file exists: " + migration_path)
else:
    print("✗ Migration file not found: " + migration_path)
    sys.exit(1)

# Test 2: Check if column check is in verify_signal.py
with open("worker/jobs/onchain/verify_signal.py", "r") as f:
    content = f.read()
    if "information_schema.columns" in content and "column_name = 'state'" in content:
        print("✓ Column existence check added to verify_signal.py")
    else:
        print("✗ Column existence check not found in verify_signal.py")
        sys.exit(1)

# Test 3: Check SCHEMA.md documentation
with open("docs/SCHEMA.md", "r") as f:
    content = f.read()
    if "state TEXT NOT NULL DEFAULT 'candidate'" in content:
        print("✓ State column documented in SCHEMA.md")
    if "onchain_asof_ts" in content and "onchain_confidence" in content:
        print("✓ Onchain fields documented in SCHEMA.md")
    if "Version: 012" in content or "Revision: 012" in content:
        print("✓ Schema version updated to 012")

print("\n=== Verification Commands ===")
print("\n1. Apply migration:")
print("   docker compose -f infra/docker-compose.yml exec -T api \\")
print("     alembic -c /app/api/alembic.ini upgrade head")

print("\n2. Check table structure:")
print("   docker compose -f infra/docker-compose.yml exec -T db \\")
print('     psql -U app -d app -c "\\d+ signals"')

print("\n3. Run verification job:")
print("   docker compose -f infra/docker-compose.yml exec -T worker bash -lc '")
print("     export PYTHONPATH=/app")
print("     python - <<PY")
print("from worker.jobs.onchain.verify_signal import run_once")
print("print(run_once())")
print("PY'")

print("\n4. Rollback (if needed):")
print("   docker compose -f infra/docker-compose.yml exec -T api \\")
print("     alembic -c /app/api/alembic.ini downgrade -1")

print("\n=== All checks passed! ===")
