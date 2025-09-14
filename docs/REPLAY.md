# 回放测试指南

## 黄金数据集定义

### golden.jsonl 结构
每行为一个 JSON 对象，包含以下字段：

```json
{
  "event_key": "TEST_PUMP_001",      // 唯一事件标识
  "ts": 1700000000,                  // Unix 时间戳
  "payload": {
    "source": "x",                   // 数据源: x/dex/topic
    "token": "PUMP",                 // 代币符号
    "sentiment": 0.8,                // 情感分数
    "volume": 50000                  // 交易量
  },
  "expected": {
    "should_alert": true             // 期望是否触发告警
  }
}
```

### 数据源类型
- `x`: 社交媒体事件
- `dex`: DEX 交易事件
- `topic`: 话题聚合事件

## 路由发现

### 自动发现可用端点
```bash
# 从 OpenAPI 规范发现路由
make routes

# 查看发现的路由
cat logs/day22/routes.json
```

### 手动验证端点
```bash
# 测试 x 端点
curl -X POST http://localhost:8000/x/ingest \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'

# 测试 dex 端点
curl -X POST http://localhost:8000/dex/snapshot \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'

# 测试 topic 端点
curl -X POST http://localhost:8000/topic/ingest \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'
```

## 端点配置

### 环境变量设置
```bash
# 配置回放端点
export REPLAY_ENDPOINT_X="http://localhost:8000/x/ingest"
export REPLAY_ENDPOINT_DEX="http://localhost:8000/dex/snapshot"
export REPLAY_ENDPOINT_TOPIC="http://localhost:8000/topic/ingest"

# 可选：设置认证令牌
export REPLAY_AUTH_TOKEN="your-bearer-token"
```

### 软化开关
```bash
# 启用软失败模式（CI/CD 友好）
export REPLAY_SOFT_FAIL=true

# 禁用软失败模式（默认，严格模式）
export REPLAY_SOFT_FAIL=false
```

软失败模式说明：
- `true`: 即使回放失败也返回退出码 0
- `false`: 回放失败返回非零退出码（默认）

## 回放执行

### 运行端到端回放
```bash
# 基础回放
bash scripts/replay_e2e.sh demo/golden/golden.jsonl

# 带端点配置的回放
REPLAY_ENDPOINT_X="http://localhost:8000/x/ingest" \
REPLAY_ENDPOINT_DEX="http://localhost:8000/dex/snapshot" \
REPLAY_ENDPOINT_TOPIC="http://localhost:8000/topic/ingest" \
bash scripts/replay_e2e.sh demo/golden/golden.jsonl

# 软失败模式回放
REPLAY_SOFT_FAIL=true \
bash scripts/replay_e2e.sh demo/golden/golden.jsonl
```

### 查看回放结果
```bash
# 查看回放清单
cat logs/day22/replay_raw/manifest.json

# 查看单个用例结果
cat logs/day22/replay_raw/0_TEST_PUMP_001.response.json
cat logs/day22/replay_raw/0_TEST_PUMP_001.meta.json

# 查看所有用例摘要
cat logs/day22/replay_raw/.cases.jsonl
```

## 评分系统

### 运行评分器
```bash
# 执行评分
python3 scripts/score_replay.py

# 软失败模式评分
SCORE_SOFT_FAIL=true python3 scripts/score_replay.py
```

### 评分指标说明

#### pipeline_success_rate
- **定义**: 成功响应（200）数量 / 黄金数据集总数
- **验收门槛**: ≥ 0.9 (90%)
- **含义**: 系统可用性指标

#### alert_accuracy_on_success
- **定义**: 在 200 响应中，告警判断正确的比例
- **验收门槛**: ≥ 0.8 (80%)
- **含义**: 系统准确性指标
- **注意**: 仅在成功响应中计算，非 200 响应不参与

#### cards_degrade_count
- **定义**: 降级服务的数量（非 200 响应）
- **验收门槛**: ≤ 2
- **含义**: 系统稳定性指标

