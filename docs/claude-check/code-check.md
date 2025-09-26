# MVP28 代码实现检查报告

生成时间: 2025-09-22
检查方式: 设计文档对照代码实现
基准文档: docs/mvp28-done.md

## 一、执行摘要

### 整体完成情况

- **设计完成度**: 100%（MVP28 文档完整）
- **代码完成度**: 约 60%（核心链路有断点）
- **可运行程度**: Primary/Secondary 卡片基本可用，Topic/Market Risk 不可用

### 关键问题

1. **数据模型偏离设计**: signals 表缺少 type 字段，无法区分 4 种卡片类型
2. **Topic 链路断裂**: Day8.1 图像识别完全未实现，Day9.1 缺少模板
3. **Market Risk 缺失**: Day18 要求的 market_risk 类型完全未实现
4. **X 平台接入不完整**: 仅 GraphQL 实现，API v2/Apify 为占位符

## 二、设计 vs 实现对照表

### 2.1 核心数据流

| 设计要求              | 实现状态 | 问题说明                 |
| --------------------- | -------- | ------------------------ |
| 固定 KOL 采集         | ✅ 70%   | 仅 GraphQL，无 API/Apify |
| 初筛（HF+规则）       | ✅ 100%  | 完整实现                 |
| 事件聚合（event_key） | ✅ 100%  | 完整实现                 |
| 精析（LLM 结构化）    | ✅ 100%  | 完整实现                 |
| 合约体检（GoPlus）    | ✅ 100%  | 完整实现                 |
| DEX 数据              | ✅ 100%  | 双源实现                 |
| Telegram 推送         | ✅ 80%   | 缺部分模板               |

### 2.2 四种卡片类型

| 卡片类型        | 设计要求        | 实现状态 | 缺失部分                                                                                                        |
| --------------- | --------------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| **Topic**       | Day8.1 + Day9.1 | ❌ 20%   | • 无 profile_events/profile_tags 表<br>• 无 image_tagging.py<br>• 无 topic_router.py<br>• 缺 topic_card.j2 模板 |
| **Primary**     | GoPlus 门禁     | ✅ 90%   | 基本完整                                                                                                        |
| **Secondary**   | 链上验证        | ✅ 80%   | 基本完整                                                                                                        |
| **Market Risk** | Day18 规则引擎  | ❌ 0%    | • 无规则定义<br>• 无模板文件<br>• 无推送逻辑                                                                    |

### 2.3 数据模型对比

#### 设计要求（MVP28）

```sql
-- signals表应该有
CREATE TABLE signals (
    event_key TEXT,
    type ENUM('topic','primary','secondary','market_risk'),  -- 关键字段
    market_type TEXT,
    -- 其他字段...
);
```

#### 实际实现（001_initial_tables.py）

```sql
-- signals表现状
CREATE TABLE signals (
    event_key TEXT,
    market_type TEXT,  -- 有这个但不是type
    -- 缺少: type字段
);
```

## 三、业务流程断点分析

### 3.1 Topic 卡片流程（断裂）

```
设计流程:
KOL头像变更 → 图像下载 → CLIP/OCR识别 → 话题提取
→ 写signals(type=topic) → 生成Topic卡片 → Telegram推送

实现状态:
KOL头像URL获取 ✅ → [断点：无图像处理] → push_topic_candidates ✅
→ [断点：无模板] → Telegram推送 ✅
```

**断点位置**:

1. worker/image_tagging.py 不存在
2. router/topic_router.py 不存在
3. templates/cards/topic_card.j2 不存在

### 3.2 Primary 卡片流程（基本完整）

```
设计流程:
X采集(含CA) → Filter → Refine → GoPlus检查 → DEX数据
→ 写signals(type=primary) → 生成Primary卡片 → Telegram推送

实现状态:
X采集 ✅ → Filter ✅ → Refine ✅ → GoPlus ✅ → DEX ✅
→ 写signals ✅ → 生成卡片 ✅ → Telegram ✅
```

### 3.3 Secondary 卡片流程（基本完整）

```
设计流程:
BigQuery链上数据 → 特征计算 → 规则评估 → 状态升级
→ 写signals(type=secondary) → 生成Secondary卡片 → Telegram推送

实现状态:
BigQuery ✅ → 特征计算 ✅ → 规则评估 ✅ → 状态升级 ✅
→ 写signals ✅ → 生成卡片 ✅ → Telegram ✅
```

### 3.4 Market Risk 卡片流程（完全缺失）

```
设计流程:
市场监控 → 规则引擎判定 → 写signals(type=market_risk)
→ 生成Market Risk卡片 → Telegram推送

实现状态:
[全链路未实现]
```

## 四、关键缺失组件清单

### 4.1 数据库缺失

