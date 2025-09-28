# RUN_NOTES — Daily Verification Commands

本文件记录从 Day0 开始，每日验收所需的关键命令。
只保存“怎么跑”的命令，不保存结果。结果会随数据变化，请实时执行确认。

================================================================

## Day0 — Environment & Infra Init (2025-08-17)

- 启动基础服务（db/redis/api）
  make up
- 查看容器状态
  docker compose -f infra/docker-compose.yml ps
- 健康检查
  curl http://localhost:8000/healthz

---

## Day1 — Monorepo Init / DB migrations (2025-08-18)

- 应用 Alembic 迁移（使用容器内 alembic.ini）
  docker compose -f infra/docker-compose.yml exec -T api alembic -c /app/api/alembic.ini upgrade head
- 确认表创建
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "\dt"

---

## Day2 — Filter / Refine / Dedup / DB pipeline (2025-08-19)

⚠ variance: 原计划是「X API 采集 / 粗筛」，实际完成的是 pipeline/demo，采集推迟到 Day8。

- 运行 demo pipeline
  make demo
- 验证 raw_posts 表有数据
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT COUNT(\*) FROM raw_posts;"

---

## Day3 — Demo ingest script & logging (2025-08-20)

⚠ variance: 原计划是「规则与关键词粗筛」，实际完成的是 demo ingest & logging；粗筛部分将在 Day8–Day9 补齐。

- 运行 demo ingestion 脚本（直接脚本方式）
  docker compose -f infra/docker-compose.yml exec -T api python scripts/demo_ingest.py

---

## Day3+ — Metrics / Cache / Benchmarks (2025-08-21)

- 运行基准测试
  make bench-sentiment
- 查看 golden.jsonl 样例
  cat scripts/golden.jsonl

---

## Day4 — HuggingFace Sentiment & Keyphrases (2025-08-22)

- 测试 rules backend（默认）
  docker compose -f infra/docker-compose.yml exec -T api python -c "from api.filter import analyze_sentiment; print(analyze_sentiment('this is bad'))"
- 测试 HF backend
  docker compose -f infra/docker-compose.yml exec -T -e SENTIMENT_BACKEND=hf -e HF_MODEL=cardiffnlp/twitter-roberta-base-sentiment-latest api python -c "from api.filter import analyze_sentiment; print(analyze_sentiment('I love this project'))"
- 测试 Keyphrases (KBIR)
  docker compose -f infra/docker-compose.yml exec -T -e KEYPHRASE_BACKEND=kbir api python -c "from api.keyphrases import extract_keyphrases; print(extract_keyphrases('Airdrop $ARB claim open now'))"
- 运行 bench-sentiment（双后端比较）
  make bench-sentiment

---

## Day5 — Event Aggregation (2025-08-23)

- 运行 demo，触发事件聚合
  make demo
- 查看 events 聚合结果（数量 & 证据数总和）
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT COUNT(\*) AS n_events, SUM(evidence_count) AS total_evidence FROM events;"
- 查看 events 表详细记录
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT event_key, evidence_count, candidate_score FROM events ORDER BY last_ts DESC;"
- 运行 verify_events 脚本
  docker compose -f infra/docker-compose.yml exec -T api python scripts/verify_events.py

---

## Day5+ — Event Key 不变性 & 合并护栏 (2025-08-24)

- 打印当前盐与严格模式
  docker compose -f infra/docker-compose.yml exec -T api sh -c 'echo "Salt: $EVENT_KEY_SALT, Strict: $EVENT_MERGE_STRICT"'

- 本地调用 make_event_key() 的最小例子

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.events import make_event_key
  from datetime import datetime, timezone
  post = {
      "type": "token_launch",
      "symbol": "TEST",
      "token_ca": "0x1234567890123456789012345678901234567890",
      "text": "Check out this new token @user https://example.com",
      "created_ts": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
  }
  key1 = make_event_key(post)
  key2 = make_event_key(post)  # Should be identical
  print(f"Key1: {key1}")
  print(f"Key2: {key2}")
  print(f"Keys match: {key1 == key2}")
  print(f"Key length: {len(key1)} (should be 40)")
  PY
  ```

- 测试 merge_event_by_key() dry-run

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.events import merge_event_by_key
  result = merge_event_by_key(
      "test_event_key_123",
      {"source": "x", "evidence": [{"data": "test"}], "sources": ["twitter", "telegram"]},
      strict=True
  )
  print(f"Would change: {result['would_change']}")
  print(f"Delta count: {result['delta_count']}")
  print(f"Sources (list): {result['sources_candidate']}")
  print(f"Sources type: {type(result['sources_candidate'])}")
  PY
  ```

- 测试 salt 变更警告（只打印一次）

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -c 'EVENT_KEY_SALT=v2 python - <<PY
  from api.events import make_event_key
  from datetime import datetime, timezone
  post = {"type": "test", "created_ts": datetime.now(timezone.utc)}
  # First call - should log salt_changed
  key1 = make_event_key(post)
  # Second call - should NOT log again
  key2 = make_event_key(post)
  print(f"Generated {key1}, {key2}")
  PY'
  ```

- 测试 token_ca 校验

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.events import make_event_key
  from datetime import datetime, timezone
  # Test missing 0x prefix warning
  post1 = {"type": "test", "token_ca": "abc123", "created_ts": datetime.now(timezone.utc)}
  key1 = make_event_key(post1)
  # Test non-hex chars warning
  post2 = {"type": "test", "token_ca": "0xGGGG", "created_ts": datetime.now(timezone.utc)}
  key2 = make_event_key(post2)
  print("Check logs for token_ca_warning events")
  PY
  ```

- 注意：真正落库与 refs 校验请见后续 Card

---

---

## Day5++ — Cross-source Evidence Merge & Dedup (2025-08-25)

- 验证证据合并（从宿主机运行）

  ```bash
  # 宿主机方式
  PYTHONPATH=. python -m scripts.verify_events --sample scripts/replay.jsonl

  # 容器方式（如果 scripts 目录已映射）
  docker compose -f infra/docker-compose.yml exec -T api python -m scripts.verify_events --sample scripts/replay.jsonl
  ```

- 严格/宽松模式对比

  ```bash
  # Strict mode (default) - 期望 cross_source_cooccurrence > 0
  EVENT_MERGE_STRICT=true PYTHONPATH=. python -m scripts.verify_events --sample scripts/replay.jsonl

  # Loose mode - 期望 cross_source_cooccurrence = 0
  EVENT_MERGE_STRICT=false PYTHONPATH=. python -m scripts.verify_events --sample scripts/replay.jsonl
  ```

- 新旧入口对比

  ```bash
  # 新入口：upsert_event_with_evidence
  python -c "
  from api.events import upsert_event_with_evidence, _build_evidence_item
  from datetime import datetime, timezone

  evidence = [
      _build_evidence_item('x', datetime.now(timezone.utc), {'tweet_id': '123'}, 'test', 1.0),
      _build_evidence_item('dex', datetime.now(timezone.utc), {'pool': '0xabc'}, 'price', 0.8)
  ]

  result = upsert_event_with_evidence(
      event={'type': 'test', 'symbol': 'TEST', 'created_ts': datetime.now(timezone.utc)},
      evidence=evidence,
      current_source='x'  # Single source mode
  )
  print(f'Event key: {result[\"event_key\"][:8]}...')
  print(f'Evidence count: {result[\"evidence_count\"]}')
  "

  # 旧入口：upsert_event (兼容性保留)
  python -c "
  from api.events import upsert_event
  from datetime import datetime, timezone

  result = upsert_event(
      {'type': 'test', 'symbol': 'TEST', 'created_ts': datetime.now(timezone.utc)},
      x_data={'tweet_id': '123', 'text': 'test'},
      dex_data={'price_usd': 0.001}
  )
  print(f'Event key: {result[\"event_key\"][:8]}...')
  "
  ```

