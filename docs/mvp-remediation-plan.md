# MVP 修补与收口计划（实情版）

版本：2025-10-01

依据：代码实查 + mvp-incomplete-features-analysis.md 审阅标注 + 近两日联调记录

优先级分级：
- P0 立即项（不收口会影响链路稳定/一致性）
- P1 短期项（1–2 个迭代内完成，降噪/降险）
- P2 中期项（可并行推进，优化体验/可观测）

---

## P0｜立即项

### P0-1 收口 signals.type，去除对 market_type 的运行时依赖
- 背景：已引入 `signals.type`（014），Topic 扫描仍依赖 `market_type='topic'`，我们已在 topic 扫描“写入/更新”时补写 `type='topic'` 并加 UPSERT，但“读取/判断”仍用 `market_type`。
- 影响：双字段并存增加心智负担，未来删除 `market_type` 前必须先完成读取路径迁移。
- 动作（代码）：
  - 修改 `worker/jobs/topic_signal_scan.py`：
    - JOIN 与 WHERE 从 `s.market_type='topic'` 改为 `s.type='topic'`
    - 读取已有 signal 时不再引用 `market_type`
  - 审计全仓是否还读写 `market_type`
    - 命令：`rg -n "market_type\b" -S`
- 验证：
  - 跑一次扫描：`docker compose -f infra/docker-compose.yml exec -T worker celery -A worker.app call worker.jobs.topic_signal_scan.scan_topic_signals`
  - 看日志：`docker compose -f infra/docker-compose.yml logs worker --since 10m | egrep "topic\.signal\.scan\.(start|done|error)"`
  - 看库（应见新写入/更新的 topic 记录）：
    - `docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT type,state,COUNT(*) cnt,MAX(ts) last_ts FROM signals GROUP BY 1,2 ORDER BY 2,1;"`
- 备注：完成一到两轮上线平稳后再做 P1-4 的删除迁移。

### P0-2（已完成）Alembic 并发索引与幂等
- 状态：已在 015 迁移内以 `CONCURRENTLY IF NOT EXISTS` 落库：
  - `uniq_signals_event_type (event_key,type)`、`idx_signals_ts`、`idx_signals_event_key`、`uniq_outbox_event_channel (event_key,channel_id)`
- 验证命令：
  - `docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT indexname FROM pg_indexes WHERE tablename='signals' AND indexname IN ('uniq_signals_event_type','idx_signals_ts','idx_signals_event_key');"`
  - `docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT indexname FROM pg_indexes WHERE tablename='push_outbox' AND indexname='uniq_outbox_event_channel';"`

### P0-3（已完成）Worker 监听与推送开关一致
- 状态：worker 监听 `celery,cards,signals,aggregation,outbox,x_polls`，`TELEGRAM_MODE=real`（api/worker 一致）。
- 验证命令：
  - `docker compose -f infra/docker-compose.yml exec -T worker celery -A worker.app inspect active_queues`
  - `docker compose -f infra/docker-compose.yml exec -T worker sh -lc 'echo TELEGRAM_MODE=$TELEGRAM_MODE'`

---

## P1｜短期项

### P1-1 调整测试与文档，统一使用 `type`
- 目标：移除测试中对 `market_type` 的读写；文档（查询样例）同步改为 `type`。
- 影响文件：
  - `tests/test_topic_integration.py`、`tests/test_rules_eval.py` 等
  - `docs/RUN_NOTES.md`、`docs/SCHEMA.md` 中的查询样例
- 验证：测试通过、文档查询不再出现 `market_type`。

### P1-2 Outbox 入队幂等适配（配合唯一索引）
- 背景：已加 `uniq_outbox_event_channel`，若重复入队可能触发唯一冲突。
- 动作：在 `api/db/repositories/outbox_repo.py:enqueue` 中：
  - 使用 SQLAlchemy Core `insert(...).on_conflict_do_nothing()`（PG 专用），或捕获 `IntegrityError` 后返回已存在行 id。
- 验证：构造重复入队用例，确保不抛异常、不重复发送。

