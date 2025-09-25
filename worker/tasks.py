from .app import app
from .jobs.onchain.verify_signal import run_once as verify_signals_once
from .jobs.outbox_retry import scheduled_process
from .jobs.outbox_dlq_recover import recover_once
from api.tasks.beat import heartbeat as beat_heartbeat
from celery.schedules import crontab
import json

@app.task
def ping():
    return "pong"

@app.task
def verify_onchain_signals():
    """Run on-chain signal verification job."""
    return verify_signals_once(limit=100)

@app.task
def onchain_verify_periodic():
    """Periodic task to verify onchain signals every minute."""
    try:
        result = verify_signals_once(limit=100)
        # Log structured output
        print(json.dumps({
            "stage": "onchain_verify_periodic",
            "scanned": result.get("scanned", 0),
            "evaluated": result.get("evaluated", 0),
            "updated": result.get("updated", 0),
            "ok": True
        }))
        return result
    except Exception as e:
        print(json.dumps({
            "stage": "onchain_verify_periodic",
            "error": str(e),
            "ok": False
        }))
        raise

@app.task(name="outbox.process_batch")
def outbox_process_batch():
    """
    Celery 任务壳：调用 outbox 重试批处理
    最小改动，不引入新依赖，不改变启动命令
    """
    return scheduled_process()


@app.task(name="outbox.recover_dlq")
def outbox_recover_dlq():
    """Recover DLQ entries back into the primary outbox."""
    return recover_once()


@app.task(name="beat.heartbeat")
def beat_heartbeat_task():
    """Record beat heartbeat for health monitoring."""
    return beat_heartbeat()

# Celery Beat schedule configuration
app.conf.beat_schedule = {
    'onchain-verify-every-minute': {
        'task': 'worker.tasks.onchain_verify_periodic',
        'schedule': 60.0,  # Run every 60 seconds
    },
    'outbox-dlq-recover': {
        'task': 'outbox.recover_dlq',
        'schedule': 60.0,
    },
    'beat-heartbeat': {
        'task': 'beat.heartbeat',
        'schedule': 5.0,
    },
}
