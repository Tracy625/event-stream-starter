# MVP 功能完整性分析报告

> 生成时间：2025-10-01
> 分析范围：GUIDS MVP 全代码库
> 分析深度：数据库、API、Worker、配置、业务逻辑

## 执行摘要

本报告通过系统性分析发现 **8 个关键问题**、**12 个中优先级问题** 和多个优化建议。最严重的问题包括数据库字段重复、Celery 任务未定义、以及多个已配置但未启用的功能模块。

---

## 一、关键问题（需立即修复）

### 1. 数据库字段重复：`signals.market_type` vs `signals.type`

**严重程度：** 🔴 高
**影响范围：** 数据一致性、查询性能

**问题描述：**

- `signals` 表存在两个语义相同的字段：
  - `market_type` (migration 001, 2025-08-18)
  - `type` (migration 014, 2025-09-24)
- 新代码使用 `type`，旧代码仍引用 `market_type`

**证据：**

```sql
-- 现状：两个字段并存
signals.market_type TEXT -- 旧字段，仅在3个测试文件中使用
signals.type TEXT CHECK(type IN ('topic','primary','secondary','market_risk')) -- 新字段，生产代码使用
```

**受影响文件：**

- `worker/jobs/topic_signal_scan.py:63` - 仍在查询 `market_type = 'topic'`
- `tests/test_rules_eval.py:46` - 测试数据仍插入 `market_type`
- `tests/test_topic_integration.py:117` - 测试查询 `market_type`

**修复建议：**

1. 创建迁移 016，删除 `market_type` 列
2. 更新所有测试文件使用 `type` 字段
3. 确保 `topic_signal_scan.py` 使用新字段

【审阅标注｜状态：部分正确】
- 现状确有双字段并存，业务应以 `type` 为准；但“仅测试引用 `market_type`”不准确，生产代码也在用该列：`worker/jobs/topic_signal_scan.py:63`、`worker/jobs/topic_signal_scan.py:80`、`worker/jobs/topic_signal_scan.py:99` 明确依赖 `market_type='topic'`。直接删除会破坏 Topic 扫描逻辑。
- 建议顺序：先改 `topic_signal_scan` 全面转 `type='topic'`（本仓已在插入与更新同时写 `type='topic'`，并加了 `ON CONFLICT (event_key,type)` 幂等），观察一段时间后再迁移去除 `market_type`。
- 参考文件：`worker/jobs/topic_signal_scan.py:89`、`worker/jobs/topic_signal_scan.py:122`、`api/alembic/versions/014_add_signals_type.py:1`。

---

### 2. Celery Beat 任务未定义：`secondary.proxy_scan_5m`

**严重程度：** 🔴 高
**影响范围：** 定时任务失败

**问题位置：** `worker/tasks.py:119-123`

```python
'secondary-proxy-scan-every-5min': {
    'task': 'secondary.proxy_scan_5m',  # ❌ 该任务从未定义！
    'schedule': 300.0,
    'options': {'queue': 'signals'},
},
```

**问题：**

- Beat schedule 引用了不存在的任务
- 导入了 `secondary_proxy_once` 但未包装为 Celery task

**修复建议：**

```python
# 在 worker/tasks.py 添加：
@app.task(name="secondary.proxy_scan_5m")
def secondary_proxy_scan_task():
    return secondary_proxy_once()
```

【审阅标注｜状态：不成立】
- 该任务已定义且可运行：`worker/jobs/secondary_proxy_scan.py:116` 处存在 `@app.task(name="secondary.proxy_scan_5m")` 的定义；Beat 也指向该任务（`worker/celeryconfig.py:31,53`），运行日志中可见 `secondary.proxy_scan_5m` 被接收并完成。
- 无需新增同名任务，避免重复。

---

### 3. LLM Refiner 功能已实现但未启用（修正：已实现，.env.example 未更新）

**严重程度：** 🟡 中
**影响范围：** 功能浪费、数据库空间

**数据库状态：**
Migration 004 创建了 10 个 `refined_*` 列：

- `refined_type`, `refined_summary`, `refined_impacted_assets`
- `refined_reasons`, `refined_confidence`
- `refine_backend`, `refine_latency_ms`, `refine_ok`
- `refine_error`, `refine_ts`

**配置状态：**

```bash
# .env.example
REFINE_BACKEND=rules  # 默认使用规则，不是 LLM
# OPENAI_API_KEY=  # 被注释掉
```

**代码状态：**

- ✅ Refiner 代码完整 (`api/refiner.py`)
- ✅ 验证脚本存在 (`scripts/verify_refiner.py`)
- ❌ 生产环境未配置 OpenAI key
- ❌ 没有代码读取 `refined_*` 字段

**建议：**

- **选项 A：** 启用 LLM - 更新 `.env.example`，文档化激活路径
- **选项 B：** 移除功能 - 创建迁移删除未使用的列

【审阅标注｜状态：部分正确】
- Refiner 模块已实现且默认后端为 `llm`（`api/refiner.py:25`）；本仓 `.env` 也设置了 `REFINE_BACKEND=llm` 与 `OPENAI_API_KEY`，可用。
- 但数据库层的 `events.refined_*` 列当前没有写入路径（代码未持久化这些列），规则引擎仅在 `RULES_REFINER=on` 时用精析结果细化“理由”（`api/rules/refiner_adapter.py:12`）。
- 结论：功能“可用但不落库 refined_* 列”。若要使用列，应补充落库流程或删除列以减负。

---

## 二、中优先级问题

### 4. HuggingFace 情感分析配置但未使用（修正：已实现，.env.example 未更新）

**配置：**

```bash
# .env.example
SENTIMENT_BACKEND=rules  # 默认规则，不是 hf
HF_MODEL=cardiffnlp/twitter-roberta-base-sentiment-latest  # 配置了但未使用
```

**影响：**

- Day4 实现的 HF 情感分析功能闲置
- 误导开发者认为在使用 AI 模型

【审阅标注｜状态：有条件可用】
- HF 客户端与烟测脚本存在（`api/services/hf_client.py:15`、`scripts/smoke_sentiment.py:1`），后端开关由 `SENTIMENT_BACKEND` 控制，默认可为 `rules` 或 `hf`（脚本与 Makefile 支持二者）。
- 业务链路中 sentiment 参与事件打分（`api/events.py:339` 起），但是否调用 HF 取决于上游设置与集成点；.env.example 的默认值可能未更新，属文档偏差而非功能缺失。

---

### 5. GoPlus 安全检查缓存表未充分利用

**表：** `goplus_cache` (migration 005)

**问题：**

- 表已创建，索引完善
- 但 `SECURITY_BACKEND=rules` (默认)，不会写入缓存
- 仅当 `SECURITY_BACKEND=goplus` 时才使用

**使用统计：**

- Python 文件引用：仅 2 个文件
- 实际写入：生产环境可能为 0

【审阅标注｜状态：基本属实】
- 已实现缓存表与 Provider（`api/alembic/versions/005_add_goplus_cache.py:1`、`api/providers/goplus_provider.py`），是否写入取决于 `SECURITY_BACKEND` 与扫描任务是否开启；配置默认倾向真实后端（compose 中 `SECURITY_BACKEND=goplus`）。
- 建议：按需增加使用统计与写入打点，避免“存在但少用”的观感。

---

### 6. 多个 Worker Jobs 未注册为任务

**未包装的 Jobs：**

- `worker/jobs/x_avatar_poll.py` - X 头像监控
- `worker/jobs/topic_aggregate.py` - 话题聚合
- `worker/jobs/push_topic_candidates.py` - 话题推送

**状态：** 文件存在但未在 `tasks.py` 中定义 `@app.task`

【审阅标注｜状态：部分正确】
- `topic_aggregate` 已包装为任务：`worker/jobs/topic_aggregate.py:15`（`@app.task`）且已在 Beat 中调度（`worker/celeryconfig.py:31,53`）。
- `x_avatar_poll` 未包装为 `@app.task`，仅提供 `run_once`，需要时可在 `tasks.py` 增加壳任务。
- `push_topic_candidates` 内部自建了独立 Celery 实例并声明任务（`worker/jobs/push_topic_candidates.py:11` 起），但主 worker 未必加载该实例；当前仅以模块函数方式被 `topic_aggregate` 同步调用（`format_topic_message/push_to_telegram`）。结论：无调度需求时可保留现状；如要独立调度需改为统一 `worker.app`。

---

### 7. `/ingest/x/replay` 端点实现不完整

**位置：** `api/routes/ingest_x.py:37-53`

```python
# TODO: hook into actual ingestion logic if needed
```

**现状：**

- 接收数据但不处理
- 仅记录幂等键

【审阅标注｜状态：正确】
- 端点含 `TODO` 注释且未调用实际入库逻辑（`api/routes/ingest_x.py:33-55`）。

---

## 三、配置冲突与冗余

### 8. X Backend 配置重复

```bash
# .env.example 中同时存在：
X_BACKEND=graphql        # 旧版单后端
X_BACKENDS=graphql,apify  # 新版多后端（优先）
```

【审阅标注｜状态：正确】
- 代码优先读取 `X_BACKENDS`，否则回退 `X_BACKEND`（`api/clients/x_client.py:49`）。建议在文档中明确优先级，减少混淆。

### 9. GoPlus 认证方式过多

```bash
GOPLUS_API_KEY=__REPLACE_ME__
GOPLUS_ACCESS_TOKEN=__REPLACE_ME__
GOPLUS_CLIENT_ID=__REPLACE_ME__
GOPLUS_CLIENT_SECRET=__REPLACE_ME__
```

**问题：** 未说明哪个优先或必需

【审阅标注｜状态：提示有效】
- `api/clients/goplus.py:79-101` 支持多种认证，建议在 `.env.example` 标注优先级与最小必需组合。

---

## 四、死代码与清理项

### 10. 备份文件遗留

```
api/keyphrases.py.bak.1755849903
api/keyphrases.py.bak.1755849871
```

【审阅标注｜状态：正确】
- 备份文件真实存在（`api/keyphrases.py.bak.1755849871`、`api/keyphrases.py.bak.1755849903`）。建议清理并在 `.gitignore` 增加规则。

### 11. Python 缓存文件

大量 `__pycache__/` 和 `.pyc` 文件未加入 `.gitignore`

【审阅标注｜状态：建议可采纳】
- 当前仓库已有 `__pycache__` 目录，建议补 `.gitignore`，减少噪音。

### 12. 废弃的路由 Shim

`api/routes/sentiment.py` - 标记为 "DEPRECATED"，仅作兼容性转发

【审阅标注｜状态：正确】
- 文件头部标注 DEPRECATED，作为 shim 使用（`api/routes/sentiment.py:1`）。可在后续移除并更新引用路径。

---

## 五、未完成的 MVP 功能（按计划对比）

### Day8.1 头像变更监控 ✅ 已实现

- 代码完整，但未集成到定时任务

### Day9.1 Meme 话题卡 ✅ 已实现

- 功能完整，正常工作

### Day9.2 Primary 卡门禁 ✅ 已实现

- GoPlus 检查已集成

### Day10-14 BigQuery 集成 ✅ 已实现

- `onchain_features` 表活跃使用
- 专家视图可用

### Day15-16 事件聚合 ⚠️ 部分完成

- 跨源聚合逻辑存在
- 热度计算已实现
- 但 `market_type` 字段问题影响使用

【审阅标注｜状态：部分正确】
- 聚合任务存在且可运行（`worker/jobs/topic_aggregate.py:15`）。
- “受 `market_type` 影响”主要体现在 Topic→Signals 的补全/扫描阶段（`topic_signal_scan` 对 `market_type='topic'` 的依赖），建议先统一到 `type='topic'` 再逐步移除旧列。

### Day17 HF 批量处理 ❌ 未启用（修正：已实现，.env.example 未更新）

- 代码存在但配置为 `rules` 后端

【审阅标注｜状态：部分正确】
- 代码与脚本均在（`api/services/hf_client.py`），启用与否取决于 `SENTIMENT_BACKEND`。文档样例如未更新，建议补充，但功能并非“未启用”。

