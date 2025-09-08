# RUN_NOTES — Daily Verification Commands

本文件记录从 Day0 开始，每日验收所需的关键命令。
只保存“怎么跑”的命令，不保存结果。结果会随数据变化，请实时执行确认。

================================================================

## Day0 — Environment & Infra Init

- 启动基础服务（db/redis/api）
  make up
- 查看容器状态
  docker compose -f infra/docker-compose.yml ps
- 健康检查
  curl http://localhost:8000/healthz

---

## Day1 — Monorepo Init / DB migrations

- 应用 Alembic 迁移（使用容器内 alembic.ini）
  docker compose -f infra/docker-compose.yml exec -T api alembic -c /app/api/alembic.ini upgrade head
- 确认表创建
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "\dt"

---

## Day2 — Filter / Refine / Dedup / DB pipeline

⚠ variance: 原计划是「X API 采集 / 粗筛」，实际完成的是 pipeline/demo，采集推迟到 Day8。

- 运行 demo pipeline
  make demo
- 验证 raw_posts 表有数据
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT COUNT(\*) FROM raw_posts;"

---

## Day3 — Demo ingest script & logging

⚠ variance: 原计划是「规则与关键词粗筛」，实际完成的是 demo ingest & logging；粗筛部分将在 Day8–Day9 补齐。

- 运行 demo ingestion 脚本（直接脚本方式）
  docker compose -f infra/docker-compose.yml exec -T api python scripts/demo_ingest.py

---

## Day3+ — Metrics / Cache / Benchmarks

- 运行基准测试
  make bench-sentiment
- 查看 golden.jsonl 样例
  cat scripts/golden.jsonl

---

## Day4 — HuggingFace Sentiment & Keyphrases

- 测试 rules backend（默认）
  docker compose -f infra/docker-compose.yml exec -T api python -c "from api.filter import analyze_sentiment; print(analyze_sentiment('this is bad'))"
- 测试 HF backend
  docker compose -f infra/docker-compose.yml exec -T -e SENTIMENT_BACKEND=hf -e HF_MODEL=cardiffnlp/twitter-roberta-base-sentiment-latest api python -c "from api.filter import analyze_sentiment; print(analyze_sentiment('I love this project'))"
- 测试 Keyphrases (KBIR)
  docker compose -f infra/docker-compose.yml exec -T -e KEYPHRASE_BACKEND=kbir api python -c "from api.keyphrases import extract_keyphrases; print(extract_keyphrases('Airdrop $ARB claim open now'))"
- 运行 bench-sentiment（双后端比较）
  make bench-sentiment

---

## Day5 — Event Aggregation

- 运行 demo，触发事件聚合
  make demo
- 查看 events 聚合结果（数量 & 证据数总和）
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT COUNT(\*) AS n_events, SUM(evidence_count) AS total_evidence FROM events;"
- 查看 events 表详细记录
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT event_key, evidence_count, candidate_score FROM events ORDER BY last_ts DESC;"
- 运行 verify_events 脚本
  docker compose -f infra/docker-compose.yml exec -T api python scripts/verify_events.py

---

---

## Day6 — Refiner (LLM Integration)

- 验证 LLM Refiner（rules / llm 两种 backend）

  ```bash
  make verify-refiner-rules
  make verify-refiner-llm
  ```

- 查看容器内环境变量，确认 REFINE/OPENAI 已加载

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'env | sort | egrep "REFINE_|OPENAI"'
  ```

- 调用 LLM Refiner 样例（确认调用链正确）

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python scripts/demo_refine.py
  ```

- 检查 Refiner 日志输出（结构化 JSON）
  ```bash
  docker compose -f infra/docker-compose.yml logs -f api | egrep "refine.request|refine.success|refine.error|refine.degrade|refine.warn"
  ```

# Day7 — GoPlus Security Integration

- 验证 risk_rules.yml 是否存在并包含样例黑名单地址

  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'ls -l /app/rules && head -40 /app/rules/risk_rules.yml'

- 检查 goplus_cache 表结构
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "\d goplus_cache"

- 运行验收脚本（首次运行应显示 red 风险，cache=false）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'cd /app && SECURITY_BACKEND=rules python -m api.scripts.verify_goplus_security'

- 再次运行验收脚本（应显示 cache=true）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'cd /app && SECURITY_BACKEND=rules python -m api.scripts.verify_goplus_security'
- 手工 curl 路由测试
  for U in \
   'http://localhost:8000/security/token?chain_id=1&address=0x123' \
   'http://localhost:8000/security/address?address=0x123' \
   'http://localhost:8000/security/approval?chain_id=1&address=0x123&type=erc20'
  do
  echo "=== $U"
    curl -s -i "$U" | sed -n '1p'
  curl -s "$U" | jq '{ok: (.summary!=null), degrade, cache, stale, label: .summary.risk_label}'
  done
