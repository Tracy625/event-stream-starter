# Migration 012 - Final Version Summary

## Key Improvements Applied

### 1. **Simplified and More Robust Structure**
- Uses `batch_alter_table` for atomic column/constraint operations
- All operations wrapped in try/except for idempotency
- No redundant NULL checks since column has DEFAULT and NOT NULL

### 2. **Proper Concurrent Index Handling**
- Uses `autocommit_block()` context for CONCURRENT operations
- PostgreSQL requires CONCURRENT index operations outside transactions
- Includes existence check using `current_schema()` for schema awareness

### 3. **Consistent Naming**
- Constraint: `signals_state_check` (PostgreSQL convention)
- Index: `idx_signals_state_created_at`

### 4. **Fully Idempotent**
- Can be run multiple times without errors
- Checks existence before creating/dropping
- Handles partial states gracefully

## Migration Commands

```bash
# Apply migration
docker compose -f infra/docker-compose.yml exec -T api \
  alembic -c /app/api/alembic.ini upgrade head

# Verify table structure
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "\d+ signals" | grep -E "state|idx_signals"

# Test job execution
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_RULES=off
  python -c "from worker.jobs.onchain.verify_signal import run_once; print(run_once())"
'

# Rollback if needed
docker compose -f infra/docker-compose.yml exec -T api \
  alembic -c /app/api/alembic.ini downgrade -1
```

## Expected Results

After migration:
- `signals.state` column exists with DEFAULT 'candidate'
- CHECK constraint ensures only valid states
- Composite index on (state, created_at DESC) for efficient queries
- Job runs without UndefinedColumn errors
- With ONCHAIN_RULES=off: writes onchain_asof_ts and onchain_confidence but keeps state as 'candidate'

## Safety Features

1. **No Table Locks**: Concurrent index creation doesn't block reads/writes
2. **Transaction Safety**: Autocommit blocks for CONCURRENT operations
3. **Error Tolerance**: All operations handle "already exists" gracefully
4. **Clean Rollback**: Downgrade properly removes all artifacts

