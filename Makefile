.PHONY: help up down logs test demo seed clean

help:
	@echo "Available targets:"
	@echo "  up      - Start all services (docker-compose up -d)"
	@echo "  down    - Stop all services (docker-compose down)"
	@echo "  logs    - Tail logs from all services"
	@echo "  test    - Run test suite"
	@echo "  demo    - Run demo/example workflow"
	@echo "  seed    - Seed database with sample data"
	@echo "  clean   - Clean up temporary files and caches"

up:
	@echo "Starting services..."
	# docker-compose up -d

down:
	@echo "Stopping services..."
	# docker-compose down

logs:
	@echo "Tailing logs..."
	# docker-compose logs -f

test:
	@echo "Running tests..."
	# pytest tests/
	# npm test

demo:
	@echo "Running demo..."
	# python scripts/demo.py

seed:
	@echo "Seeding database..."
	# python scripts/seed_db.py

clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage