# 新功能任务卡

生成时间: 2025-09-22
基于已有代码分析生成

---

## 任务卡 1: 实现 KOL 资料变更检测与 LLM 分析

**背景 / 问题描述**
- 发现位置：`worker/jobs/x_avatar_poll.py` 已有基础头像轮询功能
- 现状：只检测头像 URL hash 变化，没有深入分析变更内容
- 缺失：
  - profile_events 表不存在（存储资料变更原始事件）
  - profile_tags 表不存在（存储 LLM 分析结果）
  - 缺少对资料变更的 LLM 分析（简介、头像语义等）
- 依赖：已有 LLMRefiner (OpenAI) 和 HF sentiment 分析基础

**修复目标**
实现完整的资料变更检测链路，包括文本和图像的 LLM 分析，生成结构化的话题候选信号

**修复步骤**
1. **数据库迁移**
   ```sql
   -- 创建 profile_events 表
   CREATE TABLE profile_events (
       id SERIAL PRIMARY KEY,
       handle VARCHAR(100) NOT NULL,
       event_type VARCHAR(50) NOT NULL, -- 'avatar_change', 'bio_change', 'name_change'
       old_value TEXT,
       new_value TEXT,
       detected_at TIMESTAMPTZ DEFAULT NOW(),
       analyzed BOOLEAN DEFAULT FALSE,
       INDEX idx_profile_events_handle (handle),
       INDEX idx_profile_events_analyzed (analyzed)
   );

   -- 创建 profile_tags 表
   CREATE TABLE profile_tags (
       id SERIAL PRIMARY KEY,
       profile_event_id INTEGER REFERENCES profile_events(id),
       tag_type VARCHAR(50), -- 'meme', 'token', 'trend', 'entity'
       tag_value TEXT,
       confidence FLOAT,
       llm_source VARCHAR(50), -- 'openai', 'huggingface', 'rules'
       metadata JSONB,
       created_at TIMESTAMPTZ DEFAULT NOW()
   );
   ```

2. **扩展 x_avatar_poll.py**
   - 增加获取完整 profile 信息（bio、display_name）
   - 检测多种字段变更（不仅仅是头像）
   - 变更事件写入 profile_events 表

3. **实现 profile_analyzer.py**
   - 利用现有 LLMRefiner 分析文本变更
   - 利用 HF API 或 OpenAI Vision API 分析头像
   - 提取 meme 话题、代币符号、趋势关键词
   - 结果写入 profile_tags 表

4. **集成到现有流程**
   - 分析结果转化为候选事件
   - 复用现有 event_key 生成逻辑
   - 走现有的 signals 流程

**验收标准**
- 能检测 KOL 简介、名称、头像的变更
- LLM 能提取关键实体和话题
- 生成的候选事件能进入现有 pipeline
- 降级机制：LLM 失败时回退到规则分析

**产物**
- `api/alembic/versions/<revision>_add_profile_tables.py`
- 更新的 `worker/jobs/x_avatar_poll.py`
- 新增 `worker/jobs/profile_analyzer.py`
- 更新的 `.env.example`（新增配置项）

**优先级 / 预计工作量**
- 优先级：P1（重要功能）
- 预计耗时：1 天
- **与 P2-1 部分重复**（Day8.1 KOL 头像识别功能）

---

## 任务卡 2: 链上数据分层查询接口预留

**背景 / 问题描述**
- 发现位置：
  - `api/routes/onchain.py` 目前只支持 ETH（line 51-52 硬编码拒绝其他链）
  - `templates/sql/eth/` 只有 ETH 的 SQL 模板
  - `api/providers/onchain/bq_provider.py` 已有 chain 参数支持
  - 数据库 onchain_features 表已有 chain 字段
- 现状：架构上已预留多链支持，但实际只实现了 ETH
- 需求：预留其他链的接口，方便后期接入

**修复目标**
建立多链支持的接口框架，为后续接入 BSC、Polygon、Solana 等链预留标准化接口

