# CLAUDE.md — Project Collaboration Rules

## Required Reading (every session)
- Read `/docs/BRIEF.md` to understand product scope and users.
- Read `/docs/STATUS.md` to know current progress, today's tasks, and acceptance criteria.
- Read `/docs/WORKFLOW.md` to follow the mixed-mode kickoff process
- Do not start coding before confirming understanding of both files.
- Read `/docs/WORKFLOW.md` "One-click Demo & Migrations" section before running any DB-related tasks.

## Guardrails
- Do **not** delete/rename/move files/dirs **unless I explicitly say**: "delete <file>" or "move <file> to <dir>".
- Show all changes as diffs. Never auto-apply or run bulk refactors.
- Keep responses concise: plan (≤5 bullets) → diffs → run/test notes.

## DB Invariants
- SQL fragments must import as: `from sqlalchemy import text as sa_text`. 裸 `text(...)` 禁止使用，避免与列名冲突。
- `events` 表使用 `start_ts` 与 `last_ts`。任何查询按 `last_ts` 排序；代码中不得引用不存在的 `ts` 列。
- `api/main.py` 顶层禁止任何 DB 相关导入或初始化。健康检查 `/healthz` 必须纯返回 200。
- 所有数据库迁移操作必须通过 **`make migrate` / `make revision`** 触发，禁止直接编写 `docker compose exec ... alembic` 命令。

## Tech & Repo
- Stack: FastAPI + Celery + Postgres + Redis; Next.js skeleton only.
- Modules: collector → filter(HF+rules) → mini-LLM refine → aggregator(event_key) → security scan(GoPlus) → DEX data → notifier(Telegram).
- Target P95: end-to-end ≤ 2 minutes.

## Workflow
1.Confirm today's acceptance criteria from `/docs/STATUS.md`.
2.Propose a plan (≤5 bullets). Ask for missing ONLY if blocking.
3.Produce diffs. Provide commands to run and minimal tests.
4.If external APIs rate limit, implement backoff + caching; document it.
5.Never perform “cleanup”, “auto-structure”, or “bulk rename”.

## When risky operations are requested
- Before deletion/moves, show a step-by-step plan and the exact diffs.
- Wait for my explicit phrase: "approved" to proceed.