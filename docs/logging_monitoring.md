# Logging & Monitoring Documentation

## Overview

This document describes the structured logging and monitoring implementation for the GUIDS platform, including unified logging fields, SLO definitions, error budget policies, and acceptance testing procedures.

## Structured Logging

### Unified Log Format

All logs are output as JSON with the `[JSON]` prefix for easy parsing. Each log entry contains fixed fields for consistency:

```json
{
  "ts_iso": "2024-01-01T00:00:00.000Z",    // ISO8601 timestamp in UTC
  "ts_epoch": 1704067200,                   // Unix timestamp (seconds)
  "trace_id": "a1b2c3d4e5f6g7h8",          // 16-char hex trace ID
  "request_id": "12345678",                 // 8-char hex request ID
  "level": "info",                          // Log level: debug/info/warn/error
  "stage": "processing",                    // Event stage/category
  "message": "Event description",           // Human-readable message
  // Additional fields as needed
  "status": "success",
  "duration_ms": 123,
  "error": "error details if any"
}
```

### Context Variables

The logging system automatically injects `trace_id` and `request_id` from the request context. These are set by the `TraceMiddleware` for each incoming HTTP request.

### Usage Examples

```python
from api.utils.logging import log_json

# Basic logging
log_json("user.login", user_id="123", status="success")

# With custom level
log_json("database.error", level="error", error="Connection timeout", retry_count=3)

# With timing
log_json("api.call", service="goplus", duration_ms=250, cached=False)
```

### Log Aggregation

Logs can be filtered and aggregated using the following patterns:

- Filter by trace_id to follow a single request through the system
- Filter by stage to focus on specific components
- Filter by level to see only errors or warnings
- Group by request_id to see all operations in a request

## Service Level Objectives (SLOs)

### Primary SLOs

1. **HTTP Availability**
   - **Target**: 99% success rate (< 1% 5xx errors)
   - **Measurement Window**: 5 minutes
   - **Alert Threshold**: > 1% 5xx errors over 5 minutes
   - **Error Budget**: 0.01 (1%) monthly

2. **Pipeline Latency**
   - **Target**: P95 < 2000ms
   - **Measurement Window**: 5 minutes
   - **Alert Threshold**: P95 > 2000ms for 3 minutes
   - **Error Budget**: 5% of requests > 2000ms monthly

3. **Telegram Delivery**
   - **Target**: 80% success rate
   - **Measurement Window**: 1 minute
   - **Alert Threshold**: < 80% success rate
   - **Error Budget**: 20% monthly failure rate

4. **Configuration Stability**
   - **Target**: Zero reload errors
   - **Measurement Window**: 1 minute
   - **Alert Threshold**: Any reload error
   - **Error Budget**: 10 errors per month

### Error Budget Policy

When error budgets are exhausted:

1. **Immediate Actions**:
   - Freeze all non-critical deployments
   - Escalate to on-call engineer
   - Begin incident response procedure

2. **Recovery Requirements**:
   - Root cause analysis required
   - Postmortem for budget exhaustion
   - Error budget refreshes monthly

3. **Budget Tracking**:
   - Dashboard panel shows remaining budget percentage
   - Weekly reports on budget consumption
   - Alerts at 75%, 90%, and 100% consumption

## Metrics

### Key Metrics Exported

| Metric | Description | Labels | Unit |
|--------|-------------|--------|------|
| `http_requests_total` | Total HTTP requests | method, endpoint, status_code | counter |
| `http_request_duration_seconds` | Request processing time | method, endpoint | histogram |
| `pipeline_latency_ms` | Pipeline processing latency | - | histogram |
| `telegram_send_total` | Telegram send attempts | status, code | counter |
| `config_reload_failures_total` | Config reload failures | source, reason | counter |
| `config_reload_success_total` | Successful config reloads | source | counter |
| `cache_hits_total` | Cache hits | layer | counter |
| `cache_misses_total` | Cache misses | layer | counter |

### Dashboard Panels

The SLO dashboard (`dashboards/slo.json`) includes:

1. **5xx Error Rate** - Real-time HTTP error rate with SLO threshold
2. **Pipeline Latency P95** - 95th percentile latency tracking
3. **Config Reload Errors** - Breakdown by source and reason
4. **Telegram Error Rate** - Delivery success rate monitoring
5. **Error Budget Gauge** - Monthly budget remaining
6. **Request Rate Table** - Breakdown by endpoint and status
7. **Cache Hit Rate** - Cache effectiveness metric

## Alerts Configuration

Alerts are configured in `alerts.yml` with the following rules:

### HTTP 5xx Error Rate
```yaml
- name: http_5xx_error_rate_high
  threshold: 0.01  # > 1%
  window_seconds: 300  # 5 minutes
  severity: critical
```

### Pipeline Latency
```yaml
- name: pipeline_latency_high
  threshold: 2000  # > 2000ms
  window_seconds: 180
  severity: warn
```

### Telegram Errors
```yaml
- name: telegram_error_rate_high
  threshold: 0.2  # > 20%
  window_seconds: 60
  severity: warn
```

### Config Reload Errors
```yaml
- name: config_reload_errors
  threshold: 1  # Any error
  window_seconds: 60
  severity: error
```

## Acceptance Testing

### Test 1: Configuration Reload Error Detection

**Objective**: Verify that malformed YAML triggers error metrics and alerts.

**Steps**:
1. Create a malformed YAML file:
   ```bash
   echo "invalid: yaml: syntax:" > rules/test_invalid.yml
   ```

2. Trigger config reload (if hot reload enabled) or restart service

