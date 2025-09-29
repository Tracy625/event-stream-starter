MVP28 天计划（修订版 v2.3）
Day0. 前置约定（不问你要啥，直接定好）

范围只做：
固定 KOL 采集 → 初筛（HF 小模型+规则）→ 事件聚合（event_key）→ 精析（小号 LLM，结构化输出）→ 合约体检（GoPlus）→ DEX 数据（DexScreener/GeckoTerminal）→ 信号与 Telegram 推送
明确不做： 自动交易、多源扩展（TG 群/Reddit）、自研 K 线、复杂前端

技术栈与结构
• Monorepo: /api (FastAPI) /worker (Celery) /ui (Next.js, 先放空壳) /infra (compose+otel)
• 存储：Postgres（主库）、Redis（队列/缓存）
• 外部：X API、GoPlus、DexScreener/GeckoTerminal、Telegram Bot
• Claude 规则：CLAUDE.md 英文条件规则版（你已经要过了）+ 启动命令加 --dangerously-skip-permissions

三张核心表（最小必需字段）
• raw_posts(id, source, author, text, ts, urls[], token_ca?, symbol?)
• events(event_key, type, summary, evidence[], impacted_assets[], start_ts, last_ts, heat_10m, heat_30m)
• signals(event_key, market_type, advice_tag, confidence, goplus_risk, goplus_tax?, lp_lock?, dex_liquidity?, dex_volume_1h?, ts)

验收总指标
• 端到端 P95 延迟 ≤ 2 分钟（KOL 发帖到 Bot 卡片）
• 高置信事件卡片字段齐全且结构合法
• 三个历史已知垃圾盘样本能被体检标红
• 同一 event_key 一小时内不重复推送

Day1 基础骨架与环境

目标：仓库与 compose 能跑，API/Worker/DB/Redis 全通
任务 1. 初始化 monorepo；创建基础目录与 pyproject.toml、package.json 2. docker-compose: postgres:15、redis:7、api、worker、otel（占位） 3. FastAPI /healthz，Celery beat/worker 心跳任务 4. Alembic 迁移三张表

Claude 提示词
“Create a monorepo with api(FastAPI), worker(Celery), ui(Next.js skeleton), infra(docker-compose). Add health endpoints, Celery ping task, Alembic migrations for 3 tables defined here: [schema]. Provide docker-compose and Makefile targets: make up, make down, make logs.”
验收
• make up 一次跑起，/healthz 返回 200；celery ping 返回 pong

Day2 ｜ Pipeline 构建与验证（替代原“X 采集器”）

目标
实现基础处理流水线，支持过滤、精炼、去重、落库；为后续接入外部数据源打基础。

任务 1. 实现 filter/refine/dedup/db 四步处理链。 2. Redis 去重 & 内存去重双模式。 3. 扩展 raw_posts 表字段：is_candidate、sentiment、keywords。 4. Alembic 迁移到版本 002。 5. 验证：insert_raw_post 正常，去重逻辑生效。

验收
• make demo 能跑 pipeline 并成功写入 raw_posts。
• Redis/内存去重都可用。
• API /healthz 返回 200，容器 healthy。

⚠ 说明：原计划的“X API 采集器”任务推迟到 Day8 执行。

⸻

Day3 ｜ Demo ingest & Logging（替代原“规则与关键词粗筛”）

目标
提供 demo 级别的 pipeline 入口与结构化日志输出，用于展示和验证 Day2 pipeline。

任务 1. 新建 scripts/demo_ingest.py，支持 JSONL 输入，跑完整 pipeline。 2. 输出结构化 JSON 日志（含 filter/refine/dedup/db 各 stage）。 3. Makefile 新增 demo 目标。 4. 更新 WORKFLOW.md，记录 demo 流程。

验收
• python scripts/demo_ingest.py 能跑通 demo。
• 日志输出包含各 stage 耗时与结果。
• Makefile demo 可用。

⚠ 说明：原计划的“规则与关键词粗筛”逻辑已部分在 Day2 的 filter 中实现，剩余语言检测/黑名单将在 Day8–Day9 补齐。

D3+ Latency 预埋
优先级定义：P0=必须；P1=强烈建议；P2=锦上添花。
P0 — 观测与降级（必做）

1. 统一计时与结构化日志
   • 新增 /api/metrics.py：
   • @timeit(stage:str) 装饰器，记录毫秒耗时。
   • log_json(stage:str, \*\*kv) 输出单行 JSON（含 backend, ms, event_key 可选）。
   • 修改现有管线调用点（filter/refine/dedup/db 写在 demo 脚本里即可），加 @timeit 与 log_json(...)。
   • 验收：make demo 后，docker compose ... logs | grep '\"ms\":' 能看到 t_filter_ms, t_refine_ms, t_dedup_ms, t_db_ms, t_total_ms。
2. 后端开关与强制降级
   • .env.example 增加并被读取：
   • SENTIMENT_BACKEND=rules|hf（默认 rules）
   • HF_MODEL=cardiffnlp/twitter-roberta-base-sentiment-latest
   • HF_DEVICE=cpu
   • KEYPHRASE_BACKEND=off|hf（默认 off）
   • LATENCY_BUDGET_MS_FILTER=400、LATENCY_BUDGET_MS_REFINE=400、LATENCY_BUDGET_MS_TOTAL=120000
   • 在 scripts/demo_ingest.py 的总管线里加入 超预算降级：
   • 若 SENTIMENT_BACKEND=hf 且最近 N 次平均或 P95 超 LATENCY_BUDGET_MS_FILTER/REFINE，自动回落到 rules（只改运行期开关，不改代码）。
   • 验收：手动调小预算值，看到日志打印“降级生效”，并记录 backend="rules"。
   P0 — 可回滚（必做）
3. 实现隔离
   • 约束：HF 相关代码仅放在 /api/hf_sentiment.py、/api/keyphrases.py，调用方只认统一接口：
   • analyze_sentiment(text)->(label, score)（/api/filter.py 内部路由）
   • extract_keyphrases(text)->list[str]（默认返回空列表）
   • 验收：切换环境变量即可在 rules 与 hf 之间切换；/api/filter.py 对外签名完全不变。
   P1 — 缓存与批处理（建议做）
