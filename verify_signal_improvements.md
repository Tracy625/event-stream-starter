# Verify Signal Job - Adaptive Time Column Detection

## Improvements Applied

### 1. **Dynamic Column Detection**
Added `_detect_time_column()` helper function that:
- Queries information_schema to find available timestamp columns
- Prioritizes: `created_at` > `updated_at` > `ts`
- Falls back to `ts` if no columns found (defensive programming)

### 2. **Flexible Query Building**
- Dynamically constructs SQL query using detected column
- Uses column aliasing (`AS time_col`) for consistent access
- Safe from SQL injection since column names come from controlled list

### 3. **Enhanced Logging**
- Logs which time column is being used for transparency
- Helps with debugging schema variations across environments

### 4. **Backward Compatibility**
- Works with any schema version that has at least one time column
- Gracefully handles missing columns
- No breaking changes to existing functionality

## Code Changes

### New Function:
```python
def _detect_time_column(db) -> Literal["created_at", "updated_at", "ts"]:
    """
    Detect available timestamp column on 'signals' table.
    Priority: created_at > updated_at > ts. Fallback to 'ts' if nothing found.
    """
```

### Query Adaptation:
```python
# Build query with validated identifier
candidates_sql = f"""
    SELECT event_key, state, {time_col} AS time_col
    FROM signals
    WHERE state = 'candidate'
      AND {time_col} >= :cutoff
    ORDER BY {time_col} DESC
    LIMIT :limit
"""
```

### Delay Check Update:
```python
# Check delay using the time column (could be created_at, updated_at, or ts)
time_value = getattr(signal, 'time_col', None) or getattr(signal, 'created_at', None)
```

## Benefits

✅ **Schema Flexibility**: Adapts to different database schemas  
✅ **Production Ready**: Handles edge cases gracefully  
✅ **Observable**: Clear logging of decisions made  
✅ **Maintainable**: Single source of truth for column detection  
✅ **Safe**: No SQL injection risk, validated column names  

## Testing

The job will now:
1. Detect which time column exists in your schema
2. Use that column for filtering recent candidates
3. Log the decision for transparency
4. Process candidates using the appropriate timestamp

This ensures the verification job works correctly regardless of schema variations!
