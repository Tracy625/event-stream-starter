# Claude 放权周期

## 背景

Claude 在编码执行上的能力强于 GPT-5，但上下文保持和逻辑约束不如 GPT-5。  
因此，本项目采用 **逐步放权** 的方式，在保证架构、约束和验收稳定的前提下，让 Claude 在合适的时间接管更多复杂任务。

---

## 放权原则

1. **架构与规范优先**

   - 由 GPT-5 输出 Tech Brief、ADR、Task Cards。
   - Claude 严格在 CLAUDE.md 约束内执行，不得超范围。

2. **逐步放权**

   - 从 “小功能模块” → “核心逻辑实现” → “跨文件协作” → “性能优化/惊喜代码”。

3. **随时可回退**
   - 每个放权点必须有明确的 rollback 条件。
   - 保持 Claude 只能写 diff，不得重构整个项目。

---

## 放权周期阶段

### Day 0–Day 5（初期阶段）

- Claude 权限：**低**
- 范围：只能执行围栏内 Task Card（单文件、小功能）
- GPT-5 负责：
  - 架构设计
  - 选型决策
  - 写 Tech Brief、ADR、任务约束
- 目标：把基础架构跑通，Claude 主要“搬砖”。

### Day 6–Day 10（中期阶段）

- Claude 权限：**中**
- 范围：可以处理 **复杂逻辑**（多函数、多文件交互），如精析器、Refiner LLM 接入。
- GPT-5 负责：
  - 关键接口的输入输出约束（JSON Schema、函数签名）
  - 写明降级策略
- Claude 允许：
  - 在既定文件内新增 adapter/facade
  - 对跨模块逻辑进行 glue code 编写
- 回滚条件：如果 Claude 生成了不可运行的跨模块代码 → 禁止扩展权限，回退到“单文件模式”。
- Claude 只能执行 GPT-5 当天在 STATUS.md / mvp15_plan.md 确认过的 Task Card。不得自行提前后续任务。

### Day 11–Day 15（后期阶段）

- Claude 权限：**高**
- 范围：允许做优化和小型重构（延迟优化、缓存策略、批处理）。
- GPT-5 负责：
  - 复查 Claude 生成的复杂 diff
  - 把关全局一致性（schema、接口、env）
- Claude 允许：
  - 尝试性能优化（如异步、批量化）
  - 写单测、基准测试脚本
- 回滚条件：如发现 Claude 未按 CLAUDE.md 约束（私自重构目录、改 schema 等），立即禁止后续放权。

---

## 关键风险与对策

- **Prompt 漂移**：Claude 忘记之前的约束。

  - 对策：每天强制投喂 `STATUS.md`、`SCHEMA.md`、`RUN_NOTES.md`、CLAUDE.md、WORKFLOW.md。

- **接口无序增长**：Claude 乱加函数/字段。

  - 对策：所有新增必须写在 Task Card + ADR 里，由 GPT-5 批准。

- **上下文爆炸**：Claude 同时改 10 个东西。
  - 对策：子任务卡片化，强制“一张卡干完再下一张”。

---

## 总结

- **Day0–5**：Claude 搬砖 → **低权限**
- **Day6–10**：Claude 承担复杂逻辑 → **中权限**
- **Day11–15**：Claude 尝试优化与惊喜 → **高权限**

始终保持：**Claude 在 CLAUDE.md 约束下执行，GPT-5 把关架构与验收**。
