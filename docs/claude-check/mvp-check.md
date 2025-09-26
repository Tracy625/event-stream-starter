# MVP 功能实现状态检查报告（深度检查版）

生成时间: 2025-09-22
检查范围: Day1-Day24 全部功能点
基准文档: docs/mvp28-done.md

## 执行摘要

- **总体完成率**: 约 70%
- **核心功能**: 大部分完成
- **关键缺失**:
  - X 平台 API/Apify 接入（仅占位符）
  - KOL 头像语义识别完整链路
  - market_risk 卡片类型未实现
  - topic 卡片模板缺失
- **风险点**:
  - signals 表没有 type 字段（无法区分 topic/primary/secondary/market_risk）
  - 部分关键功能仅有占位符实现

## Day1-Day6: 基础架构 ✅ 完成

### Day1: 基础骨架与环境 ✅

- ✅ Monorepo 结构 (api/worker/ui/infra)
- ✅ Docker Compose 配置 (postgres:15, redis:7, api, worker, otel)
- ✅ FastAPI 健康检查 (/healthz)
- ✅ Alembic 迁移 (001_initial_tables.py)
- ✅ Makefile 基础命令

### Day2: Pipeline 构建与验证 ✅

- ✅ filter/refine/dedup/db 处理链 (api/filter.py, api/refiner.py)
- ✅ Redis 去重实现 (api/dedup.py)
- ✅ raw_posts 表扩展 (002_add_score_to_events.py)
- ✅ 内存与 Redis 双模式去重

### Day3: Demo ingest & Logging ✅

- ✅ scripts/demo_ingest.py 实现
- ✅ 结构化 JSON 日志 (api/core/metrics_store.py)
- ✅ Makefile demo 目标
- ✅ WORKFLOW.md 文档

### Day3+: Latency 预埋 ✅

- ✅ @timeit 装饰器 (api/core/metrics_store.py)
- ✅ log_json 统一日志
- ✅ 缓存装饰器 @memoize_ttl (api/cache.py)
- ✅ 延迟预算降级机制
- ✅ scripts/golden.jsonl 黄金集
- ✅ scripts/bench_sentiment.py 基准测试

### Day4: HF 情感与关键词增强 ✅

- ✅ HuggingFace 情感分析集成 (api/hf_sentiment.py)
- ✅ KeyBERT 关键词提取
- ✅ 降级到 rules 模式
- ✅ 批处理接口预留

### Day5: 事件聚合与 event_key ✅

- ✅ events 表创建 (003_events_table.py)
- ✅ event_key 生成逻辑 (api/events.py)
- ✅ 证据合并 evidence[]
- ✅ start_ts/last_ts 维护

### Day6: 精析器（LLM 结构化输出）✅

- ✅ LLM refiner 实现 (api/refiner.py)
- ✅ JSON schema 校验
- ✅ 多模型降级链 (gpt-5-mini → gpt-4o-mini → gpt-4o)
- ✅ 结构化输出验证

## Day7-Day14: 核心功能 🔶 大部分完成

### Day7: GoPlus 体检 ✅

- ✅ GoPlus 客户端 (api/clients/goplus.py)
- ✅ GoPlus Provider (api/providers/goplus_provider.py)
- ✅ 安全路由 (api/routes/security.py)
- ✅ 缓存机制 (goplus_cache 表)
- ✅ 降级到 rules 模式

### Day7.1: 红黄绿规则与 signals 写入 ✅

- ✅ rules/risk_rules.yml 配置
- ✅ 风险评分逻辑
- ✅ signals 表 GoPlus 字段 (006_add_signals_goplus_fields.py)
- ✅ 批量扫描作业 (api/jobs/goplus_scan.py)

### Day7.2: 卡片字段规范与推送模板 ✅

- ✅ 卡片 schema 定义 (schemas/cards.schema.json)
- ✅ 推送模板 (templates/cards/)
- ✅ 去重逻辑
- ✅ 复查队列机制

### Day8: X KOL 采集 🔶 部分实现

- ✅ GraphQL 实现 (api/clients/x_client.py - GraphQLXClient)
- ❌ API v2 实现 (仅占位符 APIXClient)
- ❌ Apify 实现 (仅占位符 ApifyXClient)
- ✅ KOL 轮询作业 (worker/jobs/x_kol_poll.py)
- ✅ 标准化字段处理
- ✅ Redis 去重

