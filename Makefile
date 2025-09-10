.PHONY: help up down logs api worker migrate revision test demo seed clean dbtest bench-sentiment smoke-sentiment smoke-sentiment-batch hf-calibrate verify-refiner demo-refine onchain-verify-once expert-dryrun

help:
	@echo "Targets:"
	@echo "  up/down/logs       - manage docker compose services"
	@echo "  migrate/revision   - Alembic apply / create new revision (use m=\"message\")"
	@echo "  demo               - run demo_ingest.py inside api container"
	@echo "  bench-sentiment    - run sentiment analysis benchmark (set SENTIMENT_BACKEND=hf for HF)"
	@echo "  smoke-sentiment    - test both sentiment backends with fixed inputs"
	@echo "  smoke-sentiment-batch - run batch sentiment processing with HF backend"
	@echo "  hf-calibrate       - calibrate HF sentiment thresholds with golden data"
	@echo "  dbtest             - quick DB insert/upsert smoke test"
	@echo "  api/worker         - run services locally (placeholder)"
	@echo "  test/seed          - run tests / seed database (placeholder)"
	@echo "  clean              - clean up temporary files and caches"

up:
	@echo "Starting services..."
	cd infra && docker compose up -d --build

down:
	@echo "Stopping services..."
	cd infra && docker compose down

logs:
	@echo "Tailing logs..."
	cd infra && docker compose logs -f

api:
	@echo "Starting API server..."
	# uvicorn api.main:app --reload

worker:
	@echo "Starting Celery worker..."
	# celery -A worker.app worker --loglevel=info

# ----- Alembic -----
migrate:
	@echo "Running alembic upgrade head inside api container..."
	cd infra && docker compose exec -T api sh -c 'cd /app/api && alembic upgrade head'

revision:
	@if [ -z "$(m)" ]; then echo 'Usage: make revision m="your message"'; exit 1; fi
	@echo "Creating alembic revision: $(m)"
	cd infra && docker compose exec -T api sh -c 'cd /app/api && alembic revision -m "$(m)"'

test:
	@echo "Running tests..."
	# pytest tests/
	# npm test

# ----- Demo -----
demo:
	@echo "Running demo ingestion pipeline inside api container..."
	docker compose -f infra/docker-compose.yml exec -T api python scripts/demo_ingest.py

seed:
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

clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage

.PHONY: dbtest
dbtest:
	@echo "Running DB smoke test..."
	cd infra && docker compose exec -T api python - <<'PY'
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