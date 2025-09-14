#!/usr/bin/env bash
set -Eeuo pipefail
trap 'echo "[bundle] Error at line $LINENO" >&2; exit 1' ERR

# Script version
SCRIPT_VERSION="v1"

# Get git commit
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# Timestamp
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(date +%s)}

# Output directory
mkdir -p artifacts

# Bundle filename
BUNDLE_NAME="day22_repro_${COMMIT}.zip"
BUNDLE_PATH="artifacts/${BUNDLE_NAME}"

# Temp directory for staging
STAGING_DIR=$(mktemp -d)
trap 'rm -rf "$STAGING_DIR"' EXIT

echo "[bundle] Creating reproducible bundle: $BUNDLE_NAME"

# Initialize manifest
MANIFEST_FILES=()
MISSING_FILES=()

# Function to add file to staging
add_file() {
    local src="$1"
    local dst="$2"

    if [[ -f "$src" ]]; then
        mkdir -p "$(dirname "$STAGING_DIR/$dst")"
        cp "$src" "$STAGING_DIR/$dst"

        # Calculate SHA256
        if command -v sha256sum >/dev/null 2>&1; then
            SHA256=$(sha256sum "$src" | awk '{print $1}')
        else
            SHA256=$(shasum -a 256 "$src" | awk '{print $1}')
        fi

        SIZE=$(stat -f%z "$src" 2>/dev/null || stat -c%s "$src" 2>/dev/null || echo 0)
        MANIFEST_FILES+=("{\"path\": \"$dst\", \"size\": $SIZE, \"sha256\": \"$SHA256\"}")
        return 0
    else
        MISSING_FILES+=("\"$dst\"")
        return 1
    fi
}

# Function to add directory
add_directory() {
    local src="$1"
    local dst="$2"

    if [[ -d "$src" ]]; then
        mkdir -p "$STAGING_DIR/$dst"

        # Copy directory contents
        find "$src" -type f | while read -r file; do
            rel_path="${file#$src/}"
            cp "$file" "$STAGING_DIR/$dst/$rel_path"

            # Calculate SHA256
            if command -v sha256sum >/dev/null 2>&1; then
                SHA256=$(sha256sum "$file" | awk '{print $1}')
            else
                SHA256=$(shasum -a 256 "$file" | awk '{print $1}')
            fi

            SIZE=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo 0)
            MANIFEST_FILES+=("{\"path\": \"$dst/$rel_path\", \"size\": $SIZE, \"sha256\": \"$SHA256\"}")
        done
        return 0
    else
        MISSING_FILES+=("\"$dst\"")
        return 1
    fi
}

# Create VERSION.txt
echo "Bundle Version: $SCRIPT_VERSION" > "$STAGING_DIR/VERSION.txt"
echo "Git Commit: $COMMIT" >> "$STAGING_DIR/VERSION.txt"
echo "Created: $TIMESTAMP" >> "$STAGING_DIR/VERSION.txt"
echo "SOURCE_DATE_EPOCH: $SOURCE_DATE_EPOCH" >> "$STAGING_DIR/VERSION.txt"

# Calculate VERSION.txt SHA256
if command -v sha256sum >/dev/null 2>&1; then
    VERSION_SHA256=$(sha256sum "$STAGING_DIR/VERSION.txt" | awk '{print $1}')
else
    VERSION_SHA256=$(shasum -a 256 "$STAGING_DIR/VERSION.txt" | awk '{print $1}')
fi
VERSION_SIZE=$(stat -f%z "$STAGING_DIR/VERSION.txt" 2>/dev/null || stat -c%s "$STAGING_DIR/VERSION.txt" 2>/dev/null || echo 0)
MANIFEST_FILES+=("{\"path\": \"VERSION.txt\", \"size\": $VERSION_SIZE, \"sha256\": \"$VERSION_SHA256\"}")

