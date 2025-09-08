# CARD B-verify — Manual Verification Commands

## Prerequisites
Ensure migration 012 is applied:
```bash
docker compose -f infra/docker-compose.yml exec -T api \
  alembic -c /app/api/alembic.ini upgrade head
```

## Step 1: Create Test Candidate

```bash
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  INSERT INTO signals (event_key, state, ts)
  VALUES ('demo_event_bverify', 'candidate', NOW() - INTERVAL '5 minutes')
  ON CONFLICT (event_key) DO UPDATE 
  SET state = 'candidate',
      ts = NOW() - INTERVAL '5 minutes',
      onchain_asof_ts = NULL,
      onchain_confidence = NULL;
  "
```

## Step 2: Run Verification Job

### Option A: With ONCHAIN_RULES=off (default)
```bash
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_VERIFICATION_DELAY_SEC=60
  export ONCHAIN_RULES=off
  export BQ_ONCHAIN_FEATURES_VIEW="dummy.table"
  python -c "from worker.jobs.onchain.verify_signal import run_once; print(run_once())"
'
```

### Option B: With ONCHAIN_RULES=on
```bash
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_VERIFICATION_DELAY_SEC=60
  export ONCHAIN_RULES=on
  export BQ_ONCHAIN_FEATURES_VIEW="dummy.table"
  python -c "from worker.jobs.onchain.verify_signal import run_once; print(run_once())"
'
```

## Step 3: Verify Results

Check the signal state and onchain fields:
```bash
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  SELECT 
    event_key,
    state,
    onchain_asof_ts,
    onchain_confidence
  FROM signals
  WHERE event_key = 'demo_event_bverify';
  "
```

Check if any events were recorded:
```bash
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  SELECT 
    event_key,
    type,
    metadata,
    created_at
  FROM signal_events
  WHERE event_key = 'demo_event_bverify'
  ORDER BY created_at DESC
  LIMIT 5;
  "
```

## Expected Results

### With ONCHAIN_RULES=off:
- `state` remains `'candidate'`
- `onchain_asof_ts` may be set (if BQ provider returns mock data)
- `onchain_confidence` should be `0.000` or `NULL`
- Event recorded with type `'onchain_verify'`

### With ONCHAIN_RULES=on:
- `state` may change to `'verified'` or `'downgraded'` (depends on features)
- `onchain_asof_ts` should be set
- `onchain_confidence` should have a value (0.0 to 1.0)
- Event recorded with verdict details

## Step 4: Cleanup

Remove test data:
```bash
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  DELETE FROM signal_events WHERE event_key = 'demo_event_bverify';
  DELETE FROM signals WHERE event_key = 'demo_event_bverify';
  "
```

## Troubleshooting

### If "scanned": 0
- Check if the candidate is old enough (> ONCHAIN_VERIFICATION_DELAY_SEC)
- Verify the `state` column exists (migration 012)
- Check if time column exists (created_at, updated_at, or ts)

### If "errors": 1
- Check if `BQ_ONCHAIN_FEATURES_VIEW` is set
- Verify rules file exists at `rules/onchain.yml`
- Check worker logs for detailed error messages

### View Worker Logs
```bash
docker compose -f infra/docker-compose.yml logs worker --tail=50
```

## Quick One-Liner Test

Complete test in one command:
```bash
docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  INSERT INTO signals (event_key, state, ts) 
  VALUES ('test_' || extract(epoch from now())::int, 'candidate', NOW() - INTERVAL '5 minutes')
  RETURNING event_key;
" && \
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app && 
  export ONCHAIN_VERIFICATION_DELAY_SEC=60 && 
  export BQ_ONCHAIN_FEATURES_VIEW="test.view" &&
  export ONCHAIN_RULES=off &&
  python -c "from worker.jobs.onchain.verify_signal import run_once; print(run_once(limit=5))"
'
```