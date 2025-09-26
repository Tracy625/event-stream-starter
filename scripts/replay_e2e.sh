#!/usr/bin/env bash
set -Eeuo pipefail
trap 'echo "[ERROR] $0 failed at line $LINENO" >&2' ERR

# Color output helpers
red()   { printf "\033[31m%s\033[0m\n" "$*" >&2; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
blue()  { printf "\033[34m%s\033[0m\n" "$*"; }

usage() {
    cat <<'EOF'
Usage: replay_e2e.sh [options] <golden.jsonl>

Options:
  --only-failed        Replay only entries whose last_status != 'success'
  --skip-succeeded     Skip entries recorded in logs/replay_cache/seen_success.tsv
  -h, --help           Show this help message

Environment:
  REPLAY_PSQL          Override command used to execute psql (defaults to docker compose psql)
EOF
}

ONLY_FAILED=false
SKIP_SUCCEEDED=false

POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --only-failed)
            ONLY_FAILED=true
            shift
            ;;
        --skip-succeeded)
            SKIP_SUCCEEDED=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        --*)
            red "Unknown option: $1"
            usage
            exit 2
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

if [[ ${#POSITIONAL[@]} -lt 1 ]]; then
    red "Usage: $0 [options] <golden.jsonl>"
    exit 2
fi

set -- "${POSITIONAL[@]}"

GOLDEN_FILE="$1"
if [[ ! -f "$GOLDEN_FILE" ]]; then
    red "Golden file not found: $GOLDEN_FILE"
    exit 2
fi

echo "=== End-to-End Replay Script ==="
echo

# Environment variables with defaults
REPLAY_ENDPOINT_X="${REPLAY_ENDPOINT_X:-}"
REPLAY_ENDPOINT_DEX="${REPLAY_ENDPOINT_DEX:-}"
REPLAY_ENDPOINT_TOPIC="${REPLAY_ENDPOINT_TOPIC:-}"
REPLAY_CONCURRENCY="${REPLAY_CONCURRENCY:-1}"
REPLAY_TIMEOUT_SEC="${REPLAY_TIMEOUT_SEC:-6}"
REPLAY_SEED="${REPLAY_SEED:-42}"
REPLAY_FREEZE_TS="${REPLAY_FREEZE_TS:-}"
REPLAY_HEADER_NOW="${REPLAY_HEADER_NOW:-X-Replay-Now}"
REPLAY_HEADER_SEED="${REPLAY_HEADER_SEED:-X-Replay-Seed}"

# Soft fail mode (case-insensitive)
REPLAY_SOFT_FAIL="${REPLAY_SOFT_FAIL:-false}"
REPLAY_SOFT_FAIL_NORMALIZED=$(echo "$REPLAY_SOFT_FAIL" | tr '[:upper:]' '[:lower:]')

# Validate soft fail value
if [[ "$REPLAY_SOFT_FAIL_NORMALIZED" != "true" && "$REPLAY_SOFT_FAIL_NORMALIZED" != "false" ]]; then
    red "REPLAY_SOFT_FAIL must be 'true' or 'false' (case-insensitive), got: '$REPLAY_SOFT_FAIL'"
    exit 2
fi

# Print mode
if [[ "$REPLAY_SOFT_FAIL_NORMALIZED" == "true" ]]; then
    blue "[replay] mode=SOFT"
else
    blue "[replay] mode=STRICT"
fi

# Output directory
OUTPUT_DIR="logs/day22/replay_raw"
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
CACHE_DIR="logs/replay_cache"
CACHE_FILE="$CACHE_DIR/seen_success.tsv"
mkdir -p "$CACHE_DIR"
SUCCESS_CACHE_TEMP="$OUTPUT_DIR/.success_keys"
> "$SUCCESS_CACHE_TEMP"

REPLAY_STATE_PY="${REPLAY_STATE_PY:-scripts/_replay_state.py}"
PSQL_CMD="${REPLAY_PSQL:-docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app}"

ensure_replay_state() {
    python3 "$REPLAY_STATE_PY" ensure
}

fetch_failed_set() {
    python3 "$REPLAY_STATE_PY" list-failed --since 9999d | python3 -c 'import sys,json; [print(json.loads(line)["unique_key"]) for line in sys.stdin if line.strip()]'
}

ensure_replay_state

declare -A FAILED_FILTER
if [[ "$ONLY_FAILED" == "true" ]]; then
    while IFS= read -r key; do
        [[ -n "$key" ]] && FAILED_FILTER["$key"]=1
    done < <(python3 - "$REPLAY_STATE_PY" <<'PY'
import os, sys
sys.path.insert(0, os.getcwd())
from scripts import _replay_state as rs  # pylint: disable=import-error

for row in rs.list_failed(None, None, None):
    print(row["unique_key"])
PY
    )
    if [[ ${#FAILED_FILTER[@]} -eq 0 ]]; then
        echo "No failed entries recorded. Nothing to replay."
        exit 0
    fi
fi

declare -A SKIP_FILTER
if [[ "$SKIP_SUCCEEDED" == "true" && -f "$CACHE_FILE" ]]; then
    while IFS= read -r key; do
        [[ -n "$key" ]] && SKIP_FILTER["$key"]=1
    done < "$CACHE_FILE"
fi

# Track statistics
TOTAL=0
OK=0
FAIL=0
# macOS doesn't support %N, use Python for milliseconds
START_TIME=$(python3 -c "import time; print(int(time.time() * 1000))")

# Temporary files for collecting results
MANIFEST_CASES="$OUTPUT_DIR/.cases.jsonl"
> "$MANIFEST_CASES"

# Function to validate sample structure
validate_sample() {
    local line="$1"
    local idx="$2"

    python3 -c "
import json
import sys

try:
    data = json.loads('$line')

    # Check required fields
    required = ['event_key', 'ts', 'payload', 'expected']
    for field in required:
        if field not in data:
            print(f'Missing required field: {field}')
            sys.exit(1)

    # Check payload.source
    if 'source' not in data['payload']:
        print('Missing payload.source')
        sys.exit(1)

    source = data['payload']['source']
    if source not in ['x', 'dex', 'topic']:
        print(f'Invalid source: {source}')
        sys.exit(1)

    # Check event_key is non-empty
    if not data['event_key'] or not str(data['event_key']).strip():
        print('event_key is empty')
        sys.exit(1)

    # Output validated data
    print(json.dumps(data))
except json.JSONDecodeError as e:
    print(f'Invalid JSON: {e}')
    sys.exit(1)
except Exception as e:
    print(f'Validation error: {e}')
    sys.exit(1)
" 2>&1
}

# Function to get endpoint for source
get_endpoint() {
    local source="$1"
    case "$source" in
        x)
            echo "$REPLAY_ENDPOINT_X"
            ;;
        dex)
            echo "$REPLAY_ENDPOINT_DEX"
            ;;
        topic)
            echo "$REPLAY_ENDPOINT_TOPIC"
            ;;
        *)
            echo ""
            ;;
    esac
}

# Function to process a single sample
process_sample() {
    local idx="$1"
    local line="$2"

    # Validate sample
    local validated
    if ! validated=$(validate_sample "$line" "$idx"); then
        red "[Sample $idx] Validation failed: $validated"
        echo "{\"idx\":$idx,\"status\":\"invalid\",\"error\":\"$validated\"}" >> "$MANIFEST_CASES"
        return 2
    fi

    # Extract fields using Python
    local event_key source ts payload
    event_key=$(echo "$validated" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['event_key'])")
    source=$(echo "$validated" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['payload']['source'])")
    ts=$(echo "$validated" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['ts'])")
    payload=$(echo "$validated" | python3 -c "import json,sys; print(json.dumps(json.loads(sys.stdin.read())['payload']))")

    local unique_key
    unique_key=$(build_unique_key "$event_key" "$source")

    if [[ "$ONLY_FAILED" == "true" && -z "${FAILED_FILTER[$unique_key]:-}" ]]; then
        yellow "[Sample $idx] Skipping (not in failed set): $unique_key"
        return 0
    fi

    if [[ "$SKIP_SUCCEEDED" == "true" && -n "${SKIP_FILTER[$unique_key]:-}" ]]; then
        yellow "[Sample $idx] Skipping (already succeeded): $unique_key"
        return 0
    fi

    blue "[Sample $idx] Processing: event_key=$event_key, source=$source"

    # Get endpoint
    local endpoint
    endpoint=$(get_endpoint "$source")
    if [[ -z "$endpoint" ]]; then
        red "[Sample $idx] No endpoint configured for source: $source"
        red "Please set REPLAY_ENDPOINT_$(echo "$source" | tr '[:lower:]' '[:upper:]')"
        echo "{\"idx\":$idx,\"event_key\":\"$event_key\",\"source\":\"$source\",\"status\":\"no_endpoint\",\"error\":\"Missing endpoint configuration\"}" >> "$MANIFEST_CASES"
        return 2
    fi

    # Prepare files
    local request_file="$OUTPUT_DIR/${idx}_${event_key}.request.json"
    local response_file="$OUTPUT_DIR/${idx}_${event_key}.response.json"
    local meta_file="$OUTPUT_DIR/${idx}_${event_key}.meta.json"

    # Save request
    echo "$payload" > "$request_file"

    # Determine freeze timestamp
    local freeze_ts="${REPLAY_FREEZE_TS:-$ts}"

    # Build headers
    local headers=()
    headers+=(-H "Content-Type: application/json")
    headers+=(-H "$REPLAY_HEADER_NOW: $freeze_ts")
    headers+=(-H "$REPLAY_HEADER_SEED: $REPLAY_SEED")

    # Send request
    local start_req=$(python3 -c "import time; print(int(time.time() * 1000))")
    local status_code
    local curl_exit

    if curl -s -w "\n%{http_code}" \
            --fail-with-body \
            --max-time "$REPLAY_TIMEOUT_SEC" \
            "${headers[@]}" \
            -X POST \
            -d "@$request_file" \
            "$endpoint" \
            > "$response_file.tmp" 2>&1; then
        curl_exit=0
    else
        curl_exit=$?
    fi

    local end_req=$(python3 -c "import time; print(int(time.time() * 1000))")
    local latency_ms=$((end_req - start_req))

    # Extract status code and response body
    if [[ -f "$response_file.tmp" ]]; then
        # Last line is status code
        status_code=$(tail -1 "$response_file.tmp")
        # Everything else is response body (use sed for portability)
        sed '$d' "$response_file.tmp" > "$response_file"
        rm -f "$response_file.tmp"
    else
        status_code="000"
        echo "{\"error\":\"Request failed\"}" > "$response_file"
    fi

    # Create metadata
    cat > "$meta_file" <<EOF
{
  "idx": $idx,
  "event_key": "$event_key",
  "source": "$source",
  "endpoint": "$endpoint",
  "status_code": $status_code,
  "latency_ms": $latency_ms,
  "headers_sent": {
    "$REPLAY_HEADER_NOW": "$freeze_ts",
    "$REPLAY_HEADER_SEED": "$REPLAY_SEED"
  }
}
EOF

    # Determine success
    if [[ "$curl_exit" -eq 0 && "$status_code" =~ ^2[0-9][0-9]$ ]]; then
        green "[Sample $idx] Success: status=$status_code, latency=${latency_ms}ms"
        echo "{\"idx\":$idx,\"event_key\":\"$event_key\",\"source\":\"$source\",\"status\":\"ok\",\"status_code\":$status_code,\"latency_ms\":$latency_ms}" >> "$MANIFEST_CASES"
        update_replay_state "$unique_key" "$source" "$payload" "success" "$latency_ms" "__NONE__"
        echo "$unique_key" >> "$SUCCESS_CACHE_TEMP"
        return 0
    else
        red "[Sample $idx] Failed: status=$status_code, latency=${latency_ms}ms"
        echo "{\"idx\":$idx,\"event_key\":\"$event_key\",\"source\":\"$source\",\"status\":\"fail\",\"status_code\":$status_code,\"latency_ms\":$latency_ms}" >> "$MANIFEST_CASES"
        local error_excerpt
        error_excerpt=$(head -c 200 "$response_file" | tr '\n' ' ')
        update_replay_state "$unique_key" "$source" "$payload" "fail:$status_code" "$latency_ms" "${error_excerpt:-__NONE__}"
        return 1
    fi
}

# Main processing loop
echo "Processing samples from: $GOLDEN_FILE"
echo "Output directory: $OUTPUT_DIR"
echo "Concurrency: $REPLAY_CONCURRENCY"
echo

IDX=0
CONFIG_ERROR=0
while IFS= read -r line; do
    # Skip empty lines
    [[ -z "$line" ]] && continue

    if process_sample "$IDX" "$line"; then
        ((OK++))
    else
        exit_code=$?
        ((FAIL++))
        if [[ $exit_code -eq 2 ]]; then
            CONFIG_ERROR=1
        fi
    fi

    ((TOTAL++))
    ((IDX++))
done < "$GOLDEN_FILE"

# Calculate duration
END_TIME=$(python3 -c "import time; print(int(time.time() * 1000))")
DURATION_MS=$((END_TIME - START_TIME))

if [[ -s "$SUCCESS_CACHE_TEMP" ]]; then
    cat "$SUCCESS_CACHE_TEMP" >> "$CACHE_FILE"
    sort -u "$CACHE_FILE" -o "$CACHE_FILE"
fi

# Generate manifest.json
echo
blue "Generating manifest.json..."

python3 <<EOF > "$OUTPUT_DIR/manifest.json"
import json

summary = {
    "total": $TOTAL,
    "ok": $OK,
    "fail": $FAIL,
    "duration_ms": $DURATION_MS
}

cases = []
with open("$MANIFEST_CASES", "r") as f:
    for line in f:
        if line.strip():
            cases.append(json.loads(line))

manifest = {
    "summary": summary,
    "cases": cases
}

print(json.dumps(manifest, indent=2))
EOF

# Print summary
echo
echo "============="
echo "Replay Summary"
echo "============="
echo "Total samples: $TOTAL"
green "Successful: $OK"
if [[ $FAIL -gt 0 ]]; then
    red "Failed: $FAIL"
fi
echo "Duration: ${DURATION_MS}ms"
echo
echo "Results saved to: $OUTPUT_DIR"
echo "Manifest: $OUTPUT_DIR/manifest.json"

# Determine exit code
if [[ $CONFIG_ERROR -eq 1 ]]; then
    red "Configuration or sample structure errors detected"
    exit 2
elif [[ $FAIL -gt 0 ]]; then
    yellow "Some samples failed"
    # Check soft fail mode
    if [[ "$REPLAY_SOFT_FAIL_NORMALIZED" == "true" ]]; then
        yellow "Soft fail mode enabled - returning exit code 0"
        exit 0
    else
        exit 1
    fi
else
    green "All samples processed successfully"
    exit 0
fi