### 查看评分报告
```bash
# 查看完整报告
cat logs/day22/replay_report.json

# 查看摘要
cat logs/day22/replay_report.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
s = data['summary']
print(f\"Pipeline Success: {s['pipeline_success_rate']:.1%}\")
print(f\"Alert Accuracy: {s['alert_accuracy_on_success']:.1%}\")
print(f\"Degraded Count: {s['cards_degrade_count']}\")
print(f\"Status: {'PASS' if s['passed'] else 'FAIL'}\")
"
```

## 产物位置

### 回放产物
- `logs/day22/replay_raw/` - 回放原始数据目录
  - `manifest.json` - 回放清单
  - `*.request.json` - 请求数据
  - `*.response.json` - 响应数据
  - `*.meta.json` - 元数据
  - `.cases.jsonl` - 用例摘要

### 评分产物
- `logs/day22/replay_report.json` - 评分报告
- `logs/day22/replay_report.html` - HTML 报告（如果生成）

## 常见问题

### Q: 回放显示 404 错误
**A**: 检查端点配置是否正确
```bash
# 验证端点可访问
curl -I http://localhost:8000/x/ingest
curl -I http://localhost:8000/dex/snapshot
curl -I http://localhost:8000/topic/ingest

# 确认服务已启动
make ps
```

### Q: 回放超时
**A**: 调整超时设置
```bash
# 增加超时时间（默认 10 秒）
export REPLAY_TIMEOUT_SEC=30
bash scripts/replay_e2e.sh demo/golden/golden.jsonl
```

### Q: 鉴权失败
**A**: 配置认证令牌
```bash
# 设置 Bearer Token
export REPLAY_AUTH_TOKEN="your-token"

# 或在 .env.local 中配置
echo "X_BEARER_TOKEN=your-token" >> .env.local
make restart
```

### Q: 如何增补黄金集
**A**: 添加新测试用例
```bash
# 1. 编辑黄金数据集
cat >> demo/golden/golden.jsonl <<'EOF'
{"event_key": "TEST_NEW_001", "ts": 1700000100, "payload": {"source": "x", "token": "NEW", "sentiment": 0.9}, "expected": {"should_alert": true}}
EOF

# 2. 重新运行回放
bash scripts/replay_e2e.sh demo/golden/golden.jsonl

# 3. 验证新用例
grep TEST_NEW_001 logs/day22/replay_raw/manifest.json
```

### Q: 评分不通过如何调试
**A**: 分析失败原因
```bash
# 1. 查看详细错误
cat logs/day22/replay_report.json | python3 -m json.tool | less

# 2. 检查失败用例
cat logs/day22/replay_report.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for case in data['by_case']:
    if not case.get('hit'):
        print(f\"{case['event_key']}: expected={case['expected_alert']}, actual={case['actual_alert']}, reason={case.get('reason')}\")
"

# 3. 查看降级原因
cat logs/day22/replay_report.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for case in data['by_case']:
    if case.get('degrade'):
        print(f\"{case['event_key']}: {case.get('degrade_reason')}\")
"
```

## 集成到 CI/CD

### GitHub Actions 示例
```yaml
- name: Run Replay Test
  env:
    REPLAY_SOFT_FAIL: true
    REPLAY_ENDPOINT_X: ${{ secrets.REPLAY_ENDPOINT_X }}
    REPLAY_ENDPOINT_DEX: ${{ secrets.REPLAY_ENDPOINT_DEX }}
    REPLAY_ENDPOINT_TOPIC: ${{ secrets.REPLAY_ENDPOINT_TOPIC }}
  run: |
    bash scripts/replay_e2e.sh demo/golden/golden.jsonl
    python3 scripts/score_replay.py
```

### 本地测试脚本
```bash
#!/bin/bash
# test_replay.sh

set -e

# 配置端点
export REPLAY_ENDPOINT_X="http://localhost:8000/x/ingest"
export REPLAY_ENDPOINT_DEX="http://localhost:8000/dex/snapshot"
export REPLAY_ENDPOINT_TOPIC="http://localhost:8000/topic/ingest"

# 运行回放
echo "Running replay..."
bash scripts/replay_e2e.sh demo/golden/golden.jsonl

# 评分
echo "Scoring results..."
python3 scripts/score_replay.py

# 显示结果
echo "Results:"
cat logs/day22/replay_report.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(json.dumps(data['summary'], indent=2))
"
```