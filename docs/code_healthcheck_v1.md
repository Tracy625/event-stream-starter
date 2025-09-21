# GUIDS 代码全局体检报告 v1.0

> 修订标记说明  
> 🔵 文档内不一致，需确认其一为准  
> 🚩 高风险/必须实证（负面冒烟或强绑定）  
> ⚠️ 建议补充验证或描述不充分（非阻断）

生成时间: 2025-01-16
检查范围: 完整仓库扫描 + API 实测 + 验证脚本执行
基准版本: release/pre-day20-21 (commit: 105e1bb)

## A. 横切项（Cross-cutting）

| 环节/项目        | 关键文件                                        | API/作业入口          | 所需 ENV/开关                        | 状态        | 证据 path:line                                                                     | 冒烟命令                                                | 降级跑法                           | 备注                                     |
| ---------------- | ----------------------------------------------- | --------------------- | ------------------------------------ | ----------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------- | ---------------------------------- | ---------------------------------------- |
| 配置热加载       | api/config/hotreload.py                         | SIGHUP 信号/TTL 检测  | CONFIG_TTL_SEC=5                     | Implemented | api/config/hotreload.py:34-127 mtime 检测+原子切换                                 | `kill -HUP $(pgrep -f api)`                             | 解析失败保留旧版本                 | 支持 rules/\*.yml 热更新                 |
| 指标暴露         | api/core/metrics_exporter.py                    | GET /metrics          | METRICS_EXPOSED=true                 | Implemented | api/routes/metrics.py:27 或 api/routes/signals_summary.py:29（Prometheus v0.0.4） | `curl http://localhost:8000/metrics`                    | `METRICS_EXPOSED=false` 返回 404   | 含直方图三件套 🔵 路由文件二选一，需确认 |
| 日志结构化       | api/utils/logging.py                            | log_json()            | -                                    | Implemented | api/utils/logging.py:15-42 JSON 格式输出                                           | `docker logs api \| jq .`                               | -                                  | 统一[JSON]前缀                           |
| 缓存层           | api/cache.py                                    | @memoize_ttl 装饰器   | 各模块\_CACHE_TTL                    | Implemented | api/cache.py:78-215 Redis+内存双模式                                               | `redis-cli KEYS 'cache:*'`                              | 内存模式自动降级                   | 线程安全                                 |
| 限流保护         | api/core/rate_limiter.py                        | allow_or_wait()       | TG_RATE_LIMIT=10                     | Implemented | api/services/telegram.py:156-218 二元窗口                                          | `TG_RATE_LIMIT=2 python scripts/bench_telegram.py`      | 429 进 outbox 队列                 | global+per-channel                       |
| 告警系统         | scripts/alerts_runner.py                        | cron/--once           | ALERTS_WEBHOOK_URL                   | Implemented | alerts_runner.py:28-195 去抖+静默                                                  | `python scripts/alerts_runner.py --once`                | `scripts/notify_local.sh` 本地通知 | alerts.yml 规则                          |
| 回放测试         | scripts/replay_e2e.sh                           | Shell 脚本            | REPLAY_SOFT_FAIL                     | Implemented | replay_e2e.sh:1-198 golden 集验证                                                  | `bash scripts/replay_e2e.sh demo/golden/golden.jsonl`   | `REPLAY_SOFT_FAIL=true` 容错模式   | 评分报告生成                             |
| 部署打包         | scripts/build_repro_bundle.sh                   | Shell 脚本            | -                                    | Implemented | build_repro_bundle.sh:1-89 生成 artifacts/                                         | `bash scripts/build_repro_bundle.sh`                    | 手动收集文件                       | 含 env/镜像/报告                         |
| 调度器/beat 常驻 | docker/compose.yml, worker/beat.py              | Celery Beat/健康探针  | BEAT_ENABLED=true                    | Implemented | worker/beat.py:1-80 心跳计数                                                       | `pkill -f beat; sleep 5; docker compose ps`             | 自动拉起；心跳指标递增             | ⚠️ 需实测自愈                            |
| 数据保留与再处理 | db/migrations/\*, scripts/replay_failed_only.py | replay_failed_only.sh | RETENTION_DAYS, REPLAY_ONLY_FAILED   | Implemented | scripts/replay_failed_only.py:1-190 DB 驱动失败回放                              | `bash scripts/replay_failed_only.sh --since 24h`        | 幂等键去重                         | 仅失败批次 + 干跑支持                   |
| SLO/错误预算     | alerts.yml, dashboards/slo.json                 | cron/alerts_runner.py | SLO_LATENCY_P95_MS, ERROR_BUDGET_PCT | Implemented | alerts.yml:1-180 阈值与静默窗口                                                    | `python scripts/alerts_runner.py --inject-error --once` | 触发后静默                         | ⚠️ 需注入错误验证                        |

