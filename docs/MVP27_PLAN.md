## Day0 — 基础架构

- 初始化 monorepo 目录结构
- 设置 API / Worker / UI / Infra 四大模块
- 接好 Postgres / Redis
- 准备 Alembic 迁移脚手架
- 验收：`docker compose up` 一次跑通，API `/healthz` 返回 200

---

## Day1 — 基础功能

- 新建 `raw_posts`、`events`、`signals` 三张表
- API 健康检查
- Docker Compose 服务可跑
- Alembic 迁移到版本 `001`
- 验收：表结构和 API 均可用

---

## Day2 — Pipeline 构建与验证（替代原“X 采集器”）

- 实现 `filter/refine/dedup/db` 四步处理链
- Redis 去重 & 内存去重双模式
- 扩展 `raw_posts` 表字段：`is_candidate`、`sentiment`、`keywords`
- Alembic 迁移到版本 `002`
- 验收：`make demo` 能跑 pipeline 并成功写入 raw_posts；Redis/内存去重都可用；API `/healthz` 返回 200
- ⚠ 说明：原计划的“X API 采集器”任务推迟到 Day8 执行

---

## Day3 — Demo ingest & Logging（替代原“规则与关键词粗筛”）

- 新建 `scripts/demo_ingest.py`，支持 JSONL 输入，跑完整 pipeline
- 输出结构化 JSON 日志（含 filter/refine/dedup/db 各 stage）
- Makefile 新增 `demo` 目标
- 更新 `WORKFLOW.md`，记录 demo 流程
- 验收：`python scripts/demo_ingest.py` 能跑通 demo；日志输出包含各 stage 耗时与结果；Makefile `demo` 可用
- ⚠ 说明：剩余语言检测/黑名单将在 Day8–Day9 补齐

---

## Day3+ — Latency 预埋

- 增加延迟观测、缓存、批处理入口
- HF 模块隔离、降级开关
- 基准脚本与黄金集
- 验收：能 bench 出指标，降级逻辑生效，接口签名稳定

---

## Day4 — HF 情感与关键词增强

- 集成 HF 英文情感模型（cardiffnlp）
- KeyBERT 抽关键词；VADER 打分兜底
- 写回 raw_posts 扩展列
- 验收：10 条样本生成稳定情绪和关键词，单批 ≤2s

---

## Day5 — 事件聚合与 event_key

- 归一化实体+关键词+时间窗口生成 event_key
- 合并多条证据
- 写入 events 表，维护 start_ts/last_ts
- 验收：相同传闻只产生 1 个事件，证据追加不重复

---

## Day6 — 精析器（小号 LLM，结构化输出）

- 高置信候选 → mini LLM 精析，输出严格 JSON
- JSON Schema 校验，不合格丢弃
- 验收：≥80% 产出合法 JSON，延时可控

---

## Day7 — GoPlus 体检（安全底座）

- Token/Address/Approval 三端点通，带缓存/退避/熔断
- 新增 goplus_cache 表
- 验收：3 个垃圾盘判红，缓存后二查 ≤200ms
- 降级：SECURITY_BACKEND=rules，degrade:true

---

## Day7.1 — 红黄绿规则与 signals 写入

- 新建 `rules/risk_rules.yml`
- 体检结果写入 signals，评分器 goplus_score
- 默认规则：honeypot 红 / 税率 >10% 红 / LP 锁<30 天 黄
- 验收：垃圾盘判红，未知项进 unknown_flags

---

## Day7.2 — 卡片字段规范与推送模板

- 产出 pushcard.schema.json
- 渲染模板（Telegram/内部 UI）
- 验收：字段映射完整，可推送调试卡

---

## Day8 — X KOL 采集

- 轮询 5–10 个 KOL，2 分钟一次
- 入库去重，写 raw_posts
- 验收：落库 ≥35，去重命中>10%，至少 1 条含 token_ca 或 symbol

---

## Day8.1 — KOL Profile 变更与头像语义标签

- 监控头像/简介变更，下载头像，pHash 去重
- CLIP/SigLIP + OCR → 话题标签
- 写入 profile_events、profile_tags
- 路由至 topic_router，产出 meme 候选
- 验收：青蛙头像 → topic_entities=["pepe"] → 推出候选卡；风景图不触发

---

## Day9 — DEX 快照（双源容错）

- DexScreener 优先，GeckoTerminal 兜底
- 返回价格/流动性/FDV/OHLC
- 验收：curl /dex/snapshot?contract=... 返回完整字段，降级标记 stale:true

---

## Day9.1 — Meme 话题卡最小链路

