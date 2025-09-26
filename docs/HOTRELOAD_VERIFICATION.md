# Configuration Hot Reload Verification

This document contains the verification commands for Card A - Configuration Hot Reload Kernel.

## Prerequisites

Ensure the following environment variables are set:
```bash
export CONFIG_HOTRELOAD_ENABLED=true
export CONFIG_HOTRELOAD_TTL_SECONDS=60
export RULES_DIR=rules
```

## Verification Commands

### 0) Start the API with hot reload enabled

```bash
# Start the services
export CONFIG_HOTRELOAD_ENABLED=true
export CONFIG_HOTRELOAD_TTL_SECONDS=60
docker compose -f infra/docker-compose.yml up -d api

# Check the startup logs
docker compose -f infra/docker-compose.yml logs api | grep "config.startup"
```

### 1) Modify a threshold value

```bash
# Modify a threshold (adjust based on actual file content)
# On macOS:
sed -i '' 's/threshold:\s*10/threshold: 11/' rules/thresholds.yml

# On Linux:
# sed -i 's/threshold:\s*10/threshold: 11/' rules/thresholds.yml

# Wait for TTL period
sleep 70
```

### 2) Observe reload logs

```bash
# Check for reload/applied logs, should see no errors
docker compose -f infra/docker-compose.yml logs --tail=200 api | egrep 'config.reload|config.applied|config.reload.error'
```

### 3) Check metrics (requires /metrics endpoint - Card D)

```bash
# This will work once the /metrics endpoint is added in Card D
curl -s 'http://localhost:8000/metrics' | egrep 'config_version|config_reload_total|config_reload_errors_total|config_last_success_unixtime'
```

### 4) SIGHUP for immediate refresh (optional)

```bash
# Send SIGHUP to trigger immediate reload
# First, find the API process PID
docker compose -f infra/docker-compose.yml exec -T api sh -c 'ps aux | grep "python.*main" | grep -v grep'

# Then send SIGHUP (replace PID with actual process ID)
docker compose -f infra/docker-compose.yml exec -T api sh -c 'kill -HUP 1'

# Or, if the main process is PID 1:
docker compose -f infra/docker-compose.yml exec -T api sh -c 'kill -HUP 1'

# Check logs for SIGHUP handling
docker compose -f infra/docker-compose.yml logs --tail=50 api | grep -i sighup
```

### 5) Disable hot reload (incident killswitch)

```bash
# Set the environment variable to disable
export CONFIG_HOTRELOAD_ENABLED=false

# Restart the API
docker compose -f infra/docker-compose.yml restart api

# Verify hot reload is disabled in logs
docker compose -f infra/docker-compose.yml logs --tail=50 api | grep "config.startup"
```

## Testing Script

Run the test script to verify basic functionality:

```bash
# Run from the project root
python api/scripts/test_hotreload.py
```

## Rollback Procedure

If you need to rollback the hot reload feature:

1. **Disable hot reload without code changes:**
   ```bash
   export CONFIG_HOTRELOAD_ENABLED=false
   docker compose -f infra/docker-compose.yml restart api
   ```

2. **Full rollback (if needed):**
   - Revert changes to `api/security/goplus.py`
   - Revert changes to `api/onchain/rules_engine.py`
   - Revert changes to `api/main.py`
   - Remove `api/config/hotreload.py`
   - Remove `api/config/__init__.py`
   - Restart services

## Key Implementation Points

1. **Atomic Replacement**: Configuration updates use RCU-style atomic replacement to ensure thread safety
2. **Fail-Safe**: Parse errors keep the old configuration version active
3. **File Validation**: Only allows `[-_a-z0-9]` filenames to prevent directory traversal
4. **TTL Throttling**: Minimum 1-second cooldown between checks to prevent thrashing
5. **Metrics**: Tracks reload count, errors, version SHA, and last success timestamp
6. **SIGHUP Support**: Can trigger immediate reload via SIGHUP signal
7. **Killswitch**: `CONFIG_HOTRELOAD_ENABLED=false` disables all hot reload functionality

## Supported Configuration Files

The following YAML files in the `rules/` directory are monitored:
- `thresholds.yml`
- `kol.yml`
- `blacklist.yml`
- `risk_rules.yml`
- `onchain.yml`
- `rules.yml`
- `topic_merge.yml`

Files are mapped to namespaces by removing the `.yml` extension:
- `thresholds.yml` → namespace `thresholds`
- `risk_rules.yml` → namespace `risk_rules`

## Log Keywords

The implementation uses consistent log keywords:
- `config.applied` - Configuration successfully applied
- `config.reload` - Configuration change detected and reloading
- `config.reload.error` - Parse or validation error during reload
- `config.startup` - Registry initialization at startup

All logs include relevant fields: `ns` (namespace), `old_sha`, `new_sha`, `elapsed_ms`, `reason`