Bug1:系统推送架构问题清单

问题概览

当前系统存在推送逻辑碎片化和卡片类型覆盖不完整的核心问题，导致无法统一处理不同信息源的推送需求。

---

一、架构层面的问题

问题 1：推送触发机制碎片化，缺乏统一入口

现状：

- 系统存在 3 种互不兼容的推送模式：
  - 模式 A：ca_hunter_scan.py → process_card.delay() → 统一卡片系统（Primary）
  - 模式 B：secondary_proxy_scan.py → process_card.delay() →
    统一卡片系统（Secondary）
  - 模式 C：topic_aggregate.py → 直接调用 TelegramNotifier（简化版
    Topic，绕过统一卡片系统）

具体表现：

- worker/jobs/ca_hunter_scan.py:219 调用 process_card.apply_async()
- worker/jobs/secondary_proxy_scan.py:101 调用 process_card.apply_async()
- worker/jobs/topic_aggregate.py:149-181 直接调用 push_to_telegram()，完全绕过
  process_card

影响：

- 每增加一个新信息源，需要复制一套扫描 → 推送逻辑
- 无法统一监控和限流
- 代码重复度高，维护成本大

涉及文件：

- worker/jobs/ca_hunter_scan.py
- worker/jobs/secondary_proxy_scan.py
- worker/jobs/topic_aggregate.py
- worker/jobs/push_topic_candidates.py

---

问题 2：Topic 信号生成与推送逻辑分离且不一致

现状：

- worker/jobs/topic_signal_scan.py 扫描 events 表，生成 signals.market_type='topic'
  记录
- 但没有任何 worker 消费这些 topic signal 并调用 process_card.delay() 推送
- worker/jobs/topic_aggregate.py 使用完全独立的逻辑直接推送，不读取 signals 表

具体表现：

- topic_signal_scan.py:121-139 写入 signals 表，type='topic'
- worker/tasks.py 中没有定时任务扫描并推送 topic signals
- topic_aggregate.py 直接从 Redis 读取候选并推送，完全绕过 signals 表

影响：

- signals 表中的 topic 记录无人消费，成为"僵尸数据"
- Topic 推送无法享受统一卡片系统的去重、降级、监控能力
- 统一卡片系统的 generate_topic_card() 和 topic_card.tg.j2 从未被实际使用

涉及文件：

- worker/jobs/topic_signal_scan.py（生成 signal 但无人消费）
- worker/jobs/topic_aggregate.py（独立推送逻辑）
- api/cards/generator.py:105-136（generate_topic_card 从未被调用）
- templates/cards/topic_card.tg.j2（模板从未被使用）
- worker/tasks.py（缺少 topic signal 推送任务）

---

问题 3：统一卡片系统的 Topic 卡片路由未被激活

现状：

- api/cards/registry.py:48-50 定义了 generate_topic_card 路由
- api/cards/generator.py:105-136 实现了完整的 generate_topic_card() 函数
- templates/cards/topic_card.tg.j2 和 topic_card.ui.j2 模板已存在
- 但没有任何代码路径会触发 render_and_push(signal, channel_id) 且 signal["type"] ==
  "topic"

具体表现：

- api/cards/render_pipeline.py:172-181 会根据 signal["type"] 路由到对应 generator
- ca_hunter_scan.py 生成 type="primary" 的 signal
- secondary_proxy_scan.py 生成 type="secondary" 的 signal
- 但没有 worker 生成 type="topic" 的 signal 并调用 render_and_push()

影响：

- 统一卡片系统的 Topic 卡片功能完全闲置
- 与 Primary/Secondary 卡片的架构不一致
- 无法为 Topic 卡片提供完整的 DEX 数据、GoPlus 扫描、规则评估等能力

涉及文件：

- api/cards/registry.py:48-50（路由已定义）
- api/cards/generator.py:105-136（生成器已实现）
- templates/cards/topic_card.tg.j2（模板已存在）
- worker/jobs/\*（缺少调用路径）

---

