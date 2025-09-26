# RUN_NOTES.md

## P0-1: 统一与修复 /metrics 暴露

### 执行日期
2025-09-18

### 变更摘要
1. **api/core/metrics_exporter.py**：
   - 添加了 `hf_degrade_count` 和 `outbox_backlog` 的兜底保证（默认值 0）
   - 添加了 `export_text()` 作为 `build_prom_text()` 的兼容别名

2. **api/routes/signals_summary.py**：
   - 移除了重复的 `/metrics` 路由（原本是处理路由冲突的代理）

3. **api/main.py**：
   - 调整路由注册顺序，将 metrics.router 移到 signals_summary.router 之前
   - 避免 `/{event_key}` catch-all 路由拦截 `/metrics` 请求

### 自检与冒烟测试

#### 404 场景（开关关闭）
```bash
# 设置 METRICS_EXPOSED=false
METRICS_EXPOSED=false docker compose -f infra/docker-compose.yml up -d api
# 测试返回 404
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/metrics
# 结果：404
```

#### 导出场景（开关开启）
```bash
# 设置 METRICS_EXPOSED=true
METRICS_EXPOSED=true docker compose -f infra/docker-compose.yml up -d api

# 文本检查：三个关键指标
curl -s http://localhost:8000/metrics | grep -E "hf_degrade_count|outbox_backlog|pipeline_latency_ms"
# 结果：
# # HELP pipeline_latency_ms Latency histogram of pipeline in milliseconds
# # TYPE pipeline_latency_ms histogram
# pipeline_latency_ms_bucket{le="50"} 0
# hf_degrade_count 0
# outbox_backlog 0

# Content-Type 检查
curl -v http://localhost:8000/metrics 2>&1 | grep -i "content-type"
# 结果：< content-type: text/plain; version=0.0.4; charset=utf-8
```

#### 路由唯一性
```bash
grep -RIn 'get("/metrics' api | wc -l
# 结果：1（仅在 api/routes/metrics.py）
```

### 验收标准达成
✅ METRICS_EXPOSED=false 时返回 404
✅ METRICS_EXPOSED=true 时返回 Prometheus 文本格式
✅ Content-Type 正确：text/plain; version=0.0.4; charset=utf-8
✅ 三个关键指标始终存在：hf_degrade_count, outbox_backlog, pipeline_latency_ms
✅ 仅有一个 /metrics 路由注册
✅ export_text() 兼容别名可用

## Day22-1: 统一 SQLAlchemy Base 到 api/models/Base

### 执行日期
2025-09-18

### 静态检查结果
```bash
# 检查重复的 declarative_base
grep -RIn "declarative_base(" api/ worker/ | grep -v "api/models.py"
# 结果：✓ No duplicate declarative_base found

# 统计模型类和导入
grep -RIn "class .*\(Base\)" api/db/models | wc -l  # 结果：2
grep -RIn "from api.models import Base" api/db/models | wc -l  # 结果：1
```

### 迁移验证
```bash
# Alembic 升级到最新
docker compose -f infra/docker-compose.yml exec -T api alembic -c api/alembic.ini upgrade head
# 输出：
# INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
# INFO  [alembic.runtime.migration] Will assume transactional DDL.

# 当前版本
docker compose -f infra/docker-compose.yml exec -T api alembic -c api/alembic.ini current
# 结果：013 (head)
```

### CRUD 冒烟测试
```bash
docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
POSTGRES_URL = os.environ.get("POSTGRES_URL", "postgresql://app:app@db:5432/app")
engine = create_engine(POSTGRES_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

from api.db.models.push_outbox import PushOutbox
s = SessionLocal()
x = PushOutbox(channel_id=1, event_key="test", payload_json={"hello":"world"})
s.add(x); s.commit(); s.refresh(x)
print("ok", x.id)
s.close()
PY
# 输出：ok 1
```

### 健康检查
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/healthz
# 结果：200
```

### 变更摘要
1. **api/models.py**：添加了 `metadata` 导出和 `__all__` 列表
2. **api/alembic/env.py**：更新 import，直接从 `api.models` 导入 `metadata`
3. **api/db/models/push_outbox.py**：已正确使用统一的 Base（无需修改）

### 验收标准达成
✅ 全仓库仅有一个 Base 定义（api/models.py）
✅ `alembic upgrade head` 成功
✅ CRUD 冒烟测试通过（输出 "ok 1"）
✅ `/healthz` 返回 200
✅ RUN_NOTES.md 已更新

## Day28: signals.type enforcement

### Verify type column and constraints
```bash
# Check column, constraint, and index
docker compose -f infra/docker-compose.yml exec -T db psql -U app -c "\d+ signals" | grep -E "type|idx_signals_type|signals_type_check"

# Verify data distribution
docker compose -f infra/docker-compose.yml exec -T db psql -U app -c "SELECT type, COUNT(*) FROM signals GROUP BY type ORDER BY type"

# Test CHECK constraint
docker compose -f infra/docker-compose.yml exec -T db psql -U app -c "INSERT INTO events (event_key, start_ts, last_ts) VALUES ('test_type_check', NOW(), NOW())"
docker compose -f infra/docker-compose.yml exec -T db psql -U app -c "INSERT INTO signals (event_key, type) VALUES ('test_type_check', 'invalid')" 2>&1 | grep -q "violates check constraint" && echo "CHECK constraint working"

# Verify index usage
docker compose -f infra/docker-compose.yml exec -T db psql -U app -c "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM signals WHERE type='topic'" | grep "Index Scan.*idx_signals_type"

# Test migration rollback
docker compose -f infra/docker-compose.yml exec -T api alembic downgrade 013
docker compose -f infra/docker-compose.yml exec -T api alembic upgrade 014
docker compose -f infra/docker-compose.yml exec -T db psql -U app -c "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='signals' AND column_name='type'"
```