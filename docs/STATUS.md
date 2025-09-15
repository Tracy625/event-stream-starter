# ⚠ Baseline: MVP20 v1.0 (2025-08-26)

# STATUS 仅反映每日执行，计划调整请见 MVP20_PLAN.md

# STATUS — Daily Plan

## Done

- Project setup: BRIEF, STATUS, WORKFLOW, CLAUDE.md
- Day 1: Monorepo init, health endpoints, migrations, docker-compose

- Day 2: filter/refine/dedup/db pipeline (verified)

  - filter/refine/dedup/db 全部通过；Redis/内存双模式验收通过
  - Alembic 迁移到 002（score 列）；API /healthz 200，容器 healthy
  - ⚠ variance: 原计划是「X API 采集器（固定 KOL → raw_posts）」，
    实际完成的是「内部 pipeline 构建与验证」，采集任务已推迟到 Day8。

- Day 3: scripts/demo_ingest.py；JSONL 结构化日志；Makefile `demo`；WORKFLOW 文档更新

  - 新建 demo_ingest 脚本，支持 JSONL 输入，跑完整 pipeline
  - 输出结构化 JSON 日志（含 filter/refine/dedup/db 各 stage）
  - Makefile 新增 `demo` 目标，WORKFLOW 文档更新
  - ⚠ variance: 原计划是「规则与关键词粗筛（黑名单/语言检测/关键词/CA 提取）」，
    实际完成的是「demo ingest + logging」，粗筛逻辑部分在 Day2 filter 已覆盖，
    剩余语言检测/黑名单将在 Day8–Day9 补齐。

- Day 3+: metrics & cache & timing & benchmark (verified)

  - /api/metrics.py 提供 timeit/log_json，结构化 JSON 日志
  - /api/cache.py 提供 @memoize_ttl 缓存，线程安全
  - scripts/demo_ingest.py 增加耗时指标与 latency budget 支持
  - scripts/golden.jsonl + scripts/bench_sentiment.py 基准测试
  - Makefile 新增 bench-sentiment 目标
  - infra/.env.example 补充 SENTIMENT/HF/KEYPHRASE 与 LATENCY*BUDGET_MS*\* 变量
  - bench_sentiment 可运行，默认 rules-only；可配置 N 次采样

- Day 4: HuggingFace Sentiment & Keywords Enhancement (verified)

  - Sentiment router 拆分 (rules/hf)，调用期路由与降级路径完成
  - HF id2label → {"pos","neu","neg"}；Score = P(pos)-P(neg)，[-1,1] 截断
  - Keyphrases: KBIR + rules fallback，去重/小写/停用词处理
  - /scripts/smoke_sentiment.py 可运行，bench-sentiment 支持双后端
  - .env.example 更新 SENTIMENT_BACKEND / HF_MODEL / KEYPHRASE_BACKEND
  - 验收通过：HF+ 返回正，HF- 返回负，坏模型时降级为 rules

- Day 5: Event Aggregation & Verification (verified)

  - Alembic 003 migration 增加 events 字段（symbol, token_ca, topic_hash, time_bucket_start, candidate_score 等）
  - 实现 api/events.py: make_event_key(), upsert_event()
  - demo_ingest 接入事件聚合（无条件 upsert，重复累计 evidence）
  - 输出 stage="pipeline.event" 结构化日志，DB evidence_count 累加验证通过
  - scripts/verify_events.py 可运行（只读），输出 JSON 统计并支持空表/错误处理
  - 验收通过：candidate_score 在 0–1；last_ts 单调递增；脚本输出 JSON 正确

- Day 6: Refiner (mini LLM, structured JSON) (verified)

  - REFINE_BACKEND=llm 成功接通 gpt-5-mini，产出结构化 JSON
  - verify_refiner/verify_refiner-llm 脚本运行通过，10/10 样本均符合 JSON schema
  - 支持降级链路：gpt-5-mini → gpt-4o-mini → gpt-4o；均有结构化日志输出
  - stage 覆盖：refine.request / refine.success / refine.error / refine.warn
  - TODO: 当前延迟 ~7–12s/条，超过 800ms 预算；需在后续阶段优化截断与超时配置
  - 当前验收通过：≥8/10 JSON 合格；容器内 pipeline 稳定，不影响 D5 时序

- Day 7: GoPlus 体检（安全底座） (verified)

  - 三个已知垃圾盘样本（黑名单地址）均被判定为 `goplus_risk=red`
  - 验证脚本 `api/scripts/verify_goplus_security.py` 两轮运行均通过；二次命中缓存（Redis/Memory）返回 `cache:true`
  - 数据库新增表 `goplus_cache`，3 条样本记录已写入；索引结构完整 `(endpoint, chain_id, key)` + `expires_at`
  - `signals` 表新增字段（`goplus_risk, buy_tax, sell_tax, lp_lock_days, honeypot`）可写入更新
  - 路由 `/security/{token|address|approval}` 全部返回 200；响应字段含 `degrade/cache/stale/summary/notes/raw`
  - 支持降级链路：GoPlus API → DB → Redis → Memory → rules；rules 模式下判定风险为 red
  - 日志覆盖：`goplus.degrade / goplus.cache.{miss,hit,db_error,db_save_error} / goplus.risk / verify.pass`
  - 批量扫描作业 `api/jobs/goplus_scan.py` 已注册至 worker（默认关闭，节流配置可控）
  - TODO: 验证批量扫描对 `signals` 的真实写入；延迟控制与额度耗尽场景需进一步压测
  - 当前验收通过：3/3 样本风险判定正确，缓存与降级逻辑均生效，pipeline 稳定

