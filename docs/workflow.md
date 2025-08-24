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

## One-click Demo (Day 3)

Run the demo pipeline to test filter → refine → dedup → db flow:

```bash
make demo
```

### Expected Output

Console shows:

- Pipeline stages: `[FILTER]`, `[REFINE]`, `[DEDUP]`, `[DB]`
- JSON logs: `[JSON]` prefixed lines with structured data
- Dedup hits: At least one `"dedup":"hit"` in JSON logs (sample 3 duplicates sample 1)
- Summary: Total posts processed, duplicates found, unique events

Example JSON log line:

```json
[JSON] {"stage":"pipeline","author":"whale_copy","passed":true,"event_key":"6d32cd68f1e02117","dedup":"hit","db":{"raw_post_id":19,"event_upserted":false},"ts":"2025-08-21T08:13:03.653058+00:00"}
```

### Verification

Check database after demo:

```bash
# Count raw posts (increases with each run)
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "SELECT count(*) FROM raw_posts;"

# View latest events (unique by event_key)
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "SELECT event_key, type, score FROM events ORDER BY last_ts DESC LIMIT 3;"
```

### Demo Data

The script processes 3 hardcoded crypto posts:

1. `$PEPE` token launch with contract address
2. `$ARB` airdrop announcement
3. Duplicate of post 1 (different author, same text) → triggers dedup hit

## One-click Demo (Day 3+)

Enhanced demo with timing metrics and latency budget support:

```bash
make demo
```

### Timing Metrics

JSON logs now include pipeline timing in milliseconds:

- `t_filter_ms`: Filter + sentiment analysis time
- `t_refine_ms`: Text refinement and event key generation time
- `t_dedup_ms`: Deduplication check time
- `t_db_ms`: Database operations time
- `t_total_ms`: Total pipeline execution time

Example JSON with timing:

```json
[JSON] {"stage":"pipeline","author":"whale_copy","passed":true,"event_key":"6d32cd68f1e02117","dedup":"hit","db":{"raw_post_id":43,"event_upserted":false},"ts":"2025-08-21T10:07:28.739616+00:00","t_filter_ms":0,"t_refine_ms":0,"t_dedup_ms":0,"t_db_ms":1,"t_total_ms":1,"backend_filter":"rules","backend_refine":"rules"}
```

### Latency Budget Degradation

Set environment variables to trigger backend degradation:

```bash
# Force degradation when filter exceeds 1ms
LATENCY_BUDGET_MS_FILTER=1 docker compose -f infra/docker-compose.yml exec -T \
  -e LATENCY_BUDGET_MS_FILTER=1 api python scripts/demo_ingest.py
```

When budget exceeded, logs show degradation:

```json
[JSON] {"stage":"degradation","phase":"filter","exceeded_ms":3,"budget_ms":1,"backend":"rules"}
```

### Verification

```bash
# Check raw_posts increment
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "SELECT count(*) FROM raw_posts;"

# Verify events last_ts updates on duplicate
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c "SELECT event_key, last_ts FROM events ORDER BY last_ts DESC LIMIT 3;"

# Grep for timing metrics
make demo 2>&1 | grep -E "t_total_ms"
```

## Rules

- Only STATUS.md defines Today tasks
- Claude must never implement tasks not in STATUS.md
- Each Task = one cycle: Card → Approve → Execute → Test

### Refiner 流程

1. 触发条件：`candidate_score ≥ THRESH` 或 `evidence_count ≥ 2`。
2. 调用 Refiner：
   - backend=llm → 调用 OpenAI SDK（模型与超时/重试/预算从环境变量读取）。
   - backend=rules → 使用 heuristic 规则生成 summary。
3. 校验结果：
   - 必须符合 JSON Schema，否则直接 reject 并记录日志。
4. 降级策略：
   - LLM 出错 → fallback 到 rules 或备用模型。
   - 超时/5xx/限流 → 按配置执行重试或 degrade。
5. 验收检查：
   - 随机样本 ≥80% 返回合法 JSON。
   - 平均延迟 < 预算。