- 扩展 event_type: topic|primary|secondary|market_risk
- is_memeable_topic 路由（KeyBERT+mini LLM）
- 建立 topic_id 聚类，24h 窗口，一小时一次推送
- 推送话题卡（不贴 CA，文案“未落地为币，谨防仿冒”）
- 验收：/signals/topic 返回关键词与热度；TG 出现 meme 卡
- 补充：固定 schema，topic_id 合并规则，黑白名单，digest 上限，降级策略

---

## Day9.2 — Primary 卡门禁 + 文案模板

- 流程：候选 → GoPlus 体检 → 红黄绿标记
- 扩展 risk_rules.yml
- 卡片模板改造：risk_note、verify_path、data_as_of、legal_note
- 二级卡必须显示 rumor/confirmed 与验证路线
- 验收：垃圾盘推 red 卡；文案均是候选/验证路径
- 补充：GoPlus source 字段，CA 归一化，rules_fired[]，防抖（状态变化才二次推）

---

## Day10 — BigQuery 项目与 Provider 接入

- 配置 GCP 凭据与 ENV
- 封装 bq_client.py，dry-run 守门，cost_guard
- /onchain/healthz 与 /onchain/freshness
- 验收：dry-run 与 query 可用，超限安全失败

---

## Day11 — SQL 模板与守门 + 成本护栏

- active_addrs、token_transfers、top_holders 三模板
- 新鲜度守门：SLO 超时降级候选
- dry-run 超预算拒绝执行
- Redis 缓存 60–120 秒
- 验收：模板返回 data_as_of；触发守门与成本护栏

---

## Day12 — 派生特征表 onchain_features

- 建表 onchain_features + signals 增加占位字段
- enrich_features.py 写入 30/60/180 窗口特征
- API /onchain/features 返回最新记录
- 验收：特征记录幂等写入；失败返回 stale:true

---

## Day13 — 证据块验证与状态机接入（S0→S2）

- 新增 rules/onchain.yml 阈值
- verify_signal.py：候选 →verified/downgraded/withdrawn
- 更新 signals.state, onchain_asof_ts, confidence
- 验收：候选在 5 分钟内升级或保持候选并标 insufficient_evidence

---

## Day14 — 专家视图 / 演示入口

- /expert/onchain?address=... 返回 24h/7d 活跃度曲线 + top10 饼图
- 限流 5/min，缓存 60–300 秒
- 验收：3–8 分钟内返回，BQ 离线时返回 stale:true

---

## Day15 — 事件聚合跨源升级

- events 跨源合并，固定 event_key 不变
- 验收：同一事件同时包含 X/DEX/GoPlus 证据；event_key 重放一致

---

## Day16 — 热度快照与斜率

- 按 token/CA 计算 10m/30m/recent 斜率、环比
- 写入 signals
- 验收：curl /signals/heat 返回斜率与趋势

---

## Day17 — HF 批量与阈值校准

- HF 批量接口，校准阈值，回灌报告
- 验收：回灌 100 样本输出 precision/recall/F1

---

## Day18 — 规则引擎 + 极简建议器

- 热度+DEX+GoPlus+情绪 → observe/caution/opportunity
- rules.yml 可热加载
- 验收：curl /rules/eval 返回 level 与 reasons[3]

---

## Day19 — 卡片 Schema + LLM 摘要

- 定版 cards.schema.json
- LLM 仅产 summary、risk_note
- 验收：/cards/preview 校验通过；LLM 超时用模板摘要

---

## Day20 — Telegram 推送（这时补全重试队列、批量推送、绑定讨论组、/cards/send、失败入队等，day9.1 做了最小推送）

- 推送卡片到频道，绑定讨论组
- 一小时同 event_key 去重
- 验收：curl /cards/send 推送 5 张卡，失败入重试队列

---

## Day21 — 端到端延迟与退化调优

- 目标：E2E P95 ≤ 2 分钟
- 指标：pipeline_latency_ms, degrade_ratio
- 验收：跑 50 事件，P95 ≤ 120s，退化占比 <10%

---

## Day22 — 回放与部署

- 新环境 30 分钟拉起，回放 golden.jsonl
- 验收：沙盒频道见卡；回放 10 条命中率 ≥80%

---

## Day23 — 配置与治理

- rules.yml 热加载
- KOL/黑白名单/阈值配置化
- 验收：改阈值 1 分钟内生效；config_lint.py 全绿

---

## Day24 — 观测面与告警

- /metrics 暴露 Prom 格式
- TG 失败重试告警
- 验收：人为打断外部源，退化率上升并告警

---

## Day25 — 文档与交付打包

- RUN_NOTES.md 汇总；cards.schema.json 定版
- /docs/E2E.md；release notes
- 验收：新人 5 分钟跑出一张卡片；所有 curl/make 命令可用