4. 轻量缓存
   • 新增 /api/cache.py：
   • memoize_ttl(seconds:int=300) 简单内存缓存装饰器（key=函数名+文本 sha1）。
   • 给 analyze_sentiment 增加缓存包装（hf 时收益明显）。
   • 验收：同一输入重复调用，日志显示第二次耗时明显降低，并打印 cache_hit=true。
5. 批处理入口
   • 在 /api/hf_sentiment.py 里，pipeline 封装 predict_batch(texts:list[str], batch_size:int=8)，单条调用复用到批处理。
   • demo 仍然单条喂，但留批处理 API 给后面真实采集用。
   • 验收：临时在 scripts/bench_sentiment.py 用 10 条样本跑一遍，打印实际 batch 大小与平均耗时。
   P1 — 基线与基准（建议做）
6. 黄金集与基准脚本
   • 新增 scripts/golden.jsonl（10 条固定英文推文样本，手动挑，包含正负面和中性）。
   • 新增 scripts/bench_sentiment.py：
   • 分别用 rules 与 hf（若可用）跑 golden.jsonl，输出：
   • avg_ms, p95_ms, agreement_ratio（两后端标签一致率）
   • Makefile 增加：
   • bench-sentiment: docker compose -f infra/docker-compose.yml exec -T api python scripts/bench_sentiment.py
   • 验收：成功打印三项指标；当 hf 不可用时只跑 rules 并给出提示。
   P2 — 文档与守则（锦上添花）
7. 文档与仓库守则更新
   • CLAUDE.md 追加：
   • “延迟 KPI 与降级规则”：必须遵守 LATENCY*BUDGET*\*，超预算自动回落 rules。
   • “接口稳定”：不得改 analyze_sentiment/extract_keyphrases 对外签名。
   • “HF 模块隔离”：仅在 /api/hf_sentiment.py、/api/keyphrases.py。
   • WORKFLOW.md 增加 “Benchmark & Degrade” 小节：
   • make bench-sentiment、如何读 JSONL 指标、如何手动切换 backend。
   • 验收：文档存在且命令可跑。
   交付物清单（Day3+ 完成后应看到）
   • 新：/api/metrics.py、/api/cache.py
   • 改：/scripts/demo_ingest.py（打点+降级）、/api/filter.py（保持接口，内部路由）、.env.example（新变量）
   • 新（可选 P1）：/scripts/golden.jsonl、/scripts/bench_sentiment.py
   • Makefile：新增 bench-sentiment
   • 文档：CLAUDE.md、WORKFLOW.md 更新

⸻
优先级与重要性
• P0（必做，阻断 Day4 风险）：计时与结构化日志、开关与降级、HF 隔离模块。
• P1（强烈建议，半天内值回票价）：缓存、批处理、基准脚本与黄金集。
• P2（可延后）：文档完善。
Day4 HF 情感与关键词增强

目标：引入 HF 模型提升可用性与可读性
任务 1. 集成 cardiffnlp/...-twitter-roberta-... 英文情感模型，缓存权重 2. KeyBERT 抽 3–5 个关键词；VADER 打分兜底 3. 将情绪、关键词、得分写回 raw_posts 扩展列

Claude 提示词

“Integrate Hugging Face sentiment model and KeyBERT. For candidate posts, compute sentiment label/score and top keywords, then persist to raw_posts extra fields. Add local caching.”

验收
• 对 10 条样本生成稳定的情绪与关键词，耗时可接受（单批 ≤2s）

Day5 事件聚合与 event_key

目标：把重复传闻合并成“事件”
任务 1. event_key 生成：按归一化实体（符号/CA）+ 主题关键词 + 时间窗口 2. 合并证据：evidence[] 放来源链接与 post_id 3. 写 events，维护 start_ts/last_ts 与 heat 指标占位

Claude 提示词

“Implement event aggregator: group candidate posts into events by (asset, topic keywords, time window). Create deterministic event_key, merge evidence list, update start_ts/last_ts.”

验收
• 相同传闻只产生 1 个事件，新增证据追加不重复

⸻

Day6 精析器（小号 LLM，结构化输出）

目标：对“高置信候选”出结构化摘要与字段
任务 1. 触发条件：候选打分 ≥ 阈值或 evidence 数 ≥ 2 2. 使用 mini LLM（便宜型号）提示词产出严格 JSON：{type, summary<=80, impacted_assets[], reasons[], confidence} 3. JSON schema 校验，不合格丢弃，日志记录

Claude 提示词

“Add a ‘refine’ step using a small LLM. Given merged evidence, output strict JSON (type, 80-char summary, impacted_assets, reasons, confidence). Validate against JSON schema, drop invalid.”

验收
• 10 条中 ≥8 条能返回合法 JSON，平均延时可控（<800ms/条，视模型而定）

⸻

好，既然 Day0–Day6 你已经走完了，我帮你把 Day7–Day15 融合版排期表列出来。融合思路是：
• 主干：采用 MVP15_PLAN.md 的依赖顺序（保证闭环合理、里程碑对）。
• 细节：借用 MVP15 天计划.docx 的工单风格（Claude Prompt 可执行、每天有验收标准）。
• 裁剪：参考 项目总览.docx 的取舍（砍掉多源/自动交易，聚焦闭环