- 启用批量扫描（可选，默认关闭）
  ENABLE_GOPLUS_SCAN=true docker compose -f infra/docker-compose.yml up -d worker
  docker compose -f infra/docker-compose.yml logs worker | grep goplus.scan | tail -40

## Day7.1

- 写入样例事件和信号（3 个垃圾盘地址）
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  INSERT INTO events (event_key, start_ts, last_ts, evidence_count, candidate_score, token_ca, symbol, evidence) VALUES
  ('TEST_BAD', NOW(), NOW(), 1, 0.5, '0xbad0000000000000000000000000000000000000', 'BAD',
  '[{\"token_ca\":\"0xbad0000000000000000000000000000000000000\",\"chain_id\":\"1\"}]'::jsonb),
  ('TEST_DEAD', NOW(), NOW(), 1, 0.5, '0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef', 'DEAD',
  '[{\"token_ca\":\"0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef\",\"chain_id\":\"56\"}]'::jsonb),
  ('TEST_ZERO', NOW(), NOW(), 1, 0.5, '0x0000000000000000000000000000000000000000', 'ZERO',
  '[{\"token_ca\":\"0x0000000000000000000000000000000000000000\",\"chain_id\":\"1\"}]'::jsonb)
  ON CONFLICT (event_key) DO NOTHING;"

  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  INSERT INTO signals(event_key) VALUES
  ('TEST_BAD'), ('TEST_DEAD'), ('TEST_ZERO')
  ON CONFLICT DO NOTHING;"

- 启动批量扫描任务（rules backend）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'ENABLE_GOPLUS_SCAN=true SECURITY_BACKEND=rules python -m api.jobs.goplus_scan'

- 查看 signals 更新结果
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  SELECT s.event_key, e.symbol, e.token_ca, s.goplus_risk, s.buy_tax, s.sell_tax, s.lp_lock_days, s.honeypot
  FROM signals s JOIN events e USING(event_key)
  WHERE s.event_key IN ('TEST_BAD','TEST_DEAD','TEST_ZERO');"

## Day8 — X KOL Collection

- 配置环境变量（使用 mock 模式）

  ```bash
  export X_BACKEND=graphql
  export X_GRAPHQL_MOCK=true
  export X_KOL_HANDLES=elonmusk,whale_alert,cryptocom
  ```

- 手动触发一轮采集

  ```bash
  curl -s "http://localhost:8000/ingest/x/kol/poll?once=true" | jq .
  ```

- 查看最近 1 小时统计

  ```bash
  curl -s "http://localhost:8000/ingest/x/kol/stats" | jq .
  ```

- 查询数据库入库结果

  ```bash
  docker compose -f infra/docker-compose.yml exec -T db \
    psql -U app -d app -c "SELECT COUNT(*) FROM raw_posts WHERE source='x';"
  ```

- 运行验收脚本

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python api/scripts/verify_x_kol.py
  ```

- 验收脚本 JSON 输出（检查 pass 字段）

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python api/scripts/verify_x_kol.py | jq .pass
  ```

- 查看带 CA/Symbol 的推文

  ```bash
  docker compose -f infra/docker-compose.yml exec -T db \
    psql -U app -d app -c "SELECT author, token_ca, symbol FROM raw_posts WHERE source='x' AND (token_ca IS NOT NULL OR symbol IS NOT NULL) LIMIT 5;"
  ```

- 检查去重键
  ```bash
  docker compose -f infra/docker-compose.yml exec -T redis redis-cli keys "dedup:x:*" | head -10
  ```

================================================================

## Day8.1 - X Avatar Monitoring (2025-09-01)

### 实现内容

- 新增 `XClient.fetch_user_profile()` 接口用于获取用户头像 URL
- 实现 `worker/jobs/x_avatar_poll.py` 轮询任务，检测 KOL 头像变更
- Redis 存储头像哈希和时间戳，TTL=14 天
- 支持 mock 模式下通过 `X_AVATAR_MOCK_BUMP` 控制变更模拟

### 运行验收

- 基线轮询（mock bump=0）

  ```bash
  docker compose -f infra/docker-compose.yml run --rm -v "$PWD":/app -w /app \
    -e PYTHONPATH=/app -e X_ENABLE_AVATAR_MONITOR=true -e X_BACKEND=graphql \
    -e X_GRAPHQL_MOCK=true -e X_KOL_HANDLES="elonmusk,whale_alert,cryptocom" \
    worker python -m worker.jobs.x_avatar_poll
  ```

- 模拟变更（mock bump=1）

  ```bash
  docker compose -f infra/docker-compose.yml run --rm -v "$PWD":/app -w /app \
    -e PYTHONPATH=/app -e X_ENABLE_AVATAR_MONITOR=true -e X_BACKEND=graphql \
    -e X_GRAPHQL_MOCK=true -e X_AVATAR_MOCK_BUMP=1 \
    -e X_KOL_HANDLES="elonmusk,whale_alert,cryptocom" \
    worker python -m worker.jobs.x_avatar_poll
  ```