| 表名              | 用途              | 影响               |
| ----------------- | ----------------- | ------------------ |
| signals.type 字段 | 区分 4 种卡片类型 | 无法路由不同卡片   |
| profile_events    | KOL 资料变更记录  | Day8.1 无法工作    |
| profile_tags      | 头像识别结果      | Topic 候选无法生成 |

### 4.2 代码文件缺失

| 文件路径                               | 功能              | 影响                |
| -------------------------------------- | ----------------- | ------------------- |
| workers/image_tagging.py               | CLIP/OCR 图像识别 | 无法识别头像 meme   |
| router/topic_router.py                 | 话题路由生成      | 无法生成 topic 候选 |
| api/clients/x_client.py (APIXClient)   | X API v2 实现     | 仅占位符            |
| api/clients/x_client.py (ApifyXClient) | Apify 实现        | 仅占位符            |

### 4.3 模板文件缺失

| 模板文件                            | 用途                 | 现状    |
| ----------------------------------- | -------------------- | ------- |
| templates/cards/topic_card.j2       | Topic 卡片模板       | 不存在  |
| templates/cards/market_risk_card.j2 | Market Risk 卡片模板 | 不存在  |
| templates/cards/primary_card.j2     | Primary 卡片模板     | ✅ 存在 |
| templates/cards/secondary_card.j2   | Secondary 卡片模板   | ✅ 存在 |

## 五、代码中的权宜之计

### 5.1 卡片类型判断（临时逻辑）

```python
# api/cards/build.py:528-533
# 没有基于type字段，而是基于规则级别判断
if 'onchain' in data and data.get('rules', {}).get('level') in ['caution', 'risk']:
    card['card_type'] = 'primary'
elif data.get('rules', {}).get('level') == 'watch':
    card['card_type'] = 'secondary'
else:
    card['card_type'] = 'topic'  # 默认值
```

### 5.2 Topic 推送（有函数无模板）

```python
# worker/jobs/push_topic_candidates.py
def format_topic_message():  # 手工格式化消息
    # 实现了但没用模板系统
```

## 六、修复优先级建议

### P0 - 阻塞核心功能（必须修复）

1. **添加 signals.type 字段**

   ```sql
   ALTER TABLE signals
   ADD COLUMN type VARCHAR(20)
   CHECK (type IN ('topic','primary','secondary','market_risk'));
   ```

2. **创建 Topic 卡片模板**

   - 新建 templates/cards/topic_card.j2

3. **实现 X 平台多源**
   - 至少实现 API v2 或 Apify 之一

### P1 - 完善主要功能

1. **实现 Day8.1 图像识别链路**

   - 创建 profile_events, profile_tags 表
   - 实现 image_tagging.py (CLIP/OCR)
   - 实现 topic_router.py

2. **实现 Market Risk**
   - 添加规则定义到 rules/rules.yml
   - 创建 market_risk_card.j2 模板
   - 实现推送逻辑

### P2 - 优化完善

1. 统一卡片路由机制
2. 完善错误处理
3. 增加监控指标

## 七、影响评估

### 7.1 当前可用功能

- ✅ Primary 卡片（代币+GoPlus）正常
- ✅ Secondary 卡片（链上验证）正常
- ✅ 基础推送功能正常

### 7.2 不可用功能

- ❌ Topic 卡片（话题候选）无法生成
- ❌ Market Risk 卡片完全不工作
- ❌ KOL 头像 meme 识别不工作
- ❌ 卡片类型区分机制失效

### 7.3 数据完整性风险

- signals 表数据无法区分类型
- 后续数据分析困难
- 无法统计各类卡片效果

## 八、结论

1. **核心问题不是 bug，而是功能未实现**

   - 约 40%的设计功能没有对应代码
   - 关键数据模型偏离设计

2. **Primary/Secondary 链路基本可用**

   - 这两个是最核心的功能
   - 完成度较高

3. **Topic/Market Risk 完全不可用**

   - Topic 缺少整个图像识别链路
   - Market Risk 完全未开始

4. **建议采取措施**
   - 紧急: 加 type 字段，修复数据模型
   - 短期: 补充 Topic 模板，让基础 Topic 工作
   - 中期: 实现完整的 Day8.1 和 Day18 功能

## 附录：快速定位

### 查看缺失的 type 字段

```bash
grep -n "type.*ENUM" api/alembic/versions/*.py
# 结果: 无匹配（证实缺失）
```

### 查找图像处理代码

```bash
find . -name "*image*.py" -o -name "*tagging*.py"
# 结果: 无相关文件（证实未实现）
```

### 查看卡片模板

```bash
ls templates/cards/
# 结果: 只有primary和secondary模板
```

### 检查 market_risk

```bash
grep -r "market_risk" --include="*.py"
# 结果: 仅在文档中提及，代码中无实现
```