Day7 ｜ GoPlus 体检（新增，安全底座）
• 目标：Token/Address/Approval 三端点通，带缓存/退避/熔断。
• 产物：clients/goplus.py、providers/goplus_provider.py、routes/security.py、alembic 新增 goplus_cache。
• 复用：Day3+ timeit/cache。
• 验收：
curl /security/token?chain_id=1&address=0xa0b8... 返回 honeypot/税率等；冷 P95 ≤800ms，热 P95 ≤200ms。
• 降级/回滚：ENV SECURITY_BACKEND=rules 返回本地规则；缓存命中即返回、打 degrade:true。
Day7.1 ｜红黄绿规则与 signals 写入
• 新增 rules/risk_rules.yml（环境可覆盖），把规则正式化
• Provider 集成评分器：goplus_score.py（或合进 provider）
• jobs/goplus_scan.py 开关式写库：把标准化字段 + 评分写入 signals
• 默认规则集（可改）：
• HONEYPOT_RED=true
• RISK_TAX_RED=10（买卖税任一 >10% → red）
• RISK_LP_YELLOW_DAYS=30（LP 锁 <30 天 → yellow）
• 评分顺序：honeypot red > tax red > lp yellow > else green；未知项进 unknown_flags[]，不降级
• 验收：3 个垃圾盘判红、缓存后二查 ≤200ms、降级时 risk=unknown + degrade:true

Day7.2 ｜卡片字段规范与推送模板
• 依据 MVP20 的卡片规范，产出 pushcard.schema.json 和渲染模板（Telegram/内部 UI）
• 字段映射：goplus_risk、buy/sell_tax、lp_lock_days、honeypot、notes[]、evidence.goplus_raw.summary、cache/degrade/stale
• 加一个“复查队列”策略（高热地址定期回扫）

Day8 ｜ X KOL 采集（新增，接 Day2 pipeline）
• 目标：5–10 个 KOL，2 分钟轮询，入库去重，规范化文本/URL/合约，并保证能被 pipeline 消费。
• 产物：
• ingestor_x/kol_timeline.py
• ENV: X_BEARER,X_KOL_IDS,X_POLL_SEC
• 更新 pipeline：保证写入的 raw_posts 字段齐全（text, author, ts, urls[], token_ca?, symbol?）
• 复用：Day2 的 filter/refine/dedup/db 链路。
• 验收：
• make ingest-x-once 拉 50 条，落库 ≥35，去重命中>10%，失败可回放。
• 从落库结果中能看到至少 1 条包含 token_ca 或 symbol 的记录。
• 降级：API 限额 → 延长 POLL_SEC，只取最新 20 条；缓存最近一次拉取结果。

Day8.1 ｜ KOL Profile 变更与头像语义标签（可投产版）

目标
把“纯图片/头像/简介梗”转化为可用的 meme 话题候选信号，并安全接入你现有的 topic→ 落地检测 →primary/secondary 状态机。要求：
• 本地推理，低成本、低耦合、可回滚。
• 不做身份识别，不贴 CA；文案统一“候选/假设 + 验证路径”。

产出（Artifacts）
• 路由与任务
• ingestor_x/profile_watch.py：轮询 KOL 资料变更并落库、下载头像
• workers/image_tagging.py：CLIP/SigLIP + OCR + pHash 去重，产出标签与实体
• router/topic_router.py：将头像标签合并社交回声，生成 topic 候选
• 资源与配置
• resources/image_tags.yml：图像 zero-shot 标签词表
• resources/meme_map.yml：标签/OCR→ 话题实体映射（含别名/正则）
• 数据结构
• 新表：profile_events（资料变更原始事件）
• 新表：profile_tags（头像推理结果）
• 复用/扩展：signals（新增 type=topic 的候选）
• API 与工具
• GET /events/profile?user_id=...
• GET /debug/profile_tags?user_id=...&limit=5
• POST /simulate/profile_change（测试钩子，可选）
• 推送
• 沙盒频道：type=topic 的 meme 候选卡
• 可选：type=profile_change 调试卡（开关控制）

环境变量与限额

X_PROFILE_POLL_SEC=300 # 轮询间隔（秒）
PROFILE_CONCURRENCY=2 # 并发下载/推理
PROFILE_RATE_LIMIT=60 # 全局限流（每分钟）
AVATAR_BUCKET_PATH=/data/avatars
AVATAR_MAX_MB=2 # 超限不下载
PHASH_MAX_DIST=4 # 图片去重阈值（汉明距离）
PROFILE_TAGGING=on # 头像推理开关
DEBUG_PROFILE_CARD=off # 调试卡片开关
MEDIA_FEED_URLS=... # RSS/新闻源（可留空）
MEDIA_POLL_SEC=300
DAILY_PUSH_CAP=50 # 每日推送上限（超限合并 digest）

模块与文件结构

/ingestor_x/profile_watch.py
/workers/image_tagging.py
/router/topic_router.py
/resources/image_tags.yml
/resources/meme_map.yml
/api/profile.py # /events/profile, /debug/profile_tags

数据模型与表结构

1. profile_events
   CREATE TABLE profile_events (
   id BIGSERIAL PRIMARY KEY,
   user_id TEXT NOT NULL,
   type TEXT NOT NULL CHECK (type IN ('profile_change')),
   old_name TEXT, old_description TEXT, old_image_url TEXT,
   new_name TEXT, new_description TEXT, new_image_url TEXT,
   image_local_path TEXT, image_phash TEXT,
   ts TIMESTAMPTZ NOT NULL DEFAULT now(),
   UNIQUE (user_id, image_phash, ts)
   );

2. profile_tags

CREATE TABLE profile_tags (
id BIGSERIAL PRIMARY KEY,
user_id TEXT NOT NULL,
image_phash TEXT NOT NULL,
tags JSONB NOT NULL, -- ["frog","meme","text"]
ocr_text TEXT,
topic_entities JSONB, -- ["pepe"]
confidence NUMERIC NOT NULL, -- 0.0~1.0
low_confidence BOOLEAN NOT NULL DEFAULT false,
sources JSONB NOT NULL, -- ["clip","ocr","social_echo"]
nsfw BOOLEAN NOT NULL DEFAULT false,
person_like BOOLEAN NOT NULL DEFAULT false,
ts TIMESTAMPTZ NOT NULL DEFAULT now(),
UNIQUE (user_id, image_phash)
);

3. signals 扩展（如未有）
   • 增加 type ENUM('topic','primary','secondary','market_risk')
   • 允许 topic 信号 evidence_block 为空
   • 统一 event_key/topic_id 字段

处理流程（端到端）