3. Verify metric increment:
   ```bash
   curl -s localhost:8000/metrics | grep config_reload_failures_total
   # Expected: config_reload_failures_total{source="test_invalid",reason="parse_error"} 1
   ```

4. Check logs for error with trace_id:
   ```bash
   docker logs api 2>&1 | grep "config.reload.error" | tail -1 | jq .
   # Expected: JSON with trace_id, reason="parse_error"
   ```

5. Clean up:
   ```bash
   rm rules/test_invalid.yml
   ```

### Test 2: HTTP 5xx Error Alert

**Objective**: Verify that 5xx errors trigger metrics and alerts.

**Steps**:
1. Create a test endpoint that returns 500:
   ```python
   # Add temporarily to api/main.py
   @app.get("/test_500")
   def test_500():
       raise Exception("Test 500 error")
   ```

2. Generate errors to exceed threshold:
   ```bash
   # Generate 10 errors (assuming low traffic, this should exceed 1%)
   for i in {1..10}; do
     curl -s http://localhost:8000/test_500 || true
   done
   ```

3. Verify metric:
   ```bash
   curl -s localhost:8000/metrics | grep 'http_requests_total.*status_code="500"'
   # Expected: http_requests_total{method="GET",endpoint="/test_500",status_code="500"} 10
   ```

4. Check alert would fire (in production with Prometheus):
   ```bash
   # Query: rate(http_requests_total{status_code=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.01
   ```

5. Verify logs have trace_id:
   ```bash
   docker logs api 2>&1 | grep "http.request.error" | tail -1 | jq .trace_id
   # Expected: 16-character hex string
   ```

### Test 3: Log Structure Validation

**Objective**: Verify all logs are valid JSON with required fields.

**Steps**:
1. Collect sample logs:
   ```bash
   # Run normal operations for 1 minute
   docker logs api 2>&1 | grep "^\[JSON\]" | tail -100 > sample_logs.txt
   ```

2. Validate JSON structure:
   ```python
   import json

   with open('sample_logs.txt') as f:
       for line in f:
           if line.startswith('[JSON] '):
               log_json = line[7:].strip()
               log = json.loads(log_json)

               # Verify required fields
               assert 'ts_iso' in log
               assert 'ts_epoch' in log
               assert 'trace_id' in log
               assert 'request_id' in log
               assert 'level' in log
               assert 'stage' in log
               assert 'message' in log

               # Verify trace_id format (16 hex chars or "no-trace")
               tid = log['trace_id']
               assert tid == 'no-trace' or (len(tid) == 16 and all(c in '0123456789abcdef' for c in tid))

   print("All logs valid!")
   ```

3. Verify trace propagation:
   ```bash
   # Make a request and track its trace_id
   TRACE_ID=$(curl -v http://localhost:8000/health 2>&1 | grep "X-Trace-Id" | cut -d' ' -f2)

   # Find all logs for this trace
   docker logs api 2>&1 | grep "\"trace_id\":\"$TRACE_ID\""
   # Expected: Multiple log entries with same trace_id
   ```

### Test 4: Dashboard Rendering

**Objective**: Verify dashboard loads and displays metrics.

**Steps**:
1. Load dashboard configuration:
   ```bash
   cat dashboards/slo.json | jq .panels[].id
   # Expected: List of panel IDs
   ```

2. Verify each metric exists:
   ```bash
   curl -s localhost:8000/metrics | grep -E "(http_requests_total|pipeline_latency_ms|config_reload|telegram_send|cache_)"
   # Expected: Multiple metric lines
   ```

3. Simulate dashboard queries (examples):
   ```bash
   # 5xx rate (would be done by Prometheus)
   # rate(http_requests_total{status_code=~"5.."}[5m]) / rate(http_requests_total[5m])

   # Cache hit rate
   curl -s localhost:8000/metrics | grep cache_hits_total
   curl -s localhost:8000/metrics | grep cache_misses_total
   ```

## Troubleshooting

### Common Issues

1. **Missing trace_id in logs**
   - Check TraceMiddleware is registered in api/main.py
   - Verify contextvars are properly propagated in async code
   - For background tasks, trace_id will be "no-trace"

2. **Metrics not appearing**
   - Ensure METRICS_EXPOSED=true in environment
   - Check /metrics endpoint is accessible
   - Verify Prometheus scraped recently

3. **Alerts not firing**
   - Check alert rule syntax in alerts.yml
   - Verify metric names match exactly
   - Ensure threshold and window are appropriate

4. **High 5xx error rate**
   - Check application logs for exceptions
   - Review recent deployments
   - Check external service dependencies

### Debug Commands

```bash
# Check current error rates
curl -s localhost:8000/metrics | grep http_requests_total | grep 'status_code="5'

# View recent errors with trace
docker logs api 2>&1 | grep '"level":"error"' | tail -10 | jq '{trace_id, stage, error}'

# Check config reload status
curl -s localhost:8000/metrics | grep config_reload

# Validate log format
docker logs api 2>&1 | grep "^\[JSON\]" | tail -1 | jq .
```

## Maintenance

### Log Rotation

Configure log rotation to prevent disk exhaustion:

```yaml
# docker-compose.yml
services:
  api:
    logging:
      driver: json-file
      options:
        max-size: "100m"
        max-file: "10"
```

### Metric Cardinality

Monitor metric cardinality to prevent explosion:
- Limit endpoint labels to key routes
- Use status_code groups (2xx, 3xx, 4xx, 5xx)
- Aggregate similar error reasons

### Performance Impact

Logging overhead is minimal:
- Context vars: ~0.01ms per request
- JSON encoding: ~0.1ms per log
- Metric updates: ~0.01ms per increment

Total overhead: < 1ms per request typical