- 查看 evidence 数组内容
  ```bash
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
    SELECT event_key, jsonb_array_length(evidence) as evidence_items,
           evidence->0->>'source' as first_source
    FROM events
    WHERE evidence IS NOT NULL
    LIMIT 5;"
  ```

---

## Day6 — Refiner (LLM Integration) (2025-08-26)

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

# Day7 — GoPlus Security Integration (2025-08-27)

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

## Day7.1 (2025-08-28)

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

## Day8 — X KOL Collection (2025-08-29)

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

## P1-2 — Topic 推送链路完成 (2025-09-26)

### 实现要点

- **Topic检测集成**：`MemeableTopicDetector` 在 `demo_ingest.py` 中实现，使用KeyBERT提取实体
- **Topic ID生成**：SHA1哈希算法 `t.{sha1(sorted_entities)[:12]}`
- **数据库存储**：events表新增 `topic_hash` 和 `topic_entities` 字段（已存在）
- **信号扫描任务**：`worker/jobs/topic_signal_scan.py` - 扫描events生成signals（Celery Beat每5分钟）
- **聚合任务优化**：`worker/jobs/topic_aggregate.py` - 支持PostgreSQL/SQLite，24小时窗口聚合
- **推送触发**：aggregate_topics末尾直接触发推送（强耦合上线版）
- **去重机制**：Redis key `topic:dedup:{topic_id}` TTL=3600秒

### 运行验收

- Topic检测与存储
  ```bash
  # 运行demo ingestion（含topic检测）
  docker compose -f infra/docker-compose.yml exec -T api python scripts/demo_ingest.py
  # 验证events表中的topic数据
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT event_key, topic_hash, topic_entities FROM events WHERE topic_hash IS NOT NULL;"
  ```

- Topic信号扫描
  ```bash
  # 手动运行扫描
  docker compose -f infra/docker-compose.yml exec -T worker python -c "from worker.jobs.topic_signal_scan import scan_topic_signals; print(scan_topic_signals.__wrapped__())"
  # 验证signals表
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT COUNT(*) FROM signals WHERE market_type='topic';"
  ```

- Topic聚合与推送
  ```bash
  # 手动运行聚合（含推送）
  export TOPIC_PUSH_MIN_MENTIONS=2
  docker compose -f infra/docker-compose.yml exec -T -e TOPIC_PUSH_MIN_MENTIONS=2 worker python -c "from worker.jobs.topic_aggregate import aggregate_topics; print(aggregate_topics.__wrapped__())"
  # 查看推送日志
  docker compose -f infra/docker-compose.yml logs worker --tail 100 | grep "topic.push"
  # 验证Redis去重
  docker compose -f infra/docker-compose.yml exec -T redis redis-cli keys "topic:dedup:*"
  ```

### 必需配置（.env）
  ```bash
  TELEGRAM_SANDBOX_CHAT_ID=your_chat_id  # 必需：Telegram频道ID
  TOPIC_PUSH_MIN_MENTIONS=3              # 可选：最小提及次数（默认3）
  TOPIC_PUSH_COOLDOWN_SEC=3600           # 可选：去重时间（默认3600秒）
  TOPIC_PUSH_ENABLED=true                # 可选：启用推送（默认true）
  ```

### 测试覆盖
- 单元测试：`pytest tests/test_topic_unit.py` （6个测试）
- 集成测试：`pytest tests/test_topic_integration.py` （4个测试）
- 性能测试：`pytest tests/test_topic_performance.py` （5个测试）

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

================================================================

## Day10 — 就绪探针与可观测最小集 (2025-09-28)

### 健康与就绪

- Liveness（存活）
  ```bash
  curl -s http://localhost:8000/healthz | jq .
  ```
- Readiness（就绪：DB/Redis/队列）
  ```bash
  # 期望 200 且响应头含 no-store
  curl -s -i http://localhost:8000/readyz | sed -n '1,5p'
  curl -s -I http://localhost:8000/readyz | grep -i 'Cache-Control'
  ```

### 指标检查（/metrics）

- 关键指标存在性（容器重启、队列 backlog、就绪延迟、onchain 并发）
  ```bash
  curl -s http://localhost:8000/metrics | egrep \
   'container_restart_total|celery_queue_backlog|celery_queue_backlog_warn_total|readyz_latency_ms_' \
   | sed -n '1,10p'

  curl -s http://localhost:8000/metrics | egrep \
   'onchain_lock_(acquire|release|wait|hold|expired)|onchain_state_cas_conflict_total|onchain_process_ms_bucket' \
   | sed -n '1,10p'
  ```

### 队列 backlog 观测（Celery 默认队列）

- 读长度（不建议在生产随意写入）
  ```bash
  docker compose -f infra/docker-compose.yml exec -T redis redis-cli LLEN celery
  ```
- 阈值（看板用）
  ```bash
  # 默认阈值，亦可在部署中配置
  echo "CELERY_BACKLOG_WARN=${CELERY_BACKLOG_WARN:-100}"
  ```

### 环境与回滚开关（on-chain 并发）

```bash
docker compose -f infra/docker-compose.yml exec -T api sh -lc \
  'echo ONCHAIN_LOCK_ENABLE=$ONCHAIN_LOCK_ENABLE; echo ONCHAIN_CAS_ENABLE=$ONCHAIN_CAS_ENABLE'
```

### Compose 健康探针（/readyz）

```bash
sed -n '60,90p' infra/docker-compose.yml | nl -ba | sed -n '1,40p'
```

### 备份演练（摘要）

- 详见 docs/ops.md；最小示例：
  ```bash
  # 导出到日期命名文件
  pg_dump -U $PGUSER -h $PGHOST -p ${PGPORT:-5432} $PGDB > backup_$(date +%F).sql
  # 恢复到 ${PGDB}_test 库
  createdb -U $PGUSER -h $PGHOST -p ${PGPORT:-5432} ${PGDB}_test || true
  psql -U $PGUSER -h $PGHOST -p ${PGPORT:-5432} -d ${PGDB}_test -f backup_$(date +%F).sql
  ```

### 预期

- /readyz 200；断开 Postgres 或 Redis 时 503，恢复后 200
- /metrics 可见：container_restart_total、celery_queue_backlog、readyz_latency_ms_bucket、onchain_* 系列
- backlog ≥ 阈值时出现 `queue.backlog.warn` 日志与 `celery_queue_backlog_warn_total` 递增

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
# - Freshness SLO：`FRESHNESS_SLO` 默认 600s，关注 `/metrics` 中 `bq_data_freshness_lag_seconds{chain="eth"}` 超阈值即视为告警

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

## CardC & CardD — Heat Calculation Service with Persistence (2025-09-09)

- 基本调用（使用 token 参数）

  ```bash
  curl -s "http://localhost:8000/signals/heat?token=USDT" | jq
  ```

- 使用 token_ca 参数

  ```bash
  curl -s "http://localhost:8000/signals/heat?token_ca=0xdac17f958d2ee523a2206206994597c13d831ec7" | jq
  ```

- 阈值对比测试

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export THETA_RISE=0.1
    echo "=== THETA_RISE=0.1 ==="
    curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{slope,trend}"
    export THETA_RISE=0.5
    echo "=== THETA_RISE=0.5 ==="
    curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{slope,trend}"'
  ```

- 噪声地板测试

  ```bash
  # 设置较高的噪声地板
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_NOISE_FLOOR=100
    curl -s "http://localhost:8000/signals/heat?token=RARE" | jq "{cnt_10m,slope,trend,degrade}"'
  ```

- EMA 平滑测试

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_EMA_ALPHA=0.3
    echo "First call:"
    curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{slope,slope_ema,trend,trend_ema}"
    echo "Second call (EMA smoothed):"
    curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{slope,slope_ema,trend,trend_ema}"'
  ```

