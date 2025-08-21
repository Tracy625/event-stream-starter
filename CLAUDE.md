# CLAUDE.md — Project Collaboration Rules

## Required Reading (every session)

- Read `/docs/BRIEF.md` to understand product scope and users.
- Read `/docs/STATUS.md` to know current progress, today's tasks, and acceptance criteria.
- Read `/docs/WORKFLOW.md` to follow the mixed-mode kickoff process
- Do not start coding before confirming understanding of both files.

## Guardrails

- Do **not** delete/rename/move files/dirs **unless I explicitly say**: "delete <file>" or "move <file> to <dir>".
- Show all changes as diffs. Never auto-apply or run bulk refactors.
- Keep responses concise: plan (≤5 bullets) → diffs → run/test notes.

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

## Guardrails (Extended)

### File & Directory Operations

- Always use `__init__.py` for Python packages (never `init.py`).
- Directory creation in project root or submodules does **not** require confirmation.
- Do **not** install dependencies or run services automatically; only create skeletons unless explicitly told otherwise.
- Never generate `node_modules` or initialize full Next.js; `/ui` must remain a minimal skeleton (package.json + README only).
- Do not delete, rename, or move existing files unless I explicitly say: "delete <file>" or "move <file> to <dir>".

### Configuration & Environment

- `.env.example` must always include at minimum:
  - `POSTGRES_URL`
  - `REDIS_URL`
  - `X_BEARER_TOKEN`
  - `GOPLUS_API_KEY`
  - `TELEGRAM_BOT_TOKEN`
  - `DEMO_MODE`
- API must always read DB connection from environment (`POSTGRES_URL`) to configure `SQLALCHEMY_DATABASE_URL`. **Hard-coded DSNs are forbidden.**

### Makefile

- Makefile must always provide at least these targets (placeholders allowed):
  `up, down, logs, api, worker, migrate, revision, demo, seed, test`.

### Docker / Compose

- `docker-compose.yml` must always include these services:
  - `postgres:15` (service name `db`)
  - `redis:7`
  - `api` (FastAPI, Python 3.11 slim)
  - `worker` (Celery worker)
  - `otel` (placeholder)
- All services must be networked properly and read config from `.env`.

### Database Schema

- Database schema must always follow `/docs/SCHEMA.md`. Do not invent or change columns without explicit instruction.

## Model Usage Rules

- 默认使用 **Sonnet** 模型执行代码生成与任务分解。
- 仅在需要跨文件重构或复杂推理时，临时切换到 **Opus**，完成后立即切回 Sonnet。
- 使用指令：`/model sonnet` 或 `/model opus`，完成任务后务必恢复到 Sonnet。
- 开工前必须 `/clear`，避免上下文污染导致幻觉或配额浪费。
- 遇到架构/冲突/多文件交叉类问题，由 GPT-5 先产出补丁思路，再交给 Sonnet 执行，保持稳定性。

## Integration Rules

- Hugging Face 等重型依赖必须延迟加载，禁止顶层 import。

### Database (Day2 Rules)

- 所有 SQLAlchemy 动态 SQL 必须统一写为 `from sqlalchemy import text as sa_text`，禁止裸 `text(...)`。
- `events` 表只有 `start_ts` 和 `last_ts` 字段，所有查询按 `last_ts` 排序；禁止引用虚构的 `ts` 列。

### Logging (Day3+ Rules)

- 所有结构化日志必须通过 `log_json(stage, **kv)` 输出，统一前缀 `[JSON]`。
- 禁止使用裸 `print` 或 `json.dumps` 输出 JSON。
- `timeit` 装饰器在函数异常时必须 log `ok=false` 并抛出异常。

### Performance & Degradation (Day3+ Rules)

- 所有分析模块必须支持延迟预算降级：读取 `LATENCY_BUDGET_MS_*` 环境变量。
- 当阶段耗时超过预算时，必须降级为 `backend="rules"`。
- 公共函数签名必须保持不变：
  - `analyze_sentiment(text) -> (label:str, score:float)`
  - `extract_keyphrases(text) -> list[str]`

### Cache (Day3+ Rules)

- `@memoize_ttl` 装饰器必须输出 JSON 日志，包含 cache hit/miss 与原因。
