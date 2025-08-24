# Development Charter (Workflow Rules)

本文件定义项目开发的全局规则与分工，确保在多模型协作（GPT-5 + Claude）下，逻辑统一、上下文可复现、实现稳定。

---

## 1. 模型分工

- **GPT-5**

  - 负责检索、比较、做技术评估与写决策文档
  - 产出 Tech Brief / ADR / PoC / 接口契约 / 阈值与护栏
  - 保证约束完整，避免库/Prompt 漂移

- **Claude**
  - 严格在 `CLAUDE.md` 约束下编码
  - 只能在“窄接口 + diff-only”模式下实现
  - 不得目录重构，仅能新增 adapter/facade
  - 必须输出 diff 与可跑命令，封装在 Makefile

---

## 2. 工程交付物

每次新模块/功能开发，必须按以下工件顺序产出：

1. **Tech Brief**

   - 候选库/模型清单
   - License / API 稳定性 / 维护度 / CPU/GPU 依赖
   - 延迟与吞吐估计、成本评估、替代方案与弃用计划

2. **ADR (Architecture Decision Record)**

   - 选型结论
   - 拒绝理由
   - 回滚条件与 FEATURE_FLAG

3. **PoC 脚本**

   - 最小 50 行以内验证脚本
   - 含 10 条黄金样本

4. **接口契约**

   - 函数签名
   - 输入输出 JSON Schema
   - 错误码与降级行为

5. **阈值与护栏**
   - p50/p95
   - 超时/重试/缓存策略
   - 调用上限与成本上限

---

## 3. 全局调试与回放

- **Repro Bundle**

  - `/scripts/collect_repro.py` 打包 env、.env、依赖版本、输入样本、日志片段、metrics 摘要、随机种子，生成 zip，可重放

- **Golden Traces**

  - 固定 10–20 条跨链路输入输出轨迹，任何改动先跑它

- **延迟与成本报告**
  - 每次改动必须输出 p50/p95、请求次数、缓存命中率

---

## 4. 优势

- 选型由 GPT-5 先踩坑，Claude 只做机械化落地
- 决策沉淀在 ADR 与 PoC，库可替换有回滚按钮
- 统一接口适配层，上层代码无感知

---

## 5. 风险与对策

- **库漂移**

  - 风险：版本升级破坏 API
  - 对策：pin 版本，UPGRADE_WINDOW 仅在 demo 分支尝试

- **Prompt 漂移**

  - 风险：不同对话导致隐式约定不一致
  - 对策：接口与验收写死在 repo 文件，模型只读文件

- **上下文爆炸**

  - 风险：Claude 同时接 10 件事导致混乱
  - 对策：子任务卡片 + 顺序执行，一张卡干完再下一张

- **无样本**
  - 风险：没有黄金样本就等于没有真相
  - 对策：每条链路固定 10 条正反样本，PoC 必须先过

---

## 6. 实施细节建议

- **适配层**

  - HF 情感、关键词、GoPlus、DEX 全走 adapter
  - ENV 开关统一：`*_BACKEND=off|rules|hf|...`

- **强 Schema**

  - 所有中间结果写 Pydantic/JSON Schema 校验
  - 不合格直接丢弃并带 downgrade=true

- **日志结构化**

  - 使用 JSON logging
  - 字段固定：stage, elapsed_ms, retries, cache_hit, backend, downgraded

- **Bench 脚本**

  - 每个 backend 必须有 baseline
  - 输出 p50/p95、吞吐、命中率

- **可回滚**
  - 每个新库上线必须附带 FEATURE_FLAG 与回滚步骤
  - 回滚说明写在 ADR

---

## 7. ADR 占位符

> 新的架构决策（库选型 / LLM 模型 / API 接入）必须追加到此处

- **ADR-2025-08-23-001: [示例] HF Sentiment Integration**
  - 决策：采用 HuggingFace 模型作为 sentiment 后端
  - 拒绝：未采用 spaCy 情感插件（维护度差）
  - 回滚：`SENTIMENT_BACKEND=rules` 可一键切回

## 8. Refiner Guardrails

- 实现 LLMRefiner 时，必须调用真实 SDK（OpenAI/HF/自建），不得保留占位逻辑。
- 必须支持超时、重试和 fallback 模型，相关配置来自环境变量。
- 日志输出统一走 `log_json`，覆盖 request / success / error / reject / degrade 场景。
- 禁止 hardcode 模型名、API key，全部通过 `.env` 或配置注入。
- 验收标准：≥80% 样本通过 schema 校验，平均延迟低于配置的预算。
