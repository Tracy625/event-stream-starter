#!/usr/bin/env bash
set -euo pipefail
COMPOSE="docker compose -f infra/docker-compose.yml"

step() { echo -e "\n== $* =="; }
http() { curl -sS -m "${3:-8}" -o /dev/null -w '%{http_code}\n' "$1"; }

step "0) compose ps"
$COMPOSE ps || true

step "1) healthz + readyz"
curl -sS http://localhost:8000/healthz | jq . || true
# 等待 readyz 200（最多 90s）
for i in {1..30}; do
  code=$(http http://localhost:8000/readyz 2>/dev/null || echo 000)
  echo "try $i: /readyz -> $code"
  [ "$code" = "200" ] && break
  sleep 3
done
[ "$code" = "200" ] || { echo "readyz failed"; $COMPOSE logs api --tail=200 | sed -n '1,200p'; exit 1; }
curl -sI http://localhost:8000/readyz | grep -i 'Cache-Control' || true

step "2) metrics 探活"
curl -sS http://localhost:8000/metrics | egrep \
'container_restart_total|celery_queue_backlog|readyz_latency_ms|onchain_lock_|onchain_process_ms' || true

step "3) Apify 直连 run-sync（验证 token/actor）"
API_TOKEN="${APIFY_API_TOKEN:-${APIFY_TOKEN:-}}"
if [ -n "${API_TOKEN:-}" ]; then
  curl -sS -X POST \
    "https://api.apify.com/v2/acts/apidojo~tweet-scraper/run-sync-get-dataset-items?token=$API_TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"twitterHandles":["elonmusk"],"tweetsDesired":3,"sort":"Latest"}' \
    | jq '.[0] | {id, full_text: .full_text, user: .user.screen_name}' || true
else
  echo "APIFY token missing in env; skip"
fi

step "4) 系统内触发 KOL 轮询（API，如果有）"
if curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8000/ingest/x/kol/poll | grep -q 200; then
  curl -sS http://localhost:8000/ingest/x/kol/poll | jq .
else
  echo "poll API unavailable; 跟日志走"
fi

step "4B) 观察 worker 日志（apify）"
$COMPOSE logs worker --tail=120 | egrep "x\.fetch\.(request|success|error)|apify" || true

step "5) DB 落库校验（10 分钟内）"
$COMPOSE exec -T db psql -U app -d app -c \
"SELECT COUNT(*) AS recent_events FROM events WHERE last_ts > NOW() - INTERVAL '10 minutes';" || true
$COMPOSE exec -T db psql -U app -d app -c \
"SELECT event_key, evidence_count, symbol, to_char(last_ts,'YYYY-MM-DD HH24:MI:SS') AS last_ts
 FROM events ORDER BY last_ts DESC LIMIT 5;" || true

step "6) 去重/冲突指标"
curl -sS http://localhost:8000/metrics | egrep \
'evidence_dedup_total|evidence_merge_ops_total|events_key_conflict_total' || true

step "7) Telegram 真发烟测"
$COMPOSE exec -T api python - <<'PY' || true
from api.services.telegram import TelegramNotifier
n = TelegramNotifier()
try:
    print("test_connection:", n.test_connection())
    # 如果配置了 sandbox，会自动重定向到 sandbox_channel_id
    r = n.send_message(chat_id=os.getenv("TG_CHANNEL_ID",""), text="GUIDS smoke test ✅")
    print("send result:", r)
except Exception as e:
    print("telegram error:", e)
PY

step "8) GoPlus 后端"
curl -sS "http://localhost:8000/security/token?chain_id=1&address=0x6982508145454ce325ddbe47a25d4ec3d2311933" | jq . || true
curl -sS http://localhost:8000/metrics | egrep 'goplus|security|degrade' || true

step "9) BigQuery onchain 健康"
curl -sS http://localhost:8000/onchain/healthz | jq . || true
echo "SA path: $GOOGLE_APPLICATION_CREDENTIALS"
$COMPOSE exec -T api sh -lc 'test -r "$GOOGLE_APPLICATION_CREDENTIALS" && echo "SA OK" || echo "SA MISSING"' || true

step "10) 并发控制指标（观察是否增长）"
curl -sS http://localhost:8000/metrics | egrep \
'onchain_lock_(acquire|release|wait|hold)|onchain_state_cas_conflict_total' || true

step "11) Topic/MR 卡片（日志检视）"
$COMPOSE logs worker --tail=200 | egrep 'cards\.generate|topic\.aggregate|market_risk' || true

step "12) 队列 backlog（可选）"
$COMPOSE exec -T redis redis-cli LLEN celery || true

echo -e "\n✅ Smoke script completed."