Database Schema Specification

TL;DR
• Current Alembic Version: 013
• Recent Changes:
• 2025-09-26 (P1-2): Topic推送链路完成，events.topic_hash/topic_entities和signals.topic_*字段已在生产使用
• 2025-08-26 (Day7): signals 扩展 goplus 字段（goplus_cache 表见 Rev 005）
• 2025-08-31 (Day8): 新增 configs/x_kol.yaml 与验收脚本 verify_x_kol.py；raw_posts 使用 metadata JSON 扩展存储 tweet_id 等字段，无数据库迁移
• 2025-08-25 (Day6): events 表新增精炼结果与执行元数据列（refined*\* 与 refine*\*），新增 2 个索引；读路径不依赖新列，向后兼容
• 2025-08-23 (Day5): events 表幂等迁移，新增 10 列 + 2 索引（保留旧列）
• 2025-08-22 (Day4): 接入 HuggingFace 情感分析与关键词抽取，更新相关 ENV
• 2025-08-21 (Day3+): 增加 metrics/cache/bench，补充结构化日志与延迟预算
• 2025-09-06 (Day12/Rev 010): 创建 onchain_features（轻量表：as_of_ts/window_minutes/...）；为 signals 增加 onchain_asof_ts、onchain_confidence
• 2025-09-07 (Rev 011): 调整 signals.onchain_confidence 为 NUMERIC(4,3)
• 2025-09-08 (Rev 012): signals 新增 state（candidate|verified|downgraded）与索引 idx_signals_state_onlystate
• 2025-09-05 (Day9.2): signals 新增字段 source_level 与 features_snapshot，完善 goplus_risk 枚举
• 2025-09-06 (Day10): 接入 BigQuery Provider 与健康检查（不涉及数据库迁移）
• 2025-09-13 (Day20): 加入 outbox_push 相关

Revision: 012（down*revision='011'）
升级命令: alembic upgrade head
容器环境示例: docker compose -f infra/docker-compose.yml exec -T api alembic upgrade head
回滚建议: 业务侧可通过开关降级（ONCHAIN_RULES=off、EXPERT_VIEW=off）；数据库列均为增量且幂等。若需回滚 schema：可退回 011（移除 state），或退回 010（仍保留 onchain_features 与 onchain*\* 列）；更早版本请按迁移链逐步降级。

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
• Day5 扩展事件聚合与验证：新增 symbol/token_ca/topic_hash/time_bucket_start/evidence_count/candidate_score/keywords_norm/version/last_sentiment/last_sentiment_score + 2 索引
• P1-2 (2025-09-26)：topic_hash 和 topic_entities 已在生产使用，存储话题检测结果
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
    • type VARCHAR(20) CHECK (type IN ('topic','primary','secondary','market_risk')) (Day28/P0-3/P1-1)
      注: P0-3 实现卡片路由表驱动化，P1-1 新增 market_risk 类型通过规则引擎判定
    • market_type TEXT (Day1)
    • advice_tag TEXT (Day1)
    • confidence INTEGER (Day1) — 当前库中为 INTEGER；链上评估置信度请使用 onchain_confidence
    • goplus_risk TEXT CHECK (goplus_risk IN ('red','yellow','green','unknown','gray')) (Day7, Day9.2 更新)
    • buy_tax DOUBLE PRECISION (Day7)
    • sell_tax DOUBLE PRECISION (Day7)
    • lp_lock_days INTEGER (Day7)
    • honeypot BOOLEAN (Day7)
    • dex_liquidity DOUBLE PRECISION (Day1)
    • dex_volume_1h DOUBLE PRECISION (Day1)
    • heat_slope DOUBLE PRECISION (Day11)
    • ts TIMESTAMPTZ DEFAULT now() (Day1)
    • topic_id TEXT (Day9, P1-2：用于存储话题标识)
    • topic_entities TEXT[] (Day9, P1-2：从events表同步)
    • topic_keywords TEXT[] (Day9)
    • topic_slope_10m DOUBLE PRECISION (Day9)
    • topic_slope_30m DOUBLE PRECISION (Day9)
    • topic_mention_count INTEGER (Day9)
    • topic_confidence DOUBLE PRECISION (Day9, P1-2：话题置信度评分)
    • state TEXT NOT NULL DEFAULT 'candidate' CHECK (state IN ('candidate','verified','downgraded')) (Day12)
    • onchain_asof_ts TIMESTAMPTZ (Day12) — 链上特征评估的 as_of 时间
    • onchain_confidence NUMERIC(4,3) (Day12) — 规则评估置信度，三位小数
      • API 映射：Card C/D 返回字段 `onchain.asof_ts`（UTC, 'Z' 结尾）来源于库列 `onchain_features.as_of_ts`；`window_min` 来源于 `window_minutes`（仅显示 30/60/180）。
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
• idx_signals_state_onlystate btree (state) (Day12)

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
014 2025-09-24 add_signals_type（新增 type 列、CHECK 约束、索引与数据回填）
     P0-3: 实现卡片路由表驱动化（CARD_ROUTES/CARD_TEMPLATES）
     P1-1: 新增 market_risk 类型通过规则引擎判定