二、信息源覆盖不完整的问题

问题 4：缺少交易所公告（Exchange Listing）采集和卡片类型

现状：

- 系统没有采集币安、OKX、Coinbase 等交易所的新币上线公告
- api/cards/registry.py 中没有 exchange 卡片类型
- 用户提到的"交易所公告"类推送需求完全未实现

需要实现：

1. 采集器：worker/jobs/exchange_poll.py


    - 支持币安 API、OKX API、Coinbase RSS
    - 解析字段：symbol, listing_time, trading_pairs, announcement_url
    - 写入 events 表，type='exchange_listing'

2. 信号扫描器：扫描 events.type='exchange_listing' 并创建 signals.type='exchange'
3. 卡片类型：


    - CardType 新增 "exchange" 枚举值
    - 生成器：generate_exchange_card()
    - 模板：templates/cards/exchange_card.tg.j2

4. 推送触发器：扫描 signals.type='exchange' 并调用 process_card.delay()

影响：

- 无法满足"交易所公告推送"的业务需求
- 用户需要手动监控交易所公告

涉及文件（需新建）：

- worker/jobs/exchange_poll.py（采集器）
- api/cards/generator.py（新增 generate_exchange_card()）
- templates/cards/exchange_card.tg.j2（模板）
- api/cards/registry.py（新增 "exchange" 类型）

---

问题 5：缺少新闻资讯（News）采集和卡片类型

现状：

- 系统没有采集方程式新闻、Decrypt、CoinDesk 等官方新闻源
- 用户提到的"方程式新闻"类推送需求完全未实现
- 缺少对新闻可信度的评估机制

需要实现：

1. 采集器：worker/jobs/news_poll.py


    - 支持 RSS、API、网页爬虫
    - 解析字段：title, summary, source, publish_time, credibility_score, url
    - 写入 events 表，type='news'

2. 信号扫描器：扫描 events.type='news' 并创建 signals.type='news'
3. 卡片类型：


    - CardType 新增 "news" 枚举值
    - 生成器：generate_news_card()
    - 模板：templates/cards/news_card.tg.j2
    - 需包含：新闻来源可信度标识、官方认证标记

4. 推送触发器：扫描 signals.type='news' 并调用 process_card.delay()

影响：

- 无法满足"新闻资讯推送"的业务需求
- 缺少官方信息源的整合能力

涉及文件（需新建）：

- worker/jobs/news_poll.py（采集器）
- api/cards/generator.py（新增 generate_news_card()）
- templates/cards/news_card.tg.j2（模板）
- api/cards/registry.py（新增 "news" 类型）

---

问题 6：缺少社区信号（Telegram/Discord）采集能力

现状：

- 系统只支持 X (Twitter) 作为信息源（worker/jobs/x_kol_poll.py）
- 无法采集 Telegram 频道、Discord 服务器的社区讨论
- 缺少多源信号的置信度加权机制

需要实现：

1. Telegram 采集器：worker/jobs/telegram_poll.py


    - 使用 Telethon 或 Pyrogram 库
    - 监控指定频道的消息
    - 提取：message_text, channel_name, timestamp, mentions

2. Discord 采集器：worker/jobs/discord_poll.py


    - 使用 discord.py 库
    - 监控指定服务器的消息
    - 提取：message_text, channel_name, author, timestamp

3. 多源信号聚合：


    - 同一 symbol 的多个来源（X + Telegram + Discord）需要加权聚合
    - 在 api/events.py 中增加 source_weight 字段
    - 在 candidate_score 计算中考虑多源置信度

影响：

- 信息源单一，容易遗漏重要信号
- 无法利用社区讨论热度作为验证依据

涉及文件（需新建）：

- worker/jobs/telegram_poll.py（采集器）
- worker/jobs/discord_poll.py（采集器）
- api/events.py（需扩展多源聚合逻辑）

---

三、符号识别和实体解析的问题

问题 7：无法识别 @mention 格式的代币关联

现状：

