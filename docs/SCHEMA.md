Database Schema Specification

TL;DR
• Current Alembic Version: 010
• Recent Changes:
• 2025-08-26 (Day7): signals 扩展 goplus 字段（goplus_cache 表见 Rev 005）
• 2025-08-31 (Day8): 新增 configs/x_kol.yaml 与验收脚本 verify_x_kol.py；raw_posts 使用 metadata JSON 扩展存储 tweet_id 等字段，无数据库迁移
• 2025-08-25 (Day6): events 表新增精炼结果与执行元数据列（refined*\* 与 refine*\*），新增 2 个索引；读路径不依赖新列，向后兼容
• 2025-08-23 (Day5): events 表幂等迁移，新增 10 列 + 2 索引（保留旧列）
• 2025-08-22 (Day4): 接入 HuggingFace 情感分析与关键词抽取，更新相关 ENV
• 2025-08-21 (Day3+): 增加 metrics/cache/bench，补充结构化日志与延迟预算
• 2025-09-04 (Day9): signals 扩展 topic 字段（话题卡最小链路）
• 2025-09-05 (Day9.2): signals 新增字段 source_level 与 features_snapshot，完善 goplus_risk 枚举
• 2025-09-06 (Day10): 接入 BigQuery Provider 与健康检查（不涉及数据库迁移）

Revision: 010（down_revision='009'）
升级命令: alembic upgrade head
容器环境示例: docker compose -f infra/docker-compose.yml exec -T api alembic upgrade head
回滚建议: 业务侧可通过 REFINE_BACKEND=rules 立即降级；数据库列为增量，通常不需要回滚。如需清理：alembic downgrade 007。

⸻

raw_posts

说明
• Day1 初始建表（id/source/author/text/ts/urls）。
• Day2 增加 token_ca/symbol。
• Day4 增加 sentiment_label/sentiment_score/keywords/is_candidate。
• Day8 X KOL 推文采集：数据入库 raw_posts，额外信息（tweet_id 等）存储于 metadata JSON，不涉及 schema 迁移

    •	id BIGSERIAL PRIMARY KEY (Day1)
    •	source TEXT NOT NULL (Day1)
    •	author TEXT (Day1)
    •	text TEXT NOT NULL (Day1)
    •	ts TIMESTAMPTZ NOT NULL (Day1)
    •	urls JSONB DEFAULT '[]'::jsonb (Day1)
    •	metadata JSONB DEFAULT '{}'::jsonb (Day1，Day8 起用于存 tweet_id 等扩展信息)
    •	token_ca TEXT (Day2)
    •	symbol TEXT (Day2)
    •	is_candidate BOOLEAN DEFAULT FALSE (Day4)
    •	sentiment_label TEXT (Day4)
    •	sentiment_score DOUBLE PRECISION (Day4)
    •	keywords TEXT[] (Day4)

Indexes
• CREATE INDEX ON raw_posts (ts); (Day1)

⸻

events

说明
• Day1 建表（含 type/summary/evidence/impacted*assets/heat*_ 等，以下标注为 legacy）
• Day2 增加 score
• Day5 扩展事件聚合与验证：新增 symbol/token*ca/topic_hash/time_bucket_start/evidence_count/candidate_score/keywords_norm/version/last_sentiment/last_sentiment_score + 2 索引
• Day6 接入 Mini-LLM Refiner：新增 refined*_ 与 refine\_\* 列，记录精炼输出、延迟与状态
• 采用幂等迁移，旧字段保留，读路径不依赖新列

字段
• event_key TEXT PRIMARY KEY (Day1)
• type TEXT (legacy, Day1)
• summary TEXT (legacy, Day1)
• evidence JSONB DEFAULT '[]'::jsonb (legacy, Day1)
• impacted_assets TEXT[] (legacy, Day1)
• start_ts TIMESTAMPTZ NOT NULL (Day1)
• last_ts TIMESTAMPTZ NOT NULL (Day1)
• heat_10m INTEGER DEFAULT 0 (legacy, Day1)
• heat_30m INTEGER DEFAULT 0 (legacy, Day1)
• score DOUBLE PRECISION NOT NULL DEFAULT 0 (Day2)

