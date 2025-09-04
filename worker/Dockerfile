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

COPY api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 保留整个仓库给 worker 用
COPY . /app
ENV PYTHONPATH=/app:/app/worker/src

CMD ["celery", "-A", "worker.app", "worker", "-l", "info"]