# On-chain Signal Verification Runbook

## Files Created/Modified

### ALLOWED_FILES (as per DX requirements)
- `worker/jobs/onchain/verify_signal.py` - Main verification job
- `worker/tasks.py` - Celery task integration  
- `api/alembic/versions/011_fix_onchain_confidence_type.py` - Migration for onchain fields
- `tests/test_verify_signal.py` - Comprehensive test suite

### Additional support files (within allowed scope)
- `worker/jobs/onchain/__init__.py` - Module init
- `worker/celeryconfig.py` - Added beat schedule

## Migration Commands

```bash
# Apply migration
cd api
alembic upgrade head

# Verify migration
alembic current

# Rollback if needed
alembic downgrade -1
```

## Test Verification Job

```bash
# Run once manually
python -c "
import sys
sys.path.insert(0, '.')
from worker.jobs.onchain.verify_signal import run_once
print(run_once())
"

# Run tests
pytest tests/test_verify_signal.py -v
```

## Environment Variables Required

```bash
export ONCHAIN_VERIFICATION_DELAY_SEC=180
export ONCHAIN_VERIFICATION_TIMEOUT_SEC=720  
export ONCHAIN_VERDICT_TTL_SEC=900
export BQ_ONCHAIN_FEATURES_VIEW="project.dataset.view"
export ONCHAIN_RULES="off"  # or "on" to enable state changes
export REDIS_URL="redis://localhost:6379/0"
export POSTGRES_URL="postgresql://user:pass@localhost/db"
```

## Features Implemented

1. **Idempotent Processing**: Redis locks prevent duplicate processing
2. **Retry Logic**: Exponential backoff for BQ queries (5s, 15s, 30s)
3. **Cost Tracking**: Monitors BQ query count and bytes scanned
4. **Graceful Degradation**: Records "evidence_delayed" when data unavailable
5. **Conservative Updates**: Only changes state when ONCHAIN_RULES=on
6. **Comprehensive Logging**: INFO for stats, ERROR with event_key context

## Statistics Returned

```json
{
  "scanned": 10,      // Total candidates found
  "evaluated": 8,     // Candidates processed
  "updated": 5,       // Successfully updated
  "skipped": 3,       // Skipped (too recent or locked)
  "errors": 0         // Processing errors
}
```

## Celery Beat Schedule

The job runs every minute via Celery beat. To start:

```bash
celery -A worker.app beat -l info
celery -A worker.app worker -l info
```

## Rollback Procedure

1. Stop Celery beat/worker
2. Run: `alembic downgrade -1`
3. Remove beat schedule entry from celeryconfig.py
4. Restart services
