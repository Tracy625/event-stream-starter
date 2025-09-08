# Migration 012 - Production-Ready Implementation

## Final Version Features

### 🎯 True Idempotency
- **Pre-checks before operations**: Queries information_schema BEFORE attempting changes
- **Avoids flush-time exceptions**: No try/except blocks that could fail during transaction flush
- **Conditional operations**: Only performs operations when actually needed

### 🔍 Existence Checks Added

#### Upgrade:
1. Checks if `state` column exists
2. Checks if `signals_state_check` constraint exists
3. Only opens batch_alter_table if changes needed
4. Checks for existing indexes before creation

#### Downgrade:
1. Checks all possible index variants
2. Checks constraint existence
3. Checks column existence
4. Only opens batch_alter_table if removals needed

### 🚀 Production Benefits
- **No wasted operations**: Skips already-completed changes
- **Clean logs**: No exception spam from redundant operations
- **Transaction efficiency**: Minimizes database round-trips
- **Safe reruns**: Can be executed multiple times without side effects

## SQL Patterns Used

### Column Check:
```sql
SELECT 1 FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name = 'signals'
  AND column_name = 'state'
```

### Constraint Check:
```sql
SELECT 1 FROM information_schema.table_constraints
WHERE table_schema = current_schema()
  AND table_name = 'signals'
  AND constraint_name = 'signals_state_check'
  AND constraint_type = 'CHECK'
```

### Index Check:
```sql
SELECT 1 FROM pg_indexes
WHERE schemaname = current_schema()
  AND indexname = :idx
```

## Verification Commands

```bash
# Apply migration (safe to run multiple times)
docker compose -f infra/docker-compose.yml exec -T api \
  alembic -c /app/api/alembic.ini upgrade head

# Verify all components created
docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  SELECT 
    'Column' as component,
    CASE WHEN column_name IS NOT NULL THEN '✓ Exists' ELSE '✗ Missing' END as status
  FROM information_schema.columns
  WHERE table_schema = current_schema()
    AND table_name = 'signals'
    AND column_name = 'state'
  UNION ALL
  SELECT 
    'Constraint' as component,
    CASE WHEN constraint_name IS NOT NULL THEN '✓ Exists' ELSE '✗ Missing' END
  FROM information_schema.table_constraints
  WHERE table_schema = current_schema()
    AND table_name = 'signals'
    AND constraint_name = 'signals_state_check'
  UNION ALL
  SELECT 
    'Index' as component,
    CASE WHEN COUNT(*) > 0 THEN '✓ Exists' ELSE '✗ Missing' END
  FROM pg_indexes
  WHERE schemaname = current_schema()
    AND tablename = 'signals'
    AND indexname LIKE 'idx_signals_state%';
"

# Test job execution
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_RULES=off
  python -c "from worker.jobs.onchain.verify_signal import run_once; print(run_once())"
'
```

## Key Improvements Summary

1. ✅ **Pre-flight checks**: Validates state before operations
2. ✅ **Adaptive indexing**: Detects best available columns
3. ✅ **Zero exceptions**: Clean execution without error suppression
4. ✅ **Concurrent operations**: No table locks during index creation
5. ✅ **Multi-schema support**: Uses current_schema() throughout
6. ✅ **Safe rollback**: Handles all possible states during downgrade

The migration is now fully production-ready with proper idempotency and error-free execution!
