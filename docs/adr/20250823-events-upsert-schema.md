# ADR 2025-08-23: Events Aggregation & Upsert Schema

## 背景

Day3 pipeline 已能写入 raw_posts，但事件维度缺失，导致重复事件无法合并。  
Day5 目标是实现事件表 (events) 的 upsert，支持证据计数与 candidate_score 计算。

## 选项

- Option A: 每次都新建事件（无 upsert）
- Option B: 基于 (event_key) 执行 upsert，递增 evidence_count
- Option C: 使用外部事件流处理框架（复杂度过高）

## 决策

选择 Option B。  
在 events 表中增加 symbol/token_ca/topic_hash/time_bucket_start 等字段，支持幂等 upsert。  
新增 candidate_score 字段，结合 sentiment_score 与 keywords 命中数计算。

## 影响

- 正面：重复事件不会膨胀，last_ts 单调递增。
- 正面：candidate_score 提供统一信号强度评估。
- 风险：计算逻辑复杂化，需性能测试确保 p95 < 50ms。
- 风险：幂等迁移可能与旧 events 表字段并存，需兼容处理。

## 回滚方案

- 保留 legacy events 表原有字段（type/summary/evidence/impacted_assets/score），不强制依赖新字段。
- 如果出错，可通过切换脚本禁用 events.upsert 调用，仅写 raw_posts。