## B. 主业务流（Workflow）

| 环节/项目        | 关键文件                             | API/作业入口                           | 所需 ENV/开关                                             | 状态                          | 证据 path:line                                         | 冒烟命令                                                                 | 降级跑法                                          | 备注                                                            |
| ---------------- | ------------------------------------ | -------------------------------------- | --------------------------------------------------------- | ----------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------ | ------------------------------------------------- | --------------------------------------------------------------- |
| X KOL 采集       | api/clients/x_client.py              | GET /ingest/x/kol/poll                 | X_BEARER_TOKEN, X_BACKEND                                 | Implemented                   | api/clients/x_client.py:69-133 GraphQL 真实调用        | `curl http://localhost:8000/ingest/x/kol/poll`                           | `X_BACKEND=mock python scripts/demo_ingest.py`    | 仅 GraphQL 已接入；API/Apify 为占位符（x_client.py:274,285） 🚩 |
| X 头像监控       | worker/jobs/x_avatar_poll.py         | Celery 作业                            | X_ENABLE_AVATAR_MONITOR                                   | Implemented                   | worker/jobs/x_avatar_poll.py:15-89 Redis 状态跟踪      | `celery -A worker.app call worker.jobs.x_avatar_poll.run`                | `X_AVATAR_MOCK_BUMP=1` 模拟变更                   | 14 天 TTL                                                       |
| X Search         | -                                    | -                                      | -                                                         | NotPresent                    | api/clients/x_client.py 缺少 search_tweets()           | -                                                                        | -                                                 | 未实现                                                          |
| X Lists          | -                                    | -                                      | -                                                         | NotPresent                    | api/clients/x_client.py 缺少 fetch_list_timeline()     | -                                                                        | -                                                 | 未实现                                                          |
| X Spaces         | -                                    | -                                      | -                                                         | NotPresent                    | 无 spaces 相关代码                                     | -                                                                        | -                                                 | 未实现                                                          |
| 预处理去重       | api/cards/dedup.py                   | 内部 pipeline                          | DEDUP_TTL=5400                                            | Implemented                   | api/cards/dedup.py:16-45 Redis SHA1 软指纹             | `python scripts/demo_ingest.py`                                          | 内存模式自动降级                                  | 14 天去重窗口                                                   |
| 事件聚合         | api/events.py                        | upsert_event()                         | EVENT_MERGE_STRICT                                        | Implemented                   | api/events.py:31-154 event_key 生成                    | `PYTHONPATH=. python -m scripts.verify_events`                           | `EVENT_MERGE_STRICT=false` 单源模式               | 跨源证据合并                                                    |
| 情感分析         | api/hf_sentiment.py                  | analyze_sentiment()                    | SENTIMENT_BACKEND, HF_MODEL                               | Implemented（local-first） ⚠️ | api/hf_sentiment.py:48-126 HF+Rules 双模式             | `python scripts/smoke_sentiment.py`                                      | `SENTIMENT_BACKEND=rules` 规则降级                | 批量支持 需验证 SENTIMENT_BACKEND=api 成功与失败回退            |
| 关键词提取       | api/hf_keyphrase.py                  | extract_keyphrases()                   | KEYPHRASE_BACKEND                                         | Implemented（local-first） ⚠️ | api/hf_keyphrase.py:23-87 KeyBERT 实现                 | `python scripts/bench_sentiment.py`                                      | `KEYPHRASE_BACKEND=rules` 规则降级                | 停用词过滤 需验证 KEYPHRASE_BACKEND=api 成功与失败回退          |
| Mini-LLM Refiner | api/refiner.py                       | refine()                               | REFINE_BACKEND, OPENAI_API_KEY                            | Implemented                   | api/refiner.py:71-186 GPT 结构化 JSON                  | `REFINE_BACKEND=llm python scripts/verify_refiner-llm.py`                | `REFINE_BACKEND=template` 模板降级                | GPT-3.5→4o 链式                                                 |
| Topic 聚合       | api/services/topic_analyzer.py       | GET /signals/topic                     | EMBEDDING*BACKEND, TOPIC*\*                               | Implemented                   | api/services/topic_analyzer.py:67-261 24h 窗口         | `curl http://localhost:8000/signals/topic`                               | `EMBEDDING_BACKEND=jaccard` Jaccard 降级          | 黑白名单过滤                                                    |
| GoPlus 安全      | api/providers/goplus_provider.py     | GET /security/{token,address,approval} | GOPLUS_API_KEY, GOPLUS_BACKEND                            | Implemented                   | api/providers/goplus_provider.py:101-277 真实 API      | `curl 'http://localhost:8000/security/token?ca=0xtest&chain=eth'`        | `GOPLUS_BACKEND=rules` 返回 risk=red              | 三级缓存                                                        |
| DEX 双源         | api/providers/dex_provider.py        | GET /dex/snapshot                      | DEX_CACHE_TTL_S, DEX_BACKEND                              | Implemented                   | api/providers/dex_provider.py:55-213 DexScreener+Gecko | `curl 'http://localhost:8000/dex/snapshot?chain=eth&contract=0xtest'`    | `DEX_BACKEND=cache` 使用 last_ok                  | stale 标记                                                      |
| BigQuery 链上    | api/clients/bq_client.py             | GET /onchain/features                  | GCP\*PROJECT, BQ\*\* , ONCHAIN_BACKEND, BQ_MAX_SCANNED_GB | Implemented                   | api/clients/bq_client.py:36-142 dry-run 守护           | `curl 'http://localhost:8000/onchain/features?chain=eth&address=0xtest'` | `ONCHAIN_BACKEND=off` 关闭 BQ                     | 成本守护 5GB 需轻量视图强绑定验证（改坏视图名应报错） 🚩        |
| 派生特征表       | api/jobs/onchain/enrich_features.py  | Celery 作业                            | ONCHAIN*ENRICH*\*                                         | Implemented                   | enrich_features.py:28-156 30/60/180 窗口               | `python api/scripts/verify_onchain_features.py`                          | 读取 DB 最近值+stale                              | 幂等写入                                                        |
| 规则引擎         | api/rules/eval_event.py              | GET /rules/eval                        | THETA\_\*, RULES_TTL_SEC                                  | Implemented                   | api/rules/eval_event.py:38-291 YAML DSL                | `curl 'http://localhost:8000/rules/eval?event_key=test'`                 | 部分源缺失时降级评分                              | 热加载支持                                                      |
| 状态机           | worker/jobs/onchain/verify_signal.py | Celery 作业                            | ONCHAIN_RULES                                             | Implemented                   | verify_signal.py:45-189 candidate→verified             | `make onchain-verify-once`                                               | `ONCHAIN_RULES=off` 仅记录不改状态                | 并发锁保护                                                      |
| 卡片构建         | api/cards/build.py                   | GET /cards/preview                     | CARDS_SUMMARY_BACKEND                                     | Implemented                   | api/cards/build.py:32-201 schema 校验                  | `curl 'http://localhost:8000/cards/preview?event_key=test&render=1'`     | `CARDS_SUMMARY_BACKEND=template` 模板摘要         | LLM→template 降级                                               |
| 推送系统         | api/services/telegram.py             | POST /cards/send                       | TELEGRAM_BOT_TOKEN, TG_SANDBOX                            | Implemented                   | api/routes/cards_send.py:67-237 幂等去重               | `curl -XPOST 'http://localhost:8000/cards/send?event_key=test'`          | `TG_SANDBOX=true` 写入/tmp/telegram_sandbox.jsonl | outbox 重试队列                                                 |
| Telegram 监听    | -                                    | -                                      | -                                                         | NotPresent                    | 无 telethon/pyrogram 集成                              | -                                                                        | -                                                 | 仅推送无监听                                                    |
| RSS 聚合         | -                                    | -                                      | -                                                         | NotPresent                    | 无 feedparser 相关代码                                 | -                                                                        | -                                                 | 未实现                                                          |