- 缓存命中测试

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_CACHE_TTL=30
    echo "First call (cache miss):"
    time curl -s "http://localhost:8000/signals/heat?token=USDT" | jq .from_cache
    echo "Second call (cache hit):"
    time curl -s "http://localhost:8000/signals/heat?token=USDT" | jq .from_cache'
  ```

- 落盘演示（幂等性）

  ```bash
  # 不落盘（默认）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_ENABLE_PERSIST=false
    curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{persisted,asof_ts}"'

  # 开启落盘（需要 signals 表中已存在对应行）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_ENABLE_PERSIST=true
    curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{persisted,asof_ts}"'

  # 查看数据库中的 heat 数据（包含 asof_ts）
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
    SELECT event_key, symbol,
           features_snapshot->'heat'->>'asof_ts' as asof_ts,
           features_snapshot->'heat' as heat
    FROM signals WHERE symbol='USDT' LIMIT 1;"
  ```

- strict_match 行为验证

  ```bash
  # 仅 symbol 存在而无 token_ca 时（strict_match=false 允许回退）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_ENABLE_PERSIST=true
    export HEAT_PERSIST_STRICT_MATCH=false
    curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{persisted,asof_ts}"'

  # strict_match=true 时不允许 symbol 回退
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_ENABLE_PERSIST=true
    export HEAT_PERSIST_STRICT_MATCH=true
    curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{persisted}"'
  ```

- 超时与异常处理

  ```bash
  # 设置极短超时测试持久化失败
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_ENABLE_PERSIST=true
    export HEAT_PERSIST_TIMEOUT_MS=1
    curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{persisted,degrade}"'
  # 期望：persisted:false, degrade:false（计算已完成）
  ```

- 并发测试（可选）

  ```bash
  # 同时发起多个请求测试锁冲突处理
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_ENABLE_PERSIST=true
    for i in 1 2 3; do
      curl -s "http://localhost:8000/signals/heat?token=USDT" | jq .persisted &
    done
    wait'
  ```

- 降级演示（样本不足）

  ```bash
  # 临时提高最小样本要求
  docker compose -f infra/docker-compose.yml exec -T api sh -lc '
    export HEAT_MIN_SAMPLE=99
    curl -s "http://localhost:8000/signals/heat?token=RARE" | jq "{slope,trend,degrade}"'
  ```

- 错误参数测试

  ```bash
  # 缺少参数
  curl -s "http://localhost:8000/signals/heat" -w "\nHTTP Status: %{http_code}\n"

  # 同时提供两个参数
  curl -s "http://localhost:8000/signals/heat?token=USDT&token_ca=0x123" -w "\nHTTP Status: %{http_code}\n"

  # 非法 token_ca（缺少 0x）
  curl -s "http://localhost:8000/signals/heat?token_ca=abc123" -w "\nHTTP Status: %{http_code}\n"
  ```

================================================================

## Card D.1: 持久化匹配改为 event_key（含兜底与日志修正） (2025-09-10)

### 验收步骤

1. **在 DB 找一条有地址的最近事件，拿 event_key 和 token_ca**

   ```bash
   docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c \
   "SELECT event_key, token_ca, symbol, last_ts
    FROM events
    WHERE token_ca ~ '^0x'
    ORDER BY last_ts DESC
    LIMIT 1"
   ```

2. **修改 infra/.env 开启持久化并关闭缓存，然后重启 api**

   ```bash
   # 编辑 infra/.env 设置:
   # HEAT_ENABLE_PERSIST=true
   # HEAT_CACHE_TTL=0
   docker compose -f infra/docker-compose.yml up -d api
   ```

3. **宿主机请求 API 并验证写入（替换为上一步的真实地址与 event_key）**

   ```bash
   # 请求 heat API（替换 0x<真实地址>）
   curl -s "http://localhost:8000/signals/heat?token_ca=0x<真实地址>" | jq .

   # 验证数据库写入（替换 <真实event_key>）
   docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c \
   "SELECT features_snapshot->'heat'
    FROM signals
    WHERE event_key = '<真实event_key>'
    LIMIT 1"
   ```

### 验收标准

- 传入合法 token_ca 时：响应 persisted:true 且 DB 对应 event_key 的 features_snapshot->'heat' 为 JSON 对象，包含 asof_ts
- 仅传 symbol 且 strict_match=false：允许解析并写入；strict_match=true：persisted:false 且 reason="event_key_not_found"
- 解析失败、锁冲突、行不存在等分支：persisted:false，日志 reason 清晰
- UPDATE 语句不再 JOIN events，仅按 event_key 命中

### 回滚

关闭 `HEAT_ENABLE_PERSIST` 即停止写库；读路径不受影响

================================================================

## Card E: 运维与可观测性完整指南 (2025-09-10)

### 1. Events 重放验证

#### Strict 模式（默认）

```bash
# 严格模式：要求 event_key 完全一致
docker compose -f infra/docker-compose.yml exec -T api sh -c '
  EVENT_MERGE_STRICT=true PYTHONPATH=. python -m scripts.verify_events --sample scripts/replay.jsonl
'
```

#### Loose 模式

```bash
# 宽松模式：允许 event_key 不一致
docker compose -f infra/docker-compose.yml exec -T api sh -c '
  EVENT_MERGE_STRICT=false PYTHONPATH=. python -m scripts.verify_events --sample scripts/replay.jsonl
'
```

#### 期望输出

- 每个事件 `refs >= 2`（多源证据）
- 重放的 `event_key` 与原始一致（strict 模式）
- 包含 X + DEX/GoPlus 的复合证据

### 2. Heat API 调用示例

#### 基础调用

```bash
# 使用 token 参数
curl -s "http://localhost:8000/signals/heat?token=USDT" | jq .

# 使用 token_ca 参数
curl -s "http://localhost:8000/signals/heat?token_ca=0xdac17f958d2ee523a2206206994597c13d831ec7" | jq .
```

#### 持久化测试

```bash
# 开启持久化
docker compose -f infra/docker-compose.yml exec -T api sh -c '
  HEAT_ENABLE_PERSIST=true HEAT_CACHE_TTL=0 \
  curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{persisted, asof_ts}"
'

# 验证数据库写入
docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  SELECT event_key, features_snapshot->'heat' as heat_data
  FROM signals
  WHERE features_snapshot->'heat' IS NOT NULL
  LIMIT 1;
"
```

#### 阈值调整演示

```bash
# 调高 THETA_RISE（更难触发 up trend）
docker compose -f infra/docker-compose.yml exec -T api sh -c '
  THETA_RISE=1.0 curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{slope, trend}"
'

# 调低 THETA_RISE（更容易触发 up trend）
docker compose -f infra/docker-compose.yml exec -T api sh -c '
  THETA_RISE=0.1 curl -s "http://localhost:8000/signals/heat?token=USDT" | jq "{slope, trend}"