- 运行验收脚本

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api \
    python api/scripts/verify_x_avatar.py
  ```

- 检查 Redis 存储的头像状态

  ```bash
  docker compose -f infra/docker-compose.yml exec -T redis \
    redis-cli keys "x:avatar:*" | head -10
  ```

- 查看特定 handle 的头像状态
  ```bash
  docker compose -f infra/docker-compose.yml exec -T redis \
    redis-cli mget x:avatar:elonmusk:last_hash \
    x:avatar:elonmusk:last_seen_ts x:avatar:elonmusk:last_change_ts
  ```

================================================================

## Day9 — DEX Snapshot (2025-09-02)

### 实现要点

- `providers/dex_provider.py`：DexScreener 优先，GeckoTerminal 兜底；Redis 短期缓存 + `last_ok` 降级
- 路由 `/dex/snapshot?chain=eth&contract=0x...` 返回价格、流动性、FDV、OHLC 及 `source/cache/stale/degrade/reason`
- 验收脚本：`api/scripts/verify_dex_snapshot.py`

### 运行验收

- 正常请求（USDC）
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -lc \
    'curl -s "http://localhost:8000/dex/snapshot?chain=eth&amp;contract=0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48" \
    | jq "{source,price_usd,liquidity_usd,fdv,ohlc,cache,stale,degrade,reason}"'
  ```
- 60 秒内二次请求命中缓存
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -lc \
    'curl -s "http://localhost:8000/dex/snapshot?chain=eth&amp;contract=0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48" >/dev/null; \
     curl -s "http://localhost:8000/dex/snapshot?chain=eth&amp;contract=0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48" | jq .cache'
  ```
- 双源失败返回 503（无缓存可回退）
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -lc \
    'curl -s -i "http://localhost:8000/dex/snapshot?chain=eth&amp;contract=0x0000000000000000000000000000000000000000" | head -n1; \
     curl -s "http://localhost:8000/dex/snapshot?chain=eth&amp;contract=0x0000000000000000000000000000000000000000" | jq "{reason,degrade,stale}"'
  ```
- Redis 观测
  ```bash
  docker compose -f infra/docker-compose.yml exec -T redis redis-cli --scan --pattern "dex:*" | head -20
  ```
- 一键验收脚本
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python api/scripts/verify_dex_snapshot.py | jq ".pass"
  ```

### 备注

- ENV：`DEX_CACHE_TTL_S=60`（兼容 `DEX_CACHE_TTL_SEC`），`DEX_TIMEOUT_S` 默认 `1.5`
- 双源都失败时：返回 `last_ok` 或 503；若 `last_ok` 命中则标记 `stale:true, degrade:true`

================================================================

## Day7.2 — Pushcard Schema & Templates (2025-09-02)

### 实现要点

- 新增 `schemas/pushcard.schema.json`（Draft-07），对象 `additionalProperties:false`
- `states.reason` 为必填，可为空字符串
- 模板：`templates/cards/primary_card.tg.j2`（Markdown，无 autoescape）、`templates/cards/primary_card.ui.j2`（HTML，有 autoescape）
- 生成与去抖：`api/cards/generator.py`、`api/cards/dedup.py`

### 运行验收

- 纯 Schema 验证
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python api/scripts/validate_cards.py | jq ".pass"
  ```
- 端到端卡片生成与去抖
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python api/scripts/verify_primary_cards.py | jq ".pass"
  ```
- 手动烟测（可选，展示 rendered）
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - &lt;&lt;PY
  from api.cards.generator import generate_card
  signals={"dex_snapshot":{"price_usd":1.0,"liquidity_usd":100.0,"fdv":1000.0,"ohlc":{"m5":{"o":1,"h":1,"l":1,"c":1},"h1":{"o":1,"h":1,"l":1,"c":1},"h24":{"o":1,"h":1,"l":1,"c":1}},"source":"dexscreener","cache":false,"stale":false,"degrade":false,"reason":""},"goplus_raw":{"summary":"ok"}}
  event={"type":"primary","risk_level":"red","token_info":{"symbol":"TKN","ca_norm":"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48","chain":"eth"},"risk_note":"note","verify_path":"/tx/0xabc","data_as_of":"2025-09-02T12:00:00Z"}
  card=generate_card(event, signals); print(len(card.get("rendered",{}).get("tg","")), len(card["rendered"]["ui"])>0)
  PY'
  ```

### 备注

- 依赖：`jsonschema`、`jinja2`、`redis` 已加入 `api/requirements.txt`
- Redis keys：`card:sent:{event_key}`、`recheck:hot`

================================================================

## Day9.1 — Meme 话题卡最小链路 (2025-09-04)

### 实现要点

