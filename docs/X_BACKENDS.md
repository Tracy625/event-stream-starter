X Backends (GraphQL + Apify) and Failover

Overview
- Supports multiple X (Twitter) data backends with ordered failover.
- Default order is GraphQL first, then Apify.
- Health/metrics exposed for visibility and tuning.

Configuration (.env)
- X_BACKENDS=graphql,apify (global default order)
- X_BACKEND=graphql  (legacy single-backend, used when X_BACKENDS empty)
- APIFY_TOKEN=       (Apify API token)
- APIFY_TWEET_SCRAPER_ACTOR=apify/tweet-scraper-v2
- APIFY_DEFAULT_COUNTRY=US
- X_FAILOVER_COOLDOWN_SEC=60
- X_REQUEST_TIMEOUT_SEC=5
- X_RETRY_MAX=2

Per-operation priority
- X_BACKENDS_TWEETS=graphql,apify
- X_BACKENDS_PROFILE=apify,graphql
- X_BACKENDS_SEARCH=apify,graphql

Caching & degrade fallback
- X_CACHE_TTL_S=180 (Redis/in-process fallback). Keys: x:tweets:{handle}:{limit}, x:profile:{handle}
- On total failure, returns last cached value with diagnostic.stale=true

Race mode (optional)
- X_RACE_MODE=true|false (default false). If true, fires first two backends with guard delay
- X_RACE_GUARD_MS=250 minimal delay between first and second fire

Apify polling guards
- APIFY_POLL_INTERVAL_MS=800, APIFY_POLL_MAX=3, APIFY_ITEMS_MAX_MULTIPLIER=2 (cost protection)

Clients
- GraphQLXClient: Uses X GraphQL (requires X_GRAPHQL_AUTH_TOKEN and X_GRAPHQL_CT0)
- ApifyXClient: Starts Tweet Scraper actor, polls dataset, maps items to unified schema
- MultiSourceXClient: Tries backends in configured order, with cooldown after failures

Metrics (Prometheus text export via /metrics)
- x_backend_request_total{backend,op,status}
- x_backend_latency_ms_bucket{backend,op,le}
- x_backend_latency_ms_sum, x_backend_latency_ms_count
- x_backend_failover_total{from}

Health Endpoint
- GET /health/x
  - backends: configured order (from X_BACKENDS or X_BACKEND)
  - status: per-backend last_ok_ts, last_err_ts, last_error, cooldown_until
  - probes: per-backend upstream RTT and status (ok|auth|timeout|net|fail)

Simple Read-only Routes (OpenAPI diagnostic)
- GET /x/tweets?handle=alice&limit=5 → minimal list (id, author, text, created_at, urls)
- GET /x/user?handle=alice → minimal profile (handle, avatar_url, ts) plus optional diagnostic:
  - diagnostic: { source_map: {field: backend}, stale: bool }

Notes
- Mapping lives in api/adapters/x_apify.py to isolate schema drift.
- Apify polling is short and bounded (≤3 attempts). For heavy workloads, consider an async job.