Day5（事件聚合扩展）
• symbol TEXT (Day5)
• token_ca TEXT (Day5)
• topic_hash TEXT (Day5, currently nullable, 待回填后加约束)
• time_bucket_start TIMESTAMPTZ (Day5, currently nullable, 待回填后加约束)
• evidence_count INTEGER NOT NULL DEFAULT 0 (Day5)
• candidate_score DOUBLE PRECISION NOT NULL DEFAULT 0 (Day5)
• keywords_norm JSONB (Day5)
• version TEXT NOT NULL DEFAULT 'v1' (Day5)
• last_sentiment TEXT (Day5)
• last_sentiment_score DOUBLE PRECISION (Day5)

Day6（Mini‑LLM Refiner 输出与执行元数据）
• refined_type TEXT (Day6)
• refined_summary TEXT (Day6)
• refined_impacted_assets TEXT[] DEFAULT '{}' (Day6)
• refined_reasons TEXT[] DEFAULT '{}' (Day6)
• refined_confidence DOUBLE PRECISION (Day6)
• refine_backend TEXT (Day6) — 取值示例：llm | rules
• refine_latency_ms INTEGER (Day6)
• refine_ok BOOLEAN (Day6) — 是否成功产出合规 JSON
• refine_error TEXT (Day6) — 异常或拒绝原因说明
• refine_ts TIMESTAMPTZ DEFAULT now() (Day6)

说明：
• refined*\* 存储模型/规则的结构化输出 {type, summary, impacted_assets[], reasons[], confidence} 的各字段拆列，便于下游查询与索引。
• refine*\* 存储执行侧元数据（后端、延迟、是否成功、错误消息、执行时间）。
• 读路径保持兼容，继续基于旧字段/新字段的组合策略演进；上线期间允许两套并存。

索引
• events_pkey PRIMARY KEY (event_key) (Day1)
• idx_events_symbol_bucket (symbol, time_bucket_start) [Day5]
• idx_events_last_ts (last_ts DESC) [Day5]
• idx_events_refine_ts (refine_ts DESC) [Day6]
• idx_events_refine_ok (refine_ok) [Day6]

约束与兼容性
• Day6 新增列均为可空（或有默认值），保持幂等迁移与回滚友好
• 后续可按数据回填状态逐步收紧约束（例如对 topic_hash、time_bucket_start）

⸻

signals

说明
• Day1 初始建表（后续阶段消费 events 结果）
• Day11: 新增 heat_slope 字段（热度斜率）
• Day13（计划）确认 goplus/dex/heat 字段均需写入，作为规则引擎输入/输出的落地表
• Day7 扩展 goplus 字段，新增枚举类型及多字段支持
• Day9 扩展 topic 字段，用于 Meme 话题卡最小链路
• Day9.2 新增 source_level 与 features_snapshot 字段，完善 goplus_risk 枚举

    • id BIGSERIAL PRIMARY KEY (Day1)
    • event_key TEXT REFERENCES events(event_key) (Day1)
    • market_type TEXT (Day1)
    • advice_tag TEXT (Day1)
    • confidence DOUBLE PRECISION (Day1, 修正：原为 INTEGER，改为浮点数以支持小数置信度)
    • goplus_risk TEXT CHECK (goplus_risk IN ('red','yellow','green','unknown','gray')) (Day7, Day9.2 更新)
    • buy_tax DOUBLE PRECISION (Day7)
    • sell_tax DOUBLE PRECISION (Day7)
    • lp_lock_days INTEGER (Day7)
    • honeypot BOOLEAN (Day7)
    • dex_liquidity DOUBLE PRECISION (Day1)
    • dex_volume_1h DOUBLE PRECISION (Day1)
    • heat_slope DOUBLE PRECISION (Day11)
    • ts TIMESTAMPTZ DEFAULT now() (Day1)
    • topic_id TEXT (Day9)
    • topic_entities TEXT[] (Day9)
    • topic_keywords TEXT[] (Day9)
    • topic_slope_10m DOUBLE PRECISION (Day9)
    • topic_slope_30m DOUBLE PRECISION (Day9)
    • topic_mention_count INTEGER (Day9)
    • topic_confidence DOUBLE PRECISION (Day9)
    • topic_sources TEXT[] (Day9)
    • topic_evidence_links JSONB DEFAULT '[]'::jsonb (Day9)
    • topic_merge_mode TEXT (Day9)
    • calc_version TEXT DEFAULT 'topic_v1' (Day9)
    • degrade BOOLEAN DEFAULT FALSE (Day9)