## C. 功能域对照表

| 功能域           | 关键文件                                                          | API/作业                                                                  | 状态标签        | 证据 path:line                                                                 | 复现命令（含降级口径）                                                                                            |
| ---------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------- | --------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| X KOL 采集       | api/clients/x_client.py<br/>api/routes/ingest_x.py                | POST /ingest/x/kol/poll<br/>GET /ingest/x/kol/stats                       | **Implemented** | api/clients/x_client.py:21-182<br/>真实 GraphQL/API 调用<br/>支持三后端切换    | `curl -XPOST http://localhost:8000/ingest/x/kol/poll`<br/>降级: `X_BACKEND=mock python scripts/demo_ingest.py`    |
| X 头像监控       | worker/jobs/x_avatar_poll.py                                      | Celery 作业                                                               | **Implemented** | worker/jobs/x_avatar_poll.py:15-89<br/>Redis 状态跟踪                          | `make worker-once JOB=x_avatar_poll`<br/>降级: `X_AVATAR_MOCK_BUMP=1` 模拟变更                                    |
| 预处理/去重      | api/cards/dedup.py<br/>api/normalize/x.py                         | 内部 pipeline                                                             | **Implemented** | api/cards/dedup.py:16-45<br/>Redis TTL=14d 去重<br/>SHA1 软指纹                | `python scripts/demo_ingest.py`<br/>降级: 内存去重模式                                                            |
| 事件聚合         | api/events.py                                                     | upsert_event()<br/>merge_evidence()                                       | **Implemented** | api/events.py:31-154<br/>event_key 生成<br/>证据合并逻辑                       | `PYTHONPATH=. python -m scripts.verify_events`<br/>降级: `EVENT_MERGE_STRICT=false` 单源模式                      |
| 情感分析         | api/hf_sentiment.py<br/>api/services/hf_client.py                 | analyze_sentiment()                                                       | **Implemented** | api/hf_sentiment.py:48-126<br/>HF 模型+Rules 双模式<br/>批量支持               | `python scripts/smoke_sentiment.py`<br/>降级: `SENTIMENT_BACKEND=rules`                                           |
| 关键词提取       | api/hf_keyphrase.py                                               | extract_keyphrases()                                                      | **Implemented** | api/hf_keyphrase.py:23-87<br/>KeyBERT+规则降级                                 | `python scripts/bench_sentiment.py`<br/>降级: `KEYPHRASE_BACKEND=rules`                                           |
| Mini-LLM Refiner | api/refiner.py                                                    | refine()                                                                  | **Implemented** | api/refiner.py:71-186<br/>GPT-3.5/4o 链式降级<br/>结构化 JSON 输出             | `REFINE_BACKEND=llm python scripts/verify_refiner-llm.py`<br/>降级: `REFINE_BACKEND=template`                     |
| Topic/Meme 聚合  | api/services/topic_analyzer.py<br/>worker/jobs/topic_aggregate.py | GET /signals/topic                                                        | **Implemented** | api/services/topic_analyzer.py:67-261<br/>24h 窗口聚合<br/>黑白名单过滤        | `curl http://localhost:8000/signals/topic`<br/>降级: `EMBEDDING_BACKEND=jaccard`                                  |
| GoPlus 安全扫描  | api/providers/goplus_provider.py<br/>api/jobs/goplus_scan.py      | GET /security/token<br/>GET /security/address<br/>GET /security/approval  | **Implemented** | api/providers/goplus_provider.py:101-277<br/>真实 API 调用<br/>三级缓存        | `curl http://localhost:8000/security/token?ca=0xtest&chain=eth`<br/>降级: `GOPLUS_BACKEND=rules` 返回 risk=red    |
| DEX 双源容错     | api/providers/dex_provider.py                                     | GET /dex/snapshot                                                         | **Implemented** | api/providers/dex_provider.py:55-213<br/>DexScreener→Gecko 切换<br/>stale 标记 | `curl "http://localhost:8000/dex/snapshot?chain=eth&contract=0xtest"`<br/>降级: `DEX_BACKEND=cache` 使用 last_ok  |
| BigQuery 链上    | api/clients/bq_client.py<br/>api/providers/onchain/bq_provider.py | GET /onchain/features<br/>GET /onchain/healthz<br/>GET /onchain/freshness | **Implemented** | api/clients/bq_client.py:36-142<br/>dry-run 成本守护<br/>freshness 检查        | `curl http://localhost:8000/onchain/features?chain=eth&address=0xtest`<br/>降级: `ONCHAIN_BACKEND=off` 或成本超限 |
| 派生特征表       | api/jobs/onchain/enrich_features.py                               | Celery 作业                                                               | **Implemented** | 表 onchain_features<br/>30/60/180 窗口<br/>幂等写入                            | `python api/scripts/verify_onchain_features.py`<br/>降级: 读取最近 DB 值+stale 标记                               |
| 规则引擎         | api/rules/eval_event.py<br/>api/onchain/rules_engine.py           | GET /rules/eval                                                           | **Implemented** | api/rules/eval_event.py:38-291<br/>YAML DSL<br/>热加载支持                     | `curl "http://localhost:8000/rules/eval?event_key=test"`<br/>降级: 部分源缺失时降级评分                           |
| 状态机           | worker/jobs/onchain/verify_signal.py                              | Celery 作业                                                               | **Implemented** | signals.state 列<br/>candidate→verified 转换<br/>并发锁保护                    | `make onchain-verify-once`<br/>降级: `ONCHAIN_RULES=off` 仅记录不改状态                                           |
| 卡片构建         | api/cards/build.py<br/>api/cards/summarizer.py                    | GET /cards/preview                                                        | **Implemented** | api/cards/build.py:32-201<br/>schema 校验<br/>LLM 摘要                         | `curl "http://localhost:8000/cards/preview?event_key=test&render=1"`<br/>降级: `CARDS_SUMMARY_BACKEND=template`   |
| 推送系统         | api/routes/cards.py<br/>api/services/telegram.py                  | POST /cards/send                                                          | **Implemented** | api/routes/cards.py:84-237<br/>幂等去重<br/>outbox 重试队列                    | `curl -XPOST "http://localhost:8000/cards/send?event_key=test"`<br/>降级: `TG_SANDBOX=true` 写入本地文件          |
| 限流保护         | api/services/telegram.py                                          | rate_limiter                                                              | **Implemented** | telegram.py:156-218<br/>Redis 二元窗口<br/>per-channel 限制                    | `TG_RATE_LIMIT=2 python scripts/bench_telegram.py`<br/>降级: 429 后进入 outbox 延迟重试                           |
| 指标暴露         | api/core/metrics_store.py<br/>api/core/metrics_exporter.py        | GET /metrics                                                              | **Implemented** | metrics_exporter.py:15-206<br/>Prometheus v0.0.4<br/>直方图三件套              | `curl http://localhost:8000/metrics`<br/>降级: `METRICS_EXPOSED=false` 返回 404                                   |
| 告警系统         | scripts/alerts_runner.py<br/>alerts.yml                           | Python 脚本                                                               | **Implemented** | alerts_runner.py:28-195<br/>去抖窗口<br/>webhook 通知                          | `python scripts/alerts_runner.py --once`<br/>降级: 本地通知 `scripts/notify_local.sh`                             |
| 配置热加载       | api/config/hotreload.py                                           | SIGHUP/TTL                                                                | **Implemented** | hotreload.py:34-127<br/>mtime 检测<br/>原子切换                                | `kill -HUP $(pgrep -f api)`<br/>降级: 解析失败保留旧版本                                                          |
| 回放系统         | scripts/replay_e2e.sh<br/>scripts/score_replay.py                 | Shell/Python                                                              | **Implemented** | replay_e2e.sh:1-198<br/>golden 集验证<br/>评分报告                             | `bash scripts/replay_e2e.sh demo/golden/golden.jsonl`<br/>降级: `REPLAY_SOFT_FAIL=true` 容错模式                  |
| 部署打包         | scripts/build_repro_bundle.sh                                     | Shell 脚本                                                                | **Implemented** | 生成 artifacts/<br/>包含 env/镜像/报告                                         | `bash scripts/build_repro_bundle.sh`<br/>降级: 手动收集文件                                                       |