- 新增路由 `/signals/topic`（固定 14 字段输出，含 degrade/topic_merge_mode）
- Pipeline：
  - `worker/pipeline/is_memeable_topic.py`（KeyBERT + mini 判定）
  - `worker/jobs/topic_aggregate.py`（24h 窗口聚合/合并/去重与限频）
  - `worker/jobs/push_topic_candidates.py`（推送候选卡，走 Telegram 适配层）
- 最小 Telegram 适配层：`api/services/telegram.py`（支持 `TELEGRAM_MODE=mock` 写入 `/tmp/telegram_sandbox.jsonl`）
- 黑白名单与阈值：`configs/topic_blacklist.yml`、`configs/topic_whitelist.yml`、`rules/topic_merge.yml`
- 斜率与窗口：Redis 存储分钟级计数，计算 `slope_10m`、`slope_30m`
- 迁移：`api/alembic/versions/007_signals_topic_ext.py`（signals/events topic 相关字段）
- 验收脚本：`api/scripts/verify_topic_signal.py`、`api/scripts/verify_topic_push.py`、`api/scripts/seed_topic_mentions.py`
- Make 目标：`verify-topic`、`verify-topic-push`、`push-topic-digest`、`seed-topic`

### 运行验收

- 应用迁移

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api alembic -c /app/api/alembic.ini upgrade head
  ```

- 验证 API 输出与字段完整性

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python -m api.scripts.verify_topic_signal
  ```

- 检查规范化与合并模式（示例）

  ```bash
  curl -s "http://localhost:8000/signals/topic?entities=pepe,frog,meme" | jq '.topic_entities,.keywords,.sources,.topic_merge_mode'
  ```

- 注入样例数据并验证斜率（应为非零且 10m != 30m）

  ```bash
  TID=$(curl -s "http://localhost:8000/signals/topic?entities=pepe,frog,meme" | jq -r .topic_id)
  docker compose -f infra/docker-compose.yml exec -T api python -m api.scripts.seed_topic_mentions "$TID"
  curl -s "http://localhost:8000/signals/topic?topic_id=$TID" | jq '.slope_10m,.slope_30m'
  ```

- 验证 Telegram 推送（mock）

  ```bash
  TELEGRAM_MODE=mock TELEGRAM_MOCK_PATH=/tmp/telegram_sandbox.jsonl \
  docker compose -f infra/docker-compose.yml exec -T api python -m api.scripts.verify_topic_push
  ```

- 检查 mock 输出文件
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api tail -n1 /tmp/telegram_sandbox.jsonl
  ```

### 备注

- ENV：`DAILY_TOPIC_PUSH_CAP, TOPIC_WINDOW_HOURS, TOPIC_SLOPE_WINDOW_10M, TOPIC_SLOPE_WINDOW_30M, TOPIC_SIM_THRESHOLD, TOPIC_JACCARD_FALLBACK, TOPIC_WHITELIST_BOOST, MINI_LLM_TIMEOUT_MS, EMBEDDING_BACKEND, KEYBERT_BACKEND, TELEGRAM_MODE, TELEGRAM_MOCK_PATH, TELEGRAM_BOT_TOKEN, TELEGRAM_SANDBOX_CHAT_ID`
- `topic_merge_mode` 默认 `normal`，仅在降级/回退时为 `fallback` 且 `degrade=true`
- Mock 模式默认安全，不连接真实 Telegram；接入正式机器人时移除 `TELEGRAM_MODE=mock`

================================================================

## Day9.2 — Primary 卡门禁 + 文案模板改造 (2025-09-05)

### 实现要点

- 扩展 `rules/risk_rules.yml`：强制 GoPlus 校验，不可伪绿；体检异常 → gray + 降级提示
- 新增 `api/security/goplus.py`：本地 evaluator，去除 provider 依赖
- 更新 `api/cards/generator.py`：Primary 卡强制经过 GoPlus gate；注入 `risk_source`、`risk_note`、`rules_fired`
- 新增去重逻辑 `api/cards/dedup.py`：按 `state|risk_color|degrade` 作为 state_version；仅状态变化时允许重发
- 模板更新：
  - `templates/cards/primary_card.*`：统一“候选/假设 + 验证路径”，渲染 `risk_note`、`legal_note`、隐藏区 `rules_fired`
  - `templates/cards/secondary_card.*`：新增 source_level、data_as_of、features_snapshot 占位
- 新增 `api/utils/ca.py`：EVM CA 归一化，去重，is_official_guess 标记
- `schemas/pushcard.schema.json` 扩展 gray 风险等级、可选 features_snapshot 与 source_level

### 运行验收

- GoPlus 体检校验

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api \
    python api/scripts/verify_goplus_security.py | jq

  ```

- DEX 快照校验（防止回归）
  docker compose -f infra/docker-compose.yml exec -T api \
   python api/scripts/verify_dex_snapshot.py | jq

