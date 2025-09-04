.PHONY: help up down logs api worker migrate revision test demo seed clean dbtest bench-sentiment smoke-sentiment verify-refiner demo-refine

help:
	@echo "Targets:"
	@echo "  up/down/logs       - manage docker compose services"
	@echo "  migrate/revision   - Alembic apply / create new revision (use m=\"message\")"
	@echo "  demo               - run demo_ingest.py inside api container"
	@echo "  bench-sentiment    - run sentiment analysis benchmark (set SENTIMENT_BACKEND=hf for HF)"
	@echo "  smoke-sentiment    - test both sentiment backends with fixed inputs"
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