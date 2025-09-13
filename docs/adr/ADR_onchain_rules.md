# ADR: On-chain Rules & Expert View Controls

## Context

项目中引入了链上特征评估（ONCHAIN_RULES）与专家视图（EXPERT_VIEW）。  
这些功能需要可控开关与回退路径，避免因数据源或性能问题影响主流程。

## Decision

1. **开关配置**

   - `ONCHAIN_RULES=on|off`
     - on：运行规则引擎，更新 signals.state (candidate → verified/downgraded)
     - off：只写 signals.onchain_asof_ts 与 onchain_confidence，不改 state
   - `EXPERT_VIEW=on|off`
     - on：启用 `/expert/onchain` API
     - off：返回 404，不暴露接口

2. **降级策略**

   - 出现 BigQuery 配额/延迟问题 → 强制 `ONCHAIN_RULES=off`，API 仍可返回缓存数据
   - 专家端异常或滥用 → 关闭 `EXPERT_VIEW`，主 API 不受影响
   - Alembic `010/011/012` 均可安全降级到 `009`，回退掉 signals.state 与 onchain 特征列

3. **数据源选择**
   - 默认：PostgreSQL (`EXPERT_SOURCE=pg`)
   - 可选：BigQuery (`EXPERT_SOURCE=bq`)
   - 所有查询必须使用参数化语句，禁止拼接 SQL

## Status

Accepted — Day12 定稿  
未来若迁移到生产大规模环境，需要进一步细化：

- BigQuery 轻量表刷新策略
- 专家限流策略（目前默认 5 req/min/key）
