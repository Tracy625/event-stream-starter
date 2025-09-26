# MVP28 完整风险评估报告（Day0-24）

生成时间: 2025-09-22
范围: MVP28-done.md 全部24天任务
评估维度: 实现难度、缺失程度、依赖关系、系统影响

## 一、极高风险任务（完全缺失或严重问题）🔴

### 1. Day9.1: Meme话题卡（核心数据模型缺陷）
**严重程度**: ⭐⭐⭐⭐⭐
- **signals表缺少type字段** - 无法区分4种卡片类型
- 设计要求: `type ENUM('topic','primary','secondary','market_risk')`
- 影响: 整个卡片分流系统失效
- is_memeable_topic路由未实现
- topic_card.j2模板缺失

### 2. Day18: 规则引擎 + Market Risk（完全未实现）
**严重程度**: ⭐⭐⭐⭐⭐
- **market_risk类型完全缺失** - MVP要求的4种类型之一
- 规则引擎只有3档，缺market_risk
- 没有market_risk_card.j2模板
- 市场风险预警功能完全缺失

### 3. Day8.1: KOL Profile变更（整条链路缺失）
**严重程度**: ⭐⭐⭐⭐⭐
- profile_events表不存在
- profile_tags表不存在
- image_tagging.py不存在（CLIP/OCR）
- topic_router.py不存在
- 图像识别功能完全缺失

### ~~4. Day14: 专家视图~~（已确认实现）
**更正说明**: 经核实，Day14功能已完整实现
- ✅ /expert/onchain路由已实现（api/routes_expert_onchain.py:353）
- ✅ X-Expert-Key验证已实现（line 384-386）
- ✅ 限流机制已实现（5/分钟，line 75, 399-400）

## 二、高风险任务（复杂易错或部分缺失）🟡

### 5. Day5: 事件聚合与event_key
**严重程度**: ⭐⭐⭐⭐
- event_key生成逻辑复杂（可能碰撞）
- 证据合并去重易出错
- 跨源聚合可能丢失数据

### 6. Day13: 状态机与并发
**严重程度**: ⭐⭐⭐⭐
- 状态转换可能死锁
- candidate → verified/downgraded/withdrawn
- 并发处理同一信号可能数据不一致
- Redis锁机制可能失效

### 7. Day8: X KOL采集（多源缺失）
**严重程度**: ⭐⭐⭐
- API v2完全未实现（仅占位符）
- Apify完全未实现（仅占位符）
- 只有GraphQL能用，单点故障风险

### 8. Day15-16: 跨源聚合与热度计算
**严重程度**: ⭐⭐⭐
- EVENT_MERGE_STRICT配置敏感
- 斜率计算可能NaN（数据不足）
- 热度持久化可能失败

### 9. Day10-12: BigQuery成本控制
**严重程度**: ⭐⭐⭐
- BQ_MAX_SCANNED_GB未设置可能天价账单
- dry_run守护可能被绕过
- 缓存失效可能重复查询

### 10. Day9.2: Primary卡门禁
**严重程度**: ⭐⭐⭐
- GoPlus降级时风险判定错误
- 多链CA归一化可能失败
- 状态变化推送逻辑复杂

## 三、中风险任务（已实现但有隐患）🟠

### 11. Day6: LLM精析器
**严重程度**: ⭐⭐
- JSON Schema验证可能大量丢弃数据
- LLM超时处理不当可能阻塞
- 降级链路可能失效

### 12. Day17: HF批量与阈值
**严重程度**: ⭐⭐
- 批量处理可能OOM
- 阈值校准可能不准
- 模型切换可能失败

### 13. Day19: 卡片Schema
**严重程度**: ⭐⭐
- Schema验证过严可能丢数据
- LLM摘要超时降级
- 渲染模板可能出错

### 14. Day20-21: Telegram推送
**严重程度**: ⭐⭐
- 速率限制可能导致消息丢失
- Outbox重试可能死循环
- 幂等键可能冲突

### 15. Day22: 回放与部署
**严重程度**: ⭐⭐
- Golden数据集可能过时
- 评分器标准可能不准
- 30分钟部署目标可能失败

### 16. Day23-24: 配置治理
**严重程度**: ⭐⭐
- 热加载并发安全问题
- 配置版本管理混乱
- 告警规则可能误报

## 四、低风险任务（基本完成）✅

### Day1-4: 基础架构
- 基本完成，风险较低

### Day7-7.2: GoPlus集成
- 完整实现，有降级机制

### Day9: DEX快照
- 双源冗余，缓存完善