- Day 7.1: 红黄绿规则与 signals 写入 (verified)

  - 新增 `rules/risk_rules.yml`，将默认规则正式化，可环境覆盖
  - `goplus_provider` 集成评分逻辑（honeypot、税率、LP 锁仓），生成 red/yellow/green
  - `api/jobs/goplus_scan.py` 扫描任务支持写库，标准化字段与评分写入 `signals`
  - 默认规则：HONEYPOT_RED=true；RISK_TAX_RED=10；RISK_LP_YELLOW_DAYS=30
  - 评分顺序：honeypot red > tax red > lp yellow > else green；未知进 unknown_flags[]
  - 三个黑名单样本判定为 red；二次查询缓存命中 ≤200ms；降级时返回 risk=unknown + degrade:true
  - 数据库更新：`signals` 表成功写入 goplus_risk 等字段，`events.evidence` 保留 GoPlus 原始摘要

- Day 8: X KOL 采集竖切 (verified)

  - 打通 X KOL 推文采集 → 标准化 → 去重 → 入库 → API 验收脚本
  - XClient 统一接口完成，支持 graphql/api/apify 三后端，可降级切换
  - 标准化推文字段：`source, author, text, ts, urls, token_ca, symbol, is_candidate`
  - 近窗去重：Redis key=`dedup:x:{tweet_id}` TTL 14d；软指纹去重 sha1
  - 入库 `raw_posts` 成功，metadata JSON 扩展位写入 `urls, token_ca, symbol, tweet_id`
  - 路由 `/ingest/x/kol/poll`、`/ingest/x/kol/stats` 返回 200 且 JSON 结构化
  - 配置支持 env 与 `configs/x_kol.yaml`（yaml 优先生效，15 handles 验收）
  - 验收脚本 `api/scripts/verify_x_kol.py` 运行，统计输出 JSON 正常
  - 当前验收通过：≥35 条写入，去重率 >10%，至少 1 条命中 CA/symbol，链路完整
  - 当前验收通过：rules 模式与写库均验证成功，pipeline 稳定

- Day 8.1: X KOL 头像变更监控 (verified)

  - 新增 Worker 作业 `worker/jobs/x_avatar_poll.py`，支持从配置/环境变量加载 KOL 列表，逐个拉取头像 URL
  - Redis 写入键：`x:avatar:{handle}:last_hash`、`last_seen_ts`、`last_change_ts`，TTL=14 天
  - mock 支持：`X_AVATAR_MOCK_BUMP`，可强制生成不同头像哈希，用于模拟变更
  - 日志覆盖：`x.avatar.request` / `x.avatar.success` / `x.avatar.change` / `x.avatar.error` / `x.avatar.stats`
  - 新增验收脚本 `api/scripts/verify_x_avatar.py`，检查 Redis 状态并返回 JSON：{pass, details}，10 分钟内有 seen 即通过
  - `.env.example` 增加开关与参数：`X_ENABLE_AVATAR_MONITOR=false`（默认关闭）、`X_AVATAR_MOCK_BUMP=0`、`X_AVATAR_POLL_INTERVAL_SEC=300`
  - `docs/RUN_NOTES.md` 新增 Day8.1 说明与 Runbook：单次执行、mock bump 模拟变更、Redis 校验
  - 当前验收通过：运行 Worker 作业 15 个 handle 全部成功；模拟 bump 多次触发 change；verify 脚本返回 pass:true

- Day9 ｜ DEX 快照（双源容错，补 Day7.2）

  - providers/dex_provider.py 门面，内部路由 DexScreener → GeckoTerminal
  - ENV: `DEX_CACHE_TTL_S=60`（兼容旧名 `DEX_CACHE_TTL_SEC`，日志警告一次）
  - Redis:
    - `dex:snapshot:{chain}:{ca_norm}:{bucket}` 短期缓存
    - `dex:last_ok:{chain}:{ca_norm}` 存放上次成功值，降级回退用
  - API: `GET /dex/snapshot?chain=eth&contract=0x...`
    - 返回价格、流动性、FDV、OHLC
    - 辅助字段：`source, cache, stale, degrade, reason`
  - 验收脚本: `scripts/verify_dex_snapshot.py`
  - Day9 DEX 快照已完成，支持双源容错与缓存降级，响应包含完整价格与流动性信息，且符合预期的缓存策略和状态标记。

- Day7.2 ｜卡片字段规范与推送模板

  - 新增 `schemas/pushcard.schema.json`，CI 校验
  - 模板：
    - `templates/cards/primary_card.tg.j2` (Telegram)
    - `templates/cards/primary_card.ui.j2` (内部 UI)
  - 字段规范：
    - `risk_note, verify_path, data_as_of, legal_note, rules_fired[]`
    - token/CA 归一化 (`ca_norm`)
    - sources: `security_source`, `dex_source`
    - metrics: `price_usd, liquidity_usd, fdv, ohlc{m5,h1,h24}`
    - 状态位：`cache, degrade, stale, reason`
    - evidence: `goplus_raw.summary`（截断）
  - 去抖：同 event_key & risk_level，30 分钟内不重复推送
  - 复查队列：Redis ZSET `recheck:hot`，Celery beat 定时回扫
  - 验收脚本:
    - `scripts/validate_cards.py` (Schema)
    - `scripts/verify_primary_cards.py` (字段/模板/去抖)
  - Day7.2 卡片字段规范与推送模板通过 Schema 校验，推送文案包含必需字段，去抖逻辑生效，复查队列正常工作。
  - 所有卡片 payload 包含 reason 字段，保证与 DEX 快照上下文一致。