步骤 A ｜ KOL 资料轮询（profile_watch.py） 1. 使用 X v2 API：GET /2/users/:id 拉取 name/description/profile_image_url 2. 差异比对，命中变更才落 profile_events 3. 下载 profile_image_url 到 AVATAR_BUCKET_PATH/{user_id}/{ts}.jpg
• 先 HEAD 检查大小，> AVATAR_MAX_MB 则跳过并记录 oversize:true 4. 计算 pHash，与最近一次对比，dist ≤ PHASH_MAX_DIST 视为同图，跳过 5. 写入 profile_events（带 image_phash 与 image_local_path） 6. 发送作业到 image_tagging 队列

步骤 B ｜头像本地推理（image_tagging.py） 1. CLIP/SigLIP zero-shot
• 从 resources/image_tags.yml 载入标签词表
• 计算图像与标签文本相似度，softmax 得到 conf_clip_top1 2. OCR（PaddleOCR/Tesseract）
• 提取文本 → 小写、去标点
• 与 meme_map.yml 别名表匹配，命中则 conf_ocr=1.0 否则 0 3. NSFW/person-like 粗分类
• 轻量 NSFW 模型命中 → 降权或丢弃
• 人像/非人像布尔标记 person_like 4. 社交回声（可选加权）
• 15 分钟窗口内转评/回复中与 topic_entities 相同关键词出现次数 m：
conf_echo = min(1.0, log(1+m)/log(10)) 5. 合成置信度（固定可复现）

confidence = 0.6*conf_clip_top1 + 0.3*conf_ocr + 0.1\*conf_echo
low_confidence = (0.6 <= confidence < 0.75) 6. 阈值与缓存
• confidence < 0.6 → 仅写 profile_tags，不进入候选
• 相同 (user_id,image_phash) 7 天内不重复推理 7. 写入 profile_tags，并调用 topic_router 进行路由

示例输出（落 profile_tags 与传给路由的 payload 完全一致）：

{
"type": "profile_change_tagging",
"user_id": "123456",
"image_phash": "phash:ab12cd34",
"tags": ["frog","meme","text"],
"ocr_text": "PEPE 2025",
"topic_entities": ["pepe"],
"confidence": 0.76,
"low_confidence": false,
"sources": ["clip","ocr","social_echo"],
"nsfw": false,
"person_like": false,
"ts": "2025-08-30T12:34:56Z"
}

步骤 C ｜生成 meme 话题候选（topic_router.py） 1. 命中条件：topic_entities 非空 且 confidence ≥ 0.6 2. 生成/合并 topic_id：24h 滑动窗口相似度聚类（关键词重合度 ≥ 阈值 或 embedding 相似度 ≥ 阈值） 3. 去重与限频：同 topic_id 1 小时仅推一次；DAILY_PUSH_CAP 保护 4. 写入 signals(type=topic)，字段：
• topic_id, topic_entities, tags, confidence, sources, social_echo_boost
• verdict_note="头像/简介变更触发；未落地为币，谨防仿冒" 5. 推送卡片（TG 沙盒）：不贴 CA，文案统一“候选/假设 + 验证路径” 6. 进入既有状态机：等待“落地检测”（新池/新合约）转 primary/secondary 流

规则与阈值（写死）
• PHASH_MAX_DIST=4 同图判定
• confidence 计算公式固定，如上
• 触发阈值：<0.6 不产候选；0.6~0.75 产候选但标 low_confidence:true
• 限流：PROFILE_RATE_LIMIT=60/min 全局；同 user_id 60 分钟只产 1 条候选
• 推送封顶：每日 DAILY_PUSH_CAP，超限合并 digest

卡片与路由集成
Topic 候选卡（meme）

必含字段：
type=topic, topic_id, topic_entities, confidence, sources,
risk_note="未落地为币，谨防仿冒", verify_path="新池/新合约 → GoPlus/BQ",
ts, event_key

文案模板（示例）：
【热点候选】头像/简介变更触发：pepe（confidence 0.76，clip+ocr）
验证路径：观察新池/新合约，如落地 → 体检/画像。未落地为币，谨防仿冒。
调试卡（可关）
type=profile_change，仅在 DEBUG_PROFILE_CARD=on 时推送，避免污染频道。

API / CLI
• GET /events/profile?user_id=...&limit=20
返回最近 profile_change 事件（含 pHash、下载路径、时间戳）
• GET /debug/profile_tags?user_id=...&limit=5
返回最近头像推理结果（tags、topic_entities、confidence）
• POST /simulate/profile_change（可选）
注入一条伪变更事件（用于验收）

⸻

日志与监控
• 结构化日志键：
• profile.poll.ok, profile.download.bytes, profile.phash.dist, profile.tagging.ms
• tagging.conf_clip, tagging.conf_ocr, tagging.conf_echo, tagging.confidence
• nsfw.hit, person_like, cache.hit, digest.coalesced_count
• 指标与告警：
• 头像下载失败率 > 5% 告警
• profile_tags 入库空窗 > 2h 告警
• 日推送命中 DAILY_PUSH_CAP 触发 digest 统计

验收（Given/When/Then） 1. 正样本（青蛙头像）
• When：将测试号头像改为带“青蛙/PEPE 文字”的图片
• Then：profile_events 记录变更；profile_tags 产出 topic_entities=["pepe"] 且 confidence ≥ 0.6；TG 沙盒出现 type=topic 候选卡

    2.	负样本（风景图）
    •	When：换成无关风景图
    •	Then：profile_events 记录；profile_tags 可能有通用标签，但 topic_entities 为空或 confidence < 0.6；不产候选卡

    3.	重复图片
    •	When：短期内换回同一头像
    •	Then：pHash 距离 ≤ 4，不重复落库，不重复推理/推送

    4.	NSFW/超大图
    •	When：超 2MB 或 NSFW
    •	Then：下载拒绝或降权/丢弃；不产候选卡；日志可见原因

    5.	日推送封顶
    •	When：同日触发 > DAILY_PUSH_CAP
    •	Then：生成 digest 消息，单条候选不再直推

