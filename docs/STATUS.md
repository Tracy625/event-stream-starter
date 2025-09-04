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

---

## Today — Day9.2 Primary 卡门禁 + 文案模板改造

- **目标**：确保所有一级卡必须过 GoPlus，卡片文案全部改为“候选/假设 + 验证路径”，降低误导风险
- **任务**：
  - Primary 卡流程：候选（来源+疑似官方/非官方）→ GoPlus 体检 → 红黄绿风险标记
  - 扩展 `rules/risk_rules.yml`：强制体检不通过即 red/yellow；体检异常时标记 gray + 降级提示
  - 卡片渲染模板改造：新增 `risk_note` 字段，统一提示（高税/LP 未锁等），固定包含 `legal_note`
  - Secondary 卡文案：来源分级（rumor/confirmed），必须显示验证路径与 `data_as_of`
  - 新增 `normalize_ca(chain, ca)` 辅助方法，CA 归一化、多 CA 去重并标记 `is_official_guess`
  - 推送防抖：同一 event_key 1 小时不重复，且仅状态变化（candidate→verified/downgraded/withdrawn）允许二次推送
  - 降级一致性：GoPlus/DEX 出错时风险标 gray，并写入 `rules_fired`、`risk_source`
- **落地文件**：
  - `rules/risk_rules.yml`
  - `api/security/goplus.py`
  - `api/cards/generator.py`, `api/cards/dedup.py`
  - `templates/cards/primary_card.tg.j2`, `templates/cards/primary_card.ui.j2`
  - `templates/cards/secondary_card.tg.j2`, `templates/cards/secondary_card.ui.j2`
  - `api/utils/ca.py`（新）
  - `schemas/pushcard.schema.json`

## Acceptance

- **验收**：
  - 3 个垃圾盘样本能被体检标红并推送 red 卡片
  - GoPlus 不可用时卡片风险为 gray，且禁止出现 green
  - Secondary 卡固定包含 `verify_path`、`data_as_of`、`source_level`，并预留 `features_snapshot`
  - 模板文案统一为“候选/假设 + 验证路径”，含 `legal_note` 与隐藏字段 `rules_fired`
  - 同一 event_key 仅“状态变化”允许二次推送
  - `risk_source:"GoPlus@vX.Y"` 必填
  - `normalize_ca` 生效，多 CA 去重并标注 `is_official_guess`

---
