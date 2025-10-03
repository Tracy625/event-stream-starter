"""Health and readiness routes"""

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text as sa_text

from api.cache import get_redis_client
from api.core.metrics import readyz_latency_ms
from api.core.metrics_store import log_json
from api.database import with_db
from api.db.repositories.outbox_repo import enqueue

router = APIRouter()


@router.get("/healthz")
def healthz():
    """Health check endpoint for container orchestration"""
    return {"status": "healthy"}


@router.get("/health")
def health():
    """Alternative health check endpoint"""
    return {"status": "healthy"}


@router.get("/readyz")
def readyz():
    """Readiness probe: DB, Redis, and queue dry-run must be OK."""
    import time

    t0 = time.time()
    log_json(stage="readyz.start", level="info", operation="readyz", status="begin")
    # DB check + queue dry-run in a rollback scope
    try:
        with with_db() as db:
            # SELECT 1
            db.execute(sa_text("SELECT 1")).scalar()
            # Outbox enqueue dry-run (uncommitted)
            try:
                enqueue(
                    db,
                    channel_id=0,
                    thread_id=None,
                    event_key="readyz_probe",
                    payload_json={"ok": True},
                )
            except Exception as e:
                # Some deployments may not have outbox tables; log but do not fail readiness
                log_json(stage="readyz.queue.dryrun.warn", error=str(e)[:120])
    except Exception as e:
        log_json(stage="readyz.db.error", level="warn", error=str(e)[:200])
        return Response(content="service unavailable", status_code=503)

    # Redis ping
    try:
        rc = get_redis_client()
        if rc is None:
            raise RuntimeError("redis client unavailable")
        rc.ping()
        # Celery queue dry-run (LPUSH/LPOP on probe key)
        probe_key = "celery:probe:readyz"
        rc.lpush(probe_key, "ok")
        v = rc.lpop(probe_key)
        if v is None:
            raise RuntimeError("celery dry-run failed")
    except Exception as e:
        log_json(stage="readyz.redis.error", level="warn", error=str(e)[:200])
        return Response(content="service unavailable", status_code=503)
    latency_ms = int((time.time() - t0) * 1000)
    log_json(
        stage="readyz.ok",
        level="info",
        operation="readyz",
        status="ready",
        latency=latency_ms,
    )
    # Observe latency in histogram
    try:
        readyz_latency_ms.observe(latency_ms)
    except Exception:
        pass
    return JSONResponse(
        {"status": "ready", "latency_ms": latency_ms},
        headers={"Cache-Control": "no-store"},
    )
