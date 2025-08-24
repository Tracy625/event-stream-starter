# ADR 2025-08-24: Refiner Integration (LLM-based JSON Output)

## 背景

Day5 已完成事件聚合与 upsert，但生成的事件摘要依赖 rules-only 逻辑，缺乏自然语言概括能力。  
Day6 目标是引入 **LLM Refiner**，对聚合后的 evidence 进行摘要与结构化输出，满足下游消费需求。

## 选项

- **Option A:** 全部依赖 rules（低延迟但表达力有限）
- **Option B:** 引入 LLM 后端（openai / hf），失败时降级为 rules
- **Option C:** 混合模式（LLM+rules ensemble），增加复杂度

## 决策

选择 **Option B**：

- 默认使用 `REFINE_BACKEND=llm`，通过 `REFINE_PROVIDER=openai` 调用小号模型（如 gpt-5-mini）。
- 增加超时、重试、fallback（gpt-4o-mini → gpt-4o → rules）。
- 输出严格符合 JSON Schema：`{type, summary<=80, impacted_assets[], reasons[], confidence}`。
- 日志覆盖 refine.request/success/error/reject/degrade，延迟预算上限 800ms（目前仍待优化）。

## 影响

- **正面：** 摘要更贴近自然语言，支持多样化事件类型。
- **正面：** 结构化 JSON 保证下游解析稳定。
- **风险：** LLM 请求延迟远超预算（p95 > 3s），可能触发频繁降级。
- **风险：** API key 或模型版本受限，需 fallback 兜底。

## 回滚方案

- 将 `.env` 中 `REFINE_BACKEND` 改为 `rules`，完全禁用 LLM Refiner。
- 保留 legacy 字段（events.type, summary, evidence, impacted_assets, heat_10m, heat_30m），兼容旧逻辑。
- 如需彻底禁用，可删除 `refiner.py` 引用，pipeline 将回退至 Day5 行为。
