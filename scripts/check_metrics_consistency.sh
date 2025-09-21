#!/usr/bin/env bash
set -euo pipefail

COMPOSE_CMD=${COMPOSE_CMD:-"docker compose -f infra/docker-compose.yml"}
METRICS_URL=${METRICS_URL:-"http://localhost:8000/metrics"}
WINDOW_SEC=${WINDOW_SEC:-86400}
TOLERANCE=${TOLERANCE:-0.01}

if ! command -v curl >/dev/null; then
  echo "curl is required" >&2
  exit 2
fi

metrics_value=$(curl -s "$METRICS_URL" | awk '/^total_apis /{print $2}' || true)
if [[ -z "$metrics_value" ]]; then
  echo "total_apis missing from /metrics" >&2
  exit 3
fi

redis_count=$($COMPOSE_CMD exec -T redis redis-cli ZCOUNT metrics:api_calls_success $(($(date +%s)-WINDOW_SEC)) +inf)
if [[ -z "$redis_count" ]]; then
  echo "Failed to fetch redis count" >&2
  exit 4
fi

expected=$(printf '%.0f' "$metrics_value")
actual=$(printf '%.0f' "$redis_count")

diff=$(( actual - expected ))
if (( diff < 0 )); then
  diff=$(( -diff ))
fi
allowed=$(python3 - <<PY
print(max(1, int($metrics_value * $TOLERANCE)))
PY
)

if (( diff > allowed )); then
  echo "Mismatch: metrics=$expected redis=$actual tolerance=$allowed" >&2
  exit 5
fi

echo "Consistency OK: metrics=$expected redis=$actual"