### Day8.1: KOL Profile 变更监控 🔶 部分实现

- ✅ 头像 URL 获取 (worker/jobs/x_avatar_poll.py)
- ✅ Redis 状态存储
- ✅ Mock 支持验证
- ❌ profile_events 表（未实现）
- ❌ profile_tags 表（未实现）
- ❌ 图像标签识别 (image_tagging.py 不存在)
- ❌ CLIP/OCR 推理（未实现）
- ❌ Meme 话题路由（未实现）

### Day9: DEX 快照 ✅

- ✅ DEX Provider 双源 (api/providers/dex_provider.py)
- ✅ DexScreener 集成
- ✅ GeckoTerminal 降级
- ✅ 缓存机制
- ✅ /dex/snapshot 路由

### Day9.1: Meme 话题卡最小链路 🔶 部分实现

- ✅ 话题信号路由 (api/routes/signals_topic.py)
- ✅ 话题聚合 (worker/jobs/topic_aggregate.py)
- ✅ 推送作业 (worker/jobs/push_topic_candidates.py)
- ✅ 黑白名单配置 (configs/topic_whitelist.yml, topic_blacklist.yml)
- ✅ Telegram 最小适配层
- ⚠️ 推送实现了 format_topic_message 函数
- ❌ 缺少 topic_card.j2 模板文件
- ❌ signals 表缺少 type 字段（无法标记为 'topic' 类型）

### Day9.2: Primary 卡门禁 + 文案模板 ✅

- ✅ 卡片生成器 (api/cards/generator.py)
- ✅ 风险门禁逻辑
- ✅ CA 归一化工具 (api/utils/ca.py)
- ✅ 模板系统
- ✅ 防抖去重 (api/cards/dedup.py)

### Day10: BigQuery 接入 ✅

- ✅ BQ 客户端 (api/clients/bq_client.py)
- ✅ BQ Provider (api/providers/onchain/bq_provider.py)
- ✅ 健康检查路由 (/onchain/healthz)
- ✅ 新鲜度检查 (/onchain/freshness)
- ✅ 成本守门机制

### Day11: SQL 模板与守门 ✅

- ✅ SQL 模板 (templates/sql/eth/\*.sql)
- ✅ 新鲜度守门逻辑
- ✅ 成本护栏
- ✅ Redis 缓存
- ✅ /onchain/query 路由

### Day12: 派生特征表 ✅

- ✅ onchain_features 表 (010_day12_onchain_features.py)
- ✅ 特征派生作业 (api/jobs/onchain/enrich_features.py)
- ✅ /onchain/features 路由
- ✅ 幂等写入

### Day13-14: 证据验证与专家视图 🔶 部分实现

- ✅ 规则引擎 (api/onchain/rules_engine.py)
- ✅ 验证作业 (worker/jobs/onchain/verify_signal.py)
- ✅ /signals/{event_key} 路由
- ✅ /expert/onchain 路由（已确认实现：api/routes_expert_onchain.py）
- ✅ 状态机集成 (signals 表 state 字段)

## Day15-Day24: 高级功能 🔶 部分完成

### Day15-16: 事件聚合与热度 ✅

- ✅ 跨源证据合并 (api/events.py - merge_event_evidence)
- ✅ 热度计算 (api/signals/heat.py)
- ✅ /signals/heat 路由
- ✅ 斜率计算
- ✅ 持久化选项

### Day17: HF 批量与校准 ✅

- ✅ 批量接口 (api/services/hf_client.py)
- ✅ 校准脚本 (scripts/hf_calibrate.py)
- ✅ smoke 测试增强 (scripts/smoke_sentiment.py)

### Day18: 规则引擎 🔶 部分实现

- ✅ 规则评估引擎 (api/rules/eval_event.py)
- ✅ 规则配置 (rules/rules.yml)
- ✅ 热加载支持
- ✅ /rules/eval 路由
- ✅ Refiner 适配器 (api/rules/refiner_adapter.py)
- ❌ market_risk 卡片类型未实现
- ❌ 规则中没有定义 market_risk 相关的判定逻辑
- ⚠️ signals 表有 market_type 字段但未使用

