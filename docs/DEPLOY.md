# 部署指南

## 前提准备

### 系统要求
- Docker Engine 20.10+
- Docker Compose v2.0+
- 可用端口：5432 (PostgreSQL), 6379 (Redis), 8000 (API)
- 至少 2GB 可用内存

### 环境验证
```bash
# 检查 Docker 版本
docker --version
docker compose version

# 检查端口占用
lsof -i :5432,6379,8000
```

## 一键部署

### 1. 初始化环境
```bash
# 克隆仓库（如果尚未克隆）
git clone <repository-url>
cd GUIDS

# 初始化配置文件和数据库
make init

# 验证 .env 文件已创建
ls -la .env
```

### 2. 启动服务
```bash
# 启动所有服务
make up

# 等待服务就绪
make wait

# 查看服务状态
make ps
```

### 3. 验证部署
```bash
# 验证 API 健康状态
make verify:api

# 检查日志
make logs
```

## Telegram 配置

### DRY-RUN 模式（测试）
```bash
# 设置为 DRY-RUN 模式（不实际发送消息）
export TELEGRAM_PUSH_ENABLED=false

# 运行 Telegram 验证
make verify:telegram

# 查看输出，应显示 "DRY-RUN: smoke-ok"
```

### LIVE 模式（生产）
```bash
# 配置 .env.local（敏感配置）
cat > .env.local <<EOF
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>
TELEGRAM_PUSH_ENABLED=true
EOF

# 重启服务以加载新配置
make restart

# 验证 Telegram 推送
make verify:telegram
```

## 首卡计时

### Mode A - 日志模式
```bash
# 监控 API 服务启动日志
MEASURE_CARD_SERVICE=api \
MEASURE_LOG_PATTERN="INFO.*Application startup complete" \
MEASURE_TIMEOUT_SEC=300 \
bash scripts/measure_boot.sh

# 查看计时报告
cat logs/day22/measure_boot.json
```

### Mode B - HTTP 轮询模式
```bash
# 监控健康检查端点
MEASURE_POLL_URL="http://localhost:8000/health" \
MEASURE_POLL_EXPR="'ok' in body" \
MEASURE_TIMEOUT_SEC=300 \
bash scripts/measure_boot.sh

# 查看计时报告
cat logs/day22/measure_boot.json
```

## 回滚与故障排查

### 服务管理
```bash
# 停止所有服务
make down

# 完全清理（包括数据卷）
make nuke

# 重启服务
make restart
```

### 日志查看
```bash
# 查看所有服务日志
make logs

# 查看特定服务日志
docker compose -f infra/docker-compose.yml logs api
docker compose -f infra/docker-compose.yml logs worker

# 查看归档日志
ls -la logs/day22/
cat logs/day22/replay_report.json
```

### 常见问题

#### 端口被占用
```bash
# 查找占用进程
lsof -i :8000
# 终止进程或更改端口配置
```

#### 数据库连接失败
```bash
# 检查数据库服务
docker compose -f infra/docker-compose.yml ps db

# 查看数据库日志
docker compose -f infra/docker-compose.yml logs db

# 重新初始化数据库
make down
make init
make up
```

#### API 启动失败
```bash
# 检查环境变量
docker compose -f infra/docker-compose.yml exec api env | grep -E "POSTGRES|REDIS"

# 检查迁移状态
docker compose -f infra/docker-compose.yml exec api alembic current
```

## 安全说明

### 敏感配置管理
- **永不** 将 `.env.local` 提交到版本控制
- 使用 `.env` 存储默认配置，`.env.local` 存储敏感值
- `.env.local` 优先级高于 `.env`

### 配置脱敏
```bash
# 生成脱敏配置用于分享或调试
bash scripts/build_repro_bundle.sh

# 查看脱敏后的配置
unzip -p artifacts/day22_repro_*.zip .env.redacted
```

### 密钥轮换
定期更新以下密钥：
- `X_BEARER_TOKEN` - API 认证令牌
- `GOPLUS_API_KEY` - 安全扫描 API 密钥
- `TELEGRAM_BOT_TOKEN` - Telegram 机器人令牌
- `POSTGRES_PASSWORD` - 数据库密码

## 生产部署清单

- [ ] 配置 `.env.local` 中的所有生产密钥
- [ ] 设置 `DEMO_MODE=false`
- [ ] 配置 `TELEGRAM_PUSH_ENABLED=true`
- [ ] 验证所有端口未被占用
- [ ] 运行首卡计时确认启动时间 < 2 分钟
- [ ] 配置日志轮转和备份策略
- [ ] 设置监控告警
- [ ] 测试回滚流程