# GUIDS Local Dev Checklist

本仓库的详细架构说明参见 `docs/BRIEF.md`。这里记录 Day 2 推送链路验收的常用命令，配合 `scripts/local_dev/day2_acceptance.sh.example` 可快速复现。

## 代码体检的 Day 2 验收演练

### 前置准备

1. 确认 `.env` 中 `METRICS_EXPOSED=true` 并运行 `docker compose -f infra/docker-compose.yml up -d api worker beat redis db`。
2. 如需模拟限流，将 `TELEGRAM_FORCE_429=1` 写入 `.env` 或在演练脚本中导出。
3. 准备 SQL 工具：`PSQL="docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app"`。

### 演练步骤

1. **插入待发送消息并开启 429 模拟**
   ```bash
   export TELEGRAM_FORCE_429=1
   docker compose -f infra/docker-compose.yml restart worker beat
   $PSQL <<'SQL'
   INSERT INTO push_outbox (channel_id, event_key, payload_json, status)
   SELECT -1003006310940, CONCAT('force429-', s), jsonb_build_object('text', CONCAT('Force 429 demo #', s)), 'pending'
   FROM generate_series(1, 30) AS s;
   SQL
   ```
2. **确认限流生效**（20 秒窗内应看到 429 相关日志且 backlog > 0）：
   ```bash
   docker compose -f infra/docker-compose.yml logs --since 20s worker | \
     grep -E '429|error_code|Too Many|rate limit|telegram_error_code'
   $PSQL -c "SELECT status, COUNT(*) FROM push_outbox GROUP BY status ORDER BY status;"
   curl -s http://localhost:8000/metrics | grep -E 'outbox_backlog|beat_heartbeat'
   ```
3. **关闭 429，等待 DLQ 回收回落**（约 60–70 秒）：
   ```bash
   unset TELEGRAM_FORCE_429
   docker compose -f infra/docker-compose.yml restart worker beat
   sleep 70
   $PSQL -c "SELECT status, COUNT(*) FROM push_outbox GROUP BY status ORDER BY status;"
   curl -s http://localhost:8000/metrics | grep -E 'outbox_backlog|dlq_(recovered|discarded)'
   ```
4. **验证 beat 自愈**：
   ```bash
   docker compose -f infra/docker-compose.yml ps beat
   docker compose -f infra/docker-compose.yml stop worker  # 暂停心跳
   sleep 20
   docker compose -f infra/docker-compose.yml ps beat      # 应显示 restart
   docker compose -f infra/docker-compose.yml start worker
   curl -s http://localhost:8000/metrics | grep -E 'beat_heartbeat'
   docker compose -f infra/docker-compose.yml exec -T redis redis-cli GET beat:last_heartbeat
   ```

### 样例输出片段

```text
{"evt":"telegram.send","code":"429","error_code":429,"reason":"forced_429",...}
{"stage":"outbox.backlog","when":"before","count":30}
{"stage":"outbox.backlog","when":"after","count":30,"processed":20}
outbox_backlog 30
beat_heartbeat_timestamp 1.758456e+09
beat_heartbeat_age_seconds 2.01
# 关闭 429 后
{"stage":"outbox.backlog","when":"after","count":0,"processed":30}
dlq_recovered_count 30
dlq_discarded_count 0
```

> 若希望一键执行，可参考 `scripts/local_dev/day2_acceptance.sh.example`，复制到 `scripts/local_dev/day2_acceptance.sh` 并酌情调整。