'
```

### 3. 环境变量完整清单

#### Event 相关

| 变量名             | 默认值 | 作用               | 回滚方式     |
| ------------------ | ------ | ------------------ | ------------ |
| EVENT_KEY_SALT     | (空)   | event_key 生成盐值 | 设为空字符串 |
| EVENT_MERGE_STRICT | true   | 严格模式合并证据   | 设为 false   |

#### Heat 计算相关

| 变量名           | 默认值 | 作用             | 回滚方式     |
| ---------------- | ------ | ---------------- | ------------ |
| THETA_RISE       | 0.2    | 上升趋势阈值     | 恢复为 0.2   |
| HEAT_MIN_SAMPLE  | 3      | 最小样本数       | 恢复为 3     |
| HEAT_NOISE_FLOOR | 1      | 噪声底限         | 恢复为 1     |
| HEAT_EMA_ALPHA   | 0.0    | EMA 平滑系数     | 设为 0 关闭  |
| HEAT_CACHE_TTL   | 30     | 缓存 TTL（秒）   | 设为 0 关闭  |
| HEAT_MAX_ROWS    | 50000  | 最大扫描行数     | 恢复为 50000 |
| HEAT_TIMEOUT_MS  | 1500   | 查询超时（毫秒） | 恢复为 1500  |

#### Heat 持久化相关

| 变量名                    | 默认值 | 作用             | 回滚方式    |
| ------------------------- | ------ | ---------------- | ----------- |
| HEAT_ENABLE_PERSIST       | false  | 是否持久化 heat  | 设为 false  |
| HEAT_PERSIST_UPSERT       | true   | 是否 upsert 模式 | 恢复为 true |
| HEAT_PERSIST_STRICT_MATCH | true   | 严格匹配模式     | 恢复为 true |
| HEAT_PERSIST_TIMEOUT_MS   | 1500   | 持久化超时       | 恢复为 1500 |

### 4. 回滚操作指南

#### 完全关闭 Heat 持久化

```bash
# 修改 infra/.env
echo "HEAT_ENABLE_PERSIST=false" >> infra/.env
docker compose -f infra/docker-compose.yml up -d api
```

#### 关闭事件合并严格模式

```bash
# 修改 infra/.env
echo "EVENT_MERGE_STRICT=false" >> infra/.env
docker compose -f infra/docker-compose.yml up -d api
```

#### 关闭 Heat 缓存

```bash
# 修改 infra/.env
echo "HEAT_CACHE_TTL=0" >> infra/.env
docker compose -f infra/docker-compose.yml up -d api
```

#### 关闭 EMA 平滑

```bash
# 修改 infra/.env
echo "HEAT_EMA_ALPHA=0" >> infra/.env
docker compose -f infra/docker-compose.yml up -d api
```

### 5. 结构化日志字段清单

#### pipeline.event.key

```bash
# 查看 event_key 生成日志
docker compose -f infra/docker-compose.yml logs api | grep '"stage":"pipeline.event.key"' | jq .
```

字段：`event_key`, `salt`, `symbol`, `token_ca`, `topic_hash`

#### pipeline.event.merge

```bash
# 查看事件合并日志
docker compose -f infra/docker-compose.yml logs api | grep '"stage":"pipeline.event.merge"' | jq .
```

字段：`event_key`, `sources`, `strict`, `merged_count`

#### pipeline.event.evidence.merge

```bash
# 查看证据合并日志
docker compose -f infra/docker-compose.yml logs api | grep '"stage":"pipeline.event.evidence.merge"' | jq .
```

字段：`event_key`, `before_count`, `after_count`, `deduped`, `sources`

#### signals.heat.compute

```bash
# 查看热度计算日志
docker compose -f infra/docker-compose.yml logs api | grep '"stage":"signals.heat.compute"' | jq .
```

字段：`token`, `token_ca`, `cnt_10m`, `cnt_30m`, `slope`, `trend`, `degrade`, `rows_scanned`, `from_cache`

#### signals.heat.persist

```bash
# 查看热度持久化日志
docker compose -f infra/docker-compose.yml logs api | grep '"stage":"signals.heat.persist"' | jq .
```

字段：`token`, `token_ca`, `event_key`, `persisted`, `reason`, `strict_match`, `match_key`, `resolved_from`, `asof_ts`

#### signals.heat.resolve

```bash
# 查看 event_key 解析日志
docker compose -f infra/docker-compose.yml logs api | grep '"stage":"signals.heat.resolve"' | jq .
```

字段：`reason`, `token_ca`, `symbol`, `error`

#### signals.heat.error

```bash
# 查看热度计算错误日志
docker compose -f infra/docker-compose.yml logs api | grep '"stage":"signals.heat.error"' | jq .
```

字段：`error`, `token`, `token_ca`

### 6. 完整验收流程

```bash
# 1. 准备测试数据
docker compose -f infra/docker-compose.yml exec -T api python scripts/demo_ingest.py

# 2. 验证事件重放
docker compose -f infra/docker-compose.yml exec -T api sh -c '
  PYTHONPATH=. python -m scripts.verify_events --sample scripts/replay.jsonl
'

# 3. 测试 Heat API（计算）
curl -s "http://localhost:8000/signals/heat?token=USDT" | jq .

# 4. 测试 Heat API（持久化）
docker compose -f infra/docker-compose.yml exec -T api sh -c '
  HEAT_ENABLE_PERSIST=true curl -s "http://localhost:8000/signals/heat?token=USDT" | jq .persisted
'

# 5. 验证日志输出
docker compose -f infra/docker-compose.yml logs api --tail=100 | grep -E '"stage":"(signals\.heat|pipeline\.event)"' | jq -c '{stage:.stage, persisted:.persisted, trend:.trend}'

# 6. 检查数据库状态
docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  SELECT COUNT(*) as total_events,
         COUNT(DISTINCT event_key) as unique_events,
         COUNT(CASE WHEN evidence_count > 1 THEN 1 END) as multi_source
  FROM events;
"
```

### 7. 故障排查

#### Heat 不持久化

```bash
# 检查配置
docker compose -f infra/docker-compose.yml exec api env | grep HEAT_

# 检查 event_key 是否存在
docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  SELECT event_key, symbol, token_ca FROM events WHERE symbol='USDT' LIMIT 1;
"

# 检查 signals 表是否有对应行
docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "
  SELECT event_key FROM signals WHERE event_key IN (SELECT event_key FROM events WHERE symbol='USDT');
"
```

#### 缓存问题

```bash
# 清理 Redis 缓存
docker compose -f infra/docker-compose.yml exec redis redis-cli FLUSHDB

# 验证缓存状态
docker compose -f infra/docker-compose.yml exec redis redis-cli KEYS "heat:*"
```

================================================================

================================================================

## Day17 — HF 批量与阈值校准 (2025-09-11)

- 批量客户端冒烟测试（正常）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc \
  'python scripts/smoke_sentiment.py --batch data/sample.jsonl --backend hf | head -n 5'

- 批量客户端冒烟测试（强制降级）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc \
  "HF_BACKEND=inference HF_TIMEOUT_MS=1 python scripts/smoke_sentiment.py --batch data/sample.jsonl --backend hf --summary-json"

- 规则后端对照输出
  docker compose -f infra/docker-compose.yml exec -T api sh -lc \
  'python scripts/smoke_sentiment.py --batch data/sample.jsonl --backend rules --summary-json'

- 阈值校准（100 样本）
  docker compose -f infra/docker-compose.yml exec -T api sh -lc \
  'python scripts/hf_calibrate.py --file data/golden_sentiment.jsonl --report reports --backend hf | tee /tmp/hf_cal.out'

- 查看校准结果与推荐阈值
  docker compose -f infra/docker-compose.yml exec -T api sh -lc \
  'ls -l reports | tail -n 5 && head -n 20 reports/hf*calibration*\*.env.patch'

- Makefile 快捷目标
  make smoke-sentiment-batch
  make hf-calibrate

================================================================

## Day18 — Rules Engine Integration (2025-09-12)

- **主要要点**
  - 集成规则引擎（`rules_engine`），支持多场景评估、热加载与 refiner（LLM）切换。
  - 路由 `/rules/eval` 支持事件级别规则评估，返回 level/reasons/all_reasons/meta 字段。
  - 支持通过环境变量 `RULES_REFINER` 控制是否启用 refiner。
  - 支持热加载：修改 `rules/rules.yml` 后，自动检测并重新加载，无需重启服务。

### 运行验收命令

```bash
# 1. 集成测试（3 场景 + 热加载 + refiner 开关）
make verify_rules
```

```bash
# 2. 手动调用 API 路由
curl -s "http://localhost:8000/rules/eval?event_key=eth:DEMO1:2025-09-10T10:00:00Z" | jq
# 验证返回字段含 level、reasons、all_reasons、meta.refine_used
```

```bash
# 3. 查看日志（api 容器）
docker compose -f infra/docker-compose.yml logs -f api | egrep "rules.eval|rules.reload|rules.refine"
```

```bash
# 4. 验证 ENV 开关
RULES_REFINER=on make verify_rules
# 确认 meta.refine_used=true
```

```bash
# 5. 热加载测试
# 修改 rules/rules.yml 并等待 RULES_TTL_SEC 秒，调用 API 确认 meta.hot_reloaded=true
# （可通过 touch rules/rules.yml 或编辑后保存触发）
```

---

================================================================

## Day19 — Internal Cards Pipeline (2025-09-12)

### 验收要点

- Schema：内部卡片契约 `schemas/cards.schema.json` 与 pushcard 分层，强约束字段。
- Summarizer：受限摘要器，仅生成 `summary` 与 `risk_note`，支持 LLM/模板降级。
- Builder：合流 goplus/dex/onchain/rules/evidence，调用 summarizer 并返回符合 Schema 的卡片。
- Preview 路由：`GET /cards/preview` 输出校验合规。
- Verify 脚本：一键执行，支持降级与模板兜底。

### 运行验收

- 校验 Schema

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api \
    python scripts/validate_cards.py | jq ".pass"

  ```

