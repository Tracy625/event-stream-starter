Ops Runbook

Postgres 备份（每日）

- Docker 自建数据库（infra/docker-compose.yml）
  - 进入容器并执行 pg_dump：
    - 启动服务：`docker compose -f infra/docker-compose.yml up -d db`
    - 导出备份：
      - `docker compose -f infra/docker-compose.yml exec -T db pg_dump -U app -d app -Fc > backup_$(date +%F).dump`
    - 恢复示例：
      - `pg_restore -h <host> -U app -d app -c backup_YYYY-MM-DD.dump`
  - 注意：生产环境请将备份文件同步到安全的对象存储（S3、OSS 等），保留至少 7–14 天保留策略。
  - 建议保留策略：7 天日备 + 4 周周备（周备可选用全量，日备用增量或全量）。
  - 恢复演练：每周在 staging 环境做一次 `pg_restore` 恢复演练，验证 dump 可用（抽样校验关键表 rowcount）。

- 托管数据库（RDS/Cloud SQL 等）
  - 建议使用云厂商提供的自动快照/备份策略：
    - 配置每日自动快照（建议凌晨低峰时段）
    - 启用 PITR（Point-in-Time Recovery）功能（若可用）
    - 定期演练恢复流程，确保 RTO/RPO 达标
  - 如需手动导出：使用 `pg_dump` 连接到托管实例，命令与上方相同。

示例脚本（手动导出/恢复演练）

```bash
#!/usr/bin/env bash
set -euo pipefail

# 环境变量：PGUSER/PGHOST/PGDB/PGPORT（可选）
BACKUP_DIR=${BACKUP_DIR:-./backups}
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F)

echo "Dumping ${PGDB} ..."
pg_dump -U "$PGUSER" -h "$PGHOST" -p "${PGPORT:-5432}" "$PGDB" > "$BACKUP_DIR/backup_${STAMP}.sql"

echo "Restoring into ${PGDB}_test ..."
createdb -U "$PGUSER" -h "$PGHOST" -p "${PGPORT:-5432}" "${PGDB}_test" || true
pg_restore -U "$PGUSER" -h "$PGHOST" -p "${PGPORT:-5432}" -d "${PGDB}_test" "$BACKUP_DIR/backup_${STAMP}.sql" || \
  psql -U "$PGUSER" -h "$PGHOST" -p "${PGPORT:-5432}" -d "${PGDB}_test" -f "$BACKUP_DIR/backup_${STAMP}.sql"

echo "OK: backup at $BACKUP_DIR/backup_${STAMP}.sql"
```


校验与监控
- 成功执行后，记录备份文件大小、校验哈希（如 `sha256sum`）并存档。
- 在备份任务旁设置失败重试与告警（如备份文件 < 1MB 直接告警）。
