#!/bin/bash
# CARD B-verify (final) — Three-branch end-to-end verification

set -e

echo "========================================================="
echo "CARD B-verify (final) — Three-Branch Verification Test"
echo "========================================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Step 0: Ensure migration is applied
echo -e "${YELLOW}Step 0: Ensuring migration 012 is applied${NC}"
echo "---------------------------------------------------------"
docker compose -f infra/docker-compose.yml exec -T api \
  alembic -c /app/api/alembic.ini upgrade head 2>/dev/null || true
echo -e "${GREEN}✓ Migration check complete${NC}"
echo ""

# Step 1: Create test candidates
echo -e "${YELLOW}Step 1: Creating two test candidates${NC}"
echo "---------------------------------------------------------"

docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  INSERT INTO signals (event_key, state, ts) VALUES
    ('demo_event_up', 'candidate', NOW() - INTERVAL '10 minutes'),
    ('demo_event_down', 'candidate', NOW() - INTERVAL '10 minutes')
  ON CONFLICT (event_key) DO UPDATE 
  SET state = 'candidate',
      ts = NOW() - INTERVAL '10 minutes',
      onchain_asof_ts = NULL,
      onchain_confidence = NULL;
  "

echo -e "${GREEN}✓ Created candidates: demo_event_up, demo_event_down${NC}"
echo ""

# Branch A: Test ONCHAIN_RULES=off
echo -e "${BLUE}═════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}BRANCH A: Testing ONCHAIN_RULES=off${NC}"
echo -e "${BLUE}═════════════════════════════════════════════════════════${NC}"
echo ""

echo "Running job with ONCHAIN_RULES=off (should only update asof_ts/confidence)..."
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_RULES=off
  export ONCHAIN_VERIFICATION_DELAY_SEC=0
  export ONCHAIN_VERDICT_TTL_SEC=1
  export BQ_ONCHAIN_FEATURES_VIEW="dummy.table"
  
  python - <<PY
import sys
from datetime import datetime, timezone
from decimal import Decimal

# Mock the BQ provider to return test data
def mock_run_template(template_name, **kwargs):
    """Mock BQProvider.run_template to return test features"""
    return {
        "data": [{
            "active_addr_pctl": 0.99,
            "growth_ratio": 2.5,
            "top10_share": 0.10,
            "self_loop_ratio": 0.01,
            "asof_ts": datetime.now(timezone.utc).isoformat()
        }],
        "metadata": {"total_bytes_processed": 123456}
    }

# Monkey-patch the BQProvider
try:
    from api.providers.onchain.bq_provider import BQProvider
    BQProvider.run_template = mock_run_template
    print("✓ Mocked BQProvider.run_template")
except Exception as e:
    print(f"Mock setup error: {e}")

# Run the job
from worker.jobs.onchain.verify_signal import run_once
result = run_once(limit=10)
print(f"OFF mode result: {result}")
PY
'

echo ""
echo "Checking database state after OFF mode..."
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -t -c "
  SELECT 
    event_key,
    state,
    CASE WHEN onchain_asof_ts IS NOT NULL THEN 'SET' ELSE 'NULL' END as asof,
    COALESCE(onchain_confidence::text, 'NULL') as conf
  FROM signals 
  WHERE event_key IN ('demo_event_up', 'demo_event_down')
  ORDER BY event_key;
  " | while read line; do
    echo "  $line"
  done

echo -e "${GREEN}✓ OFF mode test complete (state should remain 'candidate')${NC}"
echo ""

# Wait a bit to allow locks to expire
sleep 2

# Branch B: Test upgrade path
echo -e "${BLUE}═════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}BRANCH B: Testing ONCHAIN_RULES=on (Upgrade Path)${NC}"
echo -e "${BLUE}═════════════════════════════════════════════════════════${NC}"
echo ""

echo "Running job with features that trigger UPGRADE..."
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_RULES=on
  export ONCHAIN_VERIFICATION_DELAY_SEC=0
  export ONCHAIN_VERDICT_TTL_SEC=1
  export BQ_ONCHAIN_FEATURES_VIEW="dummy.table"
  
  python - <<PY
import sys
from datetime import datetime, timezone

def mock_run_template(template_name, **kwargs):
    """Mock to return upgrade-triggering features for demo_event_up"""
    # Get the address from kwargs to determine which event
    address = kwargs.get("address", "")
    
    if "up" in str(address) or "up" in str(kwargs):
        # Features that trigger upgrade (high percentile + fast growth)
        return {
            "data": [{
                "active_addr_pctl": 0.96,  # >= 0.95 (high)
                "growth_ratio": 2.5,        # >= 2.0 (fast)
                "top10_share": 0.10,        # < 0.70 (not high_risk)
                "self_loop_ratio": 0.01,    # < 0.20 (not suspicious)
                "asof_ts": datetime.now(timezone.utc).isoformat()
            }],
            "metadata": {"total_bytes_processed": 111111}
        }
    else:
        # Neutral features for other events
        return {
            "data": [{
                "active_addr_pctl": 0.85,
                "growth_ratio": 1.1,
                "top10_share": 0.20,
                "self_loop_ratio": 0.05,
                "asof_ts": datetime.now(timezone.utc).isoformat()
            }],
            "metadata": {"total_bytes_processed": 222222}
        }

