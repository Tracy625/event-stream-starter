# Migration 012 - Adaptive Index Creation

## Key Enhancement: Dynamic Time Column Detection

The migration now intelligently detects which time column is available in the `signals` table and creates the appropriate index.

### Detection Priority:
1. **First choice**: `created_at` - Standard creation timestamp
2. **Second choice**: `updated_at` - Fallback if created_at doesn't exist  
3. **Final fallback**: No time column - Creates index on state only

### Index Naming Convention:
- With `created_at`: `idx_signals_state_created_at`
- With `updated_at`: `idx_signals_state_updated_at`
- Without time column: `idx_signals_state_onlystate`

### Benefits:
✅ **Flexible**: Works with different schema versions  
✅ **Future-proof**: Adapts to schema evolution  
✅ **Safe downgrade**: Removes all possible index variants  
✅ **Performance**: Always creates the best available index  

## Verification Commands

```bash
# Apply migration and check which index was created
docker compose -f infra/docker-compose.yml exec -T api \
  alembic -c /app/api/alembic.ini upgrade head

# Check which index was created
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "SELECT indexname FROM pg_indexes WHERE tablename = 'signals' AND indexname LIKE 'idx_signals_state%'"

# Verify table structure
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "\d+ signals" | grep -E "state|idx_signals"

# Test job execution
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_RULES=off
  python -c "from worker.jobs.onchain.verify_signal import run_once; print(run_once())"
'
```

## Technical Details

### Upgrade Process:
1. Adds `state` column with CHECK constraint (idempotent)
2. Queries information_schema to detect available time columns
3. Creates the most appropriate index based on what's found
4. All operations are wrapped in proper transaction contexts

### Downgrade Process:
1. Attempts to drop all three possible index variants
2. Only drops indexes that actually exist
3. Removes constraint and column safely

### SQL Used for Detection:
```sql
SELECT column_name
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name = 'signals'
  AND column_name IN ('created_at', 'updated_at')
ORDER BY CASE column_name
    WHEN 'created_at' THEN 1
    WHEN 'updated_at' THEN 2
    ELSE 3
END
LIMIT 1
```

This ensures the migration works correctly regardless of the current schema state!