降级 / 回滚
• PROFILE_TAGGING=off：仍记录 profile_events，不做推理，不产候选
• 任意步骤失败：标注 img_parse_failed=true，不中断主流程
• 媒体源不可用：跳过，不影响 KOL 流
• 全局熔断：出现异常抖动时，开 DEBUG_PROFILE_CARD=off 与 DAILY_PUSH_CAP 限制

安全与合规
• 禁止人脸识别与身份推断；仅“人像/非人像”布尔
• 不贴 CA、不引导交易；统一风险提示
• 明确 sources=["clip","ocr","social_echo"] 与 confidence，保证可解释性

测试清单（最少要跑）
• 单元：pHash 去重、标签词表加载、meme_map 匹配、confidence 计算
• 集成：从轮询 → 下载 → 推理 → 路由 → 推送端到端
• 性能：并发=2 下 10 张图总耗时 < 2s（示例目标）
• 回归：PROFILE_TAGGING=off 时不产生任何候选

开发顺序建议（一天内拆解） 1. 搭 profile_events 表与下载器（含 pHash 去重与大小校验） 2. image_tagging.py：先 CLIP 与 pHash，后接 OCR 与 NSFW 3. 落 profile_tags，打通 topic_router 产候选 4. 卡片模板与推送；调试卡开关 5. API 两个调试接口；验收用例跑通

与其余计划的对接
• 与 Day8（KOL 采集） 并行，不顺延里程碑
• 为 Day9.1（meme 话题卡） 提供新入口（topic_id 与聚类逻辑复用）
• 后续 Day10–14 的 BigQuery/验证流程无需修改

Day9 ｜ DEX 快照（新增，双源容错）（备注：day7.2 功能需要 day9 补）
• 目标：DexScreener 优先、GeckoTerminal 兜底；返回价格/流动性/FDV/OHLC，并能映射到 token/CA。
• 产物：
providers/dex_provider.py
ENV: DEX_CACHE_TTL_S=60
事件层接口：支持通过 token_ca 查询对应行情
• 验收：
curl /dex/snapshot?chain=eth&contract=0xa0b8... 返回字段完整；若降级，source:"gecko", reason:"timeout"。
从 snapshot 结果中能取到价格与流动性，并写入缓存。
• 降级：两个源都挂 → 返回上次成功值，标记 stale:true。

Day9.1 ｜ Meme 话题卡最小链路
v2.3 新增：前移一个 最小 Telegram 适配层
（就一个 sendMessage + .env 两个变量 + 验收脚本）

目标
让候选流不再只限于“明确代币/CA”，而是能推送 meme 热点，提升推送量。

任务 1. event_type 扩展：signals 增加 topic|primary|secondary|market_risk。 2. pipeline 新增 is_memeable_topic 路由：KeyBERT 词包 + mini LLM 判定。 3. 建立 topic_id（简单哈希/相似度聚类），支持 24h 聚合。 4. 推送候选卡：只列话题关键词/词包，不给 CA，卡片文案带“未落地为币，谨防仿冒”。 5. 去重与限频：同 topic_id 一小时内只推一次。

验收
• curl /signals/topic?topic_id=… 返回关键词与热度斜率。
• Telegram 沙盒频道能看到至少 1 条 meme 热点卡，文案带风险提示。

补充要求：
• 固定输出字段（别让前端追着改）
type=topic, topic_id, topic_entities[], keywords[], slope_10m, slope_30m, mention_count_24h, confidence, sources[], calc_version, ts
说明：keywords 来自 KeyBERT，topic_entities 是你合并后的“规范化实体”（比如把 frog/pepe 合成 pepe）。
• topic_id 生成与合并规则写死
• 先按 topic_entities 相同合并，再用句向量相似度 ≥ 0.80 合并，最后才 fallback 到关键词 Jaccard ≥ 0.5。
• 24 小时窗口滑动，1 小时只推一次你已写到位；再加个日上限：DAILY_TOPIC_PUSH_CAP，超限合并 digest。
• 黑白名单与抑制
• topic_blacklist.yml（例：空泛词“good morning”“gm”“wagmi”）直接抑制。
• topic_whitelist.yml（高价值词：etf、halving、cz、election、layer2 名称）命中时降低触发阈值一点点（比如 0.05）。
• 可解释性字段
• evidence_links[]：原帖/转评的 1–3 个示例链接，方便人工复核。
• sources=["keybert","mini","avatar","media"] 明确来源，别装“上帝视角”。
• 降级策略
• mini LLM 超时：只用 KeyBERT + 规则，degrade:true。
• embedding 服务挂：只按实体/关键词聚合，topic_merge_mode:"fallback"。

验收不变，再加一条：同一 topic_id 24h 内至少能看到斜率变化（10m 与 30m 不同），防止“死数据”卡片。
⸻

Day9.2 ｜ Primary 卡门禁 + 文案模板改造（新增）

目标
确保所有一级卡必须过 GoPlus，卡片文案全部改为“候选/假设 + 验证路径”，降低误导风险。

任务 1. Primary 卡流程：候选（来源+疑似官方/非官方）→ GoPlus 体检 → 红黄绿风险标记。 2. 扩展 rules/risk_rules.yml：强制体检不通过即 red/yellow。 3. 卡片渲染模板改造：新增 risk_note 字段，统一提示（e.g. “高税/LP 未锁，谨慎”）。 4. 二级卡文案改造：来源分级（rumor/confirmed），必须显示验证路线与 data_as_of。

验收
• 3 个已知垃圾盘能被体检标红并推送 red 卡片。
• 同一 event_key 一小时内不重复推送，推送卡片包含风险提示。
• 沙盒频道能看到 meme 卡、primary 卡、二级卡，文案均是“候选/假设 + 验证路径”。

