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

- 运行 demo pipeline
  make demo
- 验证 raw_posts 表有数据
  docker compose -f infra/docker-compose.yml exec -T db psql -U app -d app -c "SELECT COUNT(\*) FROM raw_posts;"

---

## Day3 — Demo ingest script & logging

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

================================================================