### P1-3 统一 `push_topic_candidates` 的 Celery 上下文（可选增强）
- 背景：文件内自建 Celery 应用，当前仅被 `topic_aggregate` 同步函数方式调用。
- 动作：改为复用 `worker.app`（或保持函数方式，移除冗余 Celery 壳）。
- 验证：`topic.aggregate.* / topic.push.*` 日志不回归。

### P1-4 迁移 016：删除 `signals.market_type`（延后执行）
- 先完成 P0-1 与 P1-1 并观察一期；随后新增迁移删除该列。
- 验证：`\d signals` 不再显示该列；全量搜索 `market_type` 无生产引用。

### P1-5 /ingest/x/replay 明确定位
- 选项 A：接入处理流；选项 B：标记测试专用并在文档中说明。
- 验证：
  - A：回放后可见 raw_posts/events 变化
  - B：OpenAPI/README 标注清晰

### P1-6 代码卫生与忽略规则
- 清理备份：`api/keyphrases.py.bak.*`
- `.gitignore` 增加：`__pycache__/`、`*.pyc`、`*.bak*`

### P1-7 配置与文档统一
- `.env.example`：标注 `X_BACKENDS` 优先于 `X_BACKEND`；GoPlus 鉴权变量的优先级说明；HF 与 Refiner 的开关说明。

### P1-8 GoPlus 缓存使用打点
- 为 `api/providers/goplus_provider.py` 增加命中/落库统计日志或 Prom 指标，便于判断“是否充分利用”。

---

## P2｜中期项

### P2-1 LLM Refiner 的落库决策
- 现状：Refiner 可用，`RULES_REFINER=on` 时参与规则理由文本优化；`events.refined_*` 未写入。
- 选项：
  - A：实现落库 → 在 `events` 写 refined_* 字段（注意索引与行宽）
  - B：移除 refined_* 列（迁移与文档同步）

### P2-2 观测性增强
- 增加以下指标：
  - `guids_signals_in_total`、`guids_cards_out_total`、`guids_outbox_done_total`
  - `guids_worker_queue_backlog{queue=...}`（已有示例，可延伸）

### P2-3 Chaos 验证脚本
- 杀一个 worker 验证 visibility_timeout 回收；重复投同一 event_key 验证 UPSERT/唯一索引；mock↔real 切换验证 outbox 状态机。

---

## 附：关键验证命令汇总
- 队列与派发
  - `docker compose -f infra/docker-compose.yml exec -T worker celery -A worker.app inspect active_queues`
  - `docker compose -f infra/docker-compose.yml logs worker --since 10m | egrep "topic\.signal\.scan|secondary\.proxy|cards\.worker"`
- 数据与推送
  - `docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT type,state,COUNT(*) cnt,MAX(ts) last_ts FROM signals GROUP BY 1,2 ORDER BY 2,1;"`
  - `docker compose -f infra/docker-compose.yml logs worker --since 30m | egrep "telegram\.sent|telegram\.api_error"`
- Apify 与采集
  - `docker compose -f infra/docker-compose.yml logs worker --since 2h | egrep "x\.(poll\.skip|fetch|normalize|dedup|persist)"`
  - 强制一轮：
    - `docker compose -f infra/docker-compose.yml exec -T redis redis-cli DEL x:job:kol:lock`
    - `docker compose -f infra/docker-compose.yml exec -T worker python -c "from worker.jobs.x_kol_poll import run_once; import json; print(json.dumps(run_once()))"`

---

## 变更追踪（已完成）
- 015 并发索引迁移（CONCURRENTLY IF NOT EXISTS）
- worker 监听队列 + acks/visibility 对齐
- topic_signal_scan：写入/更新补 `type='topic'` + UPSERT 并去重键（短期兼容期）
- Apify 频率：60 分钟/次 × 2 条；run-sync 低成本模式
- 推送模式：`TELEGRAM_MODE=real`（api/worker 一致）

注：本文档作为“修补路线图”，建议在每次上线后对照“附：关键验证命令”做一次巡检，并将完成项勾除或迁移到“变更追踪”。