补充要求：
• GoPlus 不可用时的“硬降级”
• goplus_status:"timeout|error" 时，卡片仍可推，但必须 risk_color="gray"，risk_note="体检暂不可用，已降级"，且禁止标“green”。
• 体检结果写清“来源与版本”：risk_source:"GoPlus@vX.Y"。
• 多链 CA 归一化
• 写一个 normalize_ca(chain, ca) 辅助，保证同一事件里 CA 只有规范格式（小写、0x 前缀/无 Base58 混乱）。
• 多个可疑 CA 时，列表去重并标注 is_official_guess:true/false，不要把“猜的”伪装成“官宣”。
• 文案模板一键切换（别每次改前端文案）
• templates/card_primary.md 与 templates/card_secondary.md，占位符：{{risk_color}} {{risk_note}} {{verify_path}} {{data_as_of}}。
• 二级卡固定要求：data_as_of（分钟级时间戳）与 features_snapshot（活跃地址、top10 占比、近 30m 增速）。
• 增加 legal_note 占位：统一“非投资建议”一行，别等谁来挑刺。
• 规则命中可追溯
• 在卡片隐藏字段写：rules_fired:["goplus_tax_high","lp_unlocked"]，排查误报就靠它。
• 推送防抖
• 同一 event_key 你已做 1 小时不重复；再补“状态变化才二次推”：只有从 candidate→verified/downgraded/withdrawn 时允许重发，避免“隔几分钟重复黄色卡”。

一修：把 BigQuery 的接入直接“插”进你的排期里，保证不做空心模块，都是能跑出结果、能走业务流的活。你现在做到 Day7 了，所以我从 Day10 开始插入一段 BigQuery 专项，后面的原计划整体顺延。排期风格、字段命名、验收口径，全部沿用你文档里的写法和节奏。
插入与顺延说明
• 新增的 5 天：Day10–Day14（BigQuery 接入与证据闭环）
• 原计划的 Day10–Day20 统一顺延为：
Day10→Day15，Day11→Day16，Day12→Day17，Day13→Day18，Day14→Day19，Day15→Day20，Day16→Day21，Day17→Day22，Day18→Day23，Day19→Day24，Day20→Day25

二修：我把风险点和优化建议已经融合进你给的四天计划里了，下面这版就是“优化过的定稿”。主要强化了：成本守门、数据新鲜度显式、幂等与回滚、候选流独立性、演示入口受控。这样保证你到 Day15 卡片推送时不会因为 BigQuery 出问题卡全链。⸻

Day10 ｜ BigQuery 项目与 Provider 接入（新增）

目标
打通云端链上数据仓库最小闭环：凭据、SDK、Provider、健康检查。为后续“候选 → 证据”慢路径铺路。

任务 1. GCP 凭据与配置
• 新增 ENV：GCP_PROJECT,BQ_LOCATION,BQ_DATASET_RO,BQ_TIMEOUT_S=60,BQ_MAX_SCANNED_GB=5
• 服务账号 JSON 以挂载方式提供；api/worker 都能读到。 2. BigQuery Client 与 Provider
• clients/bq_client.py：封装 dry_run(sql)->bytes_scanned、query(sql, params)->Iterator[Row]、freshness(dataset)->{latest_block,data_as_of}
• 必须先 dry-run，超过 BQ_MAX_SCANNED_GB 拒绝执行。
• providers/onchain/bq_provider.py：统一入口，暴露 run_template(name,\*\*kwargs)，内部做模板渲染、dry-run 守门、超时与重试（退避抖动）。 3. 健康检查与新鲜度路由
• /onchain/healthz 返回 BQ 连接性。
• /onchain/freshness?chain=eth 返回 latest_block,data_as_of，用于前端标注“分钟级近实时”。 4. 结构化日志与成本打点
• 每次查询必须打印：bq_bytes_scanned,dry_run_pass,cost_guard_hit。
• BigQuery 出错不能影响候选推送，日志要落 degrade。

验收
• curl /onchain/healthz 返回 200；freshness 显示最新块号与 data_as_of。
• bq_provider.py dry-run 和 query 可用，日志显示扫描字节。
• 将 BQ_MAX_SCANNED_GB 调小，触发 cost_guard_hit=true 并安全失败（不崩 pipeline）。

降级/回滚
• ONCHAIN_BACKEND=bq|off，off 时返回 {degrade:true,reason:"bq_off"}，不中断候选流。

⸻

Day11 ｜ SQL 模板与新鲜度守门 + 成本护栏（新增）

目标
固化 3 个最小可用 SQL 模板（ETH 起步），并把“新鲜度守门 + 成本护栏”做进业务流，避免一演示就账单爆炸。

任务 1. SQL 模板（templates/sql/eth/\*.sql）
• active_addrs_window.sql：近 {30|60|180} 分钟唯一交互地址数与交易数。
• token_transfers_window.sql：近窗转账数、发送/接收地址数。
• top_holders_snapshot.sql：Top N 地址累计余额与占比。
• 参数：@address,@from_ts,@to_ts,@window_minutes。 2. 新鲜度守门
• 执行前先查 /onchain/freshness；若 now - data_as_of > FRESHNESS_SLO（ENV，默认 10 分钟），则结果标记 data_as_of_lag 并降级为“候选不升级”。 3. 成本护栏
• dry-run 估算扫描量，超过 BQ_MAX_SCANNED_GB 拒绝执行，返回 {degrade:"cost_guard"}。
• 模板强制 LIMIT + 分区过滤，禁止全表扫。 4. 缓存
• Redis 按 (template,address,window) 缓 60–120 秒；命中打印 cache_hit=true。

验收
• 三个模板能返回字段，带 data_as_of。
• 拉大 FRESHNESS_SLO 触发守门逻辑，候选不升级。
• 调小 BQ_MAX_SCANNED_GB，安全拒绝执行并返回说明。

降级/回滚
• 模板异常时返回 {stale:true,degrade:"template_error"}，不中断整体业务流。

⸻

Day12 ｜派生特征表 onchain_features 与 Alembic 迁移（新增）

目标
把 BigQuery 结果固化为你自己的“轻表”，API 读轻表，避免每次扫大表。

任务 1. Alembic 迁移
• 新建 onchain_features 表：