**修复步骤**
1. **定义支持的链枚举**
   ```python
   # api/schemas/chains.py
   from enum import Enum

   class SupportedChain(str, Enum):
       ETH = "eth"
       BSC = "bsc"
       POLYGON = "polygon"
       ARBITRUM = "arbitrum"
       OPTIMISM = "optimism"
       SOLANA = "solana"
       BASE = "base"

   CHAIN_CONFIG = {
       "eth": {
           "name": "Ethereum",
           "implemented": True,
           "bq_dataset": "bigquery-public-data.crypto_ethereum",
           "chain_id": 1
       },
       "bsc": {
           "name": "BNB Chain",
           "implemented": False,
           "bq_dataset": None,
           "chain_id": 56
       },
       # ... 其他链配置
   }
   ```

2. **更新 onchain 路由**
   ```python
   # api/routes/onchain.py
   @router.get("/features")
   async def get_onchain_features(
       chain: SupportedChain = Query(...),
       address: str = Query(...)
   ):
       if not CHAIN_CONFIG[chain]["implemented"]:
           raise HTTPException(
               status_code=501,
               detail=f"Chain '{chain}' is not yet implemented"
           )
   ```

3. **创建模板目录结构**
   ```
   templates/sql/
   ├── eth/
   │   ├── active_addrs_window.sql
   │   ├── token_transfers_window.sql
   │   └── top_holders_snapshot.sql
   ├── bsc/
   │   └── .gitkeep
   ├── polygon/
   │   └── .gitkeep
   └── solana/
       └── .gitkeep
   ```

4. **扩展 BQProvider**
   - 添加 chain 路由逻辑
   - 不同链使用不同的模板路径
   - 预留 chain-specific 特殊处理

5. **添加链识别工具**
   ```python
   # api/utils/chain_detector.py
   def detect_chain_from_address(address: str) -> Optional[str]:
       """根据地址格式自动识别链（可选功能）"""
       if address.startswith("0x") and len(address) == 42:
           # 可能是 EVM 链，需要进一步查询
           return None
       elif len(address) >= 32 and len(address) <= 44:
           # 可能是 Solana
           return "solana"
       return None
   ```

**验收标准**
- `/onchain/features?chain=eth` 继续正常工作
- `/onchain/features?chain=bsc` 返回 501 Not Implemented
- 新链的模板目录已创建
- chain 枚举和配置完整
- API 文档更新，列出支持的链

**产物**
- 新增 `api/schemas/chains.py`
- 更新的 `api/routes/onchain.py`
- 新增 `api/utils/chain_detector.py`
- 创建的链模板目录结构
- 更新的 API 文档

**优先级 / 预计工作量**
- 优先级：P1（架构预留）
- 预计耗时：3 小时
- **不与现有任务重复**

---

## 任务卡 3: 信息源多源拓展方法论

**背景 / 问题描述**
- 现有多源实现参考：
  - X 客户端：GraphQL 实现完整，API v2/Apify 是占位符
  - DEX 数据：DexScreener + GeckoTerminal 双源冗余已实现
  - LLM：OpenAI 主 + 降级到 HuggingFace + 最终降级到规则
- 缺失：统一的多源扩展模式和最佳实践文档

**方法论设计**

### 1. 抽象接口模式（参考 XClient）
```python
from abc import ABC, abstractmethod

class DataSource(ABC):
    @abstractmethod
    def fetch_data(self, params: Dict) -> Result:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass
```

### 2. 工厂模式 + 策略选择
```python
class SourceFactory:
    def get_source(self, backend: str) -> DataSource:
        if backend == "primary":
            return PrimarySource()
        elif backend == "secondary":
            return SecondarySource()
        elif backend == "off":
            return NullSource()

        # 支持动态加载
        if backend.startswith("plugin:"):
            return self._load_plugin(backend)
```

### 3. 降级链路设计
```python
class MultiSourceProvider:
    def __init__(self):
        self.sources = [
            (PrimarySource(), priority=1, timeout=1.5),
            (SecondarySource(), priority=2, timeout=3.0),
            (RuleBasedSource(), priority=99, timeout=0.1)
        ]

    async def fetch_with_fallback(self):
        for source, priority, timeout in self.sources:
            try:
                result = await source.fetch(timeout=timeout)
                log_json(stage="fetch.success", source=source.name)
                return result
            except Exception as e:
                log_json(stage="fetch.degrade",
                        source=source.name,
                        next=self._get_next_source())
                continue

        # 全部失败
        return self._empty_result()
```

