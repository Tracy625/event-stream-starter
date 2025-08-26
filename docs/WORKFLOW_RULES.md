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

## 9. 每日工作流（综合版）

> 注：本节描述人类 + GPT-5 + Claude 的每日协作节奏，不改变前述全局分工与工件顺序。  
> 注 2（与现有条款的关系）：DX 模式下不再触发“Today 一致性”检查（INCONSISTENCY_REPORT），仅以 ALLOWED_FILES 做范围校验；默认模式仍遵循 SSOT（以 STATUS.md 的 Today 为唯一来源）。

### Step 0 — 技术方案确认（GPT-5）

1. 投喂 6+1 文件（STATUS.md / CLAUDE.md / WORKFLOW.md 等）。
2. GPT-5 与人类讨论 Today（例如 Day7），完成技术调研与接口契约；必要时产出 ADR/PoC/阈值（参见第 2 节“工程交付物”）。
3. GPT-5 输出 **STATUS.md 的 Today 段定稿**；人类人工 diff/merge 并标注为 LOCKED。

### Step 1 — 拆分任务（Claude，默认 SSOT）

1. Claude 读取 `STATUS.md` 的 Today（LOCKED）作为唯一来源。
2. 若与对话内容不一致 → 输出 `INCONSISTENCY_REPORT` 并给出仅修改 `STATUS.md` 的 diff 提案，停止实现。
3. 一致则生成 **Task Cards**（1 任务 = 1 卡），格式遵循 `WORKFLOW.md`“Task Card Format”。

### Step 2 — 审卡（GPT-5）

1. 人类将 Task Cards 喂给 GPT-5；GPT-5 审查与微调，不改变任务边界。
2. 产出 **Approved & 优化后的执行 Prompt**（仍保持 Task Card 结构），准备执行。

### Step 3 — 执行任务（两种模式）

- **A. 默认执行（SSOT）**
  - Claude 按 `STATUS.md` Today 对号执行最小 diff；不一致则返回 `INCONSISTENCY_REPORT`。
- **B. 单卡直执（DX）**
  - 适用于“方案定稿 → 产卡 → 审卡”三次确认后的卡片。
  - Claude 不再回读 `STATUS.md`，仅按 Prompt 头部与白名单执行：
    ```
    MODE: DIRECT_EXECUTION
    CARD_TITLE: <标题>
    ALLOWED_FILES:
      - <相对路径1>
      - <相对路径2>
    ```
  - 任何超出 `ALLOWED_FILES` 的改动 → `SCOPE_VIOLATION` 并停止。
  - 输出仅包含 unified diffs 与最小 Runbook（迁移/启动/验证命令），不夹带解释性长文。

### Step 4 — 验收与回放

1. 按 Task Card 的验收标准逐卡验证（curl / pytest / alembic 等）。
2. 全部通过后做一次回归：
   - `alembic upgrade head`
   - 启动 API 与运行所有验证脚本
   - 手工抽查关键路由
3. 需要可重复性与对比时，使用第 3 节的 **Repro Bundle** 与 **Golden Traces**。
4. 更新 `STATUS.md` 的 Done / Variance / Next，结束当日工作。