- 模板与 Schema 校验
  docker compose -f infra/docker-compose.yml exec -T api \
   python api/scripts/validate_cards.py | jq ".pass"

- CA 归一化校验（inline）
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.utils.ca import normalize_ca
  print("eth upper+0X =>", normalize_ca("eth","0XDEADBEEF000000000000000000000000CAFEBABE"))
  print("bsc no 0x =>", normalize_ca("bsc","abcdef0000000000000000000000000000000000"))
  print("eth None =>", normalize_ca("eth", None))
  print("sol base58? =>", normalize_ca("sol","4Nd1xxxx"))
  PY

- Secondary 卡增强检查（样例生成）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
  from api.cards.generator import generate_card
  signals={"dex_snapshot":{"price_usd":1.0,"liquidity_usd":100.0,"fdv":1000.0,"ohlc":{"m5":{"o":1,"h":1,"l":1,"c":1},"h1":{"o":1,"h":1,"l":1,"c":1},"h24":{"o":1,"h":1,"l":1,"c":1}},"source":"dexscreener","cache":false,"stale":false,"degrade":false,"reason":""}}
  event={"type":"secondary","risk_level":"yellow","token_info":{"symbol":"BAD","ca_norm":"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48","chain":"eth"},"verify_path":"/tx/0xdef","data_as_of":"2025-09-05T12:00:00Z"}
  card=generate_card(event, signals); print(card.get("source_level"), card.get("features_snapshot"))
  PY'

================================================================

## Day10 — BigQuery Project & Provider Integration (2025-09-05)

### Implementation Points

- `api/clients/bq_client.py`: BigQuery client with dry-run guard, timeout, and exponential backoff
- `api/providers/onchain/bq_provider.py`: Template-based query execution with cost guards
- `api/routes/onchain.py`: Health and freshness endpoints
- `templates/sql/freshness_eth.sql`: Minimal partition-friendly query
- Docker volumes: Mount `/app/infra/secrets` for GCP service account JSON
- ENV: `GOOGLE_APPLICATION_CREDENTIALS`, `GCP_PROJECT`, `BQ_LOCATION`, `BQ_DATASET_RO`, `BQ_TIMEOUT_S`, `BQ_MAX_SCANNED_GB`, `ONCHAIN_BACKEND`

### Running Acceptance

- Prerequisites: Place service account JSON at `infra/secrets/gcp-sa.json` (DO NOT COMMIT)

  ```bash
  # Create secrets directory if not exists
  mkdir -p infra/secrets
  # Copy your service account key
  cp ~/path/to/your-sa-key.json infra/secrets/gcp-sa.json
  ```

- Health check (connectivity + dry-run probe)

  ```bash
  curl -s http://localhost:8000/onchain/healthz | jq
  # Expected: {"probe": 1, "row_count": 1, "dry_run_pass": true, "bq_bytes_scanned": <int>}
  ```

- Freshness check for Ethereum

  ```bash
  curl -s 'http://localhost:8000/onchain/freshness?chain=eth' | jq
  # Expected: {"latest_block": <int>, "data_as_of": "<iso8601>", "chain": "eth"}
  ```

- Test cost guard (temporarily set tiny threshold)

  ```bash
  docker compose -f infra/docker-compose.yml exec -T -e BQ_MAX_SCANNED_GB=0 api \
    sh -c 'curl -s http://localhost:8000/onchain/healthz | jq'
  # Expected: {"degrade": true, "reason": "cost_guard", "bq_bytes_scanned": <int>}
  ```

- Test backend off mode

  ```bash
  docker compose -f infra/docker-compose.yml exec -T -e ONCHAIN_BACKEND=off api \
    sh -c 'curl -s http://localhost:8000/onchain/freshness?chain=eth | jq'
  # Expected: {"degrade": true, "reason": "bq_off"}
  ```

- Unsupported chain fallback

  ```bash
  curl -s 'http://localhost:8000/onchain/freshness?chain=polygon' | jq
  # Expected: {"degrade": true, "reason": "unsupported_chain", "chain": "polygon"}
  ```

- Check structured logs (JSON format)

  ```bash
  docker compose -f infra/docker-compose.yml logs api | grep '"stage":"bq' | tail -5
  # Should see: bq.dry_run, bq.query, bq.freshness logs with bq_bytes_scanned field
  ```

### Notes

- All endpoints return HTTP 200 even for degraded responses (graceful degradation)
- Cost guard prevents queries exceeding `BQ_MAX_SCANNED_GB` threshold
- Dry-run is always executed first to estimate costs
- Backend can be disabled via `ONCHAIN_BACKEND=off` for testing
- Service account needs: BigQuery Job User role + Data Viewer on dataset

================================================================

## Day11 — Onchain SQL Templates & Guards (2025-09-07)

### 验收要点

