"""Celery worker configuration"""
import os
from celery import Celery

# Create Celery app
app = Celery('worker')

# Configuration
app.conf.update(
    broker_url=os.getenv('REDIS_URL', 'redis://redis:6379/0'),
    result_backend=os.getenv('REDIS_URL', 'redis://redis:6379/0'),
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# Conditionally register GoPlus scan task
if os.getenv("ENABLE_GOPLUS_SCAN", "false").lower() == "true":
    @app.task(name="worker.goplus_scan_task")
    def goplus_scan_task(batch=None):
        """Celery task wrapper for GoPlus batch scan"""
        from api.jobs.goplus_scan import goplus_scan
        return goplus_scan(batch)
    
    # Optional: Set up periodic task if using celery beat
    from celery.schedules import crontab
    app.conf.beat_schedule = app.conf.beat_schedule or {}
    app.conf.beat_schedule['goplus-scan'] = {
        'task': 'worker.goplus_scan_task',
        'schedule': crontab(minute='*/30'),  # Run every 30 minutes
        'args': ()
    }