### Day18 规则引擎 ✅ 已实现

- `rules/rules.yml` 热加载工作正常

### Day19 卡片 Schema ✅ 已实现

- Schema 验证通过
- 模板渲染正常

### Day20-21 Telegram 推送 ✅ 已实现

- Outbox 重试机制完整
- 速率限制工作正常

### Day22 部署与回放 ⚠️ 部分完成

- 部署脚本存在
- Replay endpoint 未完全实现

【审阅标注｜状态：正确】
- `/ingest/x/replay` 仅接受与记幂等键，未触发实际处理（`api/routes/ingest_x.py:33-55`）。

### Day23-24 配置治理 ✅ 已实现

- 热加载工作
- Metrics 端点活跃

---

## 六、立即行动项（P0）

1. **修复 `secondary.proxy_scan_5m` 任务定义**

   ```python
   # 在 worker/tasks.py 添加
   @app.task(name="secondary.proxy_scan_5m")
   def secondary_proxy_scan_task():
       return secondary_proxy_once()
   ```

【审阅标注｜状态：无需执行】
- 任务已存在且运行；避免重复定义同名任务。

2. **创建迁移删除 `signals.market_type`**

   ```bash
   alembic revision -m "drop_market_type_column"
   # 迁移内容：
   # op.drop_column('signals', 'market_type')
   ```

【审阅标注｜状态：延后执行】
- 先改扫描与写入路径统一用 `type`，运行平稳后再做删除迁移，避免引入运行时回归。

3. **清理备份文件**
   ```bash
   rm api/keyphrases.py.bak.*
   echo "*.bak*" >> .gitignore
   echo "__pycache__/" >> .gitignore
   echo "*.pyc" >> .gitignore
   ```

【审阅标注｜状态：同意】
- 可一次性清理并提交。

---

## 七、短期行动项（P1）

4. **决定 LLM Refiner 命运**

   - 选项 A：启用并文档化
   - 选项 B：删除 `refined_*` 列

5. **移除废弃的 sentiment 路由**

   ```bash
   rm api/routes/sentiment.py
   # 更新所有导入
   ```

【审阅标注｜状态：建议先标注后移除】
- 该 shim 当前被 `api/main.py:174` 引用，移除前需调整 import 路径，避免接口回归。

6. **完善 `.env.example` 文档**
   - 标注哪些是必需的
   - 说明多选项的优先级
   - 移除未使用的变量

---

## 八、中期行动项（P2）

7. **审计 HuggingFace 配置**

   - 如果不用，移除相关环境变量
   - 如果要用，更新默认配置

8. **完成 replay endpoint 或标记为测试专用**

9. **为 goplus_cache 添加监控指标**

10. **审查未使用的 worker jobs**
    - 决定是否集成到定时任务
    - 或删除未使用的文件

---

## 九、积极发现

以下功能实现良好，值得保留：

✅ **onchain_features** - 完整的读写路径，BigQuery 集成良好
✅ **push_outbox** - 优秀的重试机制设计
✅ **Celery Beat** - 定时任务配置合理
✅ **结构化日志** - `log_json` 使用一致
✅ **配置热加载** - 无需重启更新配置
✅ **多源 X 后端** - 故障转移机制完善

---

## 十、总结

### 数字统计

- **数据库迁移：** 15 个
- **未使用的表列：** 11 个（10 个 refined\_\* + 1 个 market_type）
- **配置但未启用的功能：** 3 个（LLM Refiner、HF Sentiment、GoPlus Cache）
- **未定义的任务：** 1 个
- **未完成的端点：** 1 个
- **需要清理的文件：** 3+ 个

### 整体评估

MVP 实现度约 **85%**，主要问题集中在：

1. 配置与实际使用不匹配
2. 部分高级功能（AI/ML）已实现但未启用
3. 数据库 schema 演进留下的技术债务

### 建议优先级

1. **立即修复：** 任务定义错误、数据库字段冲突
2. **本周内：** 决定未使用功能的去留
3. **本月内：** 清理技术债务，完善文档

---

_报告结束_