(id PK, chain TEXT, address TEXT, as_of_ts TIMESTAMPTZ,
window_minutes INT, addr_active INT, tx_count INT,
growth_ratio NUMERIC, top10_share NUMERIC, self_loop_ratio NUMERIC,
calc_version INT,
UNIQUE(chain,address,as_of_ts,window_minutes))

    •	给 signals 表加：onchain_asof_ts, onchain_confidence INT。

    2.	派生作业
    •	jobs/onchain/enrich_features.py：拉 Day11 模板结果，计算 growth_ratio（对比前一窗），写入 onchain_features。
    •	策略：优先 30 分钟窗，其次 60，再 180；从近到远。
    3.	API
    •	/onchain/features?chain=eth&address=... 返回三个窗口最新记录，含 data_as_of,calc_version。

验收
• 地址能查到 30/60/180 的特征记录。
• 唯一索引保证幂等，重复 insert 不报错。
• 模板失败/断网时，API 返回上次成功值并标记 stale:true。

降级/回滚
• 特征写入失败时不影响 signals 主流程，仅视为证据不足。

⸻

Day13 ｜证据块验证与状态机接入（S0→S2）（新增）
（Day13 和 Day14 合并为一天）

目标
把 BigQuery 证据并入信号状态机：候选 S0 → 几分钟后升级 S2（已验证/降级/撤回），更新 signals。

任务 1. 规则 DSL（最小版）
• 新增 rules/onchain.yml：

windows: [30,60,180]
thresholds:
active_addr_pctl: {high:0.95, mid:0.80}
growth_ratio: {fast:2.0, slow:1.2}
top10_share: {high_risk:0.70, mid_risk:0.40}
self_loop_ratio: {suspicious:0.20, watch:0.10}
verdict:
upgrade_if: ["active_addr_pctl>=high","growth_ratio>=fast"]
downgrade_if:["top10_share>=high_risk","self_loop_ratio>=suspicious"]

    •	背景分布按近 7 天同类合约分位数，每日批量更新（先写死，后续自动化）。

    2.	状态机接入
    •	jobs/onchain/verify_signal.py：检测 signals.state=candidate，触发 BigQuery 派生作业，取 onchain_features，按 DSL 输出 verdict。
    •	更新 signals.onchain_asof_ts,onchain_confidence,state；写 signal_events。
    •	超时 >12 分钟未取到证据时，信号保持候选，附加 verdict_note="evidence_delayed"。
    3.	API
    •	/signals/{event_key} 返回最新 state 与 onchain_features 摘要，格式对齐卡片 schema（Day14 用）。

验收
• 候选能在 5 分钟内升级为 verified/downgraded，带 onchain_asof_ts。
• 证据不足状态不变，但标注 insufficient_evidence。
• 超时逻辑生效，候选不堵塞。
• 错误自动重试，进程不崩。

降级/回滚
• ONCHAIN_RULES=off 时，仅写 onchain_asof_ts，不改 state。

⸻

Day14 ｜专家视图 / 演示入口（只内部可见）（新增）
（Day13 和 Day14 合并为一天）
目标
做一个受控的“秀肌肉”入口：输入合约地址，分钟级拉出 24h/7d 的活跃度曲线和集中度概览，用于演示与内部核查。

任务 1. 路由与模板
• /expert/onchain?chain=eth&address=... 返回：
• 近 24h/7d 的 addr_active 折线（按 30/60 分钟聚合）。
• top10_share 饼图。
• data_as_of, stale, cache_hit 标记。
• 输出字段必须与卡片 schema 一致。 2. 限流与缓存
• 必须传 X-Expert-Key；RATE_LIMIT=5/min。
• 强制走 onchain_features 轻表，不允许自由 SQL。
• 缓存 60–300 秒。 3. 成本观测
• 打点：bq_query_count,bq_scanned_mb。
• 达到阈值直接 429，防止滥用。

验收
• 内部开关开时，输入地址能在 3–8 分钟内查到 24h/7d 概览。
• 限流命中返回 429，不影响其它 API。
• BQ 离线时返回上次成功结果，标记 stale:true。

降级/回滚
• EXPERT_VIEW=off 时，该路由直接 404，避免泄露底层能力。
⸻

这样改完，Day10–Day14 就是可跑通、可演、可降级的 BigQuery 专项。
不会再出现“写了 Provider/SQL 模块，但候选卡片挂死，推不出去”的情况。⸻⸻

这 5 天插入的结果，会让什么“真的可用”
• 候选流不被卡住：BigQuery 掉线或超预算，仍然能发 S0 候选卡。
• 慢验证能闭环：3–8 分钟内产出 onchain_features，并把 signals.state 从 S0 升级到 S2（或降级/撤回）。
• 可演可审计：专家视图演示入口随时“现场查给你看”，同时有新鲜度和成本护栏，不会把你自己炸了。
• 贴合你的卡片与推送节奏：等你顺延到（原）Day15 的 Telegram 推送（新 Day20）时，直接在同一线程做“升级推”，不需要重写后端。

Day15 ｜事件聚合跨源升级（优化，不重做）（Day15+Day16 合并为一天）
• 目标：把 Day5 的聚合升级为跨源合并，固定 event_key 不变性；写 events.evidence[]。
• 产物：
/api/events.py 增强
ENV: EVENT_KEY_SALT
events 表 JSONB 字段
复用：Day5 make_event_key/upsert_event。
• 验收：
python scripts/verify_events.py --sample replay.jsonl 输出每事件 refs≥2、event_key 重放一致。
至少 1 个事件同时包含 X 采集内容 与 DEX/GoPlus 引用，证据链合并正确。
• 回滚：ENV EVENT_MERGE_STRICT=false 降为单源合并。

Day16 ｜热度快照与斜率（新增）（Day15+Day16 合并为一天）
• 目标：按 token/CA 计算 10m/30m/recent 计数、斜率、环比；写 signals（Day1 已建表）。
• 产物：signals/heat.py，ENV THETA_RISE 等。
• 验收：
curl /signals/heat?token=USDT 返回 cnt_10m,cnt_30m,trend:"up|down",slope。
• 降级：原始不足 → 只出计数不出斜率。

