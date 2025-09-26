# MVP28 业务流程分析报告

生成时间: 2025-09-22
基于文档: docs/claude-check/mvp28-done.md

## 一、设计中的完整业务流程

### 1. 核心数据流（Day0 设计）

```
固定 KOL 采集 → 初筛（HF 小模型+规则）→ 事件聚合（event_key）
→ 精析（小号 LLM，结构化输出）→ 合约体检（GoPlus）
→ DEX 数据（DexScreener/GeckoTerminal）→ 信号与 Telegram 推送
```

### 2. 四种卡片类型设计

根据 MVP 设计，系统应该支持 4 种卡片类型：

#### 2.1 Topic 卡片（话题候选）

- **触发源**:
  - KOL 头像/简介变更（Day8.1）
  - 社交热点话题聚合（Day9.1）
- **特征**:
  - 无具体代币/CA
  - 仅话题关键词
  - 风险提示："未落地为币，谨防仿冒"
- **必含字段**:
  ```
  type=topic
  topic_id
  topic_entities[]
  confidence
  sources[]
  risk_note="未落地为币，谨防仿冒"
  verify_path="新池/新合约 → GoPlus/BQ"
  ```

#### 2.2 Primary 卡片（一级信号）

- **触发源**: 明确的代币/CA 首次出现
- **流程**: 候选 → GoPlus 体检 → 风险标记（红/黄/绿）
- **门禁**: 必须通过 GoPlus 安全检查
- **特征**: 有具体 CA，经过安全验证

#### 2.3 Secondary 卡片（二级信号）

- **触发源**: 已验证代币的后续信号
- **特征**:
  - 来源分级（rumor/confirmed）
  - 包含 features_snapshot
  - data_as_of 时间戳

#### 2.4 Market Risk 卡片（市场风险）

- **触发源**: Day18 规则引擎判定
- **特征**: 市场异动、风险预警

## 二、完整的信号到推送流程

### 流程 A：社交信号 → Topic 卡片

```
1. X/Twitter 采集（KOL 推文/头像变更）
   ↓
2. Filter（情感分析、关键词提取）
   ↓
3. 话题识别（is_memeable_topic）
   - KeyBERT 提取关键词
   - Mini LLM 判定是否 meme 话题
   ↓
4. 话题聚合（topic_id 生成）
   - 24h 滑动窗口
   - 相似度聚类
   ↓
5. 写入 signals 表（type=topic）
   ↓
6. 生成 Topic 卡片
   ↓
7. Telegram 推送
```

### 流程 B：代币信号 → Primary 卡片

```
1. X/Twitter 采集（含 CA/symbol）
   ↓
2. Filter + Refine（LLM 结构化）
   ↓
3. 事件聚合（event_key）
   ↓
4. GoPlus 安全检查 ← 【门禁】
   ↓
5. DEX 数据获取
   ↓
6. 写入 signals 表（type=primary）
   ↓
7. 风险评级（红/黄/绿）
   ↓
8. 生成 Primary 卡片
   ↓
9. Telegram 推送
```

### 流程 C：链上验证 → Secondary 卡片

```
1. BigQuery 链上数据
   ↓
2. onchain_features 特征计算
   ↓
3. 规则引擎评估
   ↓
4. 状态升级（candidate → verified）
   ↓
5. 写入 signals 表（type=secondary）
   ↓
6. 生成 Secondary 卡片
   ↓
7. Telegram 推送
```

### 流程 D：市场异动 → Market Risk 卡片

```
1. DEX/CEX 数据监控
   ↓
2. 规则引擎判定（Day18）
   ↓
3. 写入 signals 表（type=market_risk）
   ↓
4. 生成 Market Risk 卡片
   ↓
5. Telegram 推送
```

## 三、代码实现状态检查

### ✅ 已实现的链路

1. **基础 Pipeline**

   - raw_posts 采集存储 ✅
   - filter/refine/dedup ✅
   - events 事件聚合 ✅
   - signals 信号生成 ✅

2. **外部数据源**

   - X/Twitter GraphQL ✅
   - GoPlus 安全检查 ✅
   - DEX 双源数据 ✅
   - BigQuery 链上数据 ✅

3. **推送系统**
   - Telegram 基础推送 ✅
   - 去重机制 ✅
   - Outbox 重试 ✅

