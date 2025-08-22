FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    celery \
    redis \
    psycopg2-binary \
    sqlalchemy \
    alembic \
    python-dotenv

COPY . .

CMD ["celery", "-A", "worker.app", "worker", "-l", "info"]