- 测试 Summarizer

  docker compose -f infra/docker-compose.yml exec -T api \
   python test_summarizer.py

- 构建单卡（最小例）

  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.cards.build import build_card
  import json
  card = build_card("TEST_BAD", render=True)
  print(json.dumps(card, indent=2, ensure_ascii=False))
  PY

- 预览路由

  curl -s "http://localhost:8000/cards/preview?event_key=TEST_BAD&render=1" | jq

- 一键校验

  EVENT_KEY=TEST_BAD make verify_cards

- 验证降级（强制 template）

CARDS_SUMMARY_TIMEOUT_MS=1 EVENT_KEY=TEST_BAD make verify_cards

- 备注
  • event*key 必须大写匹配模式 ^[A-Z0-9:*\-\.]{8,128}$。
  • 降级模式下 meta.summary_backend="template"，summary/risk_note 仍保证非空。
  • Rollback：删除 schemas/cards.schema.json、api/cards/\*、api/routes/cards.py 以及 scripts/verify_cards_preview.py 的新增内容。

================================================================

## Pre Day20+21 — Telegram Notifier & Outbox 基础设施 (2025-09-13)

### 已完成覆盖

- `/cards/send` 路由：支持 count 批量、dry_run、Redis 去重（1h 窗口），失败项入 push_outbox。
- Outbox 重试作业：429 按 retry_after，5xx/网络错误指数退避+抖动，4xx→DLQ；Celery Beat 每 20 秒调度。
- 最小速率限制：Redis 秒级窗口 (global + per-channel)，实测限流有效。
- Metrics 绑定：`telegram_send_latency_ms`、`telegram_error_code_count{code}`、`outbox_backlog`、`pipeline_latency_ms`。

### 待完成差距

- 同步降级：失败时写 `/tmp/cards/*.json`，响应体增加 `degrade=true`。
- 幂等键增强：加入 `template_v`，避免重试/模板切换重复。
- 新增指标：`external_error_rate`、`degrade_ratio`。
- Bench-pipeline 脚本：50 事件批量，统计 P50/P95/失败率/降级率。
- RUN_NOTES 文档：补充指标查看与常见问题说明。

### 验收命令

- **同步降级测试**

  ```bash
  # 设置错误 token 模拟失败
  docker compose -f infra/docker-compose.yml exec -T -e TG_BOT_TOKEN=bad api \
    curl -s -XPOST "http://localhost:8000/cards/send?event_key=ERR1&count=2" | jq .
  # 预期：HTTP 200，响应包含 degrade=true；/tmp/cards/ 下生成 JSON；DB push_outbox 有 pending。
  ```

- **幂等键测试**

  ```bash
  # 相同 event_key/channel/template_v 请求
  curl -s -XPOST "http://localhost:8000/cards/send?event_key=IDEMP1&count=1" | jq .
  curl -s -XPOST "http://localhost:8000/cards/send?event_key=IDEMP1&count=1" | jq .
  # 预期：第二次 dedup=true, sent=0
  ```

- **指标导出**

  ```bash
  curl -s http://localhost:8000/metrics | egrep "telegram|outbox|degrade"
  ```

- **Outbox 验证**

  ```bash
  # 手动触发重试作业
  docker compose -f infra/docker-compose.yml exec -T worker python -m worker.jobs.outbox_retry
  # 查看 DB 状态
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c \
    "SELECT id,event_key,status,attempt,last_error FROM push_outbox ORDER BY id DESC LIMIT 5;"
  ```

- **bench-pipeline 脚本（待实现）**

  ```bash
  make bench-pipeline
  # 预期输出：P50/P95、失败率、降级率
  ```

- **日志与错误速查**
  ```bash
  # 观察发送日志
  docker compose -f infra/docker-compose.yml logs api | egrep "telegram.send|telegram.sent|telegram.error"
  # 常见错误：
  # - 400 BAD_REQUEST → DLQ
  # - 429 Too Many Requests → retry_after 重试
  # - 5xx/网络 → 指数退避
  ```

================================================================

## P0-3 — Card Routing Table-Driven Implementation (2025-09-25)

### 验收要点

- 卡片路由表驱动化，支持 4 种类型：primary, secondary, topic, market_risk
- 使用 CARD_ROUTES 和 CARD_TEMPLATES 字典避免 if/elif 链
- 统一 generate 函数签名：generate_{type}_card(event, signals)
- 集中式 Prometheus 指标注册在 api/core/metrics.py

### 运行验收

- 验证路由表配置

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.cards.registry import CARD_ROUTES, CARD_TEMPLATES
  print("Registered routes:", list(CARD_ROUTES.keys()))
  print("Registered templates:", list(CARD_TEMPLATES.keys()))
  PY
  # Expected: ['primary', 'secondary', 'topic', 'market_risk'] for both
  ```

- 测试卡片生成（各类型）

  ```bash
  # Primary card
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.cards.generator import generate_card
  event = {"type": "primary", "event_key": "TEST:PRIMARY:001", "risk_level": "yellow"}
  signals = {"goplus_risk": "yellow", "dex_liquidity": 100000}
  card = generate_card(event, signals)
  print(f"Generated {card['card_type']} card for {card['event_key']}")
  PY
  ```

  ```bash
  # Market risk card
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.cards.generator import generate_card
  event = {"type": "market_risk", "event_key": "TEST:MR:001", "risk_level": "red"}
  signals = {"goplus_risk": "red", "dex_volume_1h": 600000, "hit_rules": ["MR01", "MR03"]}
  card = generate_card(event, signals)
  print(f"Generated {card['card_type']} card with rules: {signals.get('hit_rules')}")
  PY
  ```

- 验证模板渲染

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.cards.renderer import render_card
  card = {
      "card_type": "market_risk",
      "event_key": "TEST:MR:001",
      "summary": "High volume alert",
      "risk_note": "Volume exceeded 500K"
  }
  tg_msg = render_card(card, "tg")
  print("TG rendering OK:", bool(tg_msg))
  ui_html = render_card(card, "ui")
  print("UI rendering OK:", bool(ui_html))
  PY
  ```

================================================================

## P1-1 — Market Risk Detection via Rules Engine (2025-09-25)

### 验收要点

- 新增 MR01-MR06 市场风险规则在 rules/rules.yml
- 规则引擎支持 tags 机制，MR 规则命中添加 "market_risk" 标签
- goplus_scan 根据规则评估设置 signal type="market_risk"
- Redis 冷却机制防止重复告警（默认 600 秒）
- 环境变量支持动态阈值调整

### 运行验收