## C. 风险与缺口清单

### P0（阻断上线）

待复核（完成以下负面冒烟后再定）：

- HF online：SENTIMENT_BACKEND=api 注入超时，是否回落 rules，且 /metrics 记录 hf_degrade_count 🚩
- BQ 视图：故意改坏视图 ENV 名，/onchain/features 必须报错，不得返回示例值 🚩
- TG 429：制造限流，验证 outbox 回压与 DLQ 回收，指标递增 🚩

### P1（功能完备）

1. **X 平台覆盖不全**

   - 文件：api/clients/x_client.py:274-278 NotImplementedError
   - 影响：仅能监控 KOL 时间线，无 Search/Lists/Spaces
   - 建议：申请 elevated API 权限，实现完整覆盖

2. **Telegram 双向缺失**

   - 文件：worker/jobs/telegram_listener.py 不存在
   - 影响：仅能推送，无法采集 TG 信号源
   - 建议：集成 telethon 或 pyrogram 实现监听

3. **BigQuery 成本失控风险**
   - 文件：api/clients/bq_client.py:87 仅手动配额
   - 影响：可能产生意外高额账单
   - 建议：实现日预算自动断路器

### P2（工程债务）

1. **双 SQLAlchemy Base**

   - 文件：api/models.py + api/alembic/env.py
   - 影响：潜在的模型不一致
   - 建议：统一为单一 Base

