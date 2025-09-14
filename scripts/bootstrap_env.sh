#!/usr/bin/env bash
set -Eeuo pipefail
trap 'echo "[ERROR] $0 failed at line $LINENO" >&2' ERR

# Color output helpers
red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
blue()  { printf "\033[34m%s\033[0m\n" "$*"; }

echo "=== Environment Bootstrap Script ==="
echo

# Step 1: Check required files
echo "[1/4] Checking required files..."
if [[ ! -f infra/docker-compose.yml ]]; then
    red "✗ infra/docker-compose.yml not found"
    exit 1
fi
green "✓ infra/docker-compose.yml exists"

if [[ ! -f api/alembic.ini ]]; then
    red "✗ api/alembic.ini not found"
    exit 1
fi
green "✓ api/alembic.ini exists"

if [[ ! -f .env.example ]]; then
    red "✗ .env.example not found"
    exit 1
fi
green "✓ .env.example exists"

# Step 2: Handle .env file
echo
echo "[2/4] Checking .env file..."
if [[ -f .env ]]; then
    green "✓ .env already exists (will not overwrite)"
else
    yellow "→ .env not found, creating from .env.example..."
    # Copy line by line to preserve comments and order
    while IFS= read -r line || [[ -n "$line" ]]; do
        echo "$line"
    done < .env.example > .env
    green "✓ .env created from .env.example"
fi

# Check for .env.local
if [[ -f .env.local ]]; then
    blue "ℹ .env.local detected (will override .env values at runtime)"
fi

# Step 3: Validate required environment variables
echo
echo "[3/4] Validating environment variables..."

# Source the env file for validation
set -a
source .env
set +a

ERRORS=0
WARNINGS=0

# Function to check required variable
check_required() {
    local var_name="$1"
    local var_value="${!var_name:-}"

    if [[ -z "$var_value" || "$var_value" == "__FILL_ME__" ]]; then
        red "✗ $var_name is not set or has placeholder value"
        ERRORS=$((ERRORS + 1))
        return 1
    fi
    green "✓ $var_name is set"
    return 0
}

# Function to check numeric variable with port range validation
check_numeric() {
    local var_name="$1"
    local var_value="${!var_name:-}"
    local is_port="${2:-false}"

    if [[ ! "$var_value" =~ ^[0-9]+$ ]]; then
        red "✗ $var_name must be a number (got: $var_value)"
        ERRORS=$((ERRORS + 1))
        return 1
    fi

    # Port range validation (1-65535)
    if [[ "$is_port" == "true" ]]; then
        if [[ "$var_value" -lt 1 || "$var_value" -gt 65535 ]]; then
            red "✗ $var_name must be between 1-65535 (got: $var_value)"
            ERRORS=$((ERRORS + 1))
            return 1
        fi
    fi

    green "✓ $var_name is numeric: $var_value"
    return 0
}

# Function to check boolean variable (case-insensitive)
check_boolean() {
    local var_name="$1"
    local var_value="${!var_name:-}"
    # Normalize to lowercase for comparison
    local normalized_value=$(echo "$var_value" | tr '[:upper:]' '[:lower:]')

    # Check for invalid boolean values
    if [[ "$normalized_value" == "yes" || "$normalized_value" == "no" || "$normalized_value" == "1" || "$normalized_value" == "0" ]]; then
        red "✗ $var_name must be 'true' or 'false' (case-insensitive), not '$var_value'"
        red "  Please update your .env file to use 'true' or 'false'"
        ERRORS=$((ERRORS + 1))
        return 1
    fi

    # Only accept true or false (case-insensitive)
    if [[ "$normalized_value" != "true" && "$normalized_value" != "false" ]]; then
        red "✗ $var_name must be 'true' or 'false' (case-insensitive) (got: $var_value)"
        ERRORS=$((ERRORS + 1))
        return 1
    fi

    green "✓ $var_name is valid boolean: $normalized_value"
    return 0
}

# Check Postgres variables
echo
blue "Checking Postgres configuration..."
check_required "POSTGRES_HOST" || true
check_required "POSTGRES_PORT" || true
check_numeric "POSTGRES_PORT" "true" || true  # true = is_port
check_required "POSTGRES_DB" || true
check_required "POSTGRES_USER" || true
check_required "POSTGRES_PASSWORD" || true

# Check Redis variables
echo
blue "Checking Redis configuration..."
check_required "REDIS_URL" || true

# Check Telegram variables
echo
blue "Checking Telegram configuration..."
check_required "TELEGRAM_BOT_TOKEN" || true
check_required "TELEGRAM_CHAT_ID" || true
check_boolean "TELEGRAM_PUSH_ENABLED" || true

# Check App variables
echo
blue "Checking App configuration..."
API_PORT="${API_PORT:-8000}"
if [[ "$API_PORT" != "__FILL_ME__" ]]; then
    check_numeric "API_PORT" "true" || true  # true = is_port
else
    yellow "→ API_PORT has placeholder value (will use default: 8000)"
    WARNINGS=$((WARNINGS + 1))
fi

# Step 4: Summary and next steps
echo
echo "[4/4] Summary"
echo "============="

if [[ $ERRORS -gt 0 ]]; then
    red "✗ Found $ERRORS error(s) in configuration"
    echo
    red "Please edit .env and fix the errors above, then run this script again."
    echo
    echo "Example .env entries:"
    echo "  POSTGRES_HOST=localhost"
    echo "  POSTGRES_PORT=5432"
    echo "  POSTGRES_DB=app"
    echo "  POSTGRES_USER=app"
    echo "  POSTGRES_PASSWORD=<your-password>"
    echo "  REDIS_URL=redis://localhost:6379/0"
    echo "  TELEGRAM_BOT_TOKEN=<your-bot-token>"
    echo "  TELEGRAM_CHAT_ID=<your-chat-id>"
    echo "  TELEGRAM_PUSH_ENABLED=false"
    exit 1
fi

if [[ $WARNINGS -gt 0 ]]; then
    yellow "⚠ Found $WARNINGS warning(s) in configuration"
fi

green "✓ Environment validation successful!"
echo
echo "Next steps:"
echo "  1. Start services:    make up"
echo "  2. Run migrations:    bash scripts/db_migrate.sh"
echo "  3. Verify API:        make verify:api"
echo
green "Environment bootstrap complete!"