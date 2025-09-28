# MVP28 修复任务清单

生成时间: 2025-09-22
基于文档: design-vs-implementation.md, workflow-analysis.md, complete-risk-assessment.md

---

## P0 级别任务（阻塞性问题，1-2 天内必须修复）

### 任务 P0-1: 修复 signals 表缺少 type 字段问题(已完成)

**背景 / 问题描述**

- 发现位置：`api/alembic/versions/001_initial_tables.py`，signals 表定义
- 触发原因：无法区分 topic/primary/secondary/market_risk 四种卡片类型
- 影响范围：整个卡片分流系统失效，无法正确路由不同类型的信号

**修复目标**
确保 signals 表包含 type 字段，支持四种卡片类型区分

**修复步骤**

1. 生成新的 Alembic 迁移：`alembic revision -m "add_type_field_to_signals"`
2. 添加 type 字段：`VARCHAR(20)` 或 `ENUM('topic','primary','secondary','market_risk')`
3. 更新现有数据：根据 market_type 字段推断 type 值
4. 修改 `api/models.py` 中 Signal 模型，添加 type 字段
5. 更新所有相关 API 路由和查询逻辑

**验收标准**

- `docker compose exec -T db psql -U app -c "\d signals"` 显示 type 字段
- `alembic upgrade head` 成功执行
- `alembic downgrade -1 && alembic upgrade head` 通过
- 能够插入四种不同 type 的信号记录

**产物**

- `api/alembic/versions/<revision>_add_type_field_to_signals.py`
- 更新的 `api/models.py`
- 更新的 `docs/SCHEMA.md`

**优先级 / 预计工作量**

- 优先级：P0（必须修复）
- 预计耗时：2 小时

---

### 任务 P0-2: 创建缺失的卡片模板 (已完成)

**背景 / 问题描述**

- 发现位置：`templates/cards/` 目录
- 触发原因：topic_card.j2 和 market_risk_card.j2 模板文件不存在
- 影响范围：无法生成 Topic 类和 Market Risk 类卡片，Telegram 推送失败

**修复目标**
创建完整的卡片模板文件，支持四种卡片类型的渲染

**修复步骤**

1. 创建 `templates/cards/topic_card.j2` 模板
2. 创建 `templates/cards/market_risk_card.j2` 模板
3. 参考现有 primary_card.j2 和 secondary_card.j2 的格式
4. 确保模板包含必要字段：topic_id、entities、risk_note 等

**验收标准**

- `ls templates/cards/*.j2 | wc -l` 输出 4
- 所有模板文件语法正确
- 渲染测试通过，生成的消息格式正确
- Telegram 推送测试成功

**产物**

- `templates/cards/topic_card.j2`
- `templates/cards/market_risk_card.j2`

**优先级 / 预计工作量**

- 优先级：P0（必须修复）
- 预计耗时：1 小时

---

### 任务 P0-3: 修复卡片路由逻辑(已完成)

**背景 / 问题描述**

- 发现位置：`api/cards/generator.py`、`worker/jobs/push_topic_candidates.py`
- 触发原因：硬编码判断只支持 primary/secondary，缺少 topic/market_risk 分支
- 影响范围：即使有了 type 字段和模板，仍无法正确路由生成卡片

**修复目标**
实现完整的四种卡片类型路由机制

**修复步骤**

1. 修改 `api/cards/generator.py`，添加 topic 和 market_risk 分支
2. 实现 `generate_topic_card()` 函数
3. 实现 `generate_market_risk_card()` 函数
4. 更新 `worker/jobs/push_topic_candidates.py` 使用正确的模板

**验收标准**

- 四种 type 值都能正确路由到对应的生成函数
- 每种卡片类型都能成功生成并推送
- 日志无报错，无未处理的 type 值

**产物**

- 更新的 `api/cards/generator.py`
- 更新的 `worker/jobs/push_topic_candidates.py`

**优先级 / 预计工作量**

- 优先级：P0（必须修复）
- 预计耗时：2 小时

---

## P1 级别任务（功能性问题，1 周内修复）

### 任务 P1-1: 实现基础 Market Risk 判定逻辑(已完成)

**背景 / 问题描述**

- 发现位置：`rules/risk_rules.yml`、`api/rules/eval_event.py`
- 触发原因：Day18 设计的 market_risk 类型完全未实现
- 影响范围：无法进行市场风险预警，缺失 MVP 要求的四种卡片之一

