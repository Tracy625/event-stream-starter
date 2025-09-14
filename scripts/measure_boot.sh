#!/usr/bin/env bash
set -Eeuo pipefail

# Error handler for internal errors
error_handler() {
    local line=$1
    echo "[measure] Internal error at line $line" >&2

    # Generate error report if not already handling an error
    if [[ ! -f /tmp/measure_error_handling ]]; then
        touch /tmp/measure_error_handling

        # Try to generate JSON report for internal error
        python3 - <<'PY' 2>/dev/null || true
import json
import os

report = {
    'mode': os.environ.get('MODE', 'unknown'),
    'config': {},
    'timestamps': {
        't0_ms': int(os.environ.get('JSON_T0', '0')) if os.environ.get('JSON_T0') else None,
        't1_ms': None,
        'duration_ms': None
    },
    'status': 'internal_error',
    'diagnostics': {
        'last_error': f"Script failed at line {os.environ.get('ERROR_LINE', 'unknown')}"
    }
}

with open('logs/day22/measure_boot.json', 'w') as f:
    json.dump(report, f, indent=2)
PY
        rm -f /tmp/measure_error_handling
    fi

    exit 3
}

trap 'error_handler $LINENO' ERR

# Environment variables with defaults
MEASURE_TIMEOUT_SEC="${MEASURE_TIMEOUT_SEC:-1800}"
MEASURE_WARMUP_SEC="${MEASURE_WARMUP_SEC:-5}"
MEASURE_POLL_INTERVAL_SEC="${MEASURE_POLL_INTERVAL_SEC:-2}"

# Mode detection and validation
MODE=""
CONFIG_ERROR=""

# Check for Mode B (HTTP)
if [[ -n "${MEASURE_POLL_URL:-}" ]] || [[ -n "${MEASURE_POLL_EXPR:-}" ]]; then
    if [[ -z "${MEASURE_POLL_URL:-}" ]] || [[ -z "${MEASURE_POLL_EXPR:-}" ]]; then
        CONFIG_ERROR="Mode B requires both MEASURE_POLL_URL and MEASURE_POLL_EXPR"
    else
        MODE="http"
    fi
fi

# Check for Mode A (Log)
if [[ -z "$MODE" ]]; then
    if [[ -n "${MEASURE_CARD_SERVICE:-}" ]] || [[ -n "${MEASURE_LOG_PATTERN:-}" ]]; then
        if [[ -z "${MEASURE_CARD_SERVICE:-}" ]] || [[ -z "${MEASURE_LOG_PATTERN:-}" ]]; then
            CONFIG_ERROR="Mode A requires both MEASURE_CARD_SERVICE and MEASURE_LOG_PATTERN"
        else
            MODE="log"
        fi
    fi
fi

# No mode configured
if [[ -z "$MODE" ]] && [[ -z "$CONFIG_ERROR" ]]; then
    CONFIG_ERROR="Need either (MEASURE_POLL_URL + MEASURE_POLL_EXPR) or (MEASURE_CARD_SERVICE + MEASURE_LOG_PATTERN)"
fi

# Handle configuration error
if [[ -n "$CONFIG_ERROR" ]]; then
    echo "[measure] Configuration error: $CONFIG_ERROR" >&2

    # Generate config error report
    mkdir -p logs/day22
    python3 - <<PY 2>/dev/null || true
import json

report = {
    'mode': 'unknown',
    'config': {},
    'timestamps': {
        't0_ms': None,
        't1_ms': None,
        'duration_ms': None
    },
    'status': 'config_error',
    'diagnostics': {
        'last_error': "$CONFIG_ERROR"
    }
}

with open('logs/day22/measure_boot.json', 'w') as f:
    json.dump(report, f, indent=2)
PY

    exit 2
fi

# Ensure output directory exists
mkdir -p logs/day22

# Get start time in milliseconds
t0=$(python3 -c "import time; print(int(time.time() * 1000))")

echo "[measure] Starting boot measurement (mode=$MODE)"
echo "[measure] Timeout: ${MEASURE_TIMEOUT_SEC}s, Warmup: ${MEASURE_WARMUP_SEC}s, Poll: ${MEASURE_POLL_INTERVAL_SEC}s"

# Warmup sleep
sleep "$MEASURE_WARMUP_SEC"

# Initialize variables for results
t1=""
status="timeout"
diagnostics=""

# Export for error handler
export MODE
export JSON_T0="$t0"
export ERROR_LINE=""

