# EXECUTION_GUARDRAILS — 全局护栏（优先级最高）

本文件是 **所有 Task Cards、工作流文档、Claude DX 执行** 的最高优先级约束。  
任何冲突情况，**以本文件为准**。

---

## 1. 禁止事项

- ❌ 修改 DB schema / Alembic 迁移
- ❌ 新增或修改路由 / provider 文件（除非 Task Card 明确授权）
- ❌ 修改 `requirements.txt` 或引入新外部依赖
- ❌ 大规模格式化、重排、跨目录搬动文件
- ❌ 内置 `eval` 或不安全的表达式解析

---

## 2. 必须事项

- ✅ 只修改 Task Card 中声明的 **ALLOWED_FILES**
- ✅ 所有新建/修改必须以 **unified diff** 提交
- ✅ 每个 Task Card 顶部引用：`[遵循全局护栏] 见 docs/EXECUTION_GUARDRAILS.md`
- ✅ 使用已有工具模块：`api/models.py`、`api/db.py`、`log_json`
- ✅ 统一日志：结构化 JSON，含 stage/module/latency/理由
- ✅ 测试：使用 DEMO key，跑完清理，避免污染真实数据

---

## 3. 安全边界

- **热加载**：必须加锁（Lock + TTL + 原子替换），失败时回退旧版并打点
- **外部依赖**：若缺失则降级到 mock/空实现，不能阻塞主链路
- **YAML/配置**：UTF-8 编码，限制文件大小与规则数，AST 校验表达式
- **Refiner**：默认 `RULES_REFINER=off`；仅在 Day6 精析器已存在时才可开启

---

## 4. 回滚机制

- 每个 Task Card 必须写 **Rollback** 步骤：
  - 恢复环境变量默认值
  - `git restore` 或回退特定文件
  - 容器重启 / 缓存清理

---

## 5. 执行模式（DX）

- Claude 执行时仅产出 **最小 diff + Runbook 命令**
- 不得夹带大段解释性文字
- 验收失败 → 当日权限降级为“单文件改动 + 可回滚”

---

> 本文件更新后，必须立即在 `WORKFLOW.md`、`WORKFLOW_RULES.md`、`KICKOFF.md`、`CLAUDE_HANDOVER.md` 中同步引用。