### ❌ 关键缺失的链路

#### 1. 数据模型问题

**问题**: signals 表缺少 type 字段

```sql
-- 现状（001_initial_tables.py）
CREATE TABLE signals (
    event_key TEXT,
    market_type TEXT,  -- 有这个但不是 type
    -- 缺少: type ENUM('topic','primary','secondary','market_risk')
)

-- MVP 设计要求
signals 表应该有:
type ENUM('topic','primary','secondary','market_risk')
```

**影响**: 无法区分四种卡片类型，整个分流机制失效

#### 2. Topic 卡片链路

**设计要求**:

- Day8.1: KOL 头像变更 → 图像识别 → topic 候选
- Day9.1: 话题聚合 → topic 卡片

**实现状态**:

- ❌ profile_events 表不存在
- ❌ profile_tags 表不存在
- ❌ image_tagging.py 不存在（CLIP/OCR）
- ❌ topic_router.py 不存在
- ✅ push_topic_candidates.py 存在但不完整
- ❌ topic_card.j2 模板不存在

**代码检查**:

```python
# worker/jobs/push_topic_candidates.py
def format_topic_message() # 有实现但缺模板
# 缺少: templates/cards/topic_card.j2
```

#### 3. Market Risk 卡片链路

**设计要求**: Day18 规则引擎应支持 market_risk 判定

**实现状态**:

- ❌ 规则中无 market_risk 定义
- ❌ 无 market_risk_card 模板
- ❌ 无相关推送逻辑

#### 4. 卡片类型路由

**问题**: 无法根据 type 字段路由到不同模板

```python
# api/cards/generator.py 现状
if event.get("type") == "primary":  # 硬编码判断
    # primary 逻辑
if event.get("type") == "secondary":
    # secondary 逻辑
# 缺少 topic 和 market_risk 分支
```

## 四、问题根源分析

### 1. 架构层面

- **根本问题**: signals 表设计不支持多类型
- **影响范围**: 整个卡片分流机制无法工作

### 2. 实现层面

完成度统计：

- Topic 链路: 20% (仅有推送函数)
- Primary 链路: 90% (基本完成)
- Secondary 链路: 80% (基本完成)
- Market Risk 链路: 0% (完全未实现)

### 3. 缺失组件清单

| 组件              | 文件路径                            | 状态      |
| ----------------- | ----------------------------------- | --------- |
| signals.type 字段 | api/alembic/versions/               | ❌ 缺失   |
| profile_events 表 | api/alembic/versions/               | ❌ 缺失   |
| profile_tags 表   | api/alembic/versions/               | ❌ 缺失   |
| 图像处理          | workers/image_tagging.py            | ❌ 不存在 |
| 话题路由          | router/topic_router.py              | ❌ 不存在 |
| Topic 模板        | templates/cards/topic_card.j2       | ❌ 不存在 |
| Market Risk 模板  | templates/cards/market_risk_card.j2 | ❌ 不存在 |
| Market Risk 规则  | rules/rules.yml                     | ❌ 无定义 |

## 五、修复建议

### 优先级 P0（阻塞核心流程）

1. **添加 signals.type 字段**

   ```sql
   ALTER TABLE signals ADD COLUMN type VARCHAR(20);
   -- 或使用 ENUM
   ```

2. **实现基础 Topic 链路**
   - 创建 topic_card.j2 模板
   - 完善 push_topic_candidates.py

### 优先级 P1（完善功能）

1. **实现 Day8.1 头像识别**

   - 创建 profile_events/profile_tags 表
   - 实现 image_tagging.py
   - 实现 topic_router.py

2. **实现 Market Risk**
   - 添加规则定义
   - 创建模板
   - 实现推送逻辑

### 优先级 P2（优化）

1. 统一卡片路由机制
2. 完善类型系统

## 六、总结

MVP 设计的业务流程是完整的，但实现存在关键断点：

1. **数据模型缺陷**: signals 表缺少 type 字段，导致无法区分卡片类型
2. **Topic 链路断裂**: 头像识别完全未实现，topic 卡片缺少模板
3. **Market Risk 缺失**: 完全没有实现
4. **整体完成度**: 约 60%（比文件检查的 70% 更低）

主要问题不是"代码有 bug"，而是"关键组件根本没写"。
