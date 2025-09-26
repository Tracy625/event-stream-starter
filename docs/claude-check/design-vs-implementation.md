# MVP28 设计 vs 实际代码缺失对照表

生成时间: 2025-09-22
基准: mvp28-done.md（设计文档） vs complete-risk-assessment.md（实际检查）
说明: 仅列出有缺失或问题的任务，完全实现的任务不列入

## 🔴 完全缺失的功能（设计了但完全没写）

### Day8.1: KOL Profile 变更与头像语义标签

**设计要求**：

- 轮询 KOL 资料变更并落库、下载头像
- CLIP/SigLIP + OCR + pHash 去重，产出标签与实体
- 新表: profile_events（资料变更原始事件）
- 新表: profile_tags（头像推理结果）
- 文件: workers/image_tagging.py, router/topic_router.py
- 资源: resources/image_tags.yml, resources/meme_map.yml

**实际情况**：

- ❌ profile_events 表不存在
- ❌ profile_tags 表不存在
- ❌ image_tagging.py 文件不存在
- ❌ topic_router.py 文件不存在
- ❌ CLIP/OCR 功能完全未实现

---

### Day9.1: Meme 话题卡最小链路（部分缺失）

**设计要求**：

- signals 表增加 type 字段: ENUM('topic','primary','secondary','market_risk')
- is_memeable_topic 路由实现
- 建立 topic_id（简单哈希/相似度聚类）
- templates/topic_card.j2 模板文件
- 支持 24h 聚合，同 topic_id 一小时内只推一次

**实际情况**：

- ❌ signals 表缺少 type 字段（只有 market_type 字段）
- ❌ topic_card.j2 模板不存在
- ✅ topic 聚合逻辑部分实现（api/services/topic_analyzer.py）
- ⚠️ is_memeable_topic 函数存在但路由集成不完整

---

### Day18: 规则引擎 + Market Risk 卡片

**设计要求**：

- 输出 observe/caution/opportunity/market_risk 四档
- templates/market_risk_card.j2 模板
- 市场风险预警功能
- 热加载规则支持

**实际情况**：

- ❌ market_risk 类型完全未实现
- ❌ 规则引擎只有 observe/caution/opportunity 三档
- ❌ market_risk_card.j2 模板不存在
- ✅ 热加载功能已实现（api/config/hotreload.py）

---

## 🟡 部分缺失或实现有问题

### Day5: 事件聚合与 event_key

**设计要求**：

- event_key 生成：归一化实体+主题关键词+时间窗口
- 合并证据：evidence[]放来源链接与 post_id
- 维护 start_ts/last_ts 与 heat 指标

**实际情况**：

- ✅ event_key 生成逻辑已实现
- ⚠️ event_key 可能碰撞（生成逻辑复杂）
- ⚠️ 证据合并去重易出错
- ⚠️ 跨源聚合可能丢失数据

---

### Day8: X KOL 采集（多源缺失）

**设计要求**：

- 三种后端支持：GraphQL、API v2、Apify
- 5-10 个 KOL，2 分钟轮询
- 规范化文本/URL/合约

**实际情况**：

- ✅ GraphQL 后端已实现并可用
- ❌ API v2 完全未实现（仅占位符 raise NotImplementedError）
- ❌ Apify 完全未实现（仅占位符 raise NotImplementedError）
- ⚠️ 单点故障风险（只有 GraphQL 能用）

---

### Day13: 证据块验证与状态机

**设计要求**：

- 候选 S0 → 几分钟后升级 S2（verified/downgraded/withdrawn）
- 规则 DSL：rules/onchain.yml
- 超时>12 分钟未取到证据时保持候选

**实际情况**：

- ✅ 状态机基本实现
- ⚠️ 状态转换可能死锁
- ⚠️ 并发处理同一信号可能数据不一致
- ⚠️ Redis 锁机制可能失效

---

### Day10-12: BigQuery 链上数据

**设计要求**：

- 成本守护：BQ_MAX_SCANNED_GB 限制
- dry_run 估算扫描量
- 三个 SQL 模板（active_addrs、token_transfers、top_holders）
- 缓存 60-120 秒

