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

## Today (Day7.1):

- status:LOCKED

-

## Acceptance (Day7.1)

---