- `/onchain/healthz` 为轻探针（dry-run 或 SELECT 1/LIMIT 1），不做重扫描
- `/onchain/freshness?chain=eth` 返回 `latest_block` 与 `data_as_of`
- `/onchain/query` 三模板可用：`active_addrs_window`、`token_transfers_window`、`top_holders_snapshot`
- 统一返回字段：`data_as_of, data_as_of_lag, bq_bytes_scanned, cache_hit, approximate`
- 成本护栏：先 dry-run，超 `BQ_MAX_SCANNED_GB` → `{ "degrade": "cost_guard" }`（HTTP 200）；真实执行强制 `maximum_bytes_billed`
- 缓存：TTL 60–120 秒；命中 `cache_hit=true`；缓存检查发生在成本护栏之后

### 运行验收

- 健康与新鲜度

  ```bash
  curl -s http://localhost:8000/onchain/healthz | jq
  curl -s 'http://localhost:8000/onchain/freshness?chain=eth' | jq

  ```

- 模板执行（1 小时窗口）

NOW=$(date -u +%s); FROM=$(($NOW-3600))
  curl -s "http://localhost:8000/onchain/query?template=token_transfers_window&address=0xdAC17F958D2ee523a2206206994597C13D831ec7&from_ts=${FROM}&to_ts=${NOW}&window_minutes=60" | jq
  curl -s "http://localhost:8000/onchain/query?template=active_addrs_window&address=0xdAC17F958D2ee523a2206206994597C13D831ec7&from_ts=${FROM}&to_ts=${NOW}&window_minutes=60" | jq

- 缓存命中（第二次应 cache_hit=true）

NOW=$(date -u +%s); FROM=$(($NOW-3600))
  curl -s "http://localhost:8000/onchain/query?template=token_transfers_window&address=0xdAC17F958D2ee523a2206206994597C13D831ec7&from_ts=${FROM}&to_ts=${NOW}&window_minutes=60" | jq >/dev/null
  curl -s "http://localhost:8000/onchain/query?template=token_transfers_window&address=0xdAC17F958D2ee523a2206206994597C13D831ec7&from_ts=${FROM}&to_ts=${NOW}&window_minutes=60" | jq '.cache_hit'

- 触发新鲜度守门（需要让 API 进程读取 env，修改后重启）

  写入极小 SLO 并强制重建容器

sed -i'' -e '/^FRESHNESS_SLO=/d' infra/.env; echo 'FRESHNESS_SLO=1' >> infra/.env
docker compose -f infra/docker-compose.yml up -d --force-recreate

调用接口，预期 data_as_of_lag=true

curl -s "http://localhost:8000/onchain/query?template=active_addrs_window&address=0x0000000000000000000000000000000000000001&window_minutes=60" | jq '.data_as_of_lag'

- 触发成本护栏（通过成本护栏后再查缓存，避免缓存短路）

  设置扫描上限为 0 GB 并重启

sed -i'' -e '/^BQ_MAX_SCANNED_GB=/d' infra/.env; echo 'BQ_MAX_SCANNED_GB=0' >> infra/.env
docker compose -f infra/docker-compose.yml up -d --force-recreate

调用接口，预期返回 { "degrade": "cost_guard", "cache_hit": false }

curl -s "http://localhost:8000/onchain/query?template=active_addrs_window&address=0x0000000000000000000000000000000000000002&window_minutes=60" | jq '{degrade, cache_hit, bq_bytes_scanned}'

- 回滚默认配置并复测

恢复默认阈值并重启

sed -i'' -e '/^FRESHNESS_SLO=/d' -e '/^BQ_MAX_SCANNED_GB=/d' infra/.env
printf 'FRESHNESS_SLO=600\nBQ_MAX_SCANNED_GB=5\n' >> infra/.env
docker compose -f infra/docker-compose.yml up -d --force-recreate

健康与模板烟测

curl -s http://localhost:8000/onchain/healthz | jq
NOW=$(date -u +%s); FROM=$(($NOW-3600))
  curl -s "http://localhost:8000/onchain/query?template=token_transfers_window&address=0xdAC17F958D2ee523a2206206994597C13D831ec7&from_ts=${FROM}&to_ts=${NOW}&window_minutes=60" | jq '.cache_hit, .data_as_of_lag'

- 观测日志（可选）

docker compose -f infra/docker-compose.yml logs api | egrep '"stage":"bq\\.(dry_run|query|cache_hit|sql_preview)"' | tail -20

- 备注
  “exec -e FRESHNESS_SLO=1 curl …” 这种写法不会影响已启动的 API 进程，请使用修改 infra/.env + 强制重建容器的方式让配置生效。
  缓存检查顺序在成本护栏之后；因此即使存在缓存，超标的请求也会被 cost_guard 拦截。

================================================================

## Day E — Celery Beat Integration & Command-line Triggers (Card E)

### Implementation Points