- 验证规则加载

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.rules.eval_event import RuleEvaluator
  evaluator = RuleEvaluator()
  print(f"Loaded {len(evaluator.rules)} rule groups")
  # Check MR rules exist
  mr_rules = [r for group in evaluator.rules for r in group["rules"] if r["id"].startswith("MR")]
  print(f"Found {len(mr_rules)} market risk rules")
  PY
  # Expected: 6 MR rules
  ```

- 测试规则评估（触发 MR01）

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  import os
  from api.rules.eval_event import RuleEvaluator

  os.environ["MARKET_RISK_VOLUME_THRESHOLD"] = "500000"
  evaluator = RuleEvaluator()

  signals_data = {
      "goplus_risk": "green",
      "buy_tax": 2.0,
      "sell_tax": 2.0,
      "lp_lock_days": 180,
      "honeypot": False,
      "dex_liquidity": 100000.0,
      "dex_volume_1h": 600000.0,  # > 500000 triggers MR01
      "heat_slope": 1.0
  }
  events_data = {"last_sentiment_score": 0.7}

  result = evaluator.evaluate(signals_data, events_data)
  print(f"Tags: {result['tags']}")
  print(f"Hit rules: {result['hit_rules']}")
  print(f"Level: {result['level']} (should not be 'market_risk')")
  PY
  # Expected: Tags includes "market_risk", Hit rules includes "MR01"
  ```

- 测试冷却机制

  ```bash
  # First call sets cooldown
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.cache import get_redis_client
  import os

  redis = get_redis_client()
  event_key = "TEST:TOKEN:123"
  cooldown_key = f"mr:cooldown:{event_key}"

  # Simulate first detection
  if not redis.exists(cooldown_key):
      redis.setex(cooldown_key, 600, "1")
      print("Type would be set to market_risk")
  else:
      ttl = redis.ttl(cooldown_key)
      print(f"In cooldown, {ttl} seconds remaining")
  PY

  # Second call shows cooldown
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.cache import get_redis_client

  redis = get_redis_client()
  cooldown_key = f"mr:cooldown:TEST:TOKEN:123"

  if redis.exists(cooldown_key):
      ttl = redis.ttl(cooldown_key)
      print(f"Still in cooldown: {ttl} seconds remaining")
  PY
  ```

- 验证状态版本包含规则哈希

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.cards.dedup import make_state_version_with_rules

  event = {"event_key": "TEST:123", "state": "candidate", "risk_level": "yellow"}
  hit_rules = ["MR01", "MR03"]

  version = make_state_version_with_rules(event, hit_rules)
  print(f"State version with rules: {version}")
  # Should include _mr hash suffix

  # Test ordering stability
  version2 = make_state_version_with_rules(event, ["MR03", "MR01"])  # Different order
  print(f"Same rules, different order: {version == version2}")
  # Should be True
  PY
  ```

- 环境变量测试

  ```bash
  # Test custom thresholds
  docker compose -f infra/docker-compose.yml exec -T api sh -c '
    MARKET_RISK_VOLUME_THRESHOLD=100000 \
    MARKET_RISK_LIQ_MIN=5000 \
    python - <<PY
  from api.rules.eval_event import RuleEvaluator
  import os
  print(f"Volume threshold: {os.getenv('MARKET_RISK_VOLUME_THRESHOLD')}")
  print(f"Liquidity min: {os.getenv('MARKET_RISK_LIQ_MIN')}")
  PY'
  ```

- 验证指标注册

  ```bash
  docker compose -f infra/docker-compose.yml exec -T api python - <<'PY'
  from api.core.metrics import rules_market_risk_hits_total, signals_type_set_total
  print(f"Metric 1: {rules_market_risk_hits_total._name}")
  print(f"Metric 2: {signals_type_set_total._name}")
  PY
  # Should print metric names without error
  ```

### 环境变量配置

| 变量名                        | 默认值 | 说明                    |
| ----------------------------- | ------ | ----------------------- |
| MARKET_RISK_VOLUME_THRESHOLD | 500000 | 成交量异常阈值（USD）   |
| MARKET_RISK_LIQ_MIN          | 10000  | 最低流动性要求（USD）   |
| MARKET_RISK_LIQ_RISK         | 50000  | 流动性风险阈值（USD）   |
| MARKET_RISK_COOLDOWN_SEC     | 600    | 冷却时间（秒）          |

================================================================

### Cards 发送与降级运维指南（Day20+Day21）

#### 指标查看

- 导出全文指标
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
  from api.core.metrics import export_text
  print(export_text())
  PY'

- 精确查看降级批次数
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
  from api.core.metrics import export_text
  for line in export_text().splitlines():
  if "cards_degrade_count" in line:
  print(line)
  PY'

- 关注指标：

- `telegram_send_latency_ms`：发送延迟
- `telegram_error_code_count{code}`：错误码计数
- `outbox_backlog`：积压情况
- `pipeline_latency_ms`：链路总延迟
- `cards_degrade_count`：降级批次数

#### 日志定位

# 查看最近日志

- docker compose -f infra/docker-compose.yml logs --tail=100 api
- docker compose -f infra/docker-compose.yml logs --tail=100 worker

常见日志关键词：

- `telegram.send` / `telegram.sent`
- `telegram.timeout`
- `telegram.error`
- `outbox.process_batch`

#### 429 自救

出现 429 错误时：

- 检查 `TG_RATE_LIMIT` 配置
- 暂时降低并发或切换 `TG_SANDBOX`
- 重启 worker 重试

  docker compose -f infra/docker-compose.yml restart worker

#### 降级快照核查

- 查看最近快照文件
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'ls -lt /tmp/cards | head -n 5'

- 查看最新快照内容
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
  import os, json, glob
  files = sorted(glob.glob("/tmp/cards/\*.json"), key=os.path.getmtime, reverse=True)[:1]
  print(json.dumps(json.load(open(files[0], encoding="utf-8")), indent=2, ensure_ascii=False))
  PY'

- 快速验证命令

- 模拟失败触发降级（坏 token 或断网）
  curl -sS -XPOST "http://localhost:8000/cards/send?event*key=E_TEST*$(date +%s)&count=1&dry_run=0" | jq

- 验证计数器自增
  docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
  from api.core.metrics import export_text
  for line in export_text().splitlines():
  if "cards_degrade_count" in line:
  print(line)
  PY'

### Card A — 失败快照与批次降级标志（Day20）

#### 验收命令

```bash
# 模拟错误触发快照与降级标志
curl -sS -XPOST "http://localhost:8000/cards/send?event_key=E_ERR_$(date +%s)&count=1&dry_run=0" | jq

# 查看最近快照文件
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'ls -lt /tmp/cards | head -n 3'

# 查看最新快照内容
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
import os, json, glob
files = sorted(glob.glob("/tmp/cards/*.json"), key=os.path.getmtime, reverse=True)[:1]
print(json.dumps(json.load(open(files[0], encoding="utf-8")), indent=2, ensure_ascii=False))
PY'
```

---

### Card B — 降级批次数指标（Day20）

#### 验收命令

```bash
# 导出全文指标，确认出现 cards_degrade_count
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
from api.core.metrics import export_text
print(export_text())
PY' | grep "cards_degrade_count" || true
```

---

### Card D — 幂等键增强（Day20）

#### 验收命令

```bash
# 同一 event_key + channel_id + template_v=v1，首次发送
curl -sS -XPOST "http://localhost:8000/cards/send?event_key=E_IDEMP&count=1&template_v=v1&dry_run=0" | jq

# 再次发送相同参数，预期 dedup=true
curl -sS -XPOST "http://localhost:8000/cards/send?event_key=E_IDEMP&count=1&template_v=v1&dry_run=0" | jq

# 更换 template_v，仍可发送
curl -sS -XPOST "http://localhost:8000/cards/send?event_key=E_IDEMP&count=1&template_v=v2&dry_run=0" | jq

