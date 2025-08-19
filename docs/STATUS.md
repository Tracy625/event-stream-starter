# STATUS — Daily Plan

## Done

- Project setup: BRIEF, STATUS, WORKFLOW, CLAUDE.md
- Day 1: Monorepo init, health endpoints, migrations, docker-compose
- Day 2: filter/refine/dedup/db pipeline (verified)
  - filter/refine/dedup/db 全部通过；Redis/内存双模式验收通过
  - Alembic 迁移到 002（score 列）；API /healthz 200，容器 healthy

## Today (D3)

- 粘合脚本与演示：新增 `scripts/demo_ingest.py`，串起 filter → refine → dedup → db（仅函数调用，无网络 I/O）
- DEMO_MODE 路径：在 `scripts/demo_ingest.py` 中提供一组内置样例文本，跑通一批入库
- Makefile 快捷目标：`make demo` 一键运行 demo 脚本（容器内执行）
- 日志与可观测：最小 stdout 结构化日志（print or logging），包含 event_key 与去重命中
- 文档：在 `docs/WORKFLOW.md` 增加"一键演示"段落

## Acceptance (D3)

- `make demo` 成功执行，控制台输出每条样例对应的 event_key、dedup 命中与最终 upsert 的摘要
- Postgres 中 `raw_posts` 与 `events` 记录数量与样例条数一致（去重后 `events` 数量下降）
- 日志中可见至少一次 dedup 返回"重复命中"