### Day11: SQL模板
- 有成本守护和缓存

## 五、风险分布统计

| 风险等级 | 数量 | 占比 | 主要问题 |
|---------|------|------|---------|
| 极高风险🔴 | 3个 | 13% | 完全未实现（Day14已更正为已实现） |
| 高风险🟡 | 6个 | 25% | 部分缺失或复杂 |
| 中风险🟠 | 6个 | 25% | 已实现但有隐患 |
| 低风险✅ | 8个 | 33% | 基本完成 |

## 六、系统性问题

### 1. 数据模型问题
- signals表缺type字段是根本性缺陷
- 影响所有卡片类型区分
- 需要数据库迁移修复

### 2. 功能完整性问题
- 4种卡片类型只实现2种（50%）
- Topic和Market Risk完全缺失
- 图像识别链路完全未实现

### 3. 单点故障问题
- X数据源只有GraphQL
- 缺少多源冗余
- API v2/Apify都是占位符

### 4. 并发安全问题
- 状态机缺少完善的锁机制
- 热加载可能有竞态条件
- 事件聚合可能重复

### 5. 成本控制问题
- BigQuery可能失控
- LLM调用无限制
- 缓存策略不完善

## 七、紧急修复优先级

### P0 - 阻塞性问题（1-2天内）
1. 添加signals.type字段
2. 创建topic_card.j2模板
3. 创建market_risk_card.j2模板
4. 修复卡片路由逻辑

### P1 - 功能性问题（1周内）
1. 实现基础market_risk判定
2. 完善topic推送链路
3. 实现X API v2或Apify
4. ~~添加专家视图路由~~（已完成）

### P2 - 优化问题（2周内）
1. 实现Day8.1图像识别
2. 完善并发控制
3. 优化成本控制
4. 增强监控告警

## 八、体检脚本

```bash
#!/bin/bash
echo "=== MVP28 完整体检 ==="

# 1. 数据模型检查
echo -e "\n[1/10] 检查signals.type字段..."
docker compose exec -T db psql -U app -c "\d signals" | grep -E "type|market_type"

# 2. 卡片类型检查
echo -e "\n[2/10] 检查卡片模板..."
ls templates/cards/*.j2 | wc -l
ls templates/cards/{topic,market_risk}_card.j2 2>/dev/null

# 3. 图像处理检查
echo -e "\n[3/10] 检查图像处理组件..."
find . -name "image_tagging.py" -o -name "topic_router.py" | wc -l

# 4. 数据源检查
echo -e "\n[4/10] 检查X数据源实现..."
grep -c "NotImplementedError" api/clients/x_client.py

# 5. 专家视图检查
echo -e "\n[5/10] 检查专家视图..."
curl -s "http://localhost:8000/expert/onchain?chain=eth&address=test" | head -1

# 6. 市场风险检查
echo -e "\n[6/10] 检查market_risk支持..."
grep -r "market_risk" rules/ api/ --include="*.yml" --include="*.py" | wc -l

# 7. 事件聚合检查
echo -e "\n[7/10] 检查event_key唯一性..."
docker compose exec -T db psql -U app -c "SELECT COUNT(*), COUNT(DISTINCT event_key) FROM events;"

# 8. BigQuery成本检查
echo -e "\n[8/10] 检查BigQuery守护..."
grep "BQ_MAX_SCANNED_GB" .env || echo "WARNING: No cost guard!"

# 9. 状态机检查
echo -e "\n[9/10] 检查信号状态分布..."
docker compose exec -T db psql -U app -c "SELECT state, COUNT(*) FROM signals GROUP BY state;" 2>/dev/null

# 10. 热度API检查
echo -e "\n[10/10] 检查热度计算..."
curl -s "http://localhost:8000/signals/heat?token_ca=0x0" | jq -r '.error // "OK"'

echo -e "\n=== 体检完成 ==="
```

## 九、总结

**整体风险评估**：
- 13%的任务完全未实现（极高风险）- 更正：Day14已实现
- 25%的任务部分缺失（高风险）
- 25%的任务有隐患（中风险）
- 33%的任务基本完成（低风险）

**最严重的问题**：
1. signals表数据模型错误
2. 两种卡片类型完全缺失
3. 图像识别链路完全未实现
4. 单数据源风险

**建议**：
- 紧急修复P0问题（1-2天）
- 逐步补充P1功能（1周）
- 持续优化P2问题（2周）

这是一个**功能缺失大于bug**的项目，主要问题是"没写"而不是"写错"。