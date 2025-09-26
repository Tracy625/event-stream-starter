# MVP28 高风险任务体检清单

生成时间: 2025-09-22
用途: 标识容易出错的任务供重点体检

## 🔴 极高风险任务（最容易出问题）

### Day18: 规则引擎 + Market Risk卡片（完全缺失）
**风险点**：
1. **market_risk类型完全未实现**
   - 文档要求有market_risk卡片类型
   - 规则引擎中没有相关定义
   - 没有market_risk_card.j2模板
   - **严重问题**: 整个市场风险预警功能缺失

2. **规则引擎只实现了部分**
   - 只有observe/caution/opportunity三档
   - 缺少market_risk判定逻辑
   - **容易出错**: 市场异动无法触发警报

3. **热加载并发安全问题**
   - 多线程同时加载规则可能冲突
   - **容易出错**: 规则版本不一致

**体检命令**：
```bash
# 检查market_risk实现
grep -r "market_risk" rules/ api/ --include="*.py" --include="*.yml"

# 检查模板文件
ls templates/cards/market_risk_card.j2 2>/dev/null || echo "MISSING: market_risk template"

# 测试规则引擎是否支持market_risk
curl -s "http://localhost:8000/rules/eval?event_key=test" | jq '.level' | grep -q "market_risk" || echo "market_risk NOT supported"
```

### Day5: 事件聚合与 event_key
**风险点**：
1. **event_key生成逻辑复杂**
   - 需要归一化实体（symbol/CA）
   - 需要主题关键词
   - 需要时间窗口
   - **容易出错**: event_key不唯一或碰撞

2. **证据合并去重**
   - evidence[] 数组需要去重
   - 同一事件的多个来源需要合并
   - **容易出错**: 重复证据或丢失证据

**体检命令**：
```bash
# 检查event_key唯一性
docker compose exec -T db psql -U app -c "SELECT event_key, COUNT(*) FROM events GROUP BY event_key HAVING COUNT(*) > 1;"

# 检查证据合并
python scripts/verify_events.py --sample scripts/replay.jsonl
```

### Day8.1: KOL Profile变更与头像语义（整个链路缺失）
**风险点**：
1. **表不存在**: profile_events, profile_tags
2. **文件不存在**: image_tagging.py, topic_router.py
3. **CLIP/OCR未实现**
4. **pHash去重可能失效**
5. **置信度计算公式复杂**

**体检命令**：
```bash
# 检查表是否存在
docker compose exec -T db psql -U app -c "\dt profile_*"

# 检查文件
find . -name "image_tagging.py" -o -name "topic_router.py"
```

### Day9.1: Meme话题卡最小链路
**风险点**：
1. **signals表缺少type字段** - 无法标记卡片类型
2. **topic_id生成规则复杂**
   - 相似度聚类
   - 24h滑动窗口
   - **容易出错**: topic_id碰撞或不一致

3. **缺少模板文件**: topic_card.j2

**体检命令**：
```bash
# 检查type字段
docker compose exec -T db psql -U app -c "\d signals" | grep type

# 检查模板
ls templates/cards/topic_card.j2
```

### Day13-14: 链上验证与状态机
**风险点**：
1. **状态转换逻辑复杂**
   - candidate → verified/downgraded/withdrawn
   - **容易出错**: 状态机死锁或循环

2. **BigQuery成本失控**
   - 没有cost_guard可能扫描全表
   - **容易出错**: 天价账单

3. **并发问题**
   - 多个worker同时处理同一信号
   - **容易出错**: 数据不一致

**体检命令**：
```bash
# 检查状态分布
docker compose exec -T db psql -U app -c "SELECT state, COUNT(*) FROM signals GROUP BY state;"

# 检查BigQuery成本守护
grep "BQ_MAX_SCANNED_GB" .env
```

## 🟡 中高风险任务

### Day6: LLM精析器
**风险点**：
1. **JSON Schema验证**
   - LLM输出可能不符合schema
   - **容易出错**: 大量数据被丢弃

