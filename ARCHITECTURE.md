# Architecture

Event Stream Starter is a modular, scalable event processing pipeline built on microservices principles.

## Table of Contents

- [System Overview](#system-overview)
- [Component Architecture](#component-architecture)
- [Data Flow](#data-flow)
- [Technology Stack](#technology-stack)
- [Database Schema](#database-schema)
- [Extension Points](#extension-points)
- [Deployment Architecture](#deployment-architecture)
- [Performance Considerations](#performance-considerations)

---

## System Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Source Layer                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Twitter  │  │  Apify   │  │ BigQuery │  │   DEX    │  ...  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
└───────┼─────────────┼─────────────┼─────────────┼──────────────┘
        │             │             │             │
        └─────────────┴─────────────┴─────────────┘
                      │
        ┌─────────────▼──────────────┐
        │   Ingestion Adapters       │
        │  (Normalize & Validate)    │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │   Filter & Enrich Layer    │
        │  (Sentiment, Keywords)     │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │      Event Queue           │
        │    (Redis/Celery)          │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │      Worker Pool           │
        │  (Process & Score)         │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │     Rules Engine           │
        │  (Evaluate & Classify)     │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │    Event Storage           │
        │    (PostgreSQL)            │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │       Outbox Queue         │
        │   (Dedup & Priority)       │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │   Notification Layer       │
        │ (Telegram, Webhook, etc.)  │
        └────────────────────────────┘
```

### Design Principles

1. **Separation of Concerns** - Each component has a single, well-defined responsibility
2. **Async by Default** - Non-blocking I/O for high throughput
3. **Fail-Safe** - Graceful degradation when external services are unavailable
4. **Idempotent Operations** - Safe to retry any operation
5. **Observable** - Structured logging and metrics at every layer
6. **Configurable** - Hot-reload for rules without restarts

---

## Component Architecture

### 1. API Layer (`api/`)

**Purpose:** REST API for external access and health monitoring

**Responsibilities:**
- Health checks (`/healthz`)
- Event query endpoints (`/events`, `/signals`)
- Manual trigger endpoints
- Metrics exposure (`/metrics`)

**Technology:** FastAPI (async Python)

**Key Files:**
- `api/main.py` - Application entry point
- `api/routes/` - API route handlers
- `api/models.py` - Database models

### 2. Worker Layer (`worker/`)

**Purpose:** Async task execution and background jobs

**Responsibilities:**
- Process events from queue
- Execute scheduled tasks
- Retry failed operations
- Update event states

**Technology:** Celery (distributed task queue)

**Key Files:**
- `worker/celery_app.py` - Celery configuration
- `worker/jobs/` - Background job definitions
- `worker/pipeline/` - Processing pipeline stages

### 3. Ingestion Adapters

**Purpose:** Normalize data from heterogeneous sources

**Location:** `api/clients/`, `api/providers/`

**Adapters:**
- **X Client** (`api/clients/x_client.py`) - Twitter/X API integration
- **Apify Client** (`api/clients/apify_client.py`) - Web scraping
- **DEX Provider** (`api/providers/dex_provider.py`) - DEX data aggregation
- **GoPlus Provider** (`api/providers/security/goplus.py`) - Security scans
- **BigQuery Client** (`api/clients/bq_client.py`) - On-chain analytics

**Common Interface:**
```python
class BaseAdapter:
    async def fetch(self, params: dict) -> List[Event]:
        """Fetch raw data from source"""

    def normalize(self, raw_data: Any) -> Event:
        """Convert to standard Event format"""

    def validate(self, event: Event) -> bool:
        """Validate event structure"""
```

### 4. Processing Pipeline

**Purpose:** Transform and enrich raw events

**Stages:**

1. **Filter** (`api/pipeline/filter.py`)
   - Language detection
   - Spam filtering
   - Blacklist checks

2. **Refine** (`api/pipeline/refine.py`)
   - Text normalization
   - Entity extraction (tokens, contracts)
   - Sentiment analysis

3. **Deduplication** (`api/pipeline/dedup.py`)
   - Hash-based dedup (Redis)
   - Time-window dedup (14 days)
   - Soft fingerprinting

4. **Enrichment** (`api/pipeline/enrich.py`)
   - Security checks (GoPlus)
   - Liquidity data (DEX)
   - On-chain features (BigQuery)

### 5. Rules Engine

**Purpose:** Score and classify events

**Configuration:** `rules/rules.yml` (hot-reloadable)

**Features:**
- Expression-based conditions
- Weighted scoring
- Priority groups
- Environment variable substitution

**Example Rule:**
```yaml
- name: "high_liquidity"
  condition: "dex_liquidity >= 500000"
  score: 8
  reason: "High liquidity (≥$500K)"
```

### 6. Storage Layer

**Purpose:** Persist events and state

**Database:** PostgreSQL 15+

**Key Tables:**
- `events` - Aggregated events
- `raw_posts` - Original social posts
- `signals` - Scored signals with features
- `push_outbox` - Outgoing notifications queue
- `onchain_features` - Cached on-chain data

See [docs/SCHEMA.md](docs/SCHEMA.md) for full schema.

### 7. Cache Layer

**Purpose:** Fast lookups and deduplication

**Technology:** Redis 7+

**Usage:**
- Deduplication keys (14-day TTL)
- Rate limiting (sliding window)
- Hot-reload configuration cache
- Provider response cache (fallback data)

**Key Patterns:**
```
dedup:x:{tweet_id}           # Tweet deduplication
rate:{endpoint}:{key}        # Rate limiting
cache:dex:{chain}:{ca}       # DEX data cache
config:rules:version         # Config version tracking
```

### 8. Notification Layer

**Purpose:** Deliver events to external channels

**Pattern:** Outbox Pattern (transactional outbox)

**Flow:**
1. Event written to DB + `push_outbox` (atomic transaction)
2. Worker polls `push_outbox` for pending items
3. Send to channel (Telegram, webhook, etc.)
4. Mark as `done` or retry with exponential backoff
5. Move to DLQ after max retries

**Retry Strategy:**
- 429 errors → Use `Retry-After` header
- 5xx errors → Exponential backoff (max 10min)
- Network errors → Exponential backoff
- 4xx errors (non-429) → Move to DLQ immediately

---

## Data Flow

### End-to-End Flow Example

**Scenario:** KOL tweets about a new token

```
1. Ingestion
   X API → x_client.fetch_tweets()
   ↓
   Normalize to raw_post format

2. Filter & Refine
   ↓ filter.py (language, spam, blacklist)
   ↓ refine.py (sentiment, keywords, CA extraction)
   ↓ Extract: {symbol: "DEMO", token_ca: "0x...", sentiment: 0.75}

3. Deduplication
   ↓ dedup.py
   Redis check: dedup:x:{tweet_id}
   ↓ MISS → Continue | HIT → Skip

4. Enrichment
   ↓ enrich.py
   Parallel fetch:
   - GoPlus security scan → {risk: "green", tax: 5}
   - DEX data → {liquidity: 250000, volume_1h: 50000}
   - BigQuery on-chain → {active_addrs_24h: 1200}

5. Scoring
   ↓ rules/rules.yml
   Apply rules:
   - goplus_risk == 'green' → +3
   - dex_liquidity >= 50000 → +5
   - sentiment >= 0.7 → +4
   Final score: 12

6. Storage
   ↓ events.upsert()
   Write to DB (events + signals tables)

7. Notification
   ↓ push_outbox.insert()
   If score >= threshold:
   - Write to outbox
   - Worker picks up
   - Send to Telegram
   - Mark as done
```

---

## Technology Stack

### Backend
- **Python 3.11+** - Primary language
- **FastAPI** - Async web framework
- **Celery** - Distributed task queue
- **SQLAlchemy** - ORM
- **Alembic** - Database migrations
- **Pydantic** - Data validation

### Storage
- **PostgreSQL 15+** - Primary database
- **Redis 7+** - Cache and queue backend

### Infrastructure
- **Docker** - Containerization
- **Docker Compose** - Local orchestration
- **Make** - Build automation

### External Integrations (Optional)
- **X (Twitter) API** - Social data
- **Apify** - Web scraping
- **GoPlus API** - Security scans
- **DEX APIs** - Liquidity data (DexScreener, GeckoTerminal)
- **Google BigQuery** - On-chain data warehouse
- **Telegram Bot API** - Notifications

---

## Database Schema

### Core Tables

**events**
```sql
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    event_key VARCHAR(255) UNIQUE,
    type VARCHAR(50),
    symbol VARCHAR(20),
    token_ca VARCHAR(100),
    chain VARCHAR(20),
    summary TEXT,
    evidence JSONB,
    start_ts TIMESTAMPTZ,
    last_ts TIMESTAMPTZ,
    evidence_count INTEGER DEFAULT 1,
    version VARCHAR(10)
);
```

**signals**
```sql
CREATE TABLE signals (
    id SERIAL PRIMARY KEY,
    event_key VARCHAR(255) UNIQUE,
    state VARCHAR(20), -- candidate, verified, downgraded
    score NUMERIC(5,2),
    risk_level VARCHAR(20),
    features_snapshot JSONB,
    onchain_asof_ts TIMESTAMPTZ,
    onchain_confidence NUMERIC(4,3),
    ts TIMESTAMPTZ DEFAULT now()
);
```

**push_outbox**
```sql
CREATE TABLE push_outbox (
    id SERIAL PRIMARY KEY,
    channel_id BIGINT,
    event_key VARCHAR(255),
    payload_json JSONB,
    status VARCHAR(20), -- pending, done, failed, dlq
    retry_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

See [docs/SCHEMA.md](docs/SCHEMA.md) for complete schema.

---

## Extension Points

### Adding a New Data Source

1. Create adapter in `api/clients/your_source.py`
2. Implement `fetch()` and `normalize()` methods
3. Add job in `worker/jobs/your_source_poll.py`
4. Register Celery task
5. Add configuration to `.env.example`
6. Document in README

### Adding a New Rule

1. Edit `rules/rules.yml`
2. Add condition and score
3. Rules reload automatically (hot-reload)
4. No code changes required

### Adding a New Notification Channel

1. Create service in `api/services/your_channel.py`
2. Implement `send()` method with retry logic
3. Update `worker/jobs/send_notifications.py`
4. Add configuration to `.env.example`

---

## Deployment Architecture

### Single-Node Setup (Development)

```
┌─────────────────────────────────────┐
│         Docker Host                 │
│                                     │
│  ┌──────────┐  ┌──────────┐       │
│  │   API    │  │  Worker  │       │
│  │  :8000   │  │ (Celery) │       │
│  └────┬─────┘  └────┬─────┘       │
│       │             │              │
│  ┌────▼─────────────▼─────┐       │
│  │      PostgreSQL        │       │
│  │         :5432          │       │
│  └────────────────────────┘       │
│                                     │
│  ┌────────────────────────┐       │
│  │        Redis           │       │
│  │        :6379           │       │
│  └────────────────────────┘       │
└─────────────────────────────────────┘
```

### Multi-Node Setup (Production)

```
┌──────────────┐     ┌──────────────┐
│  API Server  │     │  API Server  │
│    (x2+)     │     │    (x2+)     │
└──────┬───────┘     └──────┬───────┘
       │                    │
       └────────┬───────────┘
                │
       ┌────────▼────────┐
       │  Load Balancer  │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │    PostgreSQL   │
       │  (RDS/Managed)  │
       └─────────────────┘

┌──────────────┐     ┌──────────────┐
│   Worker     │     │   Worker     │
│    (x3+)     │     │    (x3+)     │
└──────┬───────┘     └──────┬───────┘
       │                    │
       └────────┬───────────┘
                │
       ┌────────▼────────┐
       │  Redis Cluster  │
       │ (ElastiCache)   │
       └─────────────────┘
```

---

## Performance Considerations

### Throughput

- **API:** ~1000 req/s per instance (FastAPI async)
- **Worker:** ~100 events/s per worker (depends on enrichment)
- **Database:** Optimized for writes (events table partitioning recommended at scale)

### Latency Budget

Target P95 latency: **≤2 minutes** (end-to-end)

**Breakdown:**
- Ingestion: 500ms
- Filter/Refine: 200ms
- Enrichment: 800ms (parallel)
- Rules: 100ms
- Storage: 100ms
- Notification: 300ms

### Scalability Strategies

1. **Horizontal Scaling**
   - Add more worker instances
   - Use managed Redis (ElastiCache)
   - Database read replicas

2. **Caching**
   - Provider response cache (15-60s TTL)
   - Config hot-reload cache
   - Frequent query results

3. **Batching**
   - Bulk inserts for raw_posts
   - Batch external API calls where possible

4. **Degradation**
   - Rules-only mode when ML models fail
   - Cached data when providers offline
   - Stub responses in demo mode

---

## Monitoring & Observability

### Structured Logging

All logs are JSON-formatted with standard fields:

```json
{
  "stage": "pipeline.filter",
  "event_key": "eth:DEMO:2025-01-15T10:00:00Z",
  "passed": true,
  "latency_ms": 45,
  "timestamp": "2025-01-15T10:05:23.456Z"
}
```

### Metrics Endpoints

`GET /metrics` (Prometheus format)

**Key Metrics:**
- `pipeline_latency_ms` - Processing latency histogram
- `telegram_send_total` - Notification success/failure counters
- `outbox_backlog` - Pending notifications gauge
- `config_reload_total` - Hot-reload event counter
- `external_error_total_{code}` - External API error counters

### Health Checks

`GET /healthz` - Overall system health

Returns:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected",
  "redis": "connected"
}
```

---

## Security Architecture

### Data Protection
- Credentials in environment variables only
- No secrets in code or config files
- `.env` files gitignored

### Input Validation
- Pydantic models for all inputs
- SQL parameterization (SQLAlchemy)
- XSS protection on text fields

### Rate Limiting
- Redis-based sliding window
- Per-endpoint and global limits
- Configurable thresholds

### External API Safety
- Timeout on all external calls
- Circuit breaker pattern
- Cost guards (e.g., BigQuery byte limits)

---

## Future Enhancements

### Roadmap Ideas

1. **Real-time WebSocket API** - Live event stream
2. **GraphQL Interface** - Flexible querying
3. **ClickHouse Integration** - Time-series analytics
4. **Kafka Migration** - Higher throughput message queue
5. **Multi-tenant Support** - API key-based access control
6. **ML Model Training** - Custom sentiment/classification models
7. **Dashboard UI** - Web interface for monitoring

---

## References

- [README.md](README.md) - Quick start guide
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development guidelines
- [docs/SCHEMA.md](docs/SCHEMA.md) - Database schema details
- [samples/README.md](samples/README.md) - Sample data format
