from .app import app
from .jobs.onchain.verify_signal import run_once as verify_signals_once
from .jobs.outbox_retry import scheduled_process
from .jobs.outbox_dlq_recover import recover_once
from api.tasks.beat import heartbeat as beat_heartbeat
from celery.schedules import crontab
import json
from .jobs.x_kol_poll import run_once as kol_poll_once
from .jobs.events_compact import run_once as events_compact_once
from .jobs.ca_hunter_scan import run_once as ca_hunter_once
from api.jobs.goplus_scan import goplus_scan as goplus_scan_once
from .jobs.secondary_proxy_scan import run_once as secondary_proxy_once

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

@app.task(name="x.kol.poll_once")
def x_kol_poll_once():
    """Run KOL polling job once (scheduled by beat)."""
    return kol_poll_once()

@app.task(name="events.compact_5m")
def events_compact_task():
    """Compact raw_posts to events (5m)."""
    return events_compact_once()

@app.task(name="ca_hunter.scan_5m")
def ca_hunter_scan_task():
    """Run CA hunter MVP scan (5m)."""
    return ca_hunter_once()

@app.task(name="worker.tasks.goplus_scan_periodic")
def goplus_scan_periodic():
    """Periodic GoPlus scan to enrich signals."""
    return goplus_scan_once()

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
    'x-kol-poll-every-5min': {
        'task': 'x.kol.poll_once',
        'schedule': 300.0,  # every 5 minutes
        'options': {'queue': 'x_polls'},
    },
    'events-compact-every-5min': {
        'task': 'events.compact_5m',
        'schedule': 300.0,
        'options': {'queue': 'signals'},
    },
    'ca-hunter-scan-every-5min': {
        'task': 'ca_hunter.scan_5m',
        'schedule': 300.0,
        'options': {'queue': 'signals'},
    },
    'goplus-scan-every-15min': {
        'task': 'worker.tasks.goplus_scan_periodic',
        'schedule': 900.0,
        'options': {'queue': 'signals'},
    },
    'secondary-proxy-scan-every-5min': {
        'task': 'secondary.proxy_scan_5m',
        'schedule': 300.0,
        'options': {'queue': 'signals'},
    },
}
