.PHONY: help up down rebuild logs verify ps restart replay nuke wait
.PHONY: api worker migrate revision test demo seed clean dbtest bench-sentiment smoke-sentiment
.PHONY: smoke-sentiment-batch hf-calibrate verify-refiner demo-refine onchain-verify-once expert-dryrun verify_cards

COMPOSE := docker compose -f infra/docker-compose.yml
API_HEALTH_URL ?= http://localhost:8000/healthz
HEALTH_TIMEOUT ?= 120

help: ## Show available targets
	@awk 'BEGIN{FS=":.*##"; printf "Available targets:\n"} /^[a-zA-Z0-9_-]+:.*?##/{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: ## Preflight + up (wait for healthy)
	bash scripts/preflight.sh
	$(COMPOSE) up -d --build
	$(MAKE) wait

wait: ## Wait until API healthy or timeout
	@echo "Waiting for API healthy at $(API_HEALTH_URL) ..."
	@python3 scripts/wait_healthy.py

down: ## Stop services (keep volumes)
	$(COMPOSE) down

nuke: ## DANGER: down and remove volumes
	$(COMPOSE) down -v

rebuild: ## Rebuild without cache, then up
	$(COMPOSE) build --no-cache
	$(MAKE) up

logs: ## Tail compose logs
	$(COMPOSE) logs --tail=200 -f

ps: ## Show compose services
	$(COMPOSE) ps

restart: ## Restart api service
	$(COMPOSE) restart api

verify: ## Verify api + telegram
	$(MAKE) verify:api && $(MAKE) verify:telegram

verify\:api: ## /healthz returns ok
	@python3 scripts/verify_api.py $(API_HEALTH_URL)

verify\:telegram: ## Verify telegram smoke (honors TELEGRAM_PUSH_ENABLED)
	@set -a; \
	test -f .env && . ./.env || true; \
	test -f .env.local && . ./.env.local || true; \
	set +a; \
	python3 scripts/verify_telegram.py

replay: ## Run golden replay (exists check)
	@test -f demo/golden/golden.jsonl || (echo "golden.jsonl missing"; exit 2)
	bash scripts/replay_e2e.sh demo/golden/golden.jsonl

api: ## Start API server (placeholder)
	@echo "Starting API server..."
	# uvicorn api.main:app --reload

worker: ## Start Celery worker (placeholder)
	@echo "Starting Celery worker..."
	# celery -A worker.app worker --loglevel=info

# ----- Alembic -----
migrate: ## Apply alembic migrations
	@echo "Running alembic upgrade head inside api container..."
	$(COMPOSE) exec -T api sh -c 'cd /app/api && alembic upgrade head'

revision: ## Create alembic revision (use m="message")
	@if [ -z "$(m)" ]; then echo 'Usage: make revision m="your message"'; exit 1; fi
	@echo "Creating alembic revision: $(m)"
	$(COMPOSE) exec -T api sh -c 'cd /app/api && alembic revision -m "$(m)"'

test: ## Run tests (placeholder)
	@echo "Running tests..."
	# pytest tests/
	# npm test

# ----- Demo -----
demo: ## Run demo ingestion pipeline
	@echo "Running demo ingestion pipeline inside api container..."
	$(COMPOSE) exec -T api python scripts/demo_ingest.py

seed: ## Seed database (placeholder)
	@echo "Seeding database..."
	# python scripts/seed_db.py

# ----- Benchmark -----
bench-sentiment:
	@echo "Running sentiment analysis benchmark..."
	@docker compose -f infra/docker-compose.yml exec -T api sh -c \
		'if [ ! -f scripts/bench_sentiment.py ]; then \
			echo "Error: scripts/bench_sentiment.py not found"; \
			exit 1; \
		else \
			python scripts/bench_sentiment.py; \
		fi'