# Function to generate JSON report
generate_json() {
    local mode="$1"
    local status="$2"
    local t0="$3"
    local t1="$4"
    local diagnostics="$5"

    python3 - <<'PY'
import json
import os
import sys

mode = os.environ.get('JSON_MODE', '')
status = os.environ.get('JSON_STATUS', '')
t0 = int(os.environ.get('JSON_T0', '0'))
t1_str = os.environ.get('JSON_T1', '')
t1 = int(t1_str) if t1_str else None
diagnostics = os.environ.get('JSON_DIAGNOSTICS', '')

config = {}
if mode == 'log':
    config = {
        'service': os.environ.get('MEASURE_CARD_SERVICE', ''),
        'pattern': os.environ.get('MEASURE_LOG_PATTERN', ''),
        'poll_interval_sec': int(os.environ.get('MEASURE_POLL_INTERVAL_SEC', '2'))
    }
elif mode == 'http':
    config = {
        'url': os.environ.get('MEASURE_POLL_URL', ''),
        'expr': os.environ.get('MEASURE_POLL_EXPR', ''),
        'poll_interval_sec': int(os.environ.get('MEASURE_POLL_INTERVAL_SEC', '2'))
    }

timestamps = {
    't0_ms': t0,
    't1_ms': t1,
    'duration_ms': (t1 - t0) if t1 else None
}

report = {
    'mode': mode,
    'config': config,
    'timestamps': timestamps,
    'status': status,
    'diagnostics': diagnostics if isinstance(diagnostics, dict) else {'message': diagnostics} if diagnostics else {}
}

with open('logs/day22/measure_boot.json', 'w') as f:
    json.dump(report, f, indent=2)

print(f"[measure] Report saved to logs/day22/measure_boot.json")
PY
}

if [[ "$MODE" == "log" ]]; then
    echo "[measure] Mode A: Monitoring logs for service=$MEASURE_CARD_SERVICE"

    # Start background log monitoring
    timeout "$MEASURE_TIMEOUT_SEC" docker compose -f infra/docker-compose.yml logs -f --since 0s "$MEASURE_CARD_SERVICE" 2>/dev/null | while IFS= read -r line; do
        if echo "$line" | grep -q "$MEASURE_LOG_PATTERN"; then
            t1=$(python3 -c "import time; print(int(time.time() * 1000))")
            echo "[measure] Pattern matched: $line"
            echo "$t1" > /tmp/measure_boot_t1.tmp
            exit 0
        fi
    done &

    LOG_PID=$!

    # Poll for completion
    elapsed=0
    while [[ $elapsed -lt $MEASURE_TIMEOUT_SEC ]]; do
        if [[ -f /tmp/measure_boot_t1.tmp ]]; then
            t1=$(cat /tmp/measure_boot_t1.tmp)
            rm -f /tmp/measure_boot_t1.tmp
            status="ok"
            echo "[measure] First card detected at ${t1}ms"
            break
        fi

        sleep "$MEASURE_POLL_INTERVAL_SEC"
        elapsed=$((elapsed + MEASURE_POLL_INTERVAL_SEC))
    done

    # Kill log monitoring if still running
    kill $LOG_PID 2>/dev/null || true

    # If timeout, collect diagnostics
    if [[ "$status" == "timeout" ]]; then
        echo "[measure] Timeout reached, collecting diagnostics"
        docker compose -f infra/docker-compose.yml logs --tail=500 "$MEASURE_CARD_SERVICE" > logs/day22/measure_boot_tail.log 2>&1 || true
        diagnostics="Tail log saved to measure_boot_tail.log"
    fi

elif [[ "$MODE" == "http" ]]; then
    echo "[measure] Mode B: Polling HTTP endpoint=$MEASURE_POLL_URL"

    elapsed=0
    while [[ $elapsed -lt $MEASURE_TIMEOUT_SEC ]]; do
        # Make HTTP request and evaluate expression
        response=$(curl -s -f -w '\n%{http_code}' "$MEASURE_POLL_URL" 2>/dev/null || echo "")

        if [[ -n "$response" ]]; then
            # Split response body and status code
            body=$(echo "$response" | sed '$d')
            http_code=$(echo "$response" | tail -1)

            if [[ "$http_code" == "200" ]]; then
                # Evaluate expression
                result=$(python3 -c "
import json
body = '''${body}'''
now = $(python3 -c 'import time; print(int(time.time() * 1000))')
try:
    result = ${MEASURE_POLL_EXPR}
    print('true' if result else 'false')
except:
    print('false')
")

                if [[ "$result" == "true" ]]; then
                    t1=$(python3 -c "import time; print(int(time.time() * 1000))")
                    status="ok"
                    echo "[measure] Condition met at ${t1}ms"
                    break
                fi
            fi
        fi

        sleep "$MEASURE_POLL_INTERVAL_SEC"
        elapsed=$((elapsed + MEASURE_POLL_INTERVAL_SEC))
    done

    if [[ "$status" == "timeout" ]]; then
        diagnostics="HTTP polling timeout after ${MEASURE_TIMEOUT_SEC}s"
    fi
fi

# Generate JSON report
export JSON_MODE="$MODE"
export JSON_STATUS="$status"
export JSON_T0="$t0"
export JSON_T1="$t1"
export JSON_DIAGNOSTICS="$diagnostics"

generate_json "$MODE" "$status" "$t0" "$t1" "$diagnostics"

# Exit based on status
if [[ "$status" == "ok" ]]; then
    duration=$((t1 - t0))
    echo "[measure] Boot completed in ${duration}ms"
    exit 0
else
    echo "[measure] Boot measurement failed: $status"
    exit 1
fi