Day9.2 新增字段说明：
• source_level TEXT ENUM('rumor','confirmed')，可选，用于标识信号来源的可信度等级
• features_snapshot JSONB，可选，结构示例：
{
active_addrs: INTEGER (optional),
top10_share: DOUBLE PRECISION (optional),
growth_30m: DOUBLE PRECISION (optional),
stale: BOOLEAN (optional)
}
用于存储信号相关的特征快照，便于后续分析与回溯

Indexes
• CREATE INDEX ON signals (event_key, ts DESC); (Day1)

⸻

goplus_cache

说明
• Day7 新建表，用于缓存 GoPlus API 响应

字段
• id BIGSERIAL PRIMARY KEY (Day7)
• endpoint TEXT NOT NULL (Day7)
• chain_id TEXT NOT NULL (Day7)
• key TEXT NOT NULL (Day7)
• payload_hash TEXT NOT NULL (Day7)
• resp_json JSONB NOT NULL (Day7)
• status TEXT NOT NULL (Day7)
• fetched_at TIMESTAMPTZ NOT NULL (Day7)
• expires_at TIMESTAMPTZ NOT NULL (Day7)
• created_at TIMESTAMPTZ NOT NULL DEFAULT now() (Day7)
• updated_at TIMESTAMPTZ NOT NULL DEFAULT now() (Day7)

Indexes
• idx_goplus_cache_lookup (endpoint, chain_id, key) (Day7)
• idx_goplus_cache_expires (expires_at) (Day7)

⸻

Alembic Migration History

Revision Date Content
010 2025-09-06 onchain_features 表与 signals 新增列 (Day12)
009 2025-09-07 signals 新增字段 heat_slope (Day11)
009 2025-09-07 signals 新增字段 heat_slope (Day11)
008 2025-09-05 signals 新增字段 source_level 与 features_snapshot，更新 goplus_risk 枚举（Day9.2）
007 2025-09-04 signals 扩展 topic 字段 (Meme 话题卡最小链路)
006 2025-08-26 signals 扩展 goplus\__ 字段 (risk/tax/lp_lock_days/honeypot)
005 2025-08-25 Add goplus_cache table (迁移)
004 2025-08-24 events 新增 refined_\* 与 refine\*\* 列；新增索引 idx_events_refine_ts、idx_events_refine_ok
003 2025-08-23 events 幂等迁移：新增 10 列 + 2 索引，保留旧列
002 2025-08-22 events 增加 score 列
001 2025-08-21 初始 schema：创建 raw_posts、events、signals

注：截至 Day8 无数据库迁移，当时最新 Revision 为 006；当前（Day9.2 完成后，Day10 无迁移）最新 Revision 为 008。

⸻

Legacy 字段标注
• events.type, events.summary, events.evidence, events.impacted_assets, events.heat_10m, events.heat_30m
标记为 legacy，在 Day6 引入新的精炼结果列后，短期保留用于兼容；后续视迁移与读路径稳定性再定去留。