- Day9.1 ｜ Meme 话题卡最小链路（含最小 Telegram 适配）

  - 新增 `/signals/topic` 路由与固定输出 schema（TopicSignalResponse）
  - pipeline：
    - `worker/pipeline/is_memeable_topic.py`（KeyBERT + mini 判定）
    - `worker/jobs/topic_aggregate.py`（24h 聚合/合并/去重与限频）
    - `worker/jobs/push_topic_candidates.py`（推送到 Telegram，复用最小适配层）
  - 配置：
    - 黑名单：`configs/topic_blacklist.yml`
    - 白名单：`configs/topic_whitelist.yml`
    - 合并规则：`rules/topic_merge.yml`
  - 数据库：
    - `migrations/007_signals_topic_ext.py`（signals/events 表增量列，含 topic 字段与可解释性字段）
  - 脚本：
    - `scripts/verify_topic_signal.py`（API 返回字段/斜率/窗口）
    - `scripts/verify_topic_push.py`（Telegram mock 验证）
    - `scripts/seed_topic_mentions.py`（用于斜率计算验收）
  - 服务：
    - `api/services/topic_analyzer.py`（聚合、归一、斜率计算、降级路径）
    - `api/services/telegram.py`（最小适配层，支持 mock 写盘 `/tmp/telegram_sandbox.jsonl`）
  - 环境变量：
    - `DAILY_TOPIC_PUSH_CAP, TOPIC_WINDOW_HOURS, TOPIC_SLOPE_WINDOW_10M, TOPIC_SLOPE_WINDOW_30M`
    - `TOPIC_SIM_THRESHOLD, TOPIC_JACCARD_FALLBACK, TOPIC_WHITELIST_BOOST`
    - `MINI_LLM_TIMEOUT_MS, EMBEDDING_BACKEND, KEYBERT_BACKEND`
    - `TELEGRAM_BOT_TOKEN, TELEGRAM_SANDBOX_CHAT_ID`
  - Makefile：
    - `verify-topic`, `verify-topic-push`, `push-topic-digest`, `seed-topic`
  - 功能：
    - 实体归一化（frog/pepe→pepe），关键词去重
    - 合并顺序：entities → embedding≥0.80 → jaccard≥0.5
    - 限频：同 topic_id 1h 一次，全局上限合并 digest
    - 降级：mini 超时 →degrade，embedding 掉线 →fallback
    - Telegram 推送文案含风险提示“未落地为币，谨防仿冒”
  - 验收：
    - `/signals/topic` 返回固定 14 字段，类型正确
    - `verify_topic_signal` 脚本通过，斜率字段可计算
    - `seed_topic_mentions` 后，10m/30m 斜率非零且不同
    - `verify_topic_push` mock 模式输出到 `/tmp/telegram_sandbox.jsonl`，文案格式正确
  - Day9.1 Meme 话题卡最小链路功能完成，含最小 Telegram mock 适配层，验收通过。

- Day9.2: Primary 卡门禁 + 文案模板改造 (verified)

  - 目标：确保所有一级卡必须过 GoPlus，卡片文案全部改为“候选/假设 + 验证路径”，降低误导风险
  - 任务：
    - Primary 卡流程：候选（来源+疑似官方/非官方）→ GoPlus 体检 → 红黄绿风险标记
    - 扩展 `rules/risk_rules.yml`：强制体检不通过即 red/yellow；体检异常时标记 gray + 降级提示
    - 卡片渲染模板改造：新增 `risk_note` 字段，统一提示（高税/LP 未锁等），固定包含 `legal_note`
    - Secondary 卡文案：来源分级（rumor/confirmed），必须显示验证路径与 `data_as_of`
    - 新增 `normalize_ca(chain, ca)` 辅助方法，CA 归一化、多 CA 去重并标记 `is_official_guess`
    - 推送防抖：同一 event_key 1 小时不重复，且仅状态变化（candidate→verified/downgraded/withdrawn）允许二次推送
    - 降级一致性：GoPlus/DEX 出错时风险标 gray，并写入 `rules_fired`、`risk_source`
  - 落地文件：
    - `rules/risk_rules.yml`
    - `api/security/goplus.py`
    - `api/cards/generator.py`, `api/cards/dedup.py`
    - `templates/cards/primary_card.tg.j2`, `templates/cards/primary_card.ui.j2`
    - `templates/cards/secondary_card.tg.j2`, `templates/cards/secondary_card.ui.j2`
    - `api/utils/ca.py`（新）
    - `schemas/pushcard.schema.json`
  - 验收通过：
    - 3 个垃圾盘样本能被体检标红并推送 red 卡片
    - GoPlus 不可用时卡片风险为 gray，且禁止出现 green
    - Secondary 卡固定包含 `verify_path`、`data_as_of`、`source_level`，并预留 `features_snapshot`
    - 模板文案统一为“候选/假设 + 验证路径”，含 `legal_note` 与隐藏字段 `rules_fired`
    - 同一 event_key 仅“状态变化”允许二次推送
    - `risk_source:"GoPlus@vX.Y"` 必填
    - `normalize_ca` 生效，多 CA 去重并标注 `is_official_guess`

- Day10: BigQuery 接入最小闭环 (done)

  - 目标：打通云端链上数据仓库最小闭环（凭据、SDK、Provider、健康检查、成本守门），为后续候选 → 证据链路铺路。
  - 任务：
    - 新增 ENV：GCP_PROJECT, BQ_LOCATION, BQ_DATASET_RO, BQ_TIMEOUT_S, BQ_MAX_SCANNED_GB, ONCHAIN_BACKEND
    - 新建 `api/clients/bq_client.py`，封装 dry_run/query/freshness，支持成本守门与最大计费字节限制
    - 新建 `api/providers/onchain/bq_provider.py`，统一模板渲染、dry-run 守门、重试与 degrade 返回
    - 更新 `api/routes/onchain.py`，新增 `/onchain/healthz` 与 `/onchain/freshness`
    - 更新 compose 与 `.env.example`，挂载 SA JSON，落地 secrets 目录
    - 日志结构化输出：bq_bytes_scanned, dry_run_pass, cost_guard_hit, maximum_bytes_billed, degrade
  - 落地文件：
    - `api/clients/bq_client.py`
    - `api/providers/onchain/bq_provider.py`
    - `api/routes/onchain.py`
    - `templates/sql/freshness_eth.sql`
    - `infra/docker-compose.yml`
    - `.env.example`
    - `api/utils/logging.py`（新）
  - 验收通过：
    - `/onchain/healthz` 返回 200，dry-run-only，无 row_count
    - `/onchain/freshness?chain=eth` 返回最新块号与 data_as_of
    - 将 BQ_MAX_SCANNED_GB 调小触发 cost_guard，接口 degrade:true 且不中断流程
    - ONCHAIN_BACKEND=off 时返回 degrade:bq_off
    - maximum_bytes_billed 在日志中记录（5GB = 5368709120 bytes）
    - 日志包含 bq_bytes_scanned, cost_guard_hit, maximum_bytes_billed
  - Notes：
    - BQ_DATASET_RO 使用完整 project.dataset（例如 `bigquery-public-data.crypto_ethereum`）
    - api/worker 均挂载 `/app/infra/secrets` 并加载 .env
    - 所有错误均返回 200 + {degrade:true,...}，候选流不中断