- api/normalize/x.py:79-83 只提取 $TOKEN 格式的 symbol
- @aster_dex 这类提及会被 \_normalize_text() 完全移除（api/events.py:393）
- 无法建立 @mention → $symbol 的映射关系

具体表现：

# api/normalize/x.py:79-83

symbol*pattern = r'(?<![A-Za-z0-9*])\$[A-Za-z][A-Za-z0-9]{1,9}\b'
symbol_match = re.search(symbol_pattern, text)

# api/events.py:393

text = re.sub(r'@\w+', '', text) # @aster_dex 被移除

影响：

- 推文 "excited about @aster_dex launch" 无法关联到 $ASTER
- 相似推文可能因为缺少 symbol 而无法正确去重
- 错失大量只提及 Twitter 账号而不使用 $symbol 格式的讨论

解决方案：

1.  新建配置文件 configs/mention_to_symbol.yml：
    mentions:
    aster_dex:
    symbol: $aster
    confidence: 0.9
    chain: eth
    uniswap:
    symbol: $uni
    confidence: 1.0
    type: dex
    binance:
    symbol: null
    type: exchange # 交易所账号不映射为代币

2.  在 api/normalize/x.py 中新增函数：
    def extract_symbols_from_mentions(text: str) -> List[Tuple[str, float]]:
    """从 @提及 推断可能的 symbol"""
    mentions = re.findall(r'@(\w+)', text)
    mapping = load_mention_mapping() # 加载配置

        results = []
        for mention in mentions:
            if mention.lower() in mapping:
                entry = mapping[mention.lower()]
                if entry.get("symbol"):
                    results.append((entry["symbol"], entry.get("confidence", 0.5)))

        return results

3.  在 normalize_tweet() 中调用并合并结果

涉及文件：

- api/normalize/x.py:79-83（symbol 提取逻辑）
- api/events.py:393（@mention 移除逻辑）
- configs/mention_to_symbol.yml（需新建）

---

问题 8：缺少实体归一化和别名处理

现状：

- 系统没有处理同一代币的多种表达方式（如 "pepe", "PEPE", "$pepe", "@pepe_coin"）
- api/events.py:180-234 的 \_normalize_token_symbol() 只做小写+加$前缀
- 缺少实体归一化规则（如 "frog" → "pepe"）

具体表现：

- \_normalize_token_symbol() 只做：
  def \_normalize_token_symbol(symbol: Optional[str]) -> str:
  clean = symbol.strip().lower()
  if not clean.startswith("$"):
          clean = "$" + clean
  return clean

影响：

- "pepe", "PEPE", "$pepe" 可能生成不同的 event_key
- "frog meme" 和 "pepe meme" 无法识别为同一话题
- Topic 聚合时需要依赖 rules/topic_merge.yml（Day9.1 已实现），但缺少 symbol
  层面的归一化

解决方案：

1. 新建配置文件 configs/entity_aliases.yml：
   entities:
   pepe:
   aliases: [frog, kek, pepe_coin, pepecoin]
   canonical: pepe
   confidence: 0.95
   shib:
   aliases: [shiba, shibainu, shiba_inu]
   canonical: shib
   confidence: 1.0

2. 在 api/events.py 中新增 \_normalize_entity() 函数
3. 在 make_event_key() 调用前先归一化

涉及文件：

- api/events.py:180-201（symbol 归一化逻辑）
- rules/topic_merge.yml（Day9.1 已有话题合并规则）
- configs/entity_aliases.yml（需新建）

---

四、数据库和状态管理的问题

问题 9：signals 表缺少 pushed_at 和 push_status 字段

现状：

- signals 表没有记录推送状态的字段
- 无法查询"已生成但未推送的信号"
- 无法避免重复推送同一信号

具体表现：

- 当前 schema（docs/SCHEMA.md）中 signals 表没有：
  - pushed_at TIMESTAMP（推送时间）
  - push_status VARCHAR（pending/sent/failed）
  - push_error TEXT（推送失败原因）

影响：