**修复目标**
实现 market_risk 判定规则，支持市场异动检测和风险预警

**修复步骤**

1. 在 `rules/risk_rules.yml` 中添加 market_risk 规则定义
2. 定义判定条件：价格异动、成交量激增、流动性枯竭等
3. 修改规则引擎支持四档输出（observe/caution/opportunity/market_risk）
4. 实现 market_risk 信号生成逻辑
5. 添加环境变量 `MARKET_RISK_THRESHOLD` 等配置

**验收标准**

- 规则引擎能输出 market_risk 判定
- 触发条件测试通过
- market_risk 类型信号能写入 signals 表
- 集成测试：端到端流程能生成 market_risk 卡片

**产物**

- 更新的 `rules/risk_rules.yml`
- 更新的 `api/rules/eval_event.py`
- 更新的 `.env.example`

**优先级 / 预计工作量**

- 优先级：P1（重要）
- 预计耗时：4 小时

---

### 任务 P1-2: 完善 Topic 推送链路(已完成)

**背景 / 问题描述**

- 发现位置：`worker/jobs/push_topic_candidates.py`
- 触发原因：is_memeable_topic 路由集成不完整，topic_id 生成逻辑缺失
- 影响范围：话题类卡片无法正常聚合和推送

**修复目标**
完成 Topic 卡片的完整推送链路，包括聚合、去重和推送

**修复步骤**

1. 完善 `is_memeable_topic` 函数的路由集成
2. 实现 topic_id 生成算法（简单哈希或相似度聚类）
3. 实现 24h 滑动窗口聚合
4. 添加 1 小时内同 topic_id 去重机制
5. 集成到主推送流程

**验收标准**

- Topic 类信号能正确聚合
- 同一话题 1 小时内只推送一次
- 24 小时窗口统计正确
- Telegram 成功接收 Topic 卡片

**产物**

- 更新的 `worker/jobs/push_topic_candidates.py`
- 更新的 `api/services/topic_analyzer.py`

**优先级 / 预计工作量**

- 优先级：P1（重要）
- 预计耗时：6 小时

---

### 任务 P1-3: 实现 X 客户端多源支持(已完成)

**背景 / 问题描述**

- 发现位置：`api/clients/x_client.py`
- 触发原因：API v2 和 Apify 后端只有占位符 `raise NotImplementedError`
- 影响范围：只依赖 GraphQL 单一数据源，存在单点故障风险

**修复目标**
至少实现一个额外的 X 数据源（API v2 或 Apify），提供故障切换能力

**修复步骤**

1. 选择实现 API v2 或 Apify 其中一个
2. 实现完整的认证、请求、解析逻辑
3. 添加自动故障切换机制
4. 添加环境变量配置不同后端优先级
5. 实现健康检查和自动降级

**验收标准**

- `grep -c "NotImplementedError" api/clients/x_client.py` 输出减少
- 新后端能成功获取数据
- GraphQL 失败时自动切换到备用后端
- 性能测试：备用后端响应时间 < 5 秒

**产物**

- 更新的 `api/clients/x_client.py`
- 新增配置项到 `.env.example`

**优先级 / 预计工作量**

- 优先级：P1（重要）
- 预计耗时：8 小时

---

### 任务 P1-4: 改进事件聚合去重机制（阶段 A 已完成，阶段 B 待上线后优化）

**背景 / 问题描述**

- 发现位置：`api/events.py`、`api/cards/dedup.py`
- 触发原因：event_key 生成逻辑复杂，可能产生碰撞；证据合并去重易出错
- 影响范围：跨源聚合可能丢失数据，重复事件可能被误判为新事件

**修复目标**
优化 event_key 生成算法，减少碰撞；改进证据合并逻辑，防止数据丢失

**修复步骤**

1. 审查现有 event_key 生成逻辑，识别碰撞场景
2. 改进哈希算法或增加区分维度
3. 优化证据合并函数，确保不丢失重要信息
4. 添加 event_key 冲突检测和日志
5. 实现更智能的相似度判断

**验收标准**

- event_key 碰撞率 < 0.1%
- 证据合并不丢失原始链接和 post_id
- 跨源数据正确聚合
- 性能测试：聚合 1000 条事件 < 1 秒

**产物**

- 更新的 `api/events.py`
- 更新的 `api/cards/dedup.py`
- 新增单元测试

**优先级 / 预计工作量**

