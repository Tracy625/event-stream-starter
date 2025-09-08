# CARD B-verify — Complete Test Suite Documentation

## Overview
This document provides a comprehensive guide for running the three-branch verification tests for the on-chain signal verification job.

## Test Scripts Available

### 1. Shell Script: `test_three_branch_verify.sh`
- **Purpose**: Automated three-branch verification using Docker Compose
- **Features**: 
  - Color-coded output for easy reading
  - Automatic migration check
  - Interactive cleanup prompt
  - Tests all three branches: OFF, UPGRADE, DOWNGRADE

### 2. Python Script: `test_three_branch_verify.py`
- **Purpose**: In-container Python test with monkey-patching
- **Features**:
  - Direct function mocking
  - Detailed validation output
  - Programmatic test execution
  - No external dependencies

### 3. Manual Commands: `verify_commands.md`
- **Purpose**: Step-by-step manual verification
- **Features**:
  - Individual command execution
  - Troubleshooting guide
  - Quick one-liner tests

### 4. E2E Test Script: `test_verify_job.py`
- **Purpose**: Basic end-to-end verification
- **Features**:
  - Single candidate testing
  - Environment validation
  - Database result verification

## Quick Start

### Option 1: Run Automated Shell Test
```bash
chmod +x test_three_branch_verify.sh
./test_three_branch_verify.sh
```

### Option 2: Run Python Test in Container
```bash
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  python /app/test_three_branch_verify.py
'
```

### Option 3: Quick Manual Test
```bash
# Create candidate
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  INSERT INTO signals (event_key, state, ts)
  VALUES ('quick_test_' || extract(epoch from now())::int, 'candidate', NOW() - INTERVAL '5 minutes')
  "

# Run verification
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_VERIFICATION_DELAY_SEC=60
  export BQ_ONCHAIN_FEATURES_VIEW="dummy.table"
  export ONCHAIN_RULES=off
  python -c "from worker.jobs.onchain.verify_signal import run_once; print(run_once())"
'
```

## Three-Branch Test Scenarios

### Branch A: OFF Mode
- **Environment**: `ONCHAIN_RULES=off`
- **Expected Behavior**:
  - State remains `'candidate'`
  - `onchain_asof_ts` may be set
  - `onchain_confidence` is 0.000 or NULL
  - No state transitions occur

### Branch B: Upgrade Path
- **Environment**: `ONCHAIN_RULES=on`
- **Mock Features**:
  - `active_addr_pctl`: 0.96 (>= 0.95)
  - `growth_ratio`: 2.5 (>= 2.0)
  - `top10_share`: 0.10 (< 0.70)
  - `self_loop_ratio`: 0.01 (< 0.20)
- **Expected Result**: State → `'verified'`

### Branch C: Downgrade Path
- **Environment**: `ONCHAIN_RULES=on`
- **Mock Features**:
  - `active_addr_pctl`: 0.50
  - `growth_ratio`: 0.8
  - `top10_share`: 0.75 (>= 0.70, high_risk)
  - `self_loop_ratio`: 0.25 (>= 0.20, suspicious)
- **Expected Result**: State → `'downgraded'` or `'rejected'`

## Prerequisites

1. **Migration 012 Applied**:
```bash
docker compose -f infra/docker-compose.yml exec -T api \
  alembic -c /app/api/alembic.ini upgrade head
```

2. **Services Running**:
```bash
docker compose -f infra/docker-compose.yml up -d
```

3. **Environment Variables Set**:
- `BQ_ONCHAIN_FEATURES_VIEW` (can be dummy for testing)
- `ONCHAIN_RULES` (off/on)
- `ONCHAIN_VERIFICATION_DELAY_SEC` (seconds to wait before verification)

## Validation Checklist

### Successful Test Run:
- [ ] Migration 012 applied successfully
- [ ] Test candidates created in database
- [ ] Job returns `{"scanned": 2, "evaluated": 2, ...}`
- [ ] OFF mode: states remain 'candidate'
- [ ] UPGRADE path: demo_event_up → 'verified'
- [ ] DOWNGRADE path: demo_event_down → 'downgraded'
- [ ] Events recorded in signal_events table
- [ ] Test data cleaned up

### Common Issues:

| Issue | Cause | Solution |
|-------|-------|----------|
| `{"scanned": 0}` | Candidate too recent | Set lower `ONCHAIN_VERIFICATION_DELAY_SEC` |
| Column 'state' does not exist | Migration not applied | Run `alembic upgrade head` |
| `{"errors": 1}` | Missing BQ view config | Set `BQ_ONCHAIN_FEATURES_VIEW` |
| State not changing | ONCHAIN_RULES=off | Set `ONCHAIN_RULES=on` for state transitions |

## Monitoring & Debugging

### View Worker Logs:
```bash
docker compose -f infra/docker-compose.yml logs worker --tail=50 -f
```

### Check Database State:
```bash
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  SELECT event_key, state, onchain_confidence
  FROM signals 
  WHERE event_key LIKE 'demo_event_%'
  ORDER BY ts DESC;
  "
```

### Check Redis Locks:
```bash
docker compose -f infra/docker-compose.yml exec -T redis \
  redis-cli KEYS "onchain:verify:*"
```

## Test Results Interpretation

### Successful OFF Mode:
```
OFF mode result: {'scanned': 2, 'evaluated': 2, 'errors': 0}
Results after OFF mode:
  demo_event_up: state=candidate, asof=SET, conf=0.000
  demo_event_down: state=candidate, asof=SET, conf=0.000
```

### Successful UPGRADE:
```
ON-upgrade result: {'scanned': 1, 'evaluated': 1, 'upgraded': 1}
demo_event_up after upgrade:
  state: verified
  confidence: 0.880
```

### Successful DOWNGRADE:
```
ON-downgrade result: {'scanned': 1, 'evaluated': 1, 'downgraded': 1}
demo_event_down after downgrade:
  state: downgraded
  confidence: 0.760
```

## Cleanup

### Remove All Test Data:
```bash
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  DELETE FROM signal_events WHERE event_key LIKE 'demo_event_%';
  DELETE FROM signals WHERE event_key LIKE 'demo_event_%';
  "
```

## Summary

The three-branch verification test suite validates:
1. **OFF mode**: Features are fetched but no state transitions occur
2. **UPGRADE path**: High-quality signals get promoted to 'verified'
3. **DOWNGRADE path**: Suspicious signals get demoted to 'downgraded'

All tests use monkey-patching to mock BigQuery responses, ensuring predictable test outcomes without external dependencies.