### 4. 缓存层统一设计
```python
class CachedSource:
    def __init__(self, source: DataSource, cache: Cache):
        self.source = source
        self.cache = cache

    async def fetch(self, params):
        cache_key = self._make_key(params)

        # 1. 尝试缓存
        cached = await self.cache.get(cache_key)
        if cached and not self._is_stale(cached):
            return cached

        # 2. 获取新数据
        result = await self.source.fetch(params)

        # 3. 更新缓存
        await self.cache.set(cache_key, result, ttl=self._get_ttl())
        return result
```

### 5. 监控指标标准化
```python
# 每个数据源必须输出的指标
REQUIRED_METRICS = {
    "request_total": Counter,      # 请求总数
    "request_success": Counter,     # 成功数
    "request_latency": Histogram,   # 延迟分布
    "cache_hit_rate": Gauge,       # 缓存命中率
    "degrade_count": Counter,      # 降级次数
}
```

### 6. 配置管理模式
```yaml
# config/sources.yaml
sources:
  x_data:
    primary:
      type: graphql
      timeout: 2.0
      retry: 3
    secondary:
      type: api_v2
      timeout: 5.0
      retry: 1
    fallback:
      type: mock

  dex_data:
    sources:
      - name: dexscreener
        priority: 1
        cache_ttl: 60
      - name: geckoterminal
        priority: 2
        cache_ttl: 120
```

### 7. 插件化扩展机制
```python
# plugins/custom_source.py
class CustomSource(DataSource):
    def register(self):
        return {
            "name": "custom_source",
            "version": "1.0.0",
            "capabilities": ["realtime", "historical"]
        }
```

### 8. 测试策略
- **单源测试**：每个数据源独立测试
- **降级测试**：模拟主源失败，验证降级
- **性能测试**：并发请求，测试缓存效果
- **混沌测试**：随机失败，测试系统韧性

**实施建议**
1. **优先级排序**：可靠性 > 实时性 > 成本
2. **成本控制**：设置配额和告警
3. **版本管理**：API 版本兼容性处理
4. **文档规范**：每个数据源必须有完整文档
5. **监控先行**：先建监控，再加数据源

**已实现案例分析**

| 组件 | 主源 | 备源 | 降级 | 缓存 | 评价 |
|-----|-----|------|-----|------|-----|
| X 数据 | GraphQL | API v2(未实现) | 返回空 | Redis 14天 | 需补充备源 |
| DEX 数据 | DexScreener | GeckoTerminal | 返回空 | Redis 60秒 | ✅ 完整实现 |
| LLM 分析 | OpenAI | HuggingFace | 规则引擎 | 函数级缓存 | ✅ 三级降级 |
| BigQuery | 直连 | - | 返回空 | Redis 60秒 | 需要备份方案 |

**下一步行动**
1. 将 DexProvider 的双源模式抽象为通用模板
2. 补充 X 客户端的 API v2 实现（参考 P1-3）
3. 为 BigQuery 增加备份数据源（如 Dune Analytics）
4. 建立数据源健康度仪表板

---

## 任务关联性说明

### 与现有修复任务的关系

1. **任务卡 1（资料变更检测）**
   - 与 **P2-1**（实现 KOL 头像识别功能）部分重叠
   - 建议合并执行，本任务卡更全面（包含文本分析）

2. **任务卡 2（多链接口）**
   - 独立新功能，不与现有任务重复
   - 为将来扩展预留架构

3. **任务卡 3（多源方法论）**
   - 与 **P1-3**（实现 X 客户端多源支持）相关
   - 本卡提供方法论，P1-3 是具体实施案例

### 执行顺序建议

1. **第一步**：实施任务卡 3 的方法论，建立标准模式
2. **第二步**：按照方法论完成 P1-3（X 客户端多源）
3. **第三步**：实施任务卡 1（资料变更检测）
4. **第四步**：实施任务卡 2（多链接口预留）

---

*本文档基于现有代码分析生成，确保与现有架构兼容*