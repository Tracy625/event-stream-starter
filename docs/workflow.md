# WORKFLOW — Mixed-Mode Kickoff

## Daily Routine

1. Update `/docs/STATUS.md`

   - Move yesterday's Today → Done·
   - Write new Today + Acceptance (2–3 items max)

2. In Claude Code, run `/clear`

3. Paste kickoff prompt (from /docs/KICKOFF.md)

4. Claude will:

   - Read BRIEF + STATUS
   - Confirm today's Acceptance
   - Decompose Today into Task Cards

5. You review Task Cards

   - Approve or adjust
   - Then say: "Approved. Proceed with Task [X]"

6. Claude implements Task [X]
   - Outputs plan (≤5 bullets), diffs, run/test commands
   - You run tests & commit

## Critical Invariants (DB & Runtime)
- Migrations：新环境或变更后，**先跑** `make migrate`，再做任何 DB 验收。
- SQL 片段：统一 `from sqlalchemy import text as sa_text`，禁止裸 `text(...)`（避免与列名冲突）。
- Events 时间列：仅有 `start_ts`、`last_ts`。查询按 `last_ts` 排序，代码中不得引用 `ts` 列。
- API 健康检查：`/healthz` 不触发任何 DB 初始化；`api/main.py` 顶层不允许 DB 导入。

## One‑click Demo & Migrations
- `make migrate`：在 api 容器内执行 `alembic upgrade head`
- `make revision m="msg"`：生成新的 Alembic 版本
- `make demo`：在容器内执行 `scripts/demo_ingest.py`，串联 filter → refine → dedup → db（纯函数，无外网）
- 使用 heredoc/管道时加 `-T` 关闭 TTY，避免 "the input device is not a TTY"

## Rules

- Only STATUS.md defines Today tasks
- Claude must never implement tasks not in STATUS.md
- Each Task = one cycle: Card → Approve → Execute → Test