- Celery Beat periodic task: `onchain_verify_periodic` runs every 60 seconds
- Makefile targets: `onchain-verify-once` and `expert-dryrun` for manual triggers
- Structured JSON logging for task execution results
- Support for EVENT_KEY parameter in verify command
- Support for ADDRESS and WINDOW parameters in expert dryrun

### Running Acceptance

- Start services with Celery Beat scheduler

  ```bash
  make up
  # Check Celery logs for periodic task execution
  docker compose -f infra/docker-compose.yml logs -f worker | grep onchain_verify_periodic
  ```

- Manual onchain verification (all candidates)

  ```bash
  make onchain-verify-once
  # Expected output: {"scanned": N, "evaluated": M, "updated": K}
  ```

- Manual onchain verification (specific event)

  ```bash
  make onchain-verify-once EVENT_KEY=demo_cardc
  # Expected output: {"scanned": 1, "evaluated": 1, "updated": 0 or 1}
  ```

- Expert view dryrun (24h window by default)

  ```bash
  make expert-dryrun ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7
  # Expected output: JSON with onchain features for the address
  ```

- Expert view dryrun (custom window)

  ```bash
  make expert-dryrun ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7 WINDOW=1h
  # Expected output: JSON with 1-hour window features
  ```

- Expert view with disabled EXPERT_VIEW (should fail gracefully)

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -c 'curl -s http://localhost:8000/expert/onchain?chain=eth&address=0x123' | jq
  # Expected: {"detail": "Expert view disabled"} or similar error
  ```

### Verification Commands

- Check Celery Beat is running

  ```bash
  docker compose -f infra/docker-compose.yml ps | grep worker
  # Should show worker container running
  ```

- View periodic task logs (JSON format)

  ```bash
  docker compose -f infra/docker-compose.yml logs worker | grep '"stage":"onchain_verify_periodic"' | tail -5
  # Should see periodic execution with scanned/evaluated/updated counts
  ```

- Test cache hit for expert view

  ```bash
  # First call - cache miss
  make expert-dryrun ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7 | jq .cache_hit
  # Second call - cache hit (within TTL)
  make expert-dryrun ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7 | jq .cache_hit
  ```

### Sample Expected Output

- onchain-verify-once output:

  ```json
  {
    "scanned": 3,
    "evaluated": 2,
    "updated": 1,
    "duration_ms": 245
  }
  ```

- expert-dryrun output:
  ```json
  {
    "chain": "eth",
    "address": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "windows": {
      "30": [
        {
          "as_of_ts": "2025-09-08T10:00:00Z",
          "addr_active": 150,
          "growth_ratio": 1.2
        }
      ],
      "60": [
        {
          "as_of_ts": "2025-09-08T10:00:00Z",
          "addr_active": 300,
          "growth_ratio": 1.5
        }
      ]
    },
    "cache_hit": false,
    "stale": false
  }
  ```

================================================================

## Day12 — On-chain Features Light Table (2025-09-07)

### Migration

```bash
# Apply migration 010
docker compose -f infra/docker-compose.yml exec -T api alembic upgrade 010

# Verify migration 010 metadata
docker compose -f infra/docker-compose.yml exec -T api alembic show 010

# Roundtrip check (optional)
docker compose -f infra/docker-compose.yml exec -T api alembic downgrade -1
docker compose -f infra/docker-compose.yml exec -T api alembic upgrade head
```

### Seed and Verify

```bash
# Run Day12 verifier with stub data (writes onchain_features rows)
docker compose -f infra/docker-compose.yml exec -T api \
  env ENABLE_STUB_DATA=true python -m api.scripts.verify_onchain_features

# Inspect onchain_features distribution by window
docker compose -f infra/docker-compose.yml exec -T db \
  psql -U app -d app -c \
  "SELECT window_minutes, COUNT(*) AS cnt, MAX(growth_ratio) AS latest_growth
     FROM onchain_features
    WHERE chain='eth' AND address='0x0000000000000000000000000000000000000000'
    GROUP BY window_minutes ORDER BY window_minutes;"
```

### API Testing

````bash
# Query features endpoint (first call - cache miss)
curl -s "http://localhost:8000/onchain/features?chain=eth&address=0x0000000000000000000000000000000000000000" | jq .

# Query again (should hit cache, cache=true)
curl -s "http://localhost:8000/onchain/features?chain=eth&address=0x0000000000000000000000000000000000000000" | jq .cache

# Expected:
# - windows["30"], windows["60"], windows["180"] present (if data exists)
# - growth_ratio non-null for the second timestamp entries
# - stale=false if DB has recent rows; cache=true on second identical query

================================================================

## Day13&amp;14 — Onchain 证据接入 &amp; 专家视图 (2025-09-08)

### CARD A — 规则 DSL 与评估引擎（快速验收）

- 运行单测（规则引擎）
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api \
    pytest -q tests/test_rules_engine.py
````

- 人工抽检（边界与兜底）

  ```bash
  # 确认 YAML 严格性、边界与异常兜底（如项目保留了 edgecases 测试）
  docker compose -f infra/docker-compose.yml exec -T api \
    pytest -q tests/test_rules_engine_edgecases.py || true
  ```

- 最小内联验证（非必需）
  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.onchain.rules_engine import load_rules, evaluate
  from api.onchain.dto import OnchainFeature
  from datetime import datetime, timezone
  r = load_rules('rules/onchain.yml')
  f = OnchainFeature(active_addr_pctl=0.96, growth_ratio=2.5,
                     top10_share=0.30, self_loop_ratio=0.05,
                     asof_ts=datetime.now(timezone.utc), window_min=60)
  print(evaluate(f, r).model_dump())
  PY
  ```