012 2025-09-08 add_signals_state（新增 state 列与相关索引）
011 2025-09-07 fix_onchain_confidence_type（signals.onchain_confidence 调整为 NUMERIC(4,3)）
010 2025-09-06 day12_onchain_features（创建 onchain_features 表；并为 signals 增加 onchain_asof_ts 与 onchain_confidence）
009 2025-09-07 signals 新增字段 heat_slope (Day11)
008 2025-08-05 signals 新增字段 source_level 与 features_snapshot，更新 goplus_risk 枚举（Day9.2）
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

5. Day12/012 校验

docker compose -f infra/docker-compose.yml exec -T db \
 psql -U app -d app -c '\d+ onchain_features'

# 预期列：as_of_ts, window_minutes, growth_ratio, top10_share, self_loop_ratio

docker compose -f infra/docker-compose.yml exec -T db \
 psql -U app -d app -c '\d+ signals'

# 预期列：state（且 CHECK 范围正确）、onchain_asof_ts、onchain_confidence NUMERIC(4,3)

# 预期索引：idx_signals_state_onlystate

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
• 当前 Alembic 版本：012（head）
• Day10 未涉及数据库迁移；仅服务侧接入 BigQuery
• Day9.2 已合并（008），已在库中生效

一致性提示（Day12/012）
• 采用 PG 轻量表 onchain_features；API 显示字段与库列名存在映射（asof_ts ⇄ as_of_ts，window_min ⇄ window_minutes）。
• Card C 默认读 PG；Card D 支持 PG 默认源，BQ 可通过 `EXPERT_SOURCE=bq` 启用，失败时降级到 PG/缓存。

