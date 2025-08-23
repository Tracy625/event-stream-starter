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
  - infra/.env.example 补充 SENTIMENT/HF/KEYPHRASE 与 LATENCY_BUDGET_MS\_\* 变量
  - bench_sentiment 可运行，默认 rules-only；可配置 N 次采样
- Day 4: HuggingFace Sentiment & Keywords Enhancement (verified)
  - Sentiment router 拆分 (rules/hf)，调用期路由与降级路径完成
  - HF id2label → {"pos","neu","neg"}；Score = P(pos)-P(neg)，[-1,1] 截断
  - Keyphrases: KBIR + rules fallback，去重/小写/停用词处理
  - /scripts/smoke_sentiment.py 可运行，bench-sentiment 支持双后端
  - .env.example 更新 SENTIMENT_BACKEND / HF_MODEL / KEYPHRASE_BACKEND
  - 验收通过：HF+ 返回正，HF- 返回负，坏模型时降级为 rules

## Today (D5)

- 扩展事件信号生成逻辑，补充 sentiment + keywords 的落库与事件联动
- 在事件 upsert 流程里，将 sentiment_label/score、keywords、is_candidate 一并写入
- 为事件新增字段 candidate_score，用 sentiment + keyword 命中数计算（保持 schema 向前兼容）
- 新增 scripts/verify_signals.py：对 raw_posts 与 events 进行抽样校验，输出 candidate_score 分布

## Acceptance (D5)

- `make demo` 后，raw_posts/ events 表中有 sentiment_label/score、keywords、is_candidate 字段，且非空率 >60%
- candidate_score 在 0–1 区间，且与 sentiment/keywords 命中数相关
- `python scripts/verify_signals.py` 输出 JSON 统计：{sample_size, candidate_score_mean, candidate_score_p95}
- event upsert 的 last_ts 仍保持单调递增
