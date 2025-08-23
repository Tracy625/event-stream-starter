# Database Schema Specification

## TL;DR

- **Current Alembic Version**: 003
- **Recent Changes**:
  - 2025-08-23 (Day5): `events` 表幂等迁移，新增 10 列 + 2 索引（保留旧列）
  - 2025-08-22 (Day4): 接入 HuggingFace 情感分析与关键词抽取，更新相关 ENV
  - 2025-08-21 (Day3+): 增加 metrics/cache/bench，补充结构化日志与延迟预算

---

## raw_posts

- id BIGSERIAL PRIMARY KEY
- source TEXT NOT NULL
- author TEXT
- text TEXT NOT NULL
- ts TIMESTAMPTZ NOT NULL
- urls JSONB DEFAULT '[]'::jsonb
- token_ca TEXT
- symbol TEXT
- is_candidate BOOLEAN DEFAULT FALSE
- sentiment_label TEXT
- sentiment_score DOUBLE PRECISION
- keywords TEXT[]
- Index: `CREATE INDEX ON raw_posts (ts);`

---

## events

> **说明**：
>
> - Day1 建表（含 type/summary/evidence/impacted*assets/heat*\*）。
> - Day2 增加 `score`。
> - Day5 补齐 symbol/token_ca/topic_hash/time_bucket_start/evidence_count/candidate_score/keywords_norm/version/last_sentiment/last_sentiment_score + 2 索引。
> - 使用幂等迁移，旧字段保留，后续迁移再做约束收紧或清理。

- event_key TEXT PRIMARY KEY
- type TEXT (legacy, Day1)
- summary TEXT (legacy)
- evidence JSONB DEFAULT '[]'::jsonb (legacy)
- impacted_assets TEXT[] (legacy)
- start_ts TIMESTAMPTZ NOT NULL
- last_ts TIMESTAMPTZ NOT NULL
- heat_10m INTEGER DEFAULT 0 (legacy)
- heat_30m INTEGER DEFAULT 0 (legacy)
- score DOUBLE PRECISION NOT NULL DEFAULT 0 (legacy, Day2)
- symbol TEXT (Day5)
- token_ca TEXT (Day5)
- topic_hash TEXT (Day5, currently nullable, 待回填后加约束)
- time_bucket_start TIMESTAMPTZ (Day5, currently nullable, 待回填后加约束)
- evidence_count INTEGER NOT NULL DEFAULT 0 (Day5)
- candidate_score DOUBLE PRECISION NOT NULL DEFAULT 0 (Day5)
- keywords_norm JSONB (Day5)
- version TEXT NOT NULL DEFAULT 'v1' (Day5)
- last_sentiment TEXT (Day5)
- last_sentiment_score DOUBLE PRECISION (Day5)

**Indexes**:

- `events_pkey` PRIMARY KEY (event_key)
- `idx_events_symbol_bucket` (symbol, time_bucket_start) [Day5]
- `idx_events_last_ts` (last_ts DESC) [Day5]

**Foreign Keys**:

- `signals(event_key)` → `events(event_key)` ON DELETE CASCADE

---

## signals

- id BIGSERIAL PRIMARY KEY
- event_key TEXT REFERENCES events(event_key)
- market_type TEXT
- advice_tag TEXT
- confidence INTEGER
- goplus_risk TEXT
- goplus_tax DOUBLE PRECISION
- lp_lock_days INTEGER
- dex_liquidity DOUBLE PRECISION
- dex_volume_1h DOUBLE PRECISION
- ts TIMESTAMPTZ DEFAULT now()
- Index: `CREATE INDEX ON signals (event_key, ts DESC);`

---

## Alembic Migration History

| Revision | Date       | Content                                            |
| -------- | ---------- | -------------------------------------------------- |
| 003      | 2025-08-23 | `events` 幂等迁移：新增 10 列 + 2 索引，保留旧列   |
| 002      | 2025-08-22 | `events` 增加 `score` 列                           |
| 001      | 2025-08-21 | 初始 schema：创建 `raw_posts`、`events`、`signals` |
