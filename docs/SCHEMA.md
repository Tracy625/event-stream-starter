# Database Schema Specification

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
- Index: CREATE INDEX ON raw_posts (ts);

## events

- event_key TEXT PRIMARY KEY
- type TEXT
- summary TEXT
- evidence JSONB DEFAULT '[]'::jsonb
- impacted_assets TEXT[]
- start_ts TIMESTAMPTZ NOT NULL
- last_ts TIMESTAMPTZ NOT NULL
- heat_10m INTEGER DEFAULT 0
- heat_30m INTEGER DEFAULT 0

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
- Index: CREATE INDEX ON signals (event_key, ts DESC);