try:
    from api.providers.onchain.bq_provider import BQProvider
    BQProvider.run_template = mock_run_template
    print("✓ Mocked BQProvider for upgrade scenario")
except Exception as e:
    print(f"Mock setup error: {e}")

from worker.jobs.onchain.verify_signal import run_once
result = run_once(limit=10)
print(f"ON-upgrade result: {result}")
PY
'

echo ""
echo "Checking demo_event_up after upgrade path..."
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -t -c "
  SELECT 
    'event: ' || event_key || ', state: ' || state || 
    ', confidence: ' || COALESCE(onchain_confidence::text, 'NULL')
  FROM signals 
  WHERE event_key = 'demo_event_up';
  "

echo -e "${GREEN}✓ Upgrade path test complete (state should be 'verified')${NC}"
echo ""

# Wait for locks
sleep 2

# Branch C: Test downgrade path
echo -e "${BLUE}═════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}BRANCH C: Testing ONCHAIN_RULES=on (Downgrade Path)${NC}"
echo -e "${BLUE}═════════════════════════════════════════════════════════${NC}"
echo ""

echo "Running job with features that trigger DOWNGRADE..."
docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_RULES=on
  export ONCHAIN_VERIFICATION_DELAY_SEC=0
  export ONCHAIN_VERDICT_TTL_SEC=1
  export BQ_ONCHAIN_FEATURES_VIEW="dummy.table"
  
  python - <<PY
import sys
from datetime import datetime, timezone

def mock_run_template(template_name, **kwargs):
    """Mock to return downgrade-triggering features for demo_event_down"""
    address = kwargs.get("address", "")
    
    if "down" in str(address) or "down" in str(kwargs):
        # Features that trigger downgrade (high concentration + suspicious loops)
        return {
            "data": [{
                "active_addr_pctl": 0.50,
                "growth_ratio": 0.8,
                "top10_share": 0.75,        # >= 0.70 (high_risk)
                "self_loop_ratio": 0.25,    # >= 0.20 (suspicious)
                "asof_ts": datetime.now(timezone.utc).isoformat()
            }],
            "metadata": {"total_bytes_processed": 333333}
        }
    else:
        # Neutral features
        return {
            "data": [{
                "active_addr_pctl": 0.85,
                "growth_ratio": 1.1,
                "top10_share": 0.20,
                "self_loop_ratio": 0.05,
                "asof_ts": datetime.now(timezone.utc).isoformat()
            }],
            "metadata": {"total_bytes_processed": 444444}
        }

try:
    from api.providers.onchain.bq_provider import BQProvider
    BQProvider.run_template = mock_run_template
    print("✓ Mocked BQProvider for downgrade scenario")
except Exception as e:
    print(f"Mock setup error: {e}")

from worker.jobs.onchain.verify_signal import run_once
result = run_once(limit=10)
print(f"ON-downgrade result: {result}")
PY
'

echo ""
echo "Checking demo_event_down after downgrade path..."
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -t -c "
  SELECT 
    'event: ' || event_key || ', state: ' || state || 
    ', confidence: ' || COALESCE(onchain_confidence::text, 'NULL')
  FROM signals 
  WHERE event_key = 'demo_event_down';
  "

echo -e "${GREEN}✓ Downgrade path test complete (state should be 'downgraded' or 'rejected')${NC}"
echo ""

# Final summary
echo -e "${YELLOW}═════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}Final State Summary${NC}"
echo -e "${YELLOW}═════════════════════════════════════════════════════════${NC}"

docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  SELECT 
    event_key,
    state,
    CASE WHEN onchain_asof_ts IS NOT NULL THEN 'SET' ELSE 'NULL' END as asof_ts,
    COALESCE(onchain_confidence::text, 'NULL') as confidence
  FROM signals 
  WHERE event_key IN ('demo_event_up', 'demo_event_down')
  ORDER BY event_key;
  "

echo ""
echo "Checking signal_events for verification records..."
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  SELECT 
    event_key,
    type,
    substring(metadata::text, 1, 60) || '...' as metadata_preview
  FROM signal_events 
  WHERE event_key IN ('demo_event_up', 'demo_event_down')
    AND type = 'onchain_verify'
  ORDER BY created_at DESC
  LIMIT 6;
  "

# Cleanup
echo ""
echo -e "${YELLOW}Cleanup${NC}"
echo "---------------------------------------------------------"
read -p "Delete test data? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker compose -f infra/docker-compose.yml exec -T db \
      psql -U app -d app -c "
      DELETE FROM signal_events WHERE event_key IN ('demo_event_up', 'demo_event_down');
      DELETE FROM signals WHERE event_key IN ('demo_event_up', 'demo_event_down');
      " || true
    echo -e "${GREEN}✓ Test data cleaned up${NC}"
else
    echo -e "${YELLOW}Test data retained for inspection${NC}"
fi

echo ""
echo "========================================================="
echo -e "${GREEN}Three-Branch Verification Test Complete!${NC}"
echo "========================================================="
echo ""
echo "Expected Results:"
echo "  Branch A (OFF): Both signals remain 'candidate', confidence = 0 or 1.0"
echo "  Branch B (ON):  demo_event_up → 'verified', confidence > 0"
echo "  Branch C (ON):  demo_event_down → 'downgraded'/'rejected', confidence > 0"