Day17 ｜ HF 批量与阈值校准（优化，不重做）
• 目标：把 Day4 的 HF 模型做成批量接口，加阈值校准与回灌报告。
• 产物：services/hf_client.py（batch），scripts/smoke_sentiment.py --batch，scripts/hf_calibrate.py 生成混淆矩阵与推荐阈值。
• 复用：Day4 hf_sentiment.py/keyphrases.py。
• 验收：
回灌 100 样本，输出 precision/recall/F1 与阈值建议；坏模型 → 降级 rules。
• 降级：HF 端点超时 → 只用规则和 VADER，卡片加 degrade: "HF_off"。

Day18 ｜规则引擎 + 极简建议器（新增）
目标：热度斜率 + DEX 变化 + GoPlus 风险 + HF 情绪，输出 observe/caution/opportunity 三档，理由最多三条。
• 产物：
rules/eval_event.py
rules.yml 可热加载
ENV: THETA_LIQ,THETA_VOL,THETA_SENT
• 复用：Day6 精析器作为门后 LLM（不再自由发挥）。
• 验收：
curl /rules/eval?event_key=... 返回 level 与 reasons[3]，证据字段齐。
signals 表在对应 event_key 下包含字段：goplus_risk, buy_tax/sell_tax, lp_lock_days, dex_liquidity, dex_volume_1h, heat_slope。
• 降级：HF 关停或 DEX 缺失 → 理由里自动替换为“数据不足”。

    GPT-5整理的两个版本评估：

MVP 切片（3–4 小时）
• 目的：演示、快速跑通闭环。
• 特征：
• 规则写死在 rules.yml，简单数值比较。
• 热加载逻辑=文件改动时间戳刷新，没校验。
• 返回的理由是 YAML 里的字符串拼接，没有权重排序，也不做冲突解决。
• 缺字段直接“数据不足”一句话，没细分。
• 没有单测，验证靠你自己 curl。
• 适合场景：MVP demo，投资人看个“哦它能跑”，不追问。

稳健版（7–9 小时）
• 目的：能撑得住 MVP 上线后的几周，而不是靠临时拼接。
• 特征：
• 阈值和规则在 YAML 中支持分组、注释、优先级，能防止“全中性”或冲突。
• ENV 覆盖 YAML 的默认值，支持动态调整，不怕线上漂移。
• 缺字段时能区分：DEX、HF、GoPlus 哪个模块掉了，在理由里点名。
• Rule 命中结果带有权重/评分，用来决定 observe/caution/opportunity。
• 输出理由经过 Day6 的“精析器”LLM 校对用词，避免理由太死板（但禁止它自由发挥）。
• 基本单测 2–3 个：完整数据、缺字段、全坏数据。
• 日志打点，后续可以接 Prometheus。
• 适合场景：你要真的把它作为 MVP 产品的一部分，哪怕没几天就对接用户/内部 UI。

所以选择很简单
• 如果只是今天晚上想“跑通个流程”，那 MVP 就够了。
• 如果你考虑到你项目的节奏（Day18 就是规则引擎 + 建议器），这个模块未来一定要撑住，那只能做稳健版。

Day19 ｜卡片 Schema + LLM 摘要（复用 Day6，限定用途）
• 目标：定版 cards.schema.json；LLM 只产 summary、risk*note 两短字段。
• 产物：cards/build.py，/cards/preview 路由。
• 复用：Day6 JSON‑schema 校验器；Day10 事件证据。
• 验收：
curl /cards/preview?event_key=... 通过 schema 校验，字段包含 goplus.* 与 dex.\_。
• 降级：LLM 超时 → 模板摘要（可读但无修辞）。

Day20 ｜ Telegram 推送（新增）
补全重试队列、批量推送、绑定讨论组、/cards/send、失败入队等，day9.1 做了最小推送
（Day20+Day21 合并为一天）
• 目标：把卡片发到频道，绑定讨论组；1 小时内同 event_key 去重。
• 产物：notifier/telegram.py，ENV TG_BOT_TOKEN,TG_CHANNEL_ID,TG_RATE_LIMIT。
• 验收：
curl -XPOST /cards/send?event_key=... 沙盒频道落 5 张卡，失败有 error_code。
• 降级：TG 失败 → 落本地 outbox 重试队列；卡片保存在 /tmp/cards/\*.json。

Day21 ｜端到端延迟与退化（集中调优，复用 Day3+）
（Day20+Day21 合并为一天）

    •	目标：E2E P95 ≤ 2 分钟；失败用缓存/上次成功结果；熔断+退避。
    •	产物：make bench-pipeline；指标 pipeline_latency_ms, external_error_rate, degrade_ratio。
    •	验收：

跑 50 事件，P95 ≤ 120000ms，外呼失败率<5%，退化占比<10%。
• 注意：不在前面的日子绑手绑脚，这是集中收口。

Day22 ｜回放与部署（新增）
• 目标：新环境 30 分钟内从零到“频道看到卡片”；回放历史误判集。
• 产物：docker compose up -d 一键；scripts/replay_e2e.sh 把 golden.jsonl 打穿。
• 复用：Day3 demo/bench；Day8–15 的所有路由。
• 验收：
新目录拉起后 30 分钟内 Telegram 见卡；回放 10 条里预警命中 ≥80%。

Day23 ｜配置与治理（轻量优化，非重复）（day23&day24 合并为一天）
• 目标：rules.yml 热加载；KOL 列表、黑白名单、阈值无需改代码；敏感变量审计。
• 产物：/config/hotreload，.env.example 完整注释；scripts/config_lint.py。
• 验收：
改阈值 →1 分钟内生效；配置 lint 全绿；泄露检测脚本通过。

Day24 ｜观测面与告警（轻量优化，非重复）（day23&day24 合并为一天）
• 目标：最低限度观测：外呼成功率、延迟、退化比；TG 失败重试告警。
• 产物：/metrics 暴露 Prom 格式；alerts.yml（可用本地脚本/简单 webhook）。
• 验收：
人为打断 DEX 源，看到退化上涨；TG 失败告警命中。
