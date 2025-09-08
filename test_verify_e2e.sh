#!/bin/bash
# CARD B-verify — End-to-end test for candidate verification job

set -e

echo "================================================"
echo "CARD B-verify — Candidate Verification E2E Test"
echo "================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Create test candidate
echo -e "${YELLOW}Step 1: Creating test candidate in database${NC}"
echo "------------------------------------------------"

docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "
  -- First ensure the table has required columns
  SELECT column_name 
  FROM information_schema.columns 
  WHERE table_name = 'signals' 
    AND column_name IN ('event_key', 'state', 'ts', 'onchain_asof_ts', 'onchain_confidence')
  ORDER BY column_name;
  "

echo ""
echo "Inserting test candidate..."

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

echo -e "${GREEN}✓ Test candidate created${NC}"
echo ""

# Step 2: Check current ONCHAIN_RULES setting
echo -e "${YELLOW}Step 2: Checking ONCHAIN_RULES setting${NC}"
echo "------------------------------------------------"

RULES_SETTING=$(docker compose -f infra/docker-compose.yml exec -T worker bash -c 'echo $ONCHAIN_RULES' | tr -d '\r\n')
echo "Current ONCHAIN_RULES = '${RULES_SETTING}' (default: 'off')"
echo ""

# Step 3: Run verification job
echo -e "${YELLOW}Step 3: Running verification job${NC}"
echo "------------------------------------------------"

docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
  export PYTHONPATH=/app
  export ONCHAIN_VERIFICATION_DELAY_SEC=60  # Allow 1 minute old candidates
  export BQ_ONCHAIN_FEATURES_VIEW=${BQ_ONCHAIN_FEATURES_VIEW:-"dummy.table"}
  export ONCHAIN_RULES=${ONCHAIN_RULES:-"off"}
  
  python - <<PY
import json
import sys
sys.path.insert(0, "/app")

try:
    from worker.jobs.onchain.verify_signal import run_once
    result = run_once(limit=10)
    print("Job Result:", json.dumps(result, indent=2))
    
    # Check if we scanned anything
    if result.get("scanned", 0) > 0:
        print("✓ Successfully scanned candidates")
    else:
        print("⚠ No candidates scanned - might be too recent or missing state column")
        
except Exception as e:
    print(f"Error running job: {e}")
    import traceback
    traceback.print_exc()
PY
'

echo ""

# Step 4: Verify results in database
echo -e "${YELLOW}Step 4: Verifying results in database${NC}"
echo "------------------------------------------------"

docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -t -c "
  SELECT 
    'event_key: ' || event_key || E'\n' ||
    'state: ' || state || E'\n' ||
    'onchain_asof_ts: ' || COALESCE(onchain_asof_ts::text, 'NULL') || E'\n' ||
    'onchain_confidence: ' || COALESCE(onchain_confidence::text, 'NULL')
  FROM signals
  WHERE event_key = 'demo_event_bverify';
  "

echo ""

# Step 5: Validate expectations
echo -e "${YELLOW}Step 5: Validating expectations${NC}"
echo "------------------------------------------------"

RESULT=$(docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -t -c "
  SELECT 
    state,
    CASE WHEN onchain_asof_ts IS NOT NULL THEN 'SET' ELSE 'NULL' END as asof_status,
    COALESCE(onchain_confidence::text, 'NULL') as confidence
  FROM signals
  WHERE event_key = 'demo_event_bverify';
  " | xargs)

echo "Database state: $RESULT"

if [[ "$RULES_SETTING" == "off" ]] || [[ -z "$RULES_SETTING" ]]; then
    echo "Expected with ONCHAIN_RULES=off:"
    echo "  - state should remain 'candidate'"
    echo "  - onchain_asof_ts might be set (if BQ mock responded)"
    echo "  - onchain_confidence should be 0 or NULL"
else
    echo "Expected with ONCHAIN_RULES=on:"
    echo "  - state might change to 'verified' or 'downgraded' (if features available)"
    echo "  - onchain_asof_ts should be set"
    echo "  - onchain_confidence should have a value"
fi

echo ""

# Step 6: Cleanup
echo -e "${YELLOW}Step 6: Cleanup${NC}"
echo "------------------------------------------------"
read -p "Delete test data? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker compose -f infra/docker-compose.yml exec -T db \
      psql -U app -d app -c "
      DELETE FROM signals WHERE event_key = 'demo_event_bverify';
      DELETE FROM signal_events WHERE event_key = 'demo_event_bverify';
      "
    echo -e "${GREEN}✓ Test data cleaned up${NC}"
else
    echo -e "${YELLOW}Test data retained for inspection${NC}"
fi

echo ""
echo "================================================"
echo -e "${GREEN}End-to-end test completed${NC}"
echo "================================================"