- Day11: SQL 模板与新鲜度守门 + 成本护栏 (done)

- 目标：固化 3 个 ETH SQL 模板，并将 freshness 预检、dry-run 成本护栏、模板 LINT、短缓存接入业务流，避免一演示就账单爆炸。

  - 任务：
    - 新增 3 个 SQL 模板：
      - `templates/sql/eth/active_addrs_window.sql`
      - `templates/sql/eth/token_transfers_window.sql`
      - `templates/sql/eth/top_holders_snapshot.sql`
    - 新增 `/onchain/query` 路由，Provider 接入 freshness → dry-run → 成本护栏 → 缓存 → 真查 全链路
    - Redis 缓存 TTL 抖动 60–120 秒；cache key: `bq:tpl:{tpl}:{address}:{window}:{hash(sql)}`
    - 模板强制 LIMIT 与时间窗口；返回统一字段 `data_as_of`
    - LINT：缺 LIMIT / 缺时间窗口 / 尾部垃圾字符 / 禁止 `DATE(block_timestamp)` → {stale:true, degrade:"template_error"}
    - 健康探针与 freshness 查询使用轻量 SQL，不做全表扫描
    - `.env.example` 新增 `FRESHNESS_SLO`
  - 落地文件：
    - `api/providers/onchain/bq_provider.py`
    - `api/routes/onchain.py`
    - `api/utils/cache.py`
    - `templates/sql/eth/*.sql`
    - `.env.example`
  - 验收通过：
    - 三模板返回字段完整，含 `data_as_of`
    - 重复请求命中缓存：`cache_hit=true`
    - FRESHNESS_SLO=10 时触发 `data_as_of_lag=true`
    - BQ_MAX_SCANNED_GB=0 时返回 `{ "degrade": "cost_guard" }`，HTTP 200
    - 模板不合规时返回 `{ "stale": true, "degrade": "template_error" }`，不中断整体流
    - `/onchain/healthz` 为轻探针，不出现千万级 row_count
    - BigQuery 请求均带 `maximum_bytes_billed`，日志可见
  - Notes：
    - 缓存检查顺序改为成本护栏之后，避免缓存短路护栏
    - BigQuery 客户端统一走 `_get_client()`，移除错误的 `.client.query` 调用
    - 触发 freshness/cost_guard 验证需改 compose/.env 并重启 API 容器

- Day12: On-chain Features Light Table (done)

- 目标：固化 BigQuery 上游的窗口化链上特征为本地轻表，API 直读轻表，避免每次扫描大表与成本抖动。

  - 任务：
    - Alembic 010 迁移：新建 `onchain_features` 表；`signals` 表新增 `onchain_asof_ts`、`onchain_confidence`
    - 作业：`api/jobs/onchain/enrich_features.py`，三窗口派生与幂等写入（带 growth_ratio 计算）
    - 验证脚本：`api/scripts/verify_onchain_features.py`，stub 模式验证 30/60/180 三窗口、growth_ratio 计算、幂等性
    - API：`GET /onchain/features?chain=…&address=…` 返回三窗口最新记录，带 `stale`、`calc_version`、`degrade`、`cache`
    - 文档：`docs/SCHEMA.md`、`docs/RUN_NOTES.md` 增补 Day12 表定义与验收流程
  - 落地文件：
    - `api/alembic/versions/010_day12_onchain_features.py`
    - `api/jobs/onchain/enrich_features.py`
    - `api/scripts/verify_onchain_features.py`
    - `api/routes/onchain.py`
    - `api/schemas/onchain.py`
    - `api/__init__.py`
    - `docs/SCHEMA.md`
    - `docs/RUN_NOTES.md`
  - 验收通过：
    - 010 迁移可正常 upgrade/downgrade 往返
    - `onchain_features` 表具备唯一约束、窗口白名单 check、查询索引
    - `signals` 表存在 `onchain_asof_ts`、`onchain_confidence`
    - enrich 作业能写入 30/60/180 窗口，重跑不新增重复行（幂等性正确）
    - 有前值时 growth_ratio 计算正确，无前值为 NULL
    - API 能返回三窗口最新记录，字段齐全（含 data_as_of、calc_version、stale、degrade、cache）
    - 上游失败时回退 DB 最近值并标记 stale=true
    - Run Notes 验证命令执行成功，含迁移、作业、API 测试全链路
  - Notes：
    - Pydantic 序列化方法改为兼容 v1/v2，避免 `.json()` 报错导致 stale 误判
    - 部分 Session 工厂、DB 连接复用问题留作后续工程化清理卡

