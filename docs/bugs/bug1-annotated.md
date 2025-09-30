Bug1 验证批注（不改原文）

说明

- 本文基于 docs/bugs/bug1.md 逐条校验，未修改/覆盖原文。
- 方式：按“问题 X”逐条摘录标题，紧随其后给出【验证批注】【优先级】【结论】与关键证据（文件:行）。
- 排序：文末提供按 p0/p1/p2 的分组清单（原文中 P3 归并至 p2）。

—

问题 1：推送触发机制碎片化，缺乏统一入口

【验证批注】
- 已复现三种路径并存：
  - A/B 路径走统一卡片：worker/jobs/ca_hunter_scan.py:219、worker/jobs/secondary_proxy_scan.py:101 使用 `push_card_task.apply_async()` 触发 `worker/jobs/push_cards.py:1`（统一管线 `render_and_push()`）。
  - C 路径直推：worker/jobs/topic_aggregate.py:177-181 直接 `push_to_telegram(text)`，完全绕过统一卡片系统。
  - 统一渲染管线存在：api/cards/render_pipeline.py:200 起，`render_and_push()` 按 `signal["type"]` 路由到生成器。
- 因此“新增信息源需重复实现推送逻辑、无法统一监控和限流”的风险客观存在。

【优先级】p0

【结论】存在且未解决（Topic 仍走旁路）。

证据：worker/jobs/ca_hunter_scan.py:219, worker/jobs/secondary_proxy_scan.py:101, worker/jobs/topic_aggregate.py:177, api/cards/render_pipeline.py:200

—

问题 2：Topic 信号生成与推送逻辑分离且不一致

【验证批注】
- 生成：worker/jobs/topic_signal_scan.py:25-35, 70-114 会为有 topic 的 events 创建/更新 signals，且写入 `type='topic'` 与兼容 `market_type='topic'`。
- 调度：worker/tasks.py:126-134 存在定时“扫描生成”任务（scan），但未发现“消费并推送 topic signals（process_card）”的定时/工作流。
- 旁路：worker/jobs/topic_aggregate.py:147-181 从 Redis 候选直推 Telegram，不读取 signals。
- 统一卡片系统的 topic 路由虽已具备（见问题 3），但当前未被消费链路触发。

【优先级】p0

【结论】部分属实：扫描存在；消费/推送环节缺失，导致 signals 中的 topic 记录难以进入统一卡片通道。

证据：worker/jobs/topic_signal_scan.py:65, 86-114, worker/tasks.py:126, worker/jobs/topic_aggregate.py:147-181

—

问题 3：统一卡片系统的 Topic 卡片路由未被激活

【验证批注】
- 路由/生成器/模板均存在：
  - 路由：api/cards/registry.py:48-72 定义 `"topic" → generate_topic_card` 与模板 `topic_card`。
  - 生成器：api/cards/generator.py:105-145 存在 `generate_topic_card()`。
  - 模板：templates/cards/topic_card.tg.j2、templates/cards/topic_card.ui.j2 均存在。
- 触发缺失：未检索到任何将 `type='topic'` 的 signal 交由 `process_card`/`render_and_push` 的代码路径；Topic 仍由 topic_aggregate 走直推。

【优先级】p0

【结论】存在且未解决（能力闲置）。

证据：api/cards/registry.py:48, api/cards/generator.py:105, templates/cards/topic_card.tg.j2, worker/jobs/push_cards.py:1, worker/jobs/topic_aggregate.py:177-181

—

问题 4：缺少交易所公告（Exchange Listing）采集和卡片类型

【验证批注】
- 未找到 `worker/jobs/exchange_poll.py`、`generate_exchange_card()`、`templates/cards/exchange_card.tg.j2`，也未发现 `CardType` 包含 `exchange`。

【优先级】p1

【结论】存在且未实现。

证据：全仓检索无命中（exchange_poll/generate_exchange_card/exchange_card/CardType exchange）。

—

问题 5：缺少新闻资讯（News）采集和卡片类型

【验证批注】
- 未找到 `worker/jobs/news_poll.py`、`generate_news_card()`、`templates/cards/news_card.tg.j2`，也未发现 `CardType` 包含 `news`。

【优先级】p1

【结论】存在且未实现。

证据：全仓检索无命中（news_poll/generate_news_card/news_card/CardType news）。

—

问题 6：缺少社区信号（Telegram/Discord）采集能力

【验证批注】
- 仅看到推送器 `api/services/telegram.py` 与调用者，但未见 `worker/jobs/telegram_poll.py`、`worker/jobs/discord_poll.py` 等采集器实现。
- 多源加权聚合（source_weight）亦未见落库字段或聚合逻辑。

【优先级】p2

【结论】存在且未实现（采集与多源聚合缺失）。

证据：worker 与 api 下无 telegram_poll/discord_poll；仅有 TelegramNotifier 用于发送。

—

问题 7：无法识别 @mention 格式的代币关联