smoke-sentiment:
	@echo "Running sentiment smoke test for both backends..."
	@docker compose -f infra/docker-compose.yml exec -T api python scripts/smoke_sentiment.py

smoke-sentiment-batch:
	@BACKEND=$${BACKEND:-hf}; FILE=$${FILE:-data/sample.jsonl}; \
	echo "Running batch sentiment processing (backend=$$BACKEND, file=$$FILE)..."; \
	docker compose -f infra/docker-compose.yml exec -T api python scripts/smoke_sentiment.py --batch $$FILE --backend $$BACKEND

hf-calibrate:
	@FILE=$${FILE:-data/golden_sentiment.jsonl}; REPORT=$${REPORT:-reports}; \
	echo "Running HF sentiment threshold calibration..."; \
	docker compose -f infra/docker-compose.yml exec -T api python scripts/hf_calibrate.py --file $$FILE --report $$REPORT --backend hf

clean: ## Clean up temporary files and caches
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage

dbtest: ## Quick DB insert/upsert smoke test
	@echo "Running DB smoke test..."
	$(COMPOSE) exec -T api python - <<'PY'
	from api.database import build_engine_from_env,get_sessionmaker
	from api.db import with_session,insert_raw_post,upsert_event,now_utc
	S=get_sessionmaker(build_engine_from_env())
	with with_session(S) as s:
	    pid=insert_raw_post(s,'tester','hello world',now_utc(),['https://x.com'])
	    upsert_event(s,'evt:demo','token',0.6,'demo summary',{'posts':[pid]},now_utc())
	print('ok',pid)
	PY

verify-refiner:
	@if [ -n "$(REFINE_BACKEND)" ]; then \
	  EXTRA_ENV="-e REFINE_BACKEND=$(REFINE_BACKEND)"; \
	else \
	  EXTRA_ENV=""; \
	fi; \
	docker compose -f infra/docker-compose.yml exec -T $$EXTRA_ENV \
	  api bash -lc 'PYTHONPATH=/app python -m api.scripts.verify_refiner'

verify-refiner-rules:
	REFINE_BACKEND=rules $(MAKE) verify-refiner

verify-refiner-llm:
	REFINE_BACKEND=llm $(MAKE) verify-refiner

demo-refine:
	@if [ -n "$(REFINE_BACKEND)" ]; then \
	  EXTRA_ENV="-e REFINE_BACKEND=$(REFINE_BACKEND)"; \
	else \
	  EXTRA_ENV=""; \
	fi; \
	docker compose -f infra/docker-compose.yml exec -T $$EXTRA_ENV \
	  api bash -lc 'PYTHONPATH=/app python -m api.scripts.demo_refine'

verify-topic:
	@echo "Verifying topic signal API..."
	cd infra && docker compose exec -T api python -m api.scripts.verify_topic_signal

verify-topic-push:
	@echo "Verifying topic push to Telegram..."
	cd infra && docker compose exec -T api python -m api.scripts.verify_topic_push

verify_rules:
	@echo "Verifying rule engine with pytest..."
	docker compose -f infra/docker-compose.yml exec -T api pytest -q tests/test_rules_eval.py

push-topic-digest:
	@echo "Pushing daily topic digest..."
	cd infra && docker compose exec -T worker python -c "from worker.jobs.push_topic_candidates import push_topic_digest; push_topic_digest()"

seed-topic:
	@if [ -z "$(topic)" ]; then echo "Usage: make seed-topic topic=t.XXXX"; exit 1; fi
	docker compose -f infra/docker-compose.yml exec api bash -lc 'cd /app && python -m api.scripts.seed_topic_mentions $(topic)'