- Day13&14: Onchain 证据接入 + 专家视图 (done)

  - 目标：把 BigQuery/轻表 onchain 特征接入信号状态机（S0→S2），并提供受控的专家视图入口，限流/缓存/打点完善，可降级关闭。
  - 任务落地（Cards A–E）：
    - **Card A：规则 DSL 与评估引擎（稳定版）**
      - `rules/onchain.yml` 最小 DSL；阈值分位与窗口白名单
      - `api/onchain/dto.py` 定义 `OnchainFeature`、`Verdict`
      - `api/onchain/rules_engine.py` `load_rules/evaluate`，四类 verdict（upgrade/downgrade/hold/insufficient）
      - 边界用例与健壮性测试通过：YAML 严格键校验、边界值比较、窗口越界与异常兜底
    - **Card B：候选验证作业 + 迁移**
      - 迁移：`signals` 表新增 `onchain_asof_ts TIMESTAMPTZ`、`onchain_confidence NUMERIC(4,3)`；`state` 列与检查约束；并发安全索引
      - 作业：`worker/jobs/onchain/verify_signal.py`，扫描 `state='candidate'`，延迟验证，超时标注 `evidence_delayed`
      - 幂等与并发安全：Redis 锁 + 事件 TTL；BQ 计费统计 `bq_query_count/bq_scanned_mb`
      - 运行时开关：`ONCHAIN_RULES=off` 时仅写 asof_ts/confidence，不改 state
      - 测试：并发锁、降级优先级、超时与成本打点均覆盖
    - **Card C：/signals/{event_key} 摘要 API**
      - 返回 `state`、`onchain` 摘要与 `verdict`；Redis 缓存 120s，TTL 实时返回
      - UTC `asof_ts` 以 `Z` 结尾；小数统一 3 位四舍五入；缓存/错误降级路径稳定
    - **Card D：专家视图 `/expert/onchain`**
      - 仅内部可见：`EXPERT_VIEW=on` + `X-Expert-Key` 必须
      - 限流：`5/min/key`；缓存：180s± 抖动；打点：查询次数与字节
      - 数据源：默认 PG 轻表；可选 BQ（`EXPERT_SOURCE=bq`），BQ 失败回退上次成功值并标记 `stale:true`
      - 返回 24h/7d 活跃度序列与 top10_share 概览，字段对齐卡片 schema
    - **Card E：集成与命令行**
      - 周期任务：每分钟可调度 `verify_signal.run_once()`（开发环境可用 Make/cron 代替常驻 beat）
      - Make：`onchain-verify-once`、`expert-dryrun`；日志结构化 JSON（scanned/evaluated/updated）
  - 验收通过：
    - 候选在 3–8 分钟内可升级为 verified/downgraded，或保持 candidate 并标注 `insufficient_evidence/evidence_delayed`
    - `/signals/{event_key}` 命中缓存时返回 `cache.hit=true` 且 TTL 递减可见；数值精度正确
    - 专家视图限流/缓存/降级生效；`EXPERT_VIEW=off` 时 404；BQ 离线时返回 `stale:true` 且不崩溃
    - 运行时开关与回退路径符合 ADR：`ONCHAIN_RULES=off` 不改 state；迁移可降级
  - Notes：
    - 开发环境未常驻 beat 服务不影响演示：命令行触发与 cron 足够；生产如需常驻，单独部署 celery beat
    - BigQuery 轻表为节费与稳定性引入，默认读 PG；BQ 配置缺失时自动降级不阻断

