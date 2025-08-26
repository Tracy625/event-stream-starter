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

## Direct Execution Mode (DX)

### 触发方式：当用户指令顶部包含以下头部时进入直执模式（大小写精确匹配，顺序不限）：

- MODE: DIRECT_EXECUTION # 硬开关，告诉 Claude 切换模式
- CARD_TITLE: <标题> # 当前卡片是哪一张
- ALLOWED_FILES: # 白名单，限定 Claude 只能动这些文件
  - <相对路径 1>
  - <相对路径 2>

### DX 规则：

- 不读取、不引用 STATUS.md / WORKFLOW.md / 任意对话上下文；不生成或重排任务；仅按该卡执行。
- 只修改 ALLOWED_FILES 中列出的路径；出现其他路径的变更，立即输出 SCOPE_VIOLATION 并停止。
- 禁止引入新依赖、禁止文件重命名与重构。
- 若包含迁移文件，必须提供有效的 downgrade()。
- 输出仅包含：
  1. 逐文件 unified diff
  2. 本卡最小 Runbook（迁移/启动/验证命令）
  3. 无解释性长文

## Tech & Repo

- Stack: FastAPI + Celery + Postgres + Redis; Next.js skeleton only.
- Modules: collector → filter(HF+rules) → mini-LLM refine → aggregator(event_key) → security scan(GoPlus) → DEX data → notifier(Telegram).
- Target P95: end-to-end ≤ 2 minutes.

## Workflow

### SSOT（默认模式）

- 默认模式下，以 `/docs/STATUS.md` 的 Today 段落为唯一来源。
- 若对话内容与 Today 不一致，Claude 必须输出 `INCONSISTENCY_REPORT`，并生成仅修改 `STATUS.md` 的 diff 提案，停止实现。
- 只有当 Today 标注为 LOCKED 时，才允许进入 Task Card 阶段。

### 步骤

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

### Refiner 约束（DAY6 rules）

- 严格禁止返回裸 `print`，统一使用 `log_json`。
- LLMRefiner 只允许返回经 `RefineModel` 校验后的结构化 JSON，禁止直接拼接字符串。
- 如果 LLM 调用失败，必须走降级路径（fallback 或 rules），禁止返回半成品结果。
- 禁止在成功调用 LLM 后再强制覆盖为 rules 结果。
- 运行过程中发现 JSON schema 校验失败，必须 `log_json(stage="refine.reject", ...)`，不得静默丢弃。

### Security (Day7 rules)

- 禁止默认启用批量扫描（`ENABLE_GOPLUS_SCAN` 必须显式为 true 才能开启）。
- 所有 provider 返回必须经过 `_to_response` 包装，确保 `degrade, cache, stale, summary` 字段完整。
- 统一导入路径：`api.jobs.goplus_scan` 与 `api.scripts.verify_goplus_security`，禁止使用根目录 jobs/ 或 scripts/。
- ENV 必须设置在 **服务容器**（docker-compose 环境）中，而不是 exec 临时进程。
- 所有 Alembic downgrade 必须防御性写法（`IF EXISTS`），避免索引或表不存在时报错。

## 数据库迁移硬约束（必须遵守,DAY7 rules）

- 迁移目录唯一：`api/alembic/versions/`。**禁止**创建或使用 `migrations/versions/`。
- 生成方式：只允许引用由命令 `alembic revision -m "<msg>"` 生成的迁移；**禁止**手写文件或头部变量。
- 版本链：
  - 新迁移的 `revision` 必须是唯一新号；`down_revision` 必须指向当前 `head`。
  - **禁止**复用或猜测 revision 号，**禁止**从注释推断编号。
- 输出 Task Card 时，文件路径一律写 `api/alembic/versions/<revision>_<name>.py`。
- 在验收清单中加入：
  - `alembic show <new_revision>` 必须成功；
  - `alembic upgrade head --sql` 不报错；
  - `alembic downgrade -1 && alembic upgrade head` 必须通过。
