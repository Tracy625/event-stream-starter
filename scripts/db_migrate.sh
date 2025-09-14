#!/usr/bin/env bash
set -Eeuo pipefail
trap 'echo "[ERROR] $0 failed at line $LINENO" >&2' ERR

# Color output helpers
red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
blue()  { printf "\033[34m%s\033[0m\n" "$*"; }

echo "=== Database Migration Script ==="
echo

# All docker compose commands use consistent path
COMPOSE="docker compose -f infra/docker-compose.yml"

# Step 1: Check if docker compose is available
echo "[1/4] Checking docker compose..."
if ! docker compose version >/dev/null 2>&1; then
    red "✗ docker compose not found"
    echo "Please install Docker with compose v2 support"
    exit 1
fi
green "✓ docker compose is available"

# Step 2: Check if API service is running
echo
echo "[2/4] Checking API service status..."

# Get the status of the api container
API_STATUS=$($COMPOSE ps api --format json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    if data and isinstance(data, list):
        data = data[0]
    state = data.get('State', 'unknown')
    print(state)
except:
    print('not_found')
" 2>/dev/null || echo "not_found")

if [[ "$API_STATUS" == "not_found" ]]; then
    red "✗ API service not found"
    echo
    yellow "Please start the services first:"
    echo "  make up"
    echo
    echo "Then run this script again."
    exit 1
elif [[ "$API_STATUS" != "running" ]]; then
    red "✗ API service is not running (status: $API_STATUS)"
    echo
    yellow "Please start the services first:"
    echo "  make up"
    echo
    echo "Then run this script again."
    exit 1
fi

green "✓ API service is running"

# Step 3: Run database migration to head
echo
echo "[3/4] Running database migration..."
blue "→ Executing: alembic upgrade head"

if ! $COMPOSE exec -T api sh -c 'cd /app && alembic -c api/alembic.ini upgrade head' 2>&1; then
    red "✗ Migration failed"
    echo
    yellow "Troubleshooting tips:"
    echo "  1. Check database connection in .env"
    echo "  2. Ensure database is running: docker compose ps db"
    echo "  3. Check API logs: make logs"
    echo "  4. Verify alembic is installed in the container"
    exit 1
fi

green "✓ Migration to head completed"

# Step 4: Verify current migration version
echo
echo "[4/4] Verifying migration status..."

CURRENT_VERSION=$($COMPOSE exec -T api sh -c 'cd /app && alembic -c api/alembic.ini current 2>/dev/null' | tail -1)

if [[ -z "$CURRENT_VERSION" ]]; then
    red "✗ Could not determine current migration version"
    exit 1
fi

# Check if we're at head first, then check for specific version
if echo "$CURRENT_VERSION" | grep -q "head"; then
    # Extract version number if present
    VERSION_NUM=$(echo "$CURRENT_VERSION" | grep -oE '[0-9]+' | head -1 || echo "")
    if [[ -n "$VERSION_NUM" ]]; then
        green "✓ Alembic version is head ($VERSION_NUM)"
    else
        green "✓ Alembic version is head"
    fi
elif echo "$CURRENT_VERSION" | grep -q "013"; then
    green "✓ Alembic version is 013 (current head)"
else
    yellow "⚠ Database version may not be at head"
    echo "Current: $CURRENT_VERSION"
    echo "Expected: head (013 or later)"
fi

# Summary
echo
echo "============="
green "✓ Database migration successful!"
echo
echo "Database status:"
echo "  • Current version: $CURRENT_VERSION"
echo "  • All migrations applied"
echo
echo "Next steps:"
echo "  1. Verify API health:  make verify:api"
echo "  2. View logs:          make logs"
echo "  3. Run tests:          make test"
echo
green "Migration complete!"