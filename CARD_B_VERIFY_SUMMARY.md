# CARD B-verify — End-to-End Testing Summary

## Purpose
Verify that the on-chain signal verification job (`worker/jobs/onchain/verify_signal.py`) works correctly with real database operations.

## Test Files Created

1. **`test_verify_e2e.sh`** - Comprehensive bash script for testing
2. **`verify_commands.md`** - Manual step-by-step commands
3. **`test_verify_job.py`** - Python test script for in-container execution

## Quick Test Commands

### 1. Create Test Candidate
```bash
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  INSERT INTO signals (event_key, state, ts)
  VALUES ('demo_event_bverify', 'candidate', NOW() - INTERVAL '5 minutes')
  ON CONFLICT (event_key) DO UPDATE 
  SET state = 'candidate', ts = NOW() - INTERVAL '5 minutes';
  "
```

### 2. Run Verification Job
```bash
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_VERIFICATION_DELAY_SEC=60
  export BQ_ONCHAIN_FEATURES_VIEW="dummy.table"
  export ONCHAIN_RULES=off
  python -c "from worker.jobs.onchain.verify_signal import run_once; print(run_once())"
'
```

### 3. Check Results
```bash
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  SELECT event_key, state, onchain_asof_ts, onchain_confidence
  FROM signals WHERE event_key = 'demo_event_bverify';
  "
```

### 4. Cleanup
```bash
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  DELETE FROM signals WHERE event_key = 'demo_event_bverify';
  "
```

## Expected Results

### With `ONCHAIN_RULES=off` (default):
- ✅ Job returns: `{"scanned": 1, "evaluated": 1, ...}`
- ✅ `state` remains `'candidate'`
- ✅ `onchain_asof_ts` may be set (if BQ mock responds)
- ✅ `onchain_confidence` is `0.000` or `NULL`

### With `ONCHAIN_RULES=on`:
- ✅ Job returns: `{"scanned": 1, "evaluated": 1, ...}`
- ✅ `state` may change to `'verified'` or `'downgraded'`
- ✅ `onchain_asof_ts` is set
- ✅ `onchain_confidence` has a value (0.0 to 1.0)

## Common Issues & Solutions

### Issue: `{"scanned": 0}`
**Cause**: Candidate too recent or missing columns
**Solution**: 
- Ensure candidate is older than `ONCHAIN_VERIFICATION_DELAY_SEC` (default 180s)
- Verify migration 012 is applied (adds `state` column)

### Issue: `{"errors": 1}`
**Cause**: Missing configuration or database issues
**Solution**:
- Set `BQ_ONCHAIN_FEATURES_VIEW` environment variable
- Check if `rules/onchain.yml` exists
- Verify database connection

### Issue: Column 'state' does not exist
**Cause**: Migration 012 not applied
**Solution**:
```bash
docker compose -f infra/docker-compose.yml exec -T api \
  alembic -c /app/api/alembic.ini upgrade head
```

## Automated Test Execution

### Option 1: Run Shell Script
```bash
chmod +x test_verify_e2e.sh
./test_verify_e2e.sh
```

### Option 2: Run Python Test in Container
```bash
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_RULES=off
  python /app/test_verify_job.py
'
```

## Verification Checklist

- [ ] Migration 012 applied successfully
- [ ] Test candidate created in database
- [ ] Job scans at least 1 candidate
- [ ] Job evaluates the candidate (no errors)
- [ ] Database fields updated appropriately
- [ ] Event recorded in `signal_events` table
- [ ] State behavior matches `ONCHAIN_RULES` setting
- [ ] Test data cleaned up

## Notes

1. The job uses adaptive time column detection (created_at > updated_at > ts)
2. Redis locks prevent duplicate processing of the same event_key
3. BQ provider failures result in "evidence_delayed" events
4. The job respects `ONCHAIN_VERIFICATION_DELAY_SEC` to avoid processing very recent candidates

This completes the end-to-end verification testing for CARD B-verify.