# 在 Redis 查看幂等键
docker compose -f infra/docker-compose.yml exec -T redis redis-cli --scan --pattern 'cards:idemp:*' | head
```

---

### Card E — 外呼错误占位指标（三段式）（Day20）

#### 验收命令

```bash
# 模拟触发 429 错误
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
from api.routes import cards_send
cards_send.EXTERNAL_ERR_429.inc()
from api.core.metrics import export_text
print([l for l in export_text().splitlines() if "external_error_total_429" in l])
PY'

# 模拟触发 5xx 错误
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
from api.routes import cards_send
cards_send.EXTERNAL_ERR_5XX.inc()
from api.core.metrics import export_text
print([l for l in export_text().splitlines() if "external_error_total_5xx" in l])
PY'

# 模拟触发网络错误
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python - <<PY
from api.routes import cards_send
cards_send.EXTERNAL_ERR_NET.inc()
from api.core.metrics import export_text
print([l for l in export_text().splitlines() if "external_error_total_net" in l])
PY'
```

## Day22 — 回放与部署（最小闭环）

### 验证命令

- 环境与预检：
  make preflight
  make up
  make verify:api
  make verify:telegram

- 路由发现：
  make routes
  cat logs/day22/openapi.json | jq '.paths | keys[]' | grep -E 'x/|dex/|topic'

- 回放与评分：
  bash scripts/replay_e2e.sh demo/golden/golden.jsonl
  python3 scripts/score_replay.py

- 首卡计时：
  bash scripts/measure_boot.sh

- 打包归档：
  bash scripts/build_repro_bundle.sh

---

## Day23+24 — Configuration Governance & Observability (2025-09-15)

### Card A — Configuration Hot Reload

验收命令:

```bash
# 修改配置文件
echo "test_value: 123" >> rules/risk_rules.yml

# 等待热重载（或发送 SIGHUP）
sleep 70  # 或 docker compose -f infra/docker-compose.yml exec -T api sh -c 'kill -HUP 1'

# 查看重载日志
docker compose -f infra/docker-compose.yml logs --tail=50 api | grep "config.reload"

# 禁用热重载（紧急开关）
export CONFIG_HOTRELOAD_ENABLED=false
docker compose -f infra/docker-compose.yml restart api
```

### Card B — Configuration Lint

验收命令:

```bash
# 运行配置 lint
python scripts/config_lint.py

# 在容器内运行
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python scripts/config_lint.py'

# 预期输出: config_lint: OK
```

### Card C — Sensitive Items Guide (敏感项获取指南)

#### 敏感配置项获取方式和最小权限建议

1. **Telegram Bot Token**

   - 获取来源: Telegram @BotFather
   - 步骤:
     1. 在 Telegram 中搜索 @BotFather
     2. 发送 /newbot 创建新机器人
     3. 按提示设置名称和用户名
     4. 获得格式如 `123456789:ABC-DEF...` 的 token
   - 最小权限: 仅需要发送消息到群组/频道的权限
   - 安全建议: 定期轮换，限制机器人只加入指定群组

2. **X (Twitter) Bearer Token**

   - 获取来源: https://developer.twitter.com/en/portal/dashboard
   - 步骤:
     1. 注册开发者账号
     2. 创建 App
     3. 生成 Bearer Token
   - 最小权限: Read-only access to tweets and user profiles
   - 安全建议: 使用只读 token，监控 API 使用量

3. **GoPlus API Key**

   - 获取来源: https://gopluslabs.io/
   - 步骤:
     1. 注册账号
     2. 进入 Dashboard
     3. 创建 API Key
   - 最小权限: Token detection API access only
   - 安全建议: 设置 IP 白名单，监控配额使用

4. **OpenAI API Key**

   - 获取来源: https://platform.openai.com/api-keys
   - 步骤:
     1. 注册 OpenAI 账号
     2. 访问 API keys 页面
     3. 创建新的 API key
   - 最小权限: 仅模型访问权限，设置使用限额
   - 安全建议: 设置月度预算上限，使用项目专用 key

5. **GCP Service Account (BigQuery)**

   - 获取来源: GCP Console > IAM & Admin > Service Accounts
   - 步骤:
     1. 创建服务账号
     2. 授予 BigQuery Data Viewer 角色
     3. 创建并下载 JSON key
   - 最小权限: BigQuery Data Viewer (只读)
   - 安全建议: 限制到特定数据集，定期轮换密钥

6. **PostgreSQL Credentials**
   - 获取来源: 数据库管理员或云服务商控制台
   - 最小权限:
     - SELECT, INSERT, UPDATE, DELETE on application tables
     - No CREATE/DROP database permissions
   - 安全建议: 使用强密码，限制连接 IP，使用 SSL

#### 原子写约定（配置更新流程）

为避免配置文件半写入状态，遵循以下原子写流程：

1. 写入临时文件: `config.yml.tmp`
2. 运行 lint 验证: `python scripts/config_lint.py`
3. 如验证通过，原子替换: `mv config.yml.tmp config.yml`

示例:

```bash
# 更新配置
cp rules/risk_rules.yml rules/risk_rules.yml.tmp
echo "new_threshold: 15" >> rules/risk_rules.yml.tmp

# 验证
python scripts/config_lint.py

# 应用（仅在验证通过后）
mv rules/risk_rules.yml.tmp rules/risk_rules.yml
```

#### 安全检查清单

提交代码前必须检查:

- [ ] 所有 `__REPLACE_ME__` 占位符未被真实值替换
- [ ] .env 文件未被提交到版本控制
- [ ] .env.example 中无真实 API keys/tokens
- [ ] 运行 `scripts/config_lint.py` 无错误
- [ ] git diff 中无敏感信息

环境变量安全:

```bash
# 检查是否有敏感信息
grep -E "sk-[a-zA-Z0-9]{20,}|pk_[a-zA-Z0-9]{20,}" .env.example

# 确认占位符
grep "__REPLACE_ME__" .env.example | wc -l  # 应该 > 0

# 验证 .gitignore 包含 .env
grep "^\.env$" .gitignore
```

### Card E - 告警系统验收

#### 模拟 Telegram 错误触发告警

```bash
# 1. 启动服务并设置错误的 Telegram token
export TELEGRAM_BOT_TOKEN="__BROKEN__"
export METRICS_EXPOSED=true
docker compose -f infra/docker-compose.yml up -d api

# 2. 生成错误流量
for i in {1..10}; do
  curl -X POST http://localhost:8000/telegram/send \
    -H "Content-Type: application/json" \
    -d '{"chat_id": "test", "text": "test message"}'
done

# 3. 运行告警检测
python scripts/alerts_runner.py --once \
  --metrics 'http://localhost:8000/metrics' \
  --min-breach-seconds 30 \
  --silence-seconds 120 \
  --notify-script scripts/notify_local.sh \
  --state-file /tmp/alerts_test.json

# 期望输出: alert.fired: name=telegram_error_rate_high
```

#### 模拟 Cards 退化触发告警

```bash
# 1. 触发 cards 退化（通过发送大量事件）
for i in {1..20}; do
  curl -X POST http://localhost:8000/x/ingest \
    -H "Content-Type: application/json" \
    -d '{"text": "test degrade event"}'
done

# 2. 运行告警检测
python scripts/alerts_runner.py --once \
  --metrics 'http://localhost:8000/metrics' \
  --notify-script scripts/notify_local.sh \
  --state-file /tmp/alerts_test.json

# 期望输出: alert.fired: name=cards_degrade_spike
```

#### 持续监控模式

```bash
# 启动持续监控（每30秒检查一次）
python scripts/alerts_runner.py \
  --interval 30 \
  --metrics 'http://localhost:8000/metrics' \
  --min-breach-seconds 60 \
  --silence-seconds 300 \
  --notify-script scripts/notify_local.sh \
  --state-file .alerts_state.json

# 查看告警日志
tail -f /tmp/alerts_notifications.log
```

#### 验证告警功能

```bash
# 1. 检查告警配置
cat alerts.yml | grep -E "name:|threshold:"