# Create .env.redacted
echo "[bundle] Creating .env.redacted with sanitized values"
{
    # Collect all keys from .env and .env.local
    KEYS=()

    if [[ -f .env ]]; then
        while IFS= read -r line; do
            # Skip comments and empty lines
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$line" ]] && continue

            # Extract key
            if [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)= ]]; then
                KEY="${BASH_REMATCH[1]}"
                KEYS+=("$KEY")
            fi
        done < .env
    fi

    if [[ -f .env.local ]]; then
        while IFS= read -r line; do
            # Skip comments and empty lines
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$line" ]] && continue

            # Extract key
            if [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)= ]]; then
                KEY="${BASH_REMATCH[1]}"
                # Add only if not already in KEYS
                if [[ ! " ${KEYS[@]} " =~ " ${KEY} " ]]; then
                    KEYS+=("$KEY")
                fi
            fi
        done < .env.local
    fi

    # Sort keys for stable output
    IFS=$'\n' SORTED_KEYS=($(printf '%s\n' "${KEYS[@]}" | LC_ALL=C sort -u))

    # Generate redacted file
    for KEY in "${SORTED_KEYS[@]}"; do
        # Get value from .env.local first, then .env
        VALUE=""
        if [[ -f .env.local ]]; then
            VALUE=$(grep "^${KEY}=" .env.local 2>/dev/null | cut -d'=' -f2- | head -1 || true)
        fi
        if [[ -z "$VALUE" ]] && [[ -f .env ]]; then
            VALUE=$(grep "^${KEY}=" .env 2>/dev/null | cut -d'=' -f2- | head -1 || true)
        fi

        # Redact value
        if [[ -z "$VALUE" ]]; then
            echo "${KEY}=<EMPTY>"
        elif [[ ${#VALUE} -le 4 ]]; then
            echo "${KEY}=****"
        else
            LAST4="${VALUE: -4}"
            echo "${KEY}=****${LAST4}"
        fi
    done
} > "$STAGING_DIR/.env.redacted"

# Calculate .env.redacted SHA256
if command -v sha256sum >/dev/null 2>&1; then
    ENV_SHA256=$(sha256sum "$STAGING_DIR/.env.redacted" | awk '{print $1}')
else
    ENV_SHA256=$(shasum -a 256 "$STAGING_DIR/.env.redacted" | awk '{print $1}')
fi
ENV_SIZE=$(stat -f%z "$STAGING_DIR/.env.redacted" 2>/dev/null || stat -c%s "$STAGING_DIR/.env.redacted" 2>/dev/null || echo 0)
MANIFEST_FILES+=("{\"path\": \".env.redacted\", \"size\": $ENV_SIZE, \"sha256\": \"$ENV_SHA256\"}")

# Check required files (exit 2 if missing)
echo "[bundle] Checking required files"
if [[ ! -f "infra/docker-compose.yml" ]]; then
    echo "[bundle] FATAL: infra/docker-compose.yml not found" >&2
    exit 2
fi
if [[ ! -f "docs/DEPLOY.md" ]]; then
    echo "[bundle] FATAL: docs/DEPLOY.md not found" >&2
    exit 2
fi
if [[ ! -f "docs/REPLAY.md" ]]; then
    echo "[bundle] FATAL: docs/REPLAY.md not found" >&2
    exit 2
fi

# Add required files
add_file "infra/docker-compose.yml" "infra/docker-compose.yml"
add_file "docs/DEPLOY.md" "docs/DEPLOY.md"
add_file "docs/REPLAY.md" "docs/REPLAY.md"

# Add optional files
add_file "demo/golden/golden.jsonl" "demo/golden/golden.jsonl" || true

# Add logs directory if exists
if [[ -d "logs/day22" ]]; then
    echo "[bundle] Adding logs/day22 directory"
    mkdir -p "$STAGING_DIR/logs"
    cp -r "logs/day22" "$STAGING_DIR/logs/"

    # Add each file to manifest
    find "logs/day22" -type f | while read -r file; do
        rel_path="${file}"
        if command -v sha256sum >/dev/null 2>&1; then
            SHA256=$(sha256sum "$file" | awk '{print $1}')
        else
            SHA256=$(shasum -a 256 "$file" | awk '{print $1}')
        fi
        SIZE=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo 0)
        MANIFEST_FILES+=("{\"path\": \"$rel_path\", \"size\": $SIZE, \"sha256\": \"$SHA256\"}")
    done
else
    MISSING_FILES+=("\"logs/day22\"")
fi

# Create docker_images.json
echo "[bundle] Collecting Docker image information"
{
    echo "{"
    echo "  \"images\": ["

    # Parse services from docker-compose.yml
    SERVICES=$(grep -E '^  [a-z_]+:' infra/docker-compose.yml | sed 's/://g' | sed 's/^  //g' || true)
    FIRST=true

    for SERVICE in $SERVICES; do
        # Get image name from docker-compose.yml
        IMAGE=$(grep -A10 "^  ${SERVICE}:" infra/docker-compose.yml | grep -E '^\s+image:' | head -1 | sed 's/.*image:\s*//' || true)

        if [[ -n "$IMAGE" ]]; then
            if [[ "$FIRST" != true ]]; then
                echo ","
            fi
            FIRST=false

            echo -n "    {"
            echo -n "\"service\": \"$SERVICE\", "
            echo -n "\"image\": \"$IMAGE\""

            # Try to get image info
            if docker image inspect "$IMAGE" >/dev/null 2>&1; then
                IMAGE_ID=$(docker image inspect "$IMAGE" --format='{{.Id}}' 2>/dev/null | cut -d: -f2 | head -c 12)
                REPO_TAGS=$(docker image inspect "$IMAGE" --format='{{json .RepoTags}}' 2>/dev/null || echo '[]')
                REPO_DIGESTS=$(docker image inspect "$IMAGE" --format='{{json .RepoDigests}}' 2>/dev/null || echo '[]')

                echo -n ", \"id\": \"$IMAGE_ID\""
                echo -n ", \"repo_tags\": $REPO_TAGS"
                echo -n ", \"repo_digests\": $REPO_DIGESTS"
            else
                echo -n ", \"status\": \"<NOT_FOUND>\""
            fi

            echo -n "}"
        fi
    done

    echo ""
    echo "  ]"
    echo "}"
} > "$STAGING_DIR/docker_images.json"

# Calculate docker_images.json SHA256
if command -v sha256sum >/dev/null 2>&1; then
    DOCKER_SHA256=$(sha256sum "$STAGING_DIR/docker_images.json" | awk '{print $1}')
else
    DOCKER_SHA256=$(shasum -a 256 "$STAGING_DIR/docker_images.json" | awk '{print $1}')
fi
DOCKER_SIZE=$(stat -f%z "$STAGING_DIR/docker_images.json" 2>/dev/null || stat -c%s "$STAGING_DIR/docker_images.json" 2>/dev/null || echo 0)
MANIFEST_FILES+=("{\"path\": \"docker_images.json\", \"size\": $DOCKER_SIZE, \"sha256\": \"$DOCKER_SHA256\"}")

# Create MANIFEST.json
echo "[bundle] Creating MANIFEST.json"
{
    echo "{"
    echo "  \"metadata\": {"
    echo "    \"version\": \"$SCRIPT_VERSION\","
    echo "    \"commit\": \"$COMMIT\","
    echo "    \"created\": \"$TIMESTAMP\","
    echo "    \"source_date_epoch\": $SOURCE_DATE_EPOCH,"
    echo "    \"hostname\": \"$(hostname | sed 's/[0-9]/x/g')\""
    echo "  },"
    echo "  \"files\": ["

    # Output files
    if [[ ${#MANIFEST_FILES[@]} -gt 0 ]]; then
        FIRST=true
        for FILE_JSON in "${MANIFEST_FILES[@]}"; do
            if [[ "$FIRST" != true ]]; then
                echo ","
            fi
            FIRST=false
            echo -n "    $FILE_JSON"
        done
    fi

    echo ""
    echo "  ],"
    echo "  \"missing\": ["

    # Output missing files
    if [[ ${#MISSING_FILES[@]} -gt 0 ]]; then
        FIRST=true
        for MISSING in "${MISSING_FILES[@]}"; do
            if [[ "$FIRST" != true ]]; then
                echo ","
            fi
            FIRST=false
            echo -n "    $MISSING"
        done
    fi

    echo ""
    echo "  ]"
    echo "}"
} > "$STAGING_DIR/MANIFEST.json"

# Create sorted file list for reproducible zip
echo "[bundle] Creating reproducible zip archive"
cd "$STAGING_DIR"
find . -type f | LC_ALL=C sort > ../filelist.txt

# Create zip with sorted files
if zip -X -r "../$BUNDLE_NAME" -@ < ../filelist.txt 2>/dev/null; then
    echo "[bundle] Created zip with -X flag"
elif zip -r "../$BUNDLE_NAME" -@ < ../filelist.txt 2>/dev/null; then
    echo "[bundle] Created zip without -X flag"
else
    echo "[bundle] Error creating zip" >&2
    exit 1
fi

cd - >/dev/null
mv "$STAGING_DIR/../$BUNDLE_NAME" "$BUNDLE_PATH"
rm -f "$STAGING_DIR/../filelist.txt"

# Calculate bundle SHA256
if command -v sha256sum >/dev/null 2>&1; then
    BUNDLE_SHA256=$(sha256sum "$BUNDLE_PATH" | awk '{print $1}')
else
    BUNDLE_SHA256=$(shasum -a 256 "$BUNDLE_PATH" | awk '{print $1}')
fi

echo "[bundle] Success!"
echo "Bundle: $BUNDLE_PATH"
echo "SHA256: $BUNDLE_SHA256"