- 优先级：P1（重要）
- 预计耗时：6 小时

---

### 任务 P1-5: 完善状态机并发控制 （阶段 A 已完成，阶段 B 待上线后优化）

**背景 / 问题描述**

- 发现位置：`api/onchain/rules_engine.py`、状态转换相关代码
- 触发原因：并发处理同一信号可能数据不一致，Redis 锁机制可能失效
- 影响范围：状态转换可能死锁或数据损坏

**修复目标**
实现健壮的并发控制机制，确保状态转换的原子性和一致性

**修复步骤**

1. 实现分布式锁（使用 Redis 或数据库级锁）
2. 添加锁超时和死锁检测
3. 实现乐观锁或版本号机制
4. 添加状态转换事务保护
5. 实现锁竞争监控和告警

**验收标准**

- 并发更新同一信号不会产生数据不一致
- 锁超时自动释放，无死锁
- 压力测试：100 并发请求无错误
- 状态转换日志完整可追溯

**产物**

- 更新的状态机相关代码
- 新增并发控制工具类
- 更新的监控指标

**优先级 / 预计工作量**

- 优先级：P1（重要）
- 预计耗时：8 小时

---

## P2 级别任务（优化问题，2 周内改进）

### 任务 P2-1: 实现 KOL 头像识别功能

**背景 / 问题描述**

- 发现位置：Day8.1 设计要求
- 触发原因：整个图像识别链路完全未实现
- 影响范围：无法从 KOL 头像变更中提取话题信号

**修复目标**
实现基础的图像识别功能，支持头像变更检测和标签提取

**修复步骤**

1. 创建 `profile_events` 和 `profile_tags` 表
2. 创建 `worker/image_tagging.py` 实现 CLIP/OCR
3. 创建 `api/routes/topic_router.py`
4. 实现 pHash 去重
5. 创建 `resources/image_tags.yml` 和 `resources/meme_map.yml`

**验收标准**

- 能检测 KOL 头像变更
- 能提取图像标签和文字
- 去重机制有效
- 生成的话题候选合理

**产物**

- 新增数据库迁移文件
- `worker/image_tagging.py`
- `api/routes/topic_router.py`
- 资源配置文件

**优先级 / 预计工作量**

- 优先级：P2（可延后）
- 预计耗时：2 天

---

### 任务 P2-2: 优化 BigQuery 成本控制

**背景 / 问题描述**

- 发现位置：`api/providers/onchain/bq_provider.py`
- 触发原因：BQ_MAX_SCANNED_GB 未设置可能导致天价账单
- 影响范围：BigQuery 查询成本失控风险

**修复目标**
实现完善的 BigQuery 成本守护机制

**修复步骤**

1. 强制要求设置 `BQ_MAX_SCANNED_GB` 环境变量
2. 实现 dry_run 预检查，超限拒绝执行
3. 添加查询成本日志和告警
4. 优化 SQL 查询减少扫描量
5. 实现更智能的缓存策略

**验收标准**

- 未设置 BQ_MAX_SCANNED_GB 时拒绝启动
- dry_run 正确估算并拦截超限查询
- 每日成本报表生成
- 缓存命中率 > 80%

**产物**

- 更新的 `api/providers/onchain/bq_provider.py`
- 成本监控脚本
- 更新的 `.env.example`

**优先级 / 预计工作量**

- 优先级：P2（可延后）
- 预计耗时：4 小时

---

### 任务 P2-3: 增强 LLM 降级机制

**背景 / 问题描述**

- 发现位置：`api/rules/refiner_adapter.py`
- 触发原因：LLM 超时或失败时降级链路可能失效
- 影响范围：LLM 服务异常时整个精析功能瘫痪

**修复目标**
实现多层降级机制，确保服务高可用

**修复步骤**

1. 实现超时自动降级到规则引擎
2. 添加 LLM 健康检查和熔断器
3. 实现多模型故障切换
4. 添加降级率监控
5. 优化 JSON Schema 验证，减少丢弃率

**验收标准**

- LLM 超时 3 秒自动降级
- 降级后服务可用性 > 99%
- JSON 验证通过率 > 90%
- 降级事件有完整日志

**产物**

- 更新的 `api/rules/refiner_adapter.py`
- 新增熔断器组件
- 监控告警配置

**优先级 / 预计工作量**

- 优先级：P2（可延后）
- 预计耗时：6 小时