- Day15&16 合并执行 (Done)

  **目标达成（不改 Day5 的 event_key 维度）**

  - 事件跨源聚合与证据去重：仅以 `event_key` 合并，`events.evidence[]` 与 `evidence_count` 正确累积；去重键为 `sha1(source+stable_ref)`。
  - 热度快照与斜率：新增 `GET /signals/heat?token|token_ca`，返回 `{cnt_10m,cnt_30m,slope,trend,asof_ts}`；样本不足降级为仅计数。
  - 可选持久化：当 `HEAT_ENABLE_PERSIST=true` 时，按 **event_key** 将结果写入 `signals.features_snapshot.heat`（幂等、原地覆盖）。
  - D.1 修复：`persist_heat()` 先解析 `event_key`（优先 `token_ca`，可回退 `symbol`），**直接用 event_key 更新**，无 JOIN；路由中 **compute + persist 同一事务**，杜绝“persisted:true 但 DB 空”。
  - E 文档与可观测性：RUN_NOTES 补齐一键 smoke 流程、环境变量与回滚、结构化日志字段清单；Swagger 路由统一挂载于 `api/routes/*`。

  **关键开关**

  - `EVENT_KEY_SALT=v1`（改动仅打印告警，不改输入维度）
  - `EVENT_MERGE_STRICT=true|false`（严格跨源/单源）
  - `HEAT_ENABLE_PERSIST=true|false`（是否落盘）
  - `HEAT_CACHE_TTL=0`（0 关闭缓存）
  - `THETA_RISE`（趋势阈值），`HEAT_NOISE_FLOOR`、`HEAT_EMA_ALPHA`

  **观测点（stage）**

  - `pipeline.event.key`、`pipeline.event.merge`、`pipeline.event.evidence.merge`
  - `signals.heat.compute`、`signals.heat.persist`、`signals.heat.error`

  - **Verify 重放（严格/宽松对比）**

    ```bash
     严格：应出现跨源共现 (>0)
    docker compose -f infra/docker-compose.yml exec -T api sh -lc 'PYTHONPATH=/app EVENT_MERGE_STRICT=true  python -m scripts.verify_events --sample scripts/replay.jsonl'

     宽松：跨源共现应为 0
    docker compose -f infra/docker-compose.yml exec -T api sh -lc 'PYTHONPATH=/app EVENT_MERGE_STRICT=false python -m scripts.verify_events --sample scripts/replay.jsonl'
    ```

    期望：每事件 `refs>=2` 且 `event_key` 重放一致；严格模式统计中出现 `x + dex|goplus` 共现。

  - **Heat 接口 + 持久化（最小 smoke）**

    ```bash
     造数（落在 10m/30m 窗口内）
    docker compose -f infra/docker-compose.yml exec -T db psql -U app <<'SQL'
    BEGIN;
    INSERT INTO events(event_key,type,summary,start_ts,last_ts,symbol,token_ca,version,evidence_count)
    SELECT 'ek_test_1','topic','seed', NOW()-INTERVAL '30 min', NOW(), 'TEST','0xabc123abc123abc123abc123abc123abc123abcd','v1',2
    WHERE NOT EXISTS (SELECT 1 FROM events WHERE event_key='ek_test_1');
    INSERT INTO signals(event_key,features_snapshot,ts)
    SELECT 'ek_test_1','{}'::jsonb,NOW()
    WHERE NOT EXISTS (SELECT 1 FROM signals WHERE event_key='ek_test_1');
    DELETE FROM raw_posts WHERE token_ca='0xabc123abc123abc123abc123abc123abc123abcd';
    INSERT INTO raw_posts(symbol,token_ca,ts,source,text) VALUES
    ('TEST','0xabc123abc123abc123abc123abc123abc123abcd', NOW()-INTERVAL '9 min','x','mock'),
    ('TEST','0xabc123abc123abc123abc123abc123abc123abcd', NOW()-INTERVAL '8 min','x','mock'),
    ('TEST','0xabc123abc123abc123abc123abc123abc123abcd', NOW()-INTERVAL '7 min','x','mock'),
    ('TEST','0xabc123abc123abc123abc123abc123abc123abcd', NOW()-INTERVAL '6 min','x','mock'),
    ('TEST','0xabc123abc123abc123abc123abc123abc123abcd', NOW()-INTERVAL '5 min','x','mock'),
    ('TEST','0xabc123abc123abc123abc123abc123abc123abcd', NOW()-INTERVAL '3 min','x','mock'),
    ('TEST','0xabc123abc123abc123abc123abc123abc123abcd', NOW()-INTERVAL '1 min','x','mock'),
    ('TEST','0xabc123abc123abc123abc123abc123abc123abcd', NOW()-INTERVAL '19 min','x','mock'),
    ('TEST','0xabc123abc123abc123abc123abc123abc123abcd', NOW()-INTERVAL '11 min','x','mock');
    COMMIT;
    SQL

    开启持久化并调用（缓存关）
    docker compose -f infra/docker-compose.yml exec -T api sh -lc 'HEAT_ENABLE_PERSIST=true HEAT_CACHE_TTL=0 curl -s "http://localhost:8000/signals/heat?token_ca=0xabc123abc123abc123abc123abc123abc123abcd" | jq .'

     核对 DB 已落盘
    docker compose -f infra/docker-compose.yml exec -T db psql -U app -c "SELECT jsonb_pretty(features_snapshot) FROM signals WHERE event_key='ek_test_1'"
    ```

    期望：接口返回 `cnt_10m=7,cnt_30m=9,slope≈0.5,trend=up,persisted=true`；数据库存在 `features_snapshot.heat`。

  - **回滚校验**
    - `HEAT_ENABLE_PERSIST=false` 再调接口，`persisted=false` 且不写库。
    - `EVENT_MERGE_STRICT=false` 重跑 verify，共现计数为 0。

- Day 17: HF 批量与阈值校准 (verified)

  - Card A: 实现 `api/services/hf_client.py`，统一批量接口，支持 local/inference 后端，失败率降级
  - Card B: 增强 `scripts/smoke_sentiment.py`，支持 --batch 和 --summary-json，处理 BrokenPipeError
  - Card C: 实现 `scripts/hf_calibrate.py`，网格搜索最优阈值，生成 JSON 报告和 env.patch
  - 产物：`reports/hf_calibration_*.json` 和 `.env.patch` 包含推荐阈值（基于 Macro-F1）
  - 降级链路验证：HF_TIMEOUT_MS=1 时批量结果含 degrade:"HF_off" 标记
  - 无 schema 变更，Day4 单条预测保持兼容
  - 回滚方式：删除 api/services/hf_client.py，恢复 api/hf_sentiment.py 原调用，移除 .env 新增变量
  - 标签/分数口径沿用 Day4：`{"pos","neu","neg"}` 与 `score=P(pos)-P(neg)`（[-1,1] 截断）。
  - 阈值仅作“建议”，不自动写回 `.env`；以配置为准，避免配置漂移。

- Day18: 规则引擎 + 极简建议器（稳健版） (verified)

  - 18.1 规则引擎核心：`api/rules/eval_event.py` + `rules/rules.yml`，支持分组/优先级/权重，ENV 覆盖（`THETA_LIQ/THETA_VOL/THETA_SENT`），mtime 热加载（TTL 默认 5s），解析失败回退旧版；安全表达式（AST 白名单，字段白名单），缺源点名（dex/hf/goplus），输出 `reasons≤3` 与 `all_reasons`。
  - 18.2 API 路由：新增 `api/routes/rules.py` 暴露 `GET /rules/eval?event_key=...`，返回 `level/score/reasons/all_reasons/evidence/meta`，404/422/500 错误处理，结构化日志 `rules.eval`。
  - 18.3 门后精析适配：`api/rules/refiner_adapter.py`，ENV 开关 `RULES_REFINER`（默认 off），800ms 预算，失败降级并打点 `rules.refine_degrade`，不改事实，仅做措辞压缩去冗，`meta.refine_used` 标记。
  - 18.4 集成测试（pytest）：`tests/test_rules_eval.py` 覆盖 3 场景（完整/缺 DEX/缺 HF）、规则热加载、门后精析开关探活；使用 TestClient、DEMO key 插入与回滚清理；确保 `reasons` 为 `all_reasons` 前缀；`Makefile verify_rules` 一键运行。
  - 18.5 配置与文档：`.env.example` 补充 `THETA_LIQ/THETA_VOL/THETA_SENT/RULES_TTL_SEC/RULES_REFINER`；`Makefile` 新增 `verify_rules` 目标（容器内运行 pytest）；文档保持不覆盖。
  - 18.6 并发与热加载安全：`RuleLoader` 引入 `threading.Lock` 原子替换；`time.monotonic()` 节流；SHA256 `etag`；256KB 文件上限、200 条规则上限；ENV 白名单；AST 校验；失败回退旧版本；日志 `rules.reloaded / rules.reload_error`（含 `etag_prefix`）。
  - 18.7 错误处理与日志：路由生成 `request_id=uuid4()` 贯穿；成功路径记录 `all_reasons_n` 而非全量；异常日志裁剪 `traceback≤500`；日志统一包含 `module/request_id/rules_version/hot_reloaded/latency_ms/refine_used`；错误按 `reason` 分类（`yaml_parse_error/file_size_exceeded/io_error/validation_failed/unexpected_error`）。

  **Runbook（Day18 验收）**

  - 一键测试：`make verify_rules`
  - 单次调用：`curl -s "http://localhost:8000/rules/eval?event_key=eth:DEMO1:2025-09-10T10:00:00Z" | jq '{level,score,reasons,all_reasons,meta}'`
  - 查看日志：`docker compose -f infra/docker-compose.yml logs -f api | rg 'rules\\.(eval|reloaded|reload_error|refine_degrade)'`