# ----- Onchain Verification -----
onchain-verify-once:
	@echo "Running onchain signal verification once..."
	@if [ -z "$(EVENT_KEY)" ]; then \
		echo "Running verification for all candidate signals (limit=100)..."; \
		docker compose -f infra/docker-compose.yml exec -T worker python -c \
			"from worker.jobs.onchain.verify_signal import run_once; import json; result = run_once(limit=100); print(json.dumps(result))"; \
	else \
		echo "Running verification with limit=1 (EVENT_KEY filtering not supported)..."; \
		docker compose -f infra/docker-compose.yml exec -T worker python -c \
			"from worker.jobs.onchain.verify_signal import run_once; import json; result = run_once(limit=1); print(json.dumps(result))"; \
	fi

expert-dryrun:
	@echo "Running expert view dryrun..."
	@if [ -z "$(ADDRESS)" ]; then \
		echo "Error: ADDRESS parameter required. Usage: make expert-dryrun ADDRESS=0x123..."; \
		exit 1; \
	fi
	@WINDOW=$${WINDOW:-24h}; \
	echo "Fetching expert view for ADDRESS=$(ADDRESS) WINDOW=$$WINDOW..."; \
	if [ "$$WINDOW" = "24h" ]; then \
		WINDOW_MINS=1440; \
	elif [ "$$WINDOW" = "1h" ]; then \
		WINDOW_MINS=60; \
	elif [ "$$WINDOW" = "30m" ]; then \
		WINDOW_MINS=30; \
	else \
		echo "Warning: Unknown WINDOW format, using 24h default"; \
		WINDOW_MINS=1440; \
	fi; \
	docker compose -f infra/docker-compose.yml exec -T \
		-e EXPERT_VIEW=on \
		-e EXPERT_KEY=devkey \
		api python -c "import requests, json; r = requests.get('http://localhost:8000/expert/onchain?chain=eth&address=$(ADDRESS)', headers={'X-Expert-Key': 'devkey'}); print(json.dumps(r.json() if r.status_code == 200 else {'error': f'HTTP {r.status_code}: {r.text}'}, indent=2))"

# ----- Cards Verification (Day19) -----
verify_cards:
	@if [ -z "$(EVENT_KEY)" ]; then \
		echo "Error: EVENT_KEY parameter required. Usage: EVENT_KEY=TEST_BAD make verify_cards"; \
		exit 1; \
	fi
	@echo "Verifying /cards/preview for EVENT_KEY=$(EVENT_KEY)..."
	@python scripts/verify_cards_preview.py --event-key $(EVENT_KEY)

# ----- Telegram Benchmark -----
bench-telegram:
	@N=$${N:-5}; TEXT=$${TEXT:-"bench from scripts/bench_telegram.py"}; INTERVAL=$${INTERVAL:-200}; \
	echo "Benchmarking Telegram with N=$$N messages..."; \
	docker compose -f infra/docker-compose.yml exec -T api sh -lc \
		"python scripts/bench_telegram.py -n $$N --text \"$$TEXT\" --interval-ms $$INTERVAL"

# ----- Routes Discovery -----
.PHONY: routes
routes: ## Discover available x/dex/topic routes from OpenAPI
	@mkdir -p logs/day22
	@echo "Fetching OpenAPI spec from http://localhost:8000/openapi.json..."
	@curl -s -f http://localhost:8000/openapi.json -o logs/day22/openapi.json 2>/dev/null && \
		echo "OpenAPI spec saved to logs/day22/openapi.json" && \
		echo && \
		echo "Available routes containing x/, dex/, or topic:" && \
		echo "--------------------------------------------------" && \
		python3 -c 'import json; f = open("logs/day22/openapi.json"); spec = json.loads(f.read()); f.close(); paths = spec.get("paths", {}); c = 0; \
		[print(f"{method.upper():6} {path}") for path in paths if ("/x/" in path or "/dex/" in path or "/topic/" in path) for method in paths[path].keys() if method.upper() in ["GET", "POST", "PUT", "DELETE", "PATCH"]]' || \
		(echo "Error: Could not connect to API at http://localhost:8000" >&2; \
		 echo "Make sure the API service is running: make up" >&2; \
		 exit 1)