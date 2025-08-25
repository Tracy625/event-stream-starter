# MVP20 计划

## Day0 — 基础架构

- 初始化 monorepo 目录结构
- 设置 API / Worker / UI / Infra 四大模块
- 接好 Postgres / Redis
- 准备 Alembic 迁移脚手架
- 验收：`docker compose up` 一次跑通，API `/healthz` 返回 200

---

## Day1 — 基础功能

- 新建 `raw_posts`、`events`、`signals` 三张表
- API 健康检查
- Docker Compose 服务可跑
- Alembic 迁移到版本 `001`
- 验收：表结构和 API 均可用

---

## Day2 — Pipeline 构建与验证（替代原“X 采集器”）

- 实现 `filter/refine/dedup/db` 四步处理链
- Redis 去重 & 内存去重双模式
- 扩展 `raw_posts` 表字段：`is_candidate`、`sentiment`、`keywords`
- Alembic 迁移到版本 `002`
- 验收：`make demo` 能跑 pipeline 并成功写入 raw_posts；Redis/内存去重都可用；API `/healthz` 返回 200

⚠ 说明：原计划的“X API 采集器”任务推迟到 Day8 执行

---

## Day3 — Demo ingest & Logging（替代原“规则与关键词粗筛”）

- 新建 `scripts/demo_ingest.py`，支持 JSONL 输入，跑完整 pipeline
- 输出结构化 JSON 日志（含 filter/refine/dedup/db 各 stage）
- Makefile 新增 `demo` 目标
- 更新 `WORKFLOW.md`，记录 demo 流程
- 验收：`python scripts/demo_ingest.py` 能跑通 demo；日志输出包含各 stage 耗时与结果；Makefile `demo` 可用

⚠ 说明：原计划的“规则与关键词粗筛”逻辑已部分在 Day2 的 filter 中实现，剩余语言检测/黑名单将在 Day8–Day9 补齐

---

## Day3+ — 指标与性能

- 新建 `/api/metrics.py` 提供 `timeit` 和 `log_json`
- 新建 `/api/cache.py` 提供 `@memoize_ttl` 缓存
- demo 脚本增加耗时指标和 latency budget 支持
- 新建 `scripts/bench_sentiment.py` 基准测试
- 新建 `scripts/golden.jsonl` 作为样本集
- Makefile 新增 `bench-sentiment`
- 验收：能跑 bench，打印延迟/准确率

---

## Day4 — HuggingFace 增强

- Sentiment router：rules / hf 双后端
- HF 模型 id2label → {pos, neu, neg}，Score = P(pos)-P(neg)
- Keyphrases：HF KBIR 模型，fallback rules
- 新建 `/api/hf_sentiment.py`、`/api/keyphrases.py`
- 新建 `scripts/smoke_sentiment.py`
- `.env.example` 新增相关配置
- 验收：
  - HF+ 返回正
  - HF- 返回负
  - 坏模型降级 rules

---

## Day5 — 事件聚合

- 新建 Alembic 迁移 `003`，幂等扩展 `events` 表字段
- 新建 `/api/events.py`，实现 `make_event_key` 与 `upsert_event`
- demo pipeline 接入事件聚合，去重合并
- 新建 `scripts/verify_events.py`
- `.env.example` 新增 EVENT\_\* 配置
- 验收：
  - `make demo` 事件能去重合并
  - `verify_events.py` 输出统计 JSON

---

## Day6 — 精析器（小模型）

- 触发条件：候选 ≥ 阈值 或 evidence ≥ 2
- mini LLM 输出 JSON：{type, summary, impacted_assets[], reasons[], confidence}
- JSON Schema 校验，丢弃不合格结果
- 验收：10 条样本 ≥8 条返回合法 JSON，p95 < 800ms

---

## Day7 — GoPlus 体检（新增，安全底座）

- 目标：Token/Address/Approval 三端点通，带缓存/退避/熔断
- 产物：`clients/goplus.py`、`providers/goplus_provider.py`、`routes/security.py`、alembic 新增 goplus_cache
- 复用：Day3+ timeit/cache
- 验收：
  - `curl /security/token?chain_id=1&address=0xa0b8...` 返回 honeypot/税率等；冷 P95 ≤800ms，热 P95 ≤200ms
- 降级/回滚：ENV `SECURITY_BACKEND=rules` 返回本地规则；缓存命中即返回、打 `degrade:true`

---

## Day8 — X KOL 采集（新增，接 Day2 pipeline）

- 目标：5–10 个 KOL，2 分钟轮询，入库去重，规范化文本/URL/合约，并保证能被 pipeline 消费
- 产物：`ingestor_x/kol_timeline.py`，ENV `X_BEARER,X_KOL_IDS,X_POLL_SEC`；更新 pipeline，保证 raw_posts 字段齐全（text, author, ts, urls[], token_ca?, symbol?）
- 复用：Day2 的 filter/refine/dedup/db 链路
- 验收：
  - `make ingest-x-once` 拉 50 条，落库 ≥35，去重命中>10%，失败可回放
  - 落库结果中至少 1 条包含 `token_ca` 或 `symbol`
- 降级：API 限额 → 延长 `POLL_SEC`，只取最新 20 条；缓存最近一次拉取结果

---

## Day9 — DEX 快照（新增，双源容错）

- 目标：DexScreener 优先、GeckoTerminal 兜底；返回价格/流动性/FDV/OHLC，并能映射到 token/CA
- 产物：`providers/dex_provider.py`，ENV `DEX_CACHE_TTL_S=60`；事件层接口：支持通过 `token_ca` 查询对应行情
- 验收：
  - `curl /dex/snapshot?chain=eth&contract=0xa0b8...` 返回字段完整；若降级，`source:"gecko", reason:"timeout"`
  - 从 snapshot 结果中能取到价格与流动性，并写入缓存