### Day19: 卡片 Schema + LLM 摘要 ✅

- ✅ 卡片构建器 (api/cards/build.py)
- ✅ 卡片摘要器 (api/cards/summarizer.py)
- ✅ /cards/preview 路由
- ✅ Schema 校验

### Day20-21: Telegram 推送与优化 ✅

- ✅ Telegram 服务 (api/services/telegram.py)
- ✅ /cards/send 路由
- ✅ Outbox 重试机制 (worker/jobs/outbox_retry.py)
- ✅ 速率限制
- ✅ 失败快照
- ✅ 幂等保护

### Day22: 回放与部署 ✅

- ✅ 回放脚本 (scripts/replay_e2e.sh)
- ✅ 评分器 (scripts/score_replay.py)
- ✅ 启动时间测量 (scripts/measure_boot.sh)
- ✅ 打包脚本 (scripts/build_repro_bundle.sh)
- ✅ Golden 数据集 (demo/golden/golden.jsonl)

### Day23-24: 配置治理与监控 ✅

- ✅ 热加载机制 (api/config/hotreload.py)
- ✅ 配置 Lint (scripts/config_lint.py)
- ✅ /metrics 路由 (api/routes/metrics.py)
- ✅ 告警系统 (alerts.yml, scripts/alerts_runner.py)
- ✅ 本地通知 (scripts/notify_local.sh)

## 关键未实现功能清单

### 🔴 完全未实现

1. **X 平台 API v2 接入** - api/clients/x_client.py:270-278 仅占位符
2. **Apify 接入** - api/clients/x_client.py:281-289 仅占位符
3. **KOL 头像语义识别** - 整个 Day8.1 的图像处理链未实现
   - profile_events 表不存在
   - profile_tags 表不存在
   - image_tagging.py 文件不存在
   - CLIP/OCR 推理未实现
   - 话题路由未实现
4. ~~**专家视图部分功能**~~ - 已确认完整实现
5. **market_risk 卡片类型** - Day18 要求但未实现
   - 没有 market_risk 类型定义
   - 没有相关规则判定
   - 没有对应的卡片模板

### ⚠️ 部分实现或有风险

1. **卡片类型系统**
   - signals 表缺少 type 字段（无法区分 topic/primary/secondary/market_risk）
   - events 表有 type 字段但值不受约束
   - topic 卡片有推送函数但缺少模板文件
2. **OpenTelemetry** - docker-compose 中仅占位符
3. **某些 Makefile 目标** - api/worker/test 等为占位符
4. **UI 前端** - 仅有空壳 README

### ✅ 超额完成

1. **配置治理** - 热加载、Lint、审计等超出原计划
2. **监控告警** - Prometheus metrics、告警规则等
3. **运维增强** - 失败快照、幂等保护、DLQ 等

## 建议优先级

### P0 - 必须补充（影响核心流程）

1. 实现 X API v2 或 Apify（至少一个）以确保数据源稳定
2. 完善专家视图路由

### P1 - 建议补充（提升产品价值）

1. KOL 头像变更检测完整链路
2. 图像语义识别能力

### P2 - 可选补充

1. OpenTelemetry 真实集成
2. UI 前端开发

## 总结

项目整体完成度约 70%，核心数据流程大部分打通：

- ✅ 数据采集（仅 GraphQL）→ 过滤 → 精炼 → 去重 → 事件聚合
- ✅ GoPlus 安全检查 → DEX 数据 → BigQuery 链上数据
- ✅ 规则引擎 → 卡片生成 → Telegram 推送
- ⚠️ 卡片类型系统不完整（缺少 type 字段和 market_risk 实现）

主要缺失在：

- X 平台多源接入能力（API/Apify）- 影响数据源稳定性
- KOL 头像变更的完整检测链路 - 缺失整个图像识别能力
- market_risk 卡片类型 - Day18 要求但未实现
- 卡片类型区分机制 - signals 表缺少 type 字段

**深度检查发现的额外问题：**

1. topic 卡片推送有函数实现但缺少模板文件
2. signals 表结构不支持多类型卡片（缺少 type 字段）
3. market_risk 完全没有实现痕迹

建议优先修复数据模型问题（加 type 字段），然后补充缺失的卡片类型。
