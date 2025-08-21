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

## Today (D4)

- 打通字段：将 is_candidate, sentiment_label/score, symbol, token_ca, keywords 写入 raw_posts（保持 insert_raw_post 兼容）
- 重复事件推进 last_ts，不新增事件；保持 upsert_event 只更改允许的字段
- 增加 scripts/verify_dedup.py：读取近 N 条 raw_posts，输出去重前后计数与命中率

## Acceptance (D4)

- 运行 `make demo` 后，raw_posts 最近 5 条至少有 3 条字段非空：is_candidate、sentiment\*\*、symbol/token_ca、keywords
- 同一 event_key 在两次运行之间 last_ts 单调递增
- `python scripts/verify_dedup.py` 输出含 JSON 统计：{total, unique_event_keys, hits}