- 降级：两个源都挂 → 返回上次成功值，标记 `stale:true`

---

## Day10 — 事件聚合跨源升级（优化，不重做）

- 目标：把 Day5 的聚合升级为跨源合并，固定 event_key 不变性；写 `events.evidence[]`
- 产物：`/api/events.py` 增强；ENV `EVENT_KEY_SALT`；events 表 JSONB 字段
- 复用：Day5 make_event_key/upsert_event
- 验收：
  - `python scripts/verify_events.py --sample replay.jsonl` 输出每事件 refs≥2、event_key 重放一致
  - 至少 1 个事件同时包含 **X 采集内容** 与 **DEX/GoPlus 引用**，证据链合并正确
- 回滚：ENV `EVENT_MERGE_STRICT=false` 降为单源合并

---

## Day11 — 热度快照与斜率（新增）

- 目标：按 token/CA 计算 10m/30m/recent 计数、斜率、环比；写 signals
- 产物：`signals/heat.py`，ENV `THETA_RISE`
- 验收：`curl /signals/heat?token=USDT` 返回 cnt_10m,cnt_30m,trend:"up|down",slope
- 降级：原始不足 → 只出计数不出斜率

---

## Day12 — HF 批量与阈值校准（优化，不重做）

- 目标：把 Day4 的 HF 模型做成批量接口，加阈值校准与回灌报告
- 产物：`services/hf_client.py`（batch）、`scripts/hf_calibrate.py`
- 复用：Day4 hf_sentiment.py/keyphrases.py
- 验收：回灌 100 样本，输出 precision/recall/F1 与阈值建议；坏模型 → 降级 rules
- 降级：HF 端点超时 → 只用规则和 VADER，卡片加 `degrade: "HF_off"`

---

## Day13 — 规则引擎 + 极简建议器（新增）

- 目标：热度斜率 + DEX 变化 + GoPlus 风险 + HF 情绪，输出 observe/caution/opportunity 三档，理由最多三条
- 产物：`rules/eval_event.py`，`rules.yml` 可热加载，ENV `THETA_LIQ,THETA_VOL,THETA_SENT`
- 复用：Day6 精析器作为门后 LLM
- 验收：
  - `curl /rules/eval?event_key=...` 返回 level 与 reasons[3]，证据字段齐
  - signals 表在对应 event_key 下包含字段：`goplus_risk`, `buy_tax/sell_tax`, `lp_lock_days`, `dex_liquidity`, `dex_volume_1h`, `heat_slope`
- 降级：HF 关停或 DEX 缺失 → 理由里自动替换为“数据不足”

---

## Day14 — 卡片 Schema + LLM 摘要（复用 Day6，限定用途）

- 目标：定版 cards.schema.json；LLM 只产 summary、risk_note 两短字段
- 产物：`cards/build.py`，`/cards/preview` 路由
- 复用：Day6 JSON-schema 校验器
- 验收：`curl /cards/preview?event_key=...` 通过 schema 校验，字段包含 goplus._ 与 dex._
- 降级：LLM 超时 → 模板摘要（可读但无修辞）

---

## Day15 — Telegram 推送（新增）

- 目标：把卡片发到频道，绑定讨论组；1 小时内同 event_key 去重
- 产物：`notifier/telegram.py`，ENV `TG_BOT_TOKEN,TG_CHANNEL_ID,TG_RATE_LIMIT`
- 验收：`curl -XPOST /cards/send?event_key=...` 沙盒频道落 5 张卡，失败有 error_code
- 降级：TG 失败 → 落本地 outbox 重试队列；卡片保存在 `/tmp/cards/*.json`

---

## Day16 — 端到端延迟与退化（集中调优，复用 Day3+）

- 目标：E2E P95 ≤ 2 分钟；失败用缓存/上次成功结果；熔断+退避
- 产物：`make bench-pipeline`；指标 pipeline_latency_ms, external_error_rate, degrade_ratio
- 验收：跑 50 事件，P95 ≤ 120000ms，外呼失败率<5%，退化占比<10%

---

## Day17 — 回放与部署（新增）

- 目标：新环境 30 分钟内从零到“频道看到卡片”；回放历史误判集
- 产物：`docker compose up -d` 一键；`scripts/replay_e2e.sh` 打穿 golden.jsonl
- 复用：Day3 demo/bench；Day8–15 的所有路由
- 验收：新目录拉起后 30 分钟内 Telegram 见卡；回放 10 条里预警命中 ≥80%

---

## Day18 — 配置与治理（轻量优化，非重复）

- 目标：rules.yml 热加载；KOL 列表、黑白名单、阈值无需改代码；敏感变量审计
- 产物：`/config/hotreload`，`.env.example` 完整注释；`scripts/config_lint.py`
- 验收：改阈值 →1 分钟内生效；配置 lint 全绿；泄露检测脚本通过

---

## Day19 — 观测面与告警（轻量优化，非重复）

- 目标：最低限度观测：外呼成功率、延迟、退化比；TG 失败重试告警
- 产物：`/metrics` 暴露 Prom 格式；`alerts.yml`
- 验收：人为打断 DEX 源，看到退化上涨；TG 失败告警命中

---

## Day20 — 文档与交付打包（收尾，不重复）

- 目标：RUN_NOTES 汇总；5 分钟复现实操；接口契约与样例打包
- 产物：`RUN_NOTES.md` 终版；`cards.schema.json` 终版；`/docs/E2E.md`；release notes
- 验收：新人照着文档 5 分钟能跑出一张卡片；所有 curl/make 命令可用
