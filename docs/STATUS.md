# STATUS — Daily Plan

## Done

- Project setup: BRIEF, STATUS, WORKFLOW, CLAUDE.md
- Day 1: Monorepo init, health endpoints, migrations, docker-compose
- Day 2: filter/refine/dedup/db pipeline (verified)
  - filter/refine/dedup/db 全部通过；Redis/内存双模式验收通过
  - Alembic 迁移到 002（score 列）；API /healthz 200，容器 healthy
- Day 3: scripts/demo_ingest.py；JSONL 结构化日志；Makefile `demo`；WORKFLOW 文档更新
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

## Today (D7): Signal Scoring & Alert Routing (draft)

- 目标：对 refine 输出的事件做进一步量化评分，并建立报警路由
- 新增 api/signals.py：
  - score_event(event) → float (0–1)
  - 简单启发式规则 + LLM 打分（可配置后端）
- 新增 redis/pg 存储 signals 表，包含 event_key, score, ts
- 新增 scripts/verify_signals.py 验收脚本
- 新增报警路由逻辑（例如高于阈值的事件推送到 stdout/文件）
- 结构化日志：stage="signal.score" | "signal.alert"

## Acceptance (D7)

- 10 条样本中 ≥ 8 条成功打分（0–1 区间）
- 报警触发率符合阈值设置（如 ≥0.8）
- 容器内延迟不显著增加（≤ +200ms/条）
- 日志覆盖：signal.score / signal.alert
- 不影响 D6 pipeline 稳定性

---

## Upcoming (D8+ tentative)

- **D8: Notifications / Integrations**

  - Webhook/Slack/Email 通知模块
  - 事件级别分级推送（info/warn/critical）
  - 支持多后端降级策略（本地文件 → webhook → slack）

- **D9: UI Prototype**

  - Next.js 简单界面，展示 events/signals 列表
  - 接入 api/events & api/signals
  - 本地容器跑通 demo 页面

- **D10: End-to-End Smoke Test**
  - 从 raw_posts → events → refine → signals → alerts 全链路演示
  - 输出结构化 JSON 日志完整覆盖
  - 提供 README / demo 脚本，支持一键运行