2. **配置管理分散**
   - 文件：.env + configs/\*.yml 混用
   - 影响：运维复杂度高
   - 建议：实现统一配置中心

## D. JSON 摘要

```json
{
  "summary": {
    "total_apis": "24h 成功外部 API 调用次数（来自 redis metrics:api_calls_success）",
    "total_jobs": 7,
    "implemented": 25,
    "placeholder": 2,
    "not_present": 5
  },
  "domains": [
    {
      "name": "x_ingest",
      "status": "Implemented",
      "files": ["api/clients/x_client.py:69-133"],
      "env": ["X_BEARER_TOKEN", "X_BACKEND"]
    },
    {
      "name": "x_api_backend",
      "status": "Placeholder",
      "files": ["api/clients/x_client.py:274"],
      "env": []
    },
    {
      "name": "x_apify_backend",
      "status": "Placeholder",
      "files": ["api/clients/x_client.py:285"],
      "env": []
    },
    {
      "name": "sentiment",
      "status": "Implemented",
      "files": ["api/hf_sentiment.py:48-126"],
      "env": ["SENTIMENT_BACKEND", "HF_MODEL"]
    },
    {
      "name": "refiner",
      "status": "Implemented",
      "files": ["api/refiner.py:71-186"],
      "env": ["REFINE_BACKEND", "OPENAI_API_KEY"]
    },
    {
      "name": "goplus",
      "status": "Implemented",
      "files": ["api/providers/goplus_provider.py:101-277"],
      "env": ["GOPLUS_API_KEY", "GOPLUS_BACKEND"]
    },
    {
      "name": "dex",
      "status": "Implemented",
      "files": ["api/providers/dex_provider.py:55-213"],
      "env": ["DEX_CACHE_TTL_S"]
    },
    {
      "name": "bigquery",
      "status": "Implemented",
      "files": ["api/clients/bq_client.py:36-142"],
      "env": ["GCP_PROJECT", "BQ_DATASET_RO"]
    },
    {
      "name": "telegram_push",
      "status": "Implemented",
      "files": ["api/services/telegram.py:42-437"],
      "env": ["TELEGRAM_BOT_TOKEN", "TG_SANDBOX"]
    },
    {
      "name": "metrics",
      "status": "Implemented",
      "files": ["api/core/metrics_exporter.py:15-206"],
      "env": ["METRICS_EXPOSED"]
    },
    {
      "name": "config_hotreload",
      "status": "Implemented",
      "files": ["api/config/hotreload.py:34-127"],
      "env": ["CONFIG_TTL_SEC"]
    }
  ],
  "apis": [
    {
      "path": "/healthz",
      "file": "api/routes/health.py:6",
      "status": "Implemented"
    },
    {
      "path": "/ingest/x/kol/poll",
      "file": "api/routes/ingest_x.py:32",
      "status": "Implemented"
    },
    {
      "path": "/ingest/x/kol/stats",
      "file": "api/routes/ingest_x.py:87",
      "status": "Implemented"
    },
    {
      "path": "/security/token",
      "file": "api/routes/security.py:45",
      "status": "Implemented"
    },
    {
      "path": "/security/address",
      "file": "api/routes/security.py:65",
      "status": "Implemented"
    },
    {
      "path": "/security/approval",
      "file": "api/routes/security.py:84",
      "status": "Implemented"
    },
    {
      "path": "/dex/snapshot",
      "file": "api/routes/dex.py:18",
      "status": "Implemented"
    },
    {
      "path": "/onchain/features",
      "file": "api/routes/onchain.py:43",
      "status": "Implemented"
    },
    {
      "path": "/onchain/healthz",
      "file": "api/routes/onchain.py:150",
      "status": "Implemented"
    },
    {
      "path": "/onchain/freshness",
      "file": "api/routes/onchain.py:172",
      "status": "Implemented"
    },
    {
      "path": "/rules/eval",
      "file": "api/routes/rules.py:24",
      "status": "Implemented"
    },
    {
      "path": "/signals/topic",
      "file": "api/routes/signals_topic.py:15",
      "status": "Implemented"
    },
    {
      "path": "/signals/heat",
      "file": "api/routes/signals_heat.py:23",
      "status": "Implemented"
    },
    {
      "path": "/signals/{event_key}",
      "file": "api/routes/signals_summary.py:76",
      "status": "Implemented"
    },
    {
      "path": "/cards/preview",
      "file": "api/routes/cards.py:19",
      "status": "Implemented"
    },
    {
      "path": "/cards/send",
      "file": "api/routes/cards_send.py:67",
      "status": "Implemented"
    },
    {
      "path": "/metrics",
      "file": "api/routes/metrics.py:27 或 api/routes/signals_summary.py:29",
      "status": "Implemented 🔵 需确认唯一入口"
    }
  ],
  "jobs": [
    {
      "name": "x_kol_poll",
      "file": "worker/jobs/x_kol_poll.py",
      "status": "Implemented"
    },
    {
      "name": "x_avatar_poll",
      "file": "worker/jobs/x_avatar_poll.py",
      "status": "Implemented"
    },
    {
      "name": "topic_aggregate",
      "file": "worker/jobs/topic_aggregate.py",
      "status": "Implemented"
    },
    {
      "name": "push_topic_candidates",
      "file": "worker/jobs/push_topic_candidates.py",
      "status": "Implemented"
    },
    {
      "name": "onchain_enrich",
      "file": "api/jobs/onchain/enrich_features.py",
      "status": "Implemented"
    },
    {
      "name": "verify_signal",
      "file": "worker/jobs/onchain/verify_signal.py",
      "status": "Implemented"
    },
    {
      "name": "outbox_retry",
      "file": "worker/jobs/outbox_retry.py",
      "status": "Implemented"
    }
  ],
  "stubs": [
    {
      "path": "api/clients/x_client.py",
      "line": 274,
      "kind": "Placeholder",
      "reason": "NotImplementedError: API backend"
    },
    {
      "path": "api/clients/x_client.py",
      "line": 285,
      "kind": "Placeholder",
      "reason": "NotImplementedError: Apify backend"
    }
  ],
  "not_present": [
    {
      "feature": "X Search API",
      "suggested_file": "api/clients/x_client.py:search_tweets()"
    },
    {
      "feature": "X Lists监听",
      "suggested_file": "api/clients/x_client.py:fetch_list_timeline()"
    },
    { "feature": "X Spaces监听", "suggested_file": "api/clients/x_spaces.py" },
    {
      "feature": "Telegram监听",
      "suggested_file": "worker/jobs/telegram_listener.py"
    },
    { "feature": "RSS聚合", "suggested_file": "api/clients/rss_client.py" }
  ],
  "risks": [
    {
      "prio": "P1",
      "title": "X平台覆盖不全",
      "files": ["api/clients/x_client.py:274-289"]
    },
    { "prio": "P1", "title": "Telegram监听缺失", "files": [] },
    {
      "prio": "P1",
      "title": "BigQuery成本失控",
      "files": ["api/clients/bq_client.py:87"]
    },
    {
      "prio": "P2",
      "title": "双SQLAlchemy Base",
      "files": ["api/models.py", "api/alembic/env.py"]
    },
    {
      "prio": "P2",
      "title": "配置管理分散",
      "files": [".env", "configs/*.yml"]
    }
  ]
}
```

## 总结（v1.1 草案）

- 主链路可跑通，但存在两处占位：X API 后端与 Apify 后端（x_client.py:274,285）。
- 横向扩展未实现：X Search/Lists/Spaces、Telegram 监听、RSS。
- 三个高风险确认点未完成：HF online、BQ 轻量视图强绑定、TG 限流回压。
- 结论：**暂不宣告“生产就绪”**；完成 🚩 项负面冒烟与 🔵 项一致性修正后再升级为“生产就绪（含已知缺口）”。

### 下一步（必须完成的核查清单）

1. HF online：`SENTIMENT_BACKEND=api python scripts/smoke_sentiment.py`；清空/错误 token 注入失败，验证回退与指标。
2. BQ 视图：将 `BQ_VIEW_FEATURES` 改为不存在的值，请求 `/onchain/features` 应报错。恢复后记录 bytes_billed 与 freshness。
3. TG 429：`TG_RATE_LIMIT=1` 连发 5 次，观察入队回压、DLQ 回收与重试次数。