2. **超时处理**
   - LLM调用可能超时
   - **容易出错**: 阻塞pipeline

**体检命令**：
```bash
# 检查精析成功率
grep "refine.success\|refine.error" logs/api.log | wc -l
```

### Day15-16: 跨源聚合与热度计算
**风险点**：
1. **跨源证据合并**
   - EVENT_MERGE_STRICT设置影响行为
   - **容易出错**: 证据丢失或重复

2. **斜率计算**
   - 10m/30m窗口数据可能不足
   - **容易出错**: 斜率为NaN

**体检命令**：
```bash
# 测试严格/宽松模式
EVENT_MERGE_STRICT=true python scripts/verify_events.py
EVENT_MERGE_STRICT=false python scripts/verify_events.py

# 检查热度计算
curl -s "http://localhost:8000/signals/heat?token_ca=0xtest" | jq
```

### ~~Day18: 规则引擎~~ （已移至极高风险）

## 🟢 低风险任务（相对稳定）

### Day1-4: 基础架构
- 基本都实现了
- 风险较低

### Day7: GoPlus集成
- 实现完整
- 有降级机制

### Day9: DEX快照
- 双源冗余
- 缓存机制完善

### Day10-12: BigQuery基础
- 有cost_guard保护
- 有缓存机制

## 重点体检顺序

### 第一优先级（阻塞性问题）
1. **signals.type字段** - 检查是否存在（影响所有卡片类型）
2. **market_risk完全缺失** - Day18要求的核心功能
3. **event_key唯一性** - 检查是否有重复
4. **Topic模板** - 检查文件是否存在

### 第二优先级（功能性问题）
1. **Day8.1整个链路** - 检查组件是否存在
2. **热度计算** - 检查是否返回正确值
3. **状态机** - 检查状态转换是否正常

### 第三优先级（性能/成本问题）
1. **BigQuery成本** - 检查限制是否生效
2. **LLM超时** - 检查降级是否工作
3. **并发安全** - 检查锁机制

## 快速体检脚本

```bash
#!/bin/bash
echo "=== MVP28 高风险任务快速体检 ==="

echo "\n1. 检查signals.type字段..."
docker compose exec -T db psql -U app -c "\d signals" | grep -E "type|market_type"

echo "\n2. 检查event_key重复..."
docker compose exec -T db psql -U app -c "SELECT event_key, COUNT(*) c FROM events GROUP BY event_key HAVING COUNT(*) > 1 LIMIT 5;"

echo "\n3. 检查缺失的表..."
docker compose exec -T db psql -U app -c "\dt" | grep -E "profile_events|profile_tags|onchain_features"

echo "\n4. 检查缺失的文件..."
ls templates/cards/*.j2 | grep -E "topic|market"
find . -name "image_tagging.py" 2>/dev/null

echo "\n5. 检查BigQuery守护..."
grep "BQ_MAX_SCANNED_GB" .env || echo "WARNING: No BQ cost guard!"

echo "\n6. 检查热度API..."
curl -s "http://localhost:8000/signals/heat?token_ca=0x0000000000000000000000000000000000000000" | jq '.error // "OK"'

echo "\n7. 检查规则引擎..."
curl -s "http://localhost:8000/rules/eval?event_key=test:test:2025" | jq '.level // "FAILED"'

echo "\n8. 检查market_risk支持..."
grep -r "market_risk" rules/ api/ --include="*.yml" --include="*.py" | head -3
ls templates/cards/market_risk_card.j2 2>/dev/null || echo "ERROR: No market_risk template!"

echo "\n=== 体检完成 ==="
```

## 总结

最容易出问题的地方：
1. **数据模型缺陷**（signals.type字段）
2. **整个组件缺失**（Day8.1链路）
3. **复杂的聚合逻辑**（event_key, topic_id）
4. **状态机管理**（并发、死锁）
5. **成本控制**（BigQuery扫描）

建议先运行快速体检脚本，找出最严重的问题优先修复。