- Day19: Internal Cards Schema + Summarizer + Builder + Preview + Verify (verified)

  - scope: 已新增内部卡片契约 `schemas/cards.schema.json`（Draft-07），约束 `data.{goplus,dex,onchain}`、`rules.*`、`evidence[]`、`summary`、`risk_note`、`rendered?`、`meta.*`。成功实现 `api/cards/build.py` 组装器，输入 `event_key` 合流 `events+signals(+onchain)` 并产出符合 schema 的对象。`api/cards/summarizer.py` 受限摘要器已上线，支持超时降级为模板摘要。`GET /cards/preview?event_key=...&render=1` 路由返回卡片 JSON（含可选 rendered.tg/ui），一键校验脚本 `scripts/verify_cards_preview.py` 与 `make verify_cards` 均通过。(verified)
  - env: 已通过 `CARDS_SUMMARY_BACKEND=llm|template`（默认 llm）、`CARDS_SUMMARY_TIMEOUT_MS=1200`、`CARDS_SUMMARY_MAX_CHARS=280`、`CARDS_RISKNOTE_MAX_CHARS=160` 环境变量配置，均按预期工作。(verified)
  - acceptance: `curl -s "/cards/preview?event_key=...&render=1"` 返回 200，且所有响应通过 `schemas/cards.schema.json` 校验。响应包含 `data.goplus.*` 与 `data.dex.*` 核心字段，`summary` 与 `risk_note` 均非空且未超限。将 `CARDS_SUMMARY_TIMEOUT_MS=1` 后再请求，`meta.summary_backend="template"` 且内容可读，降级路径符合预期。(verified)
  - out_of_scope: `/cards/send` 推送与重试队列（已留待 Day20）；未包含新规则与新数据源的引入。(verified)

- Pre Day20+Day21：发送链路加固（三件套）（verified)

  - 路由 `/cards/send` 已挂载：支持 `count` 批量、`dry_run`、Redis 去重（1h 窗口），沙盒覆盖（`TG_SANDBOX`），失败项入库 `push_outbox`，返回明细结构稳定。
  - Outbox 重试作业：429 读取 `retry_after`；5xx/网络错误指数退避（含抖动，封顶 10 分钟）；4xx（非 429）→ DLQ；Celery beat 每 20 秒调度，已在日志中观察到 pending→done 的补发闭环。
  - 最小速率限制：Redis 秒级二元窗（global + per-channel），请求前 `allow_or_wait()` 拦截；本地 429 快速失败由 Outbox 兜底；在 `TG_RATE_LIMIT=2` 压测下，worker 平滑外发、无 429 淹没。
  - 指标与日志绑定：`telegram_send_latency_ms`、`telegram_error_code_count{code}`、`outbox_backlog`、`pipeline_latency_ms`；`export_text()` 验证通过，API/Worker 均有结构化日志（`telegram.send/sent/timeout`、`outbox.process_batch`）。
  - 验收记录：`/cards/send?event_key=E_REAL3&count=5` 实发 5 条；`bench_telegram.py` 在限流=2 时输出均衡；手工插入 `push_outbox` 后由 worker 补发成功。

- Day20+21: Cards 运维增强（完成）

  - Card B：失败快照（已完成）

    - 失败分支写入 push_outbox.snapshots，含 request/response/error 三元组；便于复盘。
    - 降级路径：写盘失败不阻断流程，仅日志告警。
    - 验收：curl 触发失败后，Redis/DB 中可见 snapshot 记录，字段完整。

  - Card C：运维 Run Notes（已完成）

    - docs/RUN_NOTES.md 新增 “Cards 发送与降级运维指南（Day20）”。
    - 覆盖常用指标、日志检查、429 自救、降级快照核查、快速验证命令。
    - 验收：逐条命令可在 docker compose -f infra/docker-compose.yml 环境中执行。

  - Card D：幂等键（已完成）

    - 新增 idemp_key(event_key|channel_id|template_v)，Redis SETNX+TTL。
    - 命中直接返回 dedup:true，避免重复推送/出网。
    - TTL 复用 DEDUP_TTL（90 分钟），日志含 trace_id。
    - 验收：同一 event_key+channel+template_v 重复调用返回 dedup:true，不再发送；不同 template_v 可区分。

  - Card E：外呼错误占位指标（已完成）

    - 在 Telegram 发送失败路径中增加计数：
      - 429 → external_error_total_429
      - 5xx → external_error_total_5xx
      - 网络/超时 → external_error_total_net
    - 验收：伪造响应/关网触发后，export_text() 可见计数累加。

  - 总结：发送链路现已具备快照、降级、指标、幂等保护与运维文档，满足真实环境下可观测性与自愈需求。