⸻

与实际数据库一致性校验（建议步骤）

以下命令均以 docker compose 环境为例，数据库用户/DB 名按 infra/docker-compose.yml 默认：app / app。

1. 查看表结构

docker compose -f infra/docker-compose.yml exec -T db \
 psql -U app -d app -c '\d+ events'

确认包含以下列（节选）：
• refined_type, refined_summary, refined_impacted_assets, refined_reasons, refined_confidence
• refine_backend, refine_latency_ms, refine_ok, refine_error, refine_ts

2. 校验列是否存在（信息架构查询）

docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c \
"SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name='events' AND (column_name LIKE 'refine%' OR column_name LIKE 'refined%');"

3. 校验索引是否存在

docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c \
"SELECT indexname, indexdef FROM pg_indexes WHERE tablename='events' AND indexname LIKE 'idx_events_refine%';"

预期存在：
• idx_events_refine_ts on (refine_ts DESC)
• idx_events_refine_ok on (refine_ok)

4. 升级与回滚

# 升级到最新（含 009）

alembic upgrade head

# 回滚一版（回到 007）

alembic downgrade 007

⸻

变更影响与兼容性（Day6）
• 读路径：不依赖 Day6 新增列，现网稳定性不受影响。
• 写路径：在触发条件满足时调用 Mini‑LLM Refiner，成功产出即写入 refined*\*；失败/拒绝只写入 refine*\* 的错误与状态。
• 索引影响：idx_events_refine_ts 有利于最近精炼结果检索；idx_events_refine_ok 支持快速筛选成功/失败样本，用于验收与回归分析。
• 回滚策略：遇到上游 LLM 限流或账密问题，可将 REFINE_BACKEND=rules，业务无感切换；数据库层不需回滚。

⸻

后续计划占位（非本次变更的一部分）
• 逐步弱化 events._legacy_ 的读依赖，统一由 refined\_\* 提供规范化输出
• 按下游消费侧需求决定是否增加复合索引（如 (symbol, refine_ts DESC)）

⸻

Token_info 相关说明（Schema 参考）

ca_norm 字段说明（Day9.2 更新）：
• 对于 EVM 链，ca_norm 必须是有效地址，格式为正则表达式 ^0x[a-fA-F0-9]{40}$。
• 对于非 EVM 链，ca_norm 可能为 null，且 valid 字段应为 false，表示地址无效。
• 该约束有助于区分不同链类型的地址有效性，便于统一处理与校验。

⸻

一致性提示（Day10）
• 当前 Alembic 版本：010（head）
• Day10 未涉及数据库迁移；仅服务侧接入 BigQuery
• Day9.2 已合并（008），已在库中生效

## Day12: On-chain Features Light Table

### Table: onchain_features

```sql
CREATE TABLE onchain_features (
  id BIGSERIAL PRIMARY KEY,
  chain TEXT NOT NULL,
  address TEXT NOT NULL,
  as_of_ts TIMESTAMPTZ NOT NULL,
  window_minutes INT NOT NULL CHECK (window_minutes IN (30, 60, 180)),
  addr_active INT,
  tx_count INT,
  growth_ratio NUMERIC,
  top10_share NUMERIC,
  self_loop_ratio NUMERIC,
  calc_version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (chain, address, as_of_ts, window_minutes)
);

CREATE INDEX idx_onf_lookup ON onchain_features (chain, address, window_minutes, as_of_ts);
```

### Columns added to signals table

```sql
ALTER TABLE signals ADD COLUMN onchain_asof_ts TIMESTAMPTZ;
ALTER TABLE signals ADD COLUMN onchain_confidence INT;
```

- growth_ratio: Computed as (current.addr_active - previous.addr_active) / previous.addr_active for same (chain,address,window_minutes)
- calc_version: Ensures idempotent updates (only update if new version &gt;= existing)
