import os

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
    }
}

timezone = 'UTC'