**实际情况**：

- ✅ 基础功能已实现
- ⚠️ BQ_MAX_SCANNED_GB 未设置可能天价账单
- ⚠️ dry_run 守护可能被绕过
- ⚠️ 缓存失效可能重复查询

## 🟠 已实现但有隐患

### Day6: LLM 精析器

**设计要求**：

- 触发条件：候选打分 ≥ 阈值或 evidence 数 ≥2
- 使用 mini LLM 产出严格 JSON
- JSON schema 校验，不合格丢弃

**实际情况**：

- ✅ 功能已实现
- ⚠️ JSON Schema 验证可能大量丢弃数据
- ⚠️ LLM 超时处理不当可能阻塞
- ⚠️ 降级链路可能失效

---

### Day15-16: 跨源聚合与热度计算

**设计要求**：

- 跨源合并，固定 event_key 不变性
- 计算 10m/30m/recent 计数、斜率、环比

**实际情况**：

- ✅ 基本功能实现
- ⚠️ EVENT_MERGE_STRICT 配置敏感
- ⚠️ 斜率计算可能 NaN（数据不足）
- ⚠️ 热度持久化可能失败

---

### Day20-21: Telegram 推送

**设计要求**：

- 推送到频道，绑定讨论组
- 1 小时内同 event_key 去重
- 失败入 outbox 重试队列

**实际情况**：

- ✅ 推送功能已实现
- ⚠️ 速率限制可能导致消息丢失
- ⚠️ Outbox 重试可能死循环
- ⚠️ 幂等键可能冲突

## 统计汇总

| 风险等级     | 任务数量 | 主要问题                                                 |
| ------------ | -------- | -------------------------------------------------------- |
| 完全缺失 🔴  | 3 个     | Day8.1 图像识别、Day9.1 部分、Day18 市场风险             |
| ~~误判更正~~ | 1 个     | Day14 专家视图（已确认完整实现）                         |
| 部分缺失 🟡  | 6 个     | Day5 聚合、Day8 采集、Day13 状态机、Day10-12 BigQuery 等 |
| 有隐患 🟠    | 6 个     | Day6 精析、Day15-16 热度、Day20-21 推送等                |
| 基本完成 ✅  | 8 个     | Day1-4 基础、Day7 GoPlus、Day9 DEX、Day17 HF 等          |

## 紧急修复优先级

### P0 - 阻塞性问题（必须立即修复）

1. **signals.type 字段缺失**

   - 影响：无法区分 4 种卡片类型
   - 修复：添加 type ENUM 字段，迁移现有数据

2. **market_risk 完全缺失**

   - 影响：市场风险预警功能缺失
   - 修复：实现 market_risk 判定逻辑和模板

3. **topic_card.j2 模板缺失**
   - 影响：topic 类型卡片无法渲染
   - 修复：创建模板文件

### P1 - 功能性问题（1 周内修复）

1. 实现 X API v2 或 Apify 后端（避免单点故障）
2. 实现 Day8.1 图像识别基础功能
3. ~~添加专家视图路由和限流~~（已完成）
4. 完善状态机并发控制

### P2 - 优化问题（2 周内改进）

1. 优化 event_key 生成避免碰撞
2. 完善 BigQuery 成本控制
3. 增强 LLM 降级机制
4. 改进 Telegram 重试逻辑

## 快速验证命令

```bash
# 检查最严重的问题
echo "1. 检查signals.type字段..."
docker compose exec -T db psql -U app -c "\d signals" | grep type

echo "2. 检查market_risk实现..."
grep -r "market_risk" api/ rules/ --include="*.py" --include="*.yml"

echo "3. 检查缺失的模板..."
ls templates/cards/{topic,market_risk}_card.j2 2>/dev/null

echo "4. 检查X客户端实现..."
grep -c "NotImplementedError" api/clients/x_client.py

echo "5. 检查图像处理组件..."
find . -name "image_tagging.py" -o -name "topic_router.py"
```
