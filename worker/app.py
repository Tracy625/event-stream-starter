import os

import redis
from celery import Celery

import api  # noqa: F401 ensure API instrumentation (requests metrics) available in worker

# Single source of truth for broker/backend
redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = Celery("worker", broker=redis_url, backend=redis_url)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_acks_on_failure_or_timeout=True,
    task_reject_on_worker_lost=True,
)

# Broker transport options (visibility timeout, fanout prefix)
try:
    import json as _json

    _bto = os.getenv("CELERY_BROKER_TRANSPORT_OPTIONS")
    if _bto:
        app.conf.broker_transport_options = _json.loads(_bto)
    else:
        vt = int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "3600"))
        app.conf.broker_transport_options = {
            "visibility_timeout": vt,
            "fanout_prefix": True,
            "fanout_patterns": True,
        }
except Exception:
    pass

app.autodiscover_tasks(["worker.jobs", "worker", "api.tasks"])

# 注册周期任务：每 20 秒跑一次 outbox 批处理
from celery.schedules import schedule

from api.core.metrics import (celery_queue_backlog,
                              celery_queue_backlog_warn_total,
                              container_restart_total)
from worker.tasks import outbox_process_batch

# Import tasks to ensure beat schedule is registered
from . import tasks

# Increment restart counter on worker startup
try:
    container_restart_total.inc()
except Exception:
    pass


CELERY_BACKLOG_WARN = int(os.getenv("CELERY_BACKLOG_WARN", "100"))
CELERY_SAMPLE_TIMEOUT_MS = int(os.getenv("CELERY_SAMPLE_TIMEOUT_MS", "300"))


def _record_queue_backlog():
    """Measure default Celery queue backlog and record gauge."""
    try:
        r = redis.from_url(
            redis_url, socket_timeout=max(0.05, CELERY_SAMPLE_TIMEOUT_MS / 1000.0)
        )
        # Default Celery queue key is 'celery'
        size = r.llen("celery") or 0
        celery_queue_backlog.set(float(size), labels={"queue": "celery"})
        if size >= CELERY_BACKLOG_WARN:
            # log a warning via metrics_store if available
            try:
                from api.core.metrics_store import log_json

                log_json(
                    stage="queue.backlog.warn",
                    queue="celery",
                    size=int(size),
                    threshold=CELERY_BACKLOG_WARN,
                )
            except Exception:
                pass
            try:
                celery_queue_backlog_warn_total.inc(labels={"queue": "celery"})
            except Exception:
                pass
    except Exception:
        # Swallow errors; readiness/metrics will capture redis issues
        pass


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # 20 秒一次，名字别和现有的冲突
    sender.add_periodic_task(
        schedule(20.0),
        outbox_process_batch.s(),
        name="outbox-process-every-20s",
    )
    # Queue backlog sampling every 30s
    sender.add_periodic_task(
        schedule(30.0),
        app.signature("worker.app._record_queue_backlog", immutable=True),
        name="queue-backlog-sample-30s",
    )


# Expose backlog recorder as a task for beat scheduling
@app.task(name="worker.app._record_queue_backlog")
def _record_queue_backlog_task():
    _record_queue_backlog()


if __name__ == "__main__":
    print("Celery app loaded:", app)