- 统一信号推送器无法查询"待推送信号"
- 推送失败后无法追溯原因
- 无法统计推送成功率

解决方案：

1. 新建 Alembic 迁移 015_add_signals_push_fields.py：
   ALTER TABLE signals ADD COLUMN pushed_at TIMESTAMP;
   ALTER TABLE signals ADD COLUMN push_status VARCHAR(20) DEFAULT 'pending';
   ALTER TABLE signals ADD COLUMN push_error TEXT;
   CREATE INDEX idx_signals_push_pending ON signals(push_status, ts) WHERE push_status
   = 'pending';

2. 在统一推送器查询时过滤：
   SELECT \* FROM signals
   WHERE push_status = 'pending'
   AND state = 'verified'
   AND ts >= NOW() - INTERVAL '24 hours'
   ORDER BY ts DESC LIMIT 50

涉及文件：

- docs/SCHEMA.md（需更新 schema 定义）
- api/alembic/versions/015\_\*.py（需新建迁移）

---

问题 10：缺少信号优先级和推送策略配置

现状：

- 所有信号推送优先级相同，无法区分紧急程度
- 缺少推送频率限制策略（如"同一 symbol 1 小时内最多推送 3 次"）
- 缺少用户订阅偏好管理

需要实现：

1. 信号优先级：


    - signals 表新增 priority INT（1=低, 3=中, 5=高）
    - Exchange Listing = 5（最高优先级）
    - News = 4
    - Primary = 3
    - Secondary = 2
    - Topic = 1

2. 推送策略配置：

# configs/push_policy.yml

rate_limits:
same_symbol_1h: 3 # 同一 symbol 1 小时内最多推送 3 次
same_type_1h: 10 # 同一类型 1 小时内最多推送 10 次
total_1h: 50 # 总推送量 1 小时内最多 50 条

priority_boost:
exchange: +2 # 交易所公告优先级+2
verified_kol: +1 # 认证 KOL 优先级+1

3. 用户订阅管理：


    - 新建 user_subscriptions 表
    - 字段：user_id, symbol_filter, type_filter, min_priority, mute_until

涉及文件（需新建）：

- configs/push_policy.yml（策略配置）
- api/alembic/versions/016_user_subscriptions.py（订阅表迁移）
- api/services/push_scheduler.py（推送调度器）

---

五、监控和可观测性的问题

问题 11：缺少统一的推送漏斗监控

现状：

- 虽然有 api/core/metrics.py 的 Prometheus 指标
- 但缺少端到端推送漏斗的监控：
  - Event 生成量
  - Signal 生成量
  - Card 渲染量
  - 实际推送量
  - 推送成功率

具体表现：

- cards_generated_total 和 cards_push_total 是独立指标
- 无法回答："为什么生成了 100 个 signal 但只推送了 20 条？"
- 缺少各环节的转化率监控

解决方案：

1. 新增 Grafana Dashboard dashboards/push_funnel.json：
   {
   "title": "Push Funnel",
   "panels": [
   {"metric": "events_upsert_total", "label": "Events Created"},
   {"metric": "signals_created_total", "label": "Signals Generated"},
   {"metric": "cards_generated_total", "label": "Cards Rendered"},
   {"metric": "cards_push_total", "label": "Push Sent"},
   {"metric": "cards_push_fail_total", "label": "Push Failed"}
   ]
   }

2. 新增转化率指标：

# api/core/metrics.py

push_funnel_conversion = Gauge('push_funnel_conversion_rate',
'Conversion rate between funnel stages',
['from_stage', 'to_stage'])

涉及文件：

- api/core/metrics.py（新增转化率指标）
- dashboards/push_funnel.json（需新建）

---

问题 12：缺少推送失败的告警和重试机制完整性

现状：

- 虽然 worker/jobs/push_cards.py 有 Celery 重试机制
- 但缺少：
  - 推送失败告警（Slack/钉钉/邮件）
  - DLQ（Dead Letter Queue）的手动恢复工具
  - 推送失败的根因分析面板