---

### 任务 P2-4: 改进 Telegram 重试机制

**背景 / 问题描述**

- 发现位置：`api/services/telegram.py`、`worker/jobs/outbox_retry.py`
- 触发原因：Outbox 重试可能死循环，速率限制处理不当
- 影响范围：消息可能丢失或重复发送

**修复目标**
实现智能的重试和限流机制

**修复步骤**

1. 实现指数退避重试策略
2. 添加最大重试次数限制
3. 实现令牌桶限流算法
4. 优化幂等键生成避免冲突
5. 添加死信队列处理

**验收标准**

- 重试间隔递增：1s, 2s, 4s, 8s...
- 最多重试 5 次后进入死信队列
- 速率限制遵守 Telegram API 要求
- 无消息丢失或重复

**产物**

- 更新的 `api/services/telegram.py`
- 更新的 `worker/jobs/outbox_retry.py`
- 新增死信队列处理逻辑

**优先级 / 预计工作量**

- 优先级：P2（可延后）
- 预计耗时：4 小时

---

### 任务 P2-5: 优化热度计算性能

**背景 / 问题描述**

- 发现位置：`api/signals/heat.py`
- 触发原因：斜率计算可能 NaN，热度持久化可能失败
- 影响范围：热度指标不准确或计算失败

**修复目标**
提升热度计算的准确性和可靠性

**修复步骤**

1. 处理数据不足时的 NaN 问题
2. 实现热度计算缓存
3. 优化斜率算法
4. 添加异常值过滤
5. 实现批量持久化

**验收标准**

- 无 NaN 或 Inf 输出
- 计算性能 < 100ms
- 持久化成功率 > 99.9%
- 热度趋势准确反映实际

**产物**

- 更新的 `api/signals/heat.py`
- 新增单元测试
- 性能测试报告

**优先级 / 预计工作量**

- 优先级：P2（可延后）
- 预计耗时：4 小时

---

### 任务 P2-6: 完善监控告警系统

**背景 / 问题描述**

- 发现位置：`alerts.yml`、监控相关代码
- 触发原因：告警规则可能误报，缺少关键指标监控
- 影响范围：无法及时发现和响应系统问题

**修复目标**
建立完善的监控告警体系

**修复步骤**

1. 添加关键业务指标监控
2. 优化告警阈值减少误报
3. 实现告警聚合和抑制
4. 添加自定义监控面板
5. 实现告警自动升级机制

**验收标准**

- 误报率 < 5%
- 关键故障 3 分钟内告警
- 告警信息包含处理建议
- 监控覆盖率 > 90%

**产物**

- 更新的 `alerts.yml`
- 新增 Grafana 面板配置
- 告警处理 SOP 文档

**优先级 / 预计工作量**

- 优先级：P2（可延后）
- 预计耗时：1 天

---

## 任务执行计划

### 第一阶段（1-2 天）

- 完成所有 P0 任务
- 建立基本的四种卡片类型支持

### 第二阶段（3-7 天）

- 完成 P1 任务
- 确保核心功能完整可用

### 第三阶段（8-14 天）

- 完成 P2 任务
- 持续优化和改进

## 验收检查清单

```bash
# P0 验收
- [ ] signals 表包含 type 字段
- [ ] 四种卡片模板都存在
- [ ] 卡片路由逻辑完整

# P1 验收
- [ ] market_risk 判定工作
- [ ] topic 推送链路完整
- [ ] 至少两个 X 数据源可用
- [ ] 事件聚合准确
- [ ] 并发控制稳定

# P2 验收
- [ ] 图像识别功能可用
- [ ] BigQuery 成本可控
- [ ] LLM 降级机制健壮
- [ ] Telegram 推送可靠
- [ ] 热度计算准确
- [ ] 监控告警完善
```

## 风险提示

1. **数据迁移风险**：修改 signals 表结构需要谨慎处理现有数据
2. **兼容性风险**：确保新增字段和逻辑向后兼容
3. **性能风险**：新增功能可能影响系统性能，需要压力测试
4. **成本风险**：BigQuery 和 LLM 调用需要严格控制成本

## 回归测试要求

每个任务完成后必须执行：

1. 单元测试：`pytest tests/`
2. 集成测试：端到端流程验证
3. 性能测试：确保 P95 < 2 分钟
4. 回归测试：之前的功能仍然正常

---

_本文档将根据实际修复进度持续更新_