# 2. 测试本地通知脚本
ALERT_MESSAGE="Test alert" ALERT_RULE="test_rule" ALERT_SEVERITY="warn" \
  bash scripts/notify_local.sh

# 3. 查看告警状态
cat .alerts_state.json | jq '.breaches, .silenced'

# 4. 验证日志格式
python scripts/alerts_runner.py --help 2>&1 | head -5
```

================================================================

## Day23+24 — 配置与治理 + 观测告警（追加验收手册，Card F 用） (2025-09-15)

> 本段为 **新增补充**，不修改历史内容。目标：将 Day23+24 的 A–E 卡片以“可直接运行”的命令固化，包含原子写、热加载、lint、/metrics、告警、自救回滚与常见故障排查。所有命令均以 compose 环境为准。

### 统一开发约束（强制执行清单）

- 最小 diff，禁止大范围重构；依赖仅限标准库 + `pyyaml`
- Prom 命名规范：计数 `_total`；时间单位 `_ms`；直方图三件套 `_bucket/_sum/_count`
- 日志关键字：`config.reload`、`config.applied`、`config.reload.error`、`alert.fired`
- 任何 ENV 变更必须同步 `.env.example` 注释，并确保 `scripts/config_lint.py` 通过
- 生产改配置必须走“原子写流程”，禁止直接覆写造成半写入

---

### 原子写流程（配置变更，Card B 依赖）

```bash
# 以 risk_rules.yml 为例
cp rules/risk_rules.yml rules/risk_rules.yml.tmp
# 编辑 *.tmp 后执行 Lint
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python scripts/config_lint.py'
# 仅在 Lint 通过时原子替换
mv rules/risk_rules.yml.tmp rules/risk_rules.yml
```

---

### 热加载最短验证（Card A）

```bash
# 修改配置（示例：阈值）
sed -i '' 's/threshold: 10/threshold: 11/' rules/risk_rules.yml
# 等待 TTL 或 SIGHUP 立即刷新
sleep 70 || true
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'kill -HUP 1' || true

# 观察关键日志
docker compose -f infra/docker-compose.yml logs --tail=200 api \
  | egrep 'config\.reload|config\.applied|config\.reload\.error'

# 版本与计数指标
curl -s http://localhost:8000/metrics \
  | egrep 'config_version|config_reload_total'
```

---

### 配置 Lint（Card B）

```bash
# 容器内执行 Lint
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python scripts/config_lint.py'
# 预期：退出码 0 且含 "config_lint: OK"
```

---

### .env.example 规范检查（Card C）

```bash
# 占位与注释检查
grep "__REPLACE_ME__" .env.example | wc -l
grep -E "用途|必填|默认|来源|权限" -n .env.example | head
# METRICS_EXPOSED 默认必须为 false
grep -q '^METRICS_EXPOSED=false' .env.example && echo "ok: metrics off by default"
```

---

### /metrics 验收（Card D）

```bash
# 1) 开阀门（容器内有效）
export METRICS_EXPOSED=true
curl -is http://localhost:8000/metrics | grep -i 'content-type'

# 2) Prom 格式头两行
curl -s http://localhost:8000/metrics | head -n 10 | grep -E '^# (HELP|TYPE) '

# 3) 直方图三件套必须存在（>0 行）
curl -s http://localhost:8000/metrics | grep -E '^pipeline_latency_ms_(bucket|sum|count)' | wc -l

# 4) 关阀门（通过 compose/env 生效）
export METRICS_EXPOSED=false
docker compose -f infra/docker-compose.yml up -d api
curl -is http://localhost:8000/metrics | head -n 2  # 预期：404
```

---

### 告警系统验收（Card E）

```bash
# 0) 确保 /metrics 可访问
export METRICS_EXPOSED=true

# 1) 制造 TG 错误流（不要用生产值）
export TELEGRAM_BOT_TOKEN=__BROKEN__
python scripts/alerts_runner.py --once --metrics 'http://localhost:8000/metrics' \
  --min-breach-seconds 30 --silence-seconds 120 \
  --notify-script scripts/notify_local.sh --state-file .alerts_state.json
# 预期：输出包含 "alert.fired" 且 name=telegram_error_rate_high

# 2) 静默窗口验证（静默期内再次运行）
python scripts/alerts_runner.py --once --metrics 'http://localhost:8000/metrics' \
  --min-breach-seconds 30 --silence-seconds 120 \
  --notify-script scripts/notify_local.sh --state-file .alerts_state.json
# 预期：输出 "alert.silenced"

# 3) 退化告警（人为提升 cards_degrade_count）
python scripts/alerts_runner.py --once --metrics 'http://localhost:8000/metrics' \
  --notify-script scripts/notify_local.sh --state-file .alerts_state.json
# 命中阈值则触发 name=cards_degrade_spike
```

---

### 常见故障排查（按优先级）

1. **路由冲突**：若 `/metrics` 返回 JSON 404，检查是否被 `/{event_key}` 吞掉。采用正则收窄或在该路由内转发 `/metrics`。
2. **多处 metrics 实现**：仓内如有 `api/metrics.py`、`api/core/metrics.py`、`api/routes/metrics.py`，确保路由端调用的 builder 唯一且包含直方图三件套。
3. **ENV 未生效**：宿主机 `export` 不等于容器内 ENV。修改 `infra/.env` 或用 compose 注入并重启。避免在代码中模块级缓存 ENV。
4. **Content-Type 错误**：返回应为 `text/plain; version=0.0.4; charset=utf-8`，否则 Prom 拒收。
5. **Lint 未覆盖**：任何新增 ENV 需同步 `.env.example` 注释，并保证 `scripts/config_lint.py` 通过。

---

### 回滚速查

- **配置回滚**：恢复 `.yml.bak` 或上一个 commit；`docker compose -f infra/docker-compose.yml up -d api`
- **热加载关闭**：`CONFIG_HOTRELOAD_ENABLED=false` 并重启 api
- **/metrics 关闭**：`METRICS_EXPOSED=false` 并重启 api（对外暴露由反代/ACL 控制）
- **告警停用**：注释 `alerts.yml` 所有规则或停止 `alerts_runner`
- **脚本自测失败**：仅回滚 `scripts/` 目录变更，不影响 API 运行

> 完成以上小节后，更新 `STATUS.md` 的 Today 段为 Day23+24 SSOT，并引用本段为运行手册来源（Card G 单独提交）。

### 护栏（card G）

### 新增 Makefile 目标

- `make config-lint`  
  执行 `scripts/config_lint.py`，检查 YAML 与环境变量，敏感项为 0 时返回 OK。

  - 预期：出现 `config_lint: OK`，可有 Warning（如空格）。
  - 回滚：删除 Makefile 对应 target。

- `make metrics-check`  
  快速检查 `/metrics`，显示 HELP/TYPE 与直方图三件套。

  - 预期：HTTP/1.1 200 OK，出现 `pipeline_latency_ms` 等指标。
  - 回滚：删除 Makefile 对应 target。

- `make alerts-once`  
  单次运行 `scripts/alerts_runner.py`，基于 `/metrics` 触发告警检查。

  - 预期：阈值命中时日志含 `alert.fired`，静默期内不重复。
  - 回滚：删除 Makefile 对应 target。

- `make reload-hup`  
  向容器 PID 1 发送 `SIGHUP`，触发配置热加载。

  - 使用前请先在 `docker top <api-container>` 查 PID 并写入命令。
  - 回滚：删除 Makefile 对应 target。

- `make verify-day23-24`  
  串测所有上述目标。
  - 回滚：删除 Makefile 对应 target。

### 其他文件

- `.github/PULL_REQUEST_TEMPLATE.md`
  - 必须贴上 `make config-lint` 输出片段
  - 必须说明是否需要 `METRICS_EXPOSED=true`（默认不公开）
  - 回滚：删除该文件。
