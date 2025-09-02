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