【验证批注】
- 仅识别 `$TOKEN`：api/normalize/x.py:80 使用 `symbol_pattern` 提取 `$...`。
- `@mention` 在归一化文本时被移除：api/events.py:393 `re.sub(r'@\w+', '', text)`。
- 配置映射与提取函数（configs/mention_to_symbol.yml、extract_symbols_from_mentions）未发现实现。

【优先级】p1

【结论】存在且未实现（映射缺失，信息损失）。

证据：api/normalize/x.py:80, api/events.py:393

—

问题 8：缺少实体归一化和别名处理

【验证批注】
- 当前仅小写 + `$` 前缀：api/events.py:180-201 的 `_normalize_token_symbol()` 实现简单。
- 未见 `configs/entity_aliases.yml` 与 `_normalize_entity()` 等实体级归一化逻辑。

【优先级】p2

【结论】存在且未实现（同义/别名未归一）。

证据：api/events.py:180, 全仓无 entity_aliases.yml

—

问题 9：signals 表缺少 pushed_at 和 push_status 字段

【验证批注】
- docs/SCHEMA.md 未列出 `pushed_at/push_status/push_error` 字段；migrations 下亦未找到相应迁移（仅见 015_add_indexes_idempotency 等）。
- 推送出错会入 outbox DLQ（worker/jobs/push_cards.py），但 signals 本身无推送状态字段用于统一调度/去重。

【优先级】p1

【结论】存在且未实现（schema 缺此三字段）。

证据：docs/SCHEMA.md:1, api/alembic/versions/015_add_indexes_idempotency.py:8

—

问题 10：缺少信号优先级和推送策略配置

【验证批注】
- 未找到 `configs/push_policy.yml`、`api/services/push_scheduler.py`、`user_subscriptions` 迁移；signals 也无 `priority` 列。
- 现有 outbox 处理按时间/重试排序，未见全局策略优先级（仅业务内局部“priority”字段如规则优先级）。

【优先级】p2

【结论】存在且未实现。

证据：api/db/repositories/outbox_repo.py:22-63（按时间/尝试排序），全仓无 push_policy.yml/push_scheduler/user_subscriptions。

—

问题 11：缺少统一的推送漏斗监控

【验证批注】
- 已有计数：api/core/metrics.py:217-236 定义 `cards_generated_total/cards_push_total/cards_push_fail_total`。
- 未见 `push_funnel_conversion` 指标；dashboards 目录无 `push_funnel.json`。

【优先级】p2（原文 P3 归并 p2）

【结论】存在且未实现（缺漏斗面板与转化率指标）。

证据：api/core/metrics.py:217, dashboards/（无 push_funnel.json）

—

问题 12：缺少推送失败的告警和重试机制完整性

【验证批注】
- 已有：DLQ/重试链路存在（worker/jobs/outbox_retry.py、outbox_dlq_recover.py），alerts.yml 有通用指标告警（如 telegram_error_rate_high）。
- 未见：针对 `cards_push_fail_total` 的显式告警规则；也不存在 `scripts/dlq_inspect.py`/`dlq_retry.py` 一键工具。

【优先级】p2（原文 P3 归并 p2）

【结论】部分存在（基础能力有），但“失败率专属告警 + DLQ 运维脚本”缺失。

证据：alerts.yml:1, worker/jobs/outbox_retry.py:1, worker/jobs/outbox_dlq_recover.py:1，scripts/ 下无 dlq_inspect.py/dlq_retry.py

—

问题 13：推送相关配置分散在多处，缺少统一管理

【验证批注】
- 现状属实：ENV 与多个 YAML 均在用（configs/x_kol.yaml、configs/topic_blacklist.yml 等），且 topic 推送参数散落 ENV（TOPIC_PUSH_*）。
- 未见 `configs/push_config.yml`，但已存在热加载内核（api/config/hotreload.py）。

【优先级】p2

【结论】存在且未实现（统一配置清单未提供）。

证据：configs/x_kol.yaml, configs/topic_blacklist.yml, worker/jobs/topic_aggregate.py:151-153, api/config/hotreload.py:1

—

按优先级分组（p0/p1/p2）

- p0：
  - 问题 1 推送触发机制碎片化（未解决）
  - 问题 2 Topic 生成与推送分离（部分属实：缺消费/推送）
  - 问题 3 Topic 卡片路由未激活（未解决）

- p1：
  - 问题 4 交易所公告采集/卡片缺失
  - 问题 5 新闻资讯采集/卡片缺失
  - 问题 7 @mention → $symbol 映射缺失
  - 问题 9 signals 缺 pushed_at/push_status/push_error

- p2：
  - 问题 6 社区信号采集与多源加权缺失
  - 问题 8 实体归一化/别名缺失
  - 问题 10 推送优先级与策略配置缺失
  - 问题 11 推送漏斗/转化率监控缺失（原 P3）
  - 问题 12 失败告警完整性与 DLQ 工具缺失（原 P3）
  - 问题 13 配置分散，缺统一 push_config（可结合热加载）

注：为与请求一致，原文 P3 问题归并至 p2 分组。

