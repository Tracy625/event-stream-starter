import os
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

broker_url = REDIS_URL
result_backend = REDIS_URL

# Single beat schedule definition
beat_schedule = {
    'ping-every-minute': {
        'task': 'worker.tasks.ping',
        'schedule': 60.0,
    },
    'verify-onchain-signals': {
        'task': 'worker.tasks.verify_onchain_signals',
        'schedule': 60.0,  # Every minute
    },

    # 每 5 分钟执行一次：扫描事件并生成 topic signals
    "scan_topic_signals": {
        "task": "worker.jobs.topic_signal_scan.scan_topic_signals",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "signals"},
    },

    # 每小时执行一次：聚合 topics
    "aggregate_topics": {
        "task": "worker.jobs.topic_aggregate.aggregate_topics",
        "schedule": crontab(minute=0),  # 每小时整点
        "options": {"queue": "aggregation"},
    }
}

timezone = 'UTC'

# Task routing configuration
task_routes = {
    'worker.tasks.*': {'queue': 'default'},
    'worker.jobs.x_kol_poll.*': {'queue': 'x_polls'},
    'worker.jobs.x_avatar_poll.*': {'queue': 'x_polls'},
    'worker.jobs.outbox_retry.*': {'queue': 'outbox'},
    'worker.jobs.push_cards.*': {'queue': 'cards'},

    # 新增路由
    "worker.jobs.topic_signal_scan.scan_topic_signals": {"queue": "signals"},
    "worker.jobs.topic_aggregate.aggregate_topics": {"queue": "aggregation"},
}

# Task retry configuration
task_annotations = {
    'worker.jobs.push_cards.process_card': {
        'rate_limit': '10/s',
        'time_limit': 30,
        'soft_time_limit': 25
    }
}