- Day22 回放与部署（最小闭环）

  - 一键部署、首卡时间量化、Golden 回放与评分、可重现打包

  - Tasks (max 3)

    1. 一键化与预检：Makefile 目标完成；preflight/env/migrate 脚本可用；`make verify:telegram` 发出 smoke-ok
    2. Golden 回放：`replay_e2e.sh` + `score_replay.py` 跑通 `demo/golden/golden.jsonl`，产出 `replay_report.json`
    3. 首卡计时与打包：`measure_boot.sh` ≤ 30m；`build_repro_bundle.sh` 生成 `artifacts/day22_repro_*.zip`

  ### Acceptance

  - Fresh clone → `make up` 成功；API /healthz 200；alembic at head=013
  - `make verify:telegram` 成功在频道看到 “smoke-ok”
  - `scripts/measure_boot.sh` 报告 `duration_ms ≤ 1_800_000`（30 分钟）
  - `scripts/replay_e2e.sh demo/golden/golden.jsonl` 完成并生成 `replay_report.json`；评分达标：`pipeline_success_rate ≥ 0.90`、`alert_accuracy_on_success ≥ 0.80`、`cards_degrade_count ≤ 2`
  - 生成 `artifacts/day22_repro_*.zip`，包含 redacted env、镜像 digests 与回放报告

  - Safeguards

    - `TELEGRAM_PUSH_ENABLED=false` 时跳过真实发送但仍写回放报告
    - 失败保留 `logs/day22/*.log` 供定位
    - 验收请关闭软化开关：`REPLAY_SOFT_FAIL=false`、`SCORE_SOFT_FAIL=false`（软化模式仅用于开发调试，否则不会阻塞流水线）。

- Day23+24: 配置治理 & 观测告警 (verified)

  - 目标：

    - rules/\*.yml 热加载，阈值/KOL/黑白名单改动 ≤ 1min 生效
    - .env.example 注释补齐 + 敏感变量审计；config_lint 全绿
    - /metrics 暴露成功率/延迟/退化比 + 热加载指标；受 METRICS_EXPOSED 控制
    - TG 失败自动重试 + 本地告警（alerts.yml + scripts/alerts_runner.py）

  - 产物：

    - `api/config/hotreload.py`（TTL+mtime/sha1 侦测，解析成功后原子切换，SIGHUP 立即刷新，fail-safe 回退旧版）
    - `scripts/config_lint.py`（YAML/ENV/敏感项统一 Lint，`config_lint: OK|FAIL` 口径）
    - `.env.example`（完整注释与占位 `__REPLACE_ME__`；新增 `METRICS_EXPOSED=false`）
    - `api/routes/metrics.py`（Prom v0.0.4，直方图三件套 `_bucket/_sum/_count`，计数器 `_total`，单位 `_ms`）
    - `alerts.yml` + `scripts/alerts_runner.py`（去抖 `window_seconds`、静默 `silence_seconds`、状态持久化 `--state-file`）
    - `scripts/notify_local.sh`（本地通知示例）
    - 文档：`docs/RUN_NOTES.md` 新增 Day23+24 运行手册（原子写流程、热加载演示、metrics 与告警验收、回滚速查）

  - 验收（均在 compose 环境通过）：

    - 配置热更：改阈值后 ≤ 1 分钟日志出现 `config.reload`/`config.applied`，`/metrics` 的 `config_version` 变化
    - Lint：`python scripts/config_lint.py` 退出码 0；缺失/敏感项扫描通过
    - Metrics：`Content-Type: text/plain; version=0.0.4`；`pipeline_latency_ms` 直方图三件套输出；`METRICS_EXPOSED=false` 返回 404 并打 `metrics.denied`
    - 告警：坏 TG token 触发 `telegram_error_rate_high`，静默窗口内不重复告警；人为断 DEX 源 `cards_degrade_spike` 击中；日志前缀 `alert.*` 统一

  - Notes：
    - 修复了 `/metrics` 被 `/{event_key}` 吞路由的问题（限制通配正则并在 signals_summary 内转发兜底）
    - 整理多处 `metrics.py` 命名冲突，路由只调用唯一的 builder；避免导入阴影
    - 所有开关在请求/运行时动态读取 ENV，禁止模块级缓存；容器内设置生效
    - 指标命名遵循 Prom 规范：计数 `_total`，时间单位 `_ms`，直方图三件套齐全

- Day23+24: card G 新增

  - 完成配置治理与观测告警全链路：
    - rules/\*.yml 热加载（≤1min 生效，config.reload 日志可见）
    - .env.example 全量注释与敏感项占位，config_lint 全绿
    - /metrics 暴露成功率、延迟、退化比，包含 config_reload_total 与 config_version
    - alerts.yml + scripts/alerts_runner.py 支持去抖、静默窗口与 webhook 通知
    - 新增 Makefile 护栏：`config-lint / metrics-check / alerts-once / reload-hup / verify-day23-24`
    - 新增 PR Template，硬性要求 config-lint 输出与 METRICS_EXPOSED 审核
  - 验收：
    - 修改 rules/\*.yml 后 ≤1min 出现 config.reload 日志，/metrics 的 config_version 变化
    - `make config-lint` 返回 OK，敏感/缺失项为 0
    - 断 DEX 源 → 退化比上涨；坏 TG token → 重试触发 + 告警命中
    - /metrics 可抓到 telegram_send_total / retry_total / pipeline_latency_ms_bucket / cards_degrade_count
    - 所有 Makefile 新增目标执行成功，PR Template 生效
  - 回滚：注释 alerts.yml 全部规则；删除 Makefile 新增目标与 PR Template