---

### CARD B — 候选验证作业与迁移（幂等/降级可用）

- 应用迁移（到 head）

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api \
    alembic -c /app/api/alembic.ini upgrade head
  ```

- 检查 signals 必要列与索引

  ```bash
  docker compose -f infra/docker-compose.yml exec -T db \
    psql -U app -d app -c "\d+ signals"
  ```

- 造一条候选（需先有 events 外键）

  ```bash
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  INSERT INTO events (event_key, start_ts, last_ts, summary, type)
  VALUES ('DEMO_B', NOW(), NOW(), 'stub summary', 'stub') ON CONFLICT DO NOTHING;
  INSERT INTO signals (event_key, state, ts)
  VALUES ('DEMO_B','candidate', NOW()) ON CONFLICT DO NOTHING;
  "
  ```

- 跑一次作业

  ```bash
  docker compose -f infra/docker-compose.yml exec -T worker bash -lc '
    export PYTHONPATH=/app
    python - <<PY
  from worker.jobs.onchain.verify_signal import run_once
  print(run_once())
  PY
  '
  ```

- 验证写入效果
  ```bash
  docker compose -f infra/docker-compose.yml exec -T db \
    psql -U app -d app -c "
    SELECT event_key, state, onchain_asof_ts, onchain_confidence
      FROM signals WHERE event_key='DEMO_B';
    "
  ```

> 注：`ONCHAIN_RULES=off` 时仅写 `onchain_asof_ts/onchain_confidence`，不改 `state`。

---

### CARD C — `/signals/{event_key}` 摘要接口

- 未命中缓存

  ```bash
  curl -s "http://localhost:8000/signals/DEMO_B" | jq .
  ```

- 二次命中缓存（TTL 下降）

  ```bash
  curl -s "http://localhost:8000/signals/DEMO_B" | jq '.cache'
  ```

- 404 场景（不存在的 key）
  ```bash
  curl -s -i "http://localhost:8000/signals/NO_SUCH_KEY" | head -1
  ```

---

### CARD D — 专家视图（限流/缓存/打点）

- 正常调用（需在 `infra/.env` 打开 `EXPERT_VIEW=on` 并设置 `EXPERT_KEY`）

  ```bash
  curl -s -H "X-Expert-Key: ${EXPERT_KEY:-dev_expert_key}" \
    "http://localhost:8000/expert/onchain?chain=eth&amp;address=0xdAC17F958D2ee523a2206206994597C13D831ec7" | jq .
  ```

- 登录失败（缺少/错误密钥 → 403）

  ```bash
  curl -s -i "http://localhost:8000/expert/onchain?chain=eth&amp;address=0x123" | head -1
  ```

- 限流验证（1 分钟内超过阈值 → 429）

  ```bash
  for i in 1 2 3 4 5 6; do
    curl -s -o /dev/null -w "%{http_code}\n" \
      -H "X-Expert-Key: ${EXPERT_KEY:-dev_expert_key}" \
      "http://localhost:8000/expert/onchain?chain=eth&amp;address=0xdAC17F958D2ee523a2206206994597C13D831ec7";
  done
  ```

- 缓存命中（第二次应 `cache.hit=true` 或 TTL 下降）
  ```bash
  curl -s -H "X-Expert-Key: ${EXPERT_KEY:-dev_expert_key}" \
    "http://localhost:8000/expert/onchain?chain=eth&amp;address=0xdAC17F958D2ee523a2206206994597C13D831ec7" | jq '.cache // .cache_hit'
  ```

> BQ 源可选：设置 `EXPERT_SOURCE=bq` 且配置 `BQ_ONCHAIN_FEATURES_VIEW`。没有凭证时会优雅降级，返回 `stale/empty`。

---

### CARD E — 集成与命令行触发（补充）

> 已有「Day E」章节记录了详细命令。这里补充两条常用快捷方式：

- 一键验证所有候选

  ```bash
  make onchain-verify-once
  ```

- 专家视图干跑（24h 窗口，地址必填）
  ```bash
  make expert-dryrun ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7
  ```

================================================================

```

```