## Day12/012: On-chain Features Light（定稿）

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
ALTER TABLE signals ADD COLUMN onchain_confidence NUMERIC(4,3);
```

### API 字段映射与精度

- 数据库列名：`as_of_ts`, `window_minutes`; API 返回：`asof_ts`, `window_min`（仅展示，不改库名）。
- 数值字段统一三位小数（ROUND_HALF_UP）；时间统一 UTC ISO8601 且以 'Z' 结尾。
- 仅 60 分钟窗口参与 S0→S2 判定；专家视图可提供 30/60/180 聚合。

- growth_ratio: Computed as (current.addr_active - previous.addr_active) / previous.addr_active for same (chain,address,window_minutes)
- calc_version: Ensures idempotent updates (only update if new version &gt;= existing)
- 注：signals.confidence 仍为 INTEGER；链上评估置信度写入 onchain_confidence（NUMERIC(4,3)）。

---

## 内部卡片结构 (Internal Card Structure)

**版本**: cards@19.0  
**更新日期**: 2025-09-12 (Day19)  
**Schema 文件**: `schemas/cards.schema.json`  
**共享定义**: `schemas/common.schema.json` (diagnosticFlags, ohlcFrame 通过$ref 统一定义)

### 字段表

| 字段路径          | 类型    | 必填 | 说明           | 约束                                           |
| ----------------- | ------- | ---- | -------------- | ---------------------------------------------- |
| **顶层**          |         |      |                |                                                |
| card_type         | string  | ✓    | 卡片类型       | enum: primary, secondary, topic, market_risk   |
| event_key         | string  | ✓    | 事件键         | pattern: ^[A-Z0-9:_\-\.]{8,128}$               |
| data              | object  | ✓    | 数据载荷       | required: goplus, dex                          |
| summary           | string  | ✓    | 摘要文本       | minLength: 4, maxLength: 280                   |
| risk_note         | string  | ✓    | 风险提示       | minLength: 4, maxLength: 160                   |
| rendered          | object  |      | 渲染结果       | 含 tg, ui                                      |
| evidence          | array   |      | 证据列表       | 元素含 type, desc, url                         |
| meta              | object  | ✓    | 元数据         | required: version, data_as_of, summary_backend |
| **data.goplus**   |         |      |                |                                                |
| risk              | string  | ✓    | 风险等级       | enum: green, yellow, red, gray                 |
| risk_source       | string  | ✓    | 来源标识       | 如 GoPlus@vX.Y                                 |
| tax_buy           | number  |      | 买入税率       | 0 ≤ x ≤ 1                                      |
| tax_sell          | number  |      | 卖出税率       | 0 ≤ x ≤ 1                                      |
| lp_locked         | boolean |      | 流动性锁定     |                                                |
| honeypot          | boolean |      | 蜜罐标记       |                                                |
| diagnostic        | object  |      | 诊断信息       | 含 source, cache, stale, degrade               |
| **data.dex**      |         |      |                |                                                |
| price_usd         | number  |      | USD 价格       | minimum: 0                                     |
| liquidity_usd     | number  |      | USD 流动性     | minimum: 0                                     |
| fdv               | number  |      | 完全稀释估值   | minimum: 0                                     |
| ohlc              | object  |      | OHLC 数据      | 含 m5, m15, h1                                 |
| diagnostic        | object  |      | 诊断信息       | 同 goplus                                      |
| **data.onchain**  |         |      |                |                                                |
| features_snapshot | object  |      | 特征快照       | 宽松对象                                       |
| source_level      | string  |      | 来源等级       |                                                |
| **data.rules**    |         |      |                |                                                |
| level             | string  | ✓    | 规则等级       | enum: none, watch, caution, risk               |
| score             | number  |      | 评分           | 0 ≤ x ≤ 100                                    |
| reasons           | array   |      | 简要原因       | max 3 项, 每项 ≤120 字符                       |
| all_reasons       | array   |      | 详细原因       | max 20 项, 每项 ≤160 字符                      |
| **meta**          |         |      |                |                                                |
| version           | string  | ✓    | 版本号         | const: cards@19.0                              |
| data_as_of        | string  | ✓    | 数据时间       | format: date-time                              |
| summary_backend   | string  | ✓    | 摘要后端       | enum: llm, template                            |
| used_refiner      | string  |      | 使用的 refiner |                                                |
| degrade           | boolean |      | 降级标记       |                                                |

### 示例 JSON

```json
{
  "card_type": "primary",
  "event_key": "ETH:TOKEN:0X1234567890ABCDEF",
  "data": {
    "goplus": {
      "risk": "yellow",
      "risk_source": "GoPlus@v1.2",
      "tax_buy": 0.05,
      "tax_sell": 0.1,
      "lp_locked": true,
      "honeypot": false,
      "diagnostic": {
        "source": "api",
        "cache": false,
        "stale": false,
        "degrade": false
      }
    },
    "dex": {
      "price_usd": 0.0234,
      "liquidity_usd": 125000.5,
      "fdv": 2340000,
      "ohlc": {
        "m5": {
          "open": 0.023,
          "high": 0.0236,
          "low": 0.0228,
          "close": 0.0234,
          "ts": "2025-09-12T10:05:00Z"
        },
        "m15": {
          "open": 0.0225,
          "high": 0.0238,
          "low": 0.0224,
          "close": 0.0234,
          "ts": "2025-09-12T10:15:00Z"
        }
      }
    },
    "rules": {
      "level": "watch",
      "score": 65,
      "reasons": ["High sell tax detected", "Moderate liquidity concerns"]
    }
  },
  "summary": "Token showing moderate risk with 10% sell tax and $125k liquidity on DEX",
  "risk_note": "Elevated sell tax may impact exit strategy",
  "meta": {
    "version": "cards@19.0",
    "data_as_of": "2025-09-12T10:15:00Z",
    "summary_backend": "llm"
  }
}
```

---

## 来源与合流规则 (Source Merging Rules)

**版本**: Day19  
**更新日期**: 2025-09-12

### 数据来源映射

卡片数据从以下来源合流：

| 目标字段          | 来源 Provider                     | 降级策略                    |
| ----------------- | --------------------------------- | --------------------------- |
| data.goplus       | goplus_provider.get_latest()      | 省略字段，meta.degrade=true |
| data.dex          | dex_provider.get_latest()         | 省略字段，meta.degrade=true |
| data.onchain      | onchain_provider.get_snapshot()   | 整体省略（可选字段）        |
| data.rules        | rules.evaluator.get_rules()       | 默认 level="none"           |
| evidence          | evidence.store.get_by_event()     | 整体省略（可选字段）        |
| summary/risk_note | cards.summarizer.summarize_card() | 模板降级                    |

### 时间戳策略

- **data_as_of**: 取所有参与合流的数据源中最旧的时间戳（as_of/ts/updated_at）
- 若无任何时间戳，使用当前 UTC 时间并标记 meta.degrade=true
- 时间格式统一为 ISO8601，UTC 时区，以'Z'结尾

### 降级规则

当核心数据源缺失时：

1. 设置 meta.degrade = true
2. 在 rules.reasons 数组追加缺失原因（最多 3 条）
3. 继续构建卡片，不抛异常（除非 goplus 和 dex 都缺失）

### 卡片类型判定

- **primary**: 有 onchain 数据且 rules.level 为 caution/risk
- **secondary**: rules.level 为 watch
- **topic**: topic 类型信号
- **market_risk**: 由规则引擎 MR01-MR06 触发（P1-1）

### 校验要求

所有生成的卡片必须通过 schemas/cards.schema.json 校验，失败则抛出 ValueError

---

## 缓存键约定 (Cache Key Convention)

**版本**: Day20+21  
**更新日期**: 2025-09-13

| Key Pattern                         | 作用              | TTL          | 备注                                |
| ----------------------------------- | ----------------- | ------------ | ----------------------------------- |
| rate:tg:{bucket}                    | Telegram 限流控制 | 2s           | bucket 可为`global`或`channel:{id}` |
| cards:sent:{event_key}:{yyyyMMddHH} | 卡片去重追踪      | 5400s (1.5h) | 按小时分桶避免 key 过期不一致       |

---

## Outbox 表结构与索引（Day20+21）

**版本**: Day20+21  
**更新日期**: 2025-09-13

### push_outbox 表

| 字段         | 类型         | 约束                   | 说明                         |
| ------------ | ------------ | ---------------------- | ---------------------------- |
| id           | BIGSERIAL    | PRIMARY KEY            | 主键                         |
| channel_id   | BIGINT       | NOT NULL               | Telegram 频道 ID             |
| thread_id    | BIGINT       | NULL                   | Telegram 线程 ID（可选）     |
| event_key    | VARCHAR(128) | NOT NULL               | 事件键                       |
| payload_json | JSONB        | NOT NULL               | 消息载荷                     |
| status       | VARCHAR(16)  | NOT NULL CHECK         | 状态：pending/retry/done/dlq |
| attempt      | INT          | NOT NULL DEFAULT 0     | 重试次数                     |
| next_try_at  | TIMESTAMPTZ  | NULL                   | 下次重试时间                 |
| last_error   | TEXT         | NULL                   | 最后错误信息                 |
| created_at   | TIMESTAMPTZ  | NOT NULL DEFAULT NOW() | 创建时间                     |
| updated_at   | TIMESTAMPTZ  | NOT NULL DEFAULT NOW() | 更新时间                     |

### 索引

| 索引名                            | 字段                  | 用途               |
| --------------------------------- | --------------------- | ------------------ |
| ix_push_outbox_status_next_try_at | (status, next_try_at) | 批量拉取待处理消息 |
| ix_push_outbox_event_key          | event_key             | 按事件键查询       |
| ix_push_outbox_channel_id         | channel_id            | 按频道查询         |

### 状态说明

- **pending**: 新入队，等待首次发送
- **retry**: 发送失败，等待重试
- **done**: 发送成功
- **dlq**: 死信队列，超过最大重试次数

### push_outbox_dlq 表（归档表）

| 字段      | 类型        | 约束                   | 说明                |
| --------- | ----------- | ---------------------- | ------------------- |
| id        | BIGSERIAL   | PRIMARY KEY            | 主键                |
| ref_id    | BIGINT      | NOT NULL               | 引用 push_outbox.id |
| snapshot  | JSONB       | NOT NULL               | 完整行快照          |
| failed_at | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | 失败时间            |

### 典型查询

```sql
-- 拉取待处理消息
SELECT * FROM push_outbox
WHERE status IN ('pending', 'retry')
  AND (next_try_at IS NULL OR next_try_at <= NOW())
ORDER BY next_try_at NULLS FIRST, created_at ASC
LIMIT 50;

-- 查询某事件的推送状态
SELECT * FROM push_outbox
WHERE event_key = 'EVENT_KEY'
ORDER BY created_at DESC;

-- 统计各状态消息数
SELECT status, COUNT(*)
FROM push_outbox
GROUP BY status;
```