具体表现：

- worker/jobs/push_cards.py:115-124 会把失败任务送入 DLQ
- worker/jobs/outbox_dlq_recover.py 提供自动恢复
- 但缺少人工介入的管理界面

解决方案：

1. 新增告警规则 alerts.yml：

- alert: HighPushFailureRate
  expr: rate(cards_push_fail_total[5m]) > 0.1
  annotations:
  summary: "Push failure rate exceeds 10%"

2. 新增 DLQ 管理脚本：

# scripts/dlq_inspect.py

# 查看 DLQ 中的失败任务，按失败原因分组

# scripts/dlq_retry.py --signal-id=xxx

# 手动重试指定任务

涉及文件：

- alerts.yml（需扩展告警规则）
- scripts/dlq_inspect.py（需新建）
- scripts/dlq_retry.py（需新建）

---

六、配置和治理的问题

问题 13：推送相关配置分散在多处，缺少统一管理

现状：

- 推送配置分散在：
  - .env 文件（TELEGRAM_BOT_TOKEN, TELEGRAM_SANDBOX_CHAT_ID）
  - configs/x_kol.yaml（KOL 列表）
  - rules/topic_merge.yml（话题合并规则）
  - configs/topic_blacklist.yml（话题黑名单）
  - 代码硬编码（如 topic_aggregate.py 中的 DAILY_TOPIC_PUSH_CAP）

影响：

- 修改推送策略需要改多处配置
- 缺少配置的版本管理和回滚能力
- 容易遗漏配置项导致功能异常

解决方案：

1. 新建统一配置文件 configs/push_config.yml：
   telegram:
   bot_token: ${TELEGRAM_BOT_TOKEN}
   channels:
   primary: ${TELEGRAM_PRIMARY_CHANNEL_ID}
   secondary: ${TELEGRAM_SECONDARY_CHANNEL_ID}
   topic: ${TELEGRAM_TOPIC_CHANNEL_ID}
   news: ${TELEGRAM_NEWS_CHANNEL_ID}

rate_limits:
daily_topic_push_cap: 20
same_symbol_1h: 3
total_1h: 50

sources:
x_kol:
config_file: configs/x_kol.yaml
poll_interval_sec: 300
exchange:
enabled: false
supported: [binance, okx, coinbase]
news:
enabled: false
sources: [formula_news, decrypt, coindesk]

2. 使用 api/config/hotreload.py 实现热加载（Day15 已有）

涉及文件：

- configs/push_config.yml（需新建）
- api/config/hotreload.py（Day15 已实现）

---

总结：问题优先级分级

P0（阻塞性问题，必须解决）

- 问题 1：推送触发机制碎片化
- 问题 2：Topic 信号生成与推送逻辑分离
- 问题 3：统一卡片系统的 Topic 卡片未被激活

P1（核心功能缺失）

- 问题 4：缺少交易所公告采集和卡片类型
- 问题 5：缺少新闻资讯采集和卡片类型
- 问题 7：无法识别 @mention 格式的代币关联
- 问题 9：signals 表缺少 pushed_at 字段

P2（功能增强）

- 问题 6：缺少社区信号采集能力
- 问题 8：缺少实体归一化和别名处理
- 问题 10：缺少信号优先级和推送策略配置
- 问题 13：推送配置分散

P3（运维优化）

- 问题 11：缺少统一推送漏斗监控
- 问题 12：缺少推送失败告警完整性

---

建议的实施路径

Phase 1：架构统一（1-2 周）

- 解决问题 1、2、3：实现统一信号推送器
- 解决问题 9：扩展 signals 表 schema

Phase 2：功能补齐（2-3 周）

- 解决问题 4、5：实现 Exchange 和 News 采集及卡片类型
- 解决问题 7：实现 @mention 映射

Phase 3：增强优化（1-2 周）

- 解决问题 8、10、13：实现实体归一化、推送策略、统一配置
- 解决问题 11、12：完善监控和告警
