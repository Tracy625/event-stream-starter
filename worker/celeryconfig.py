import os

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

broker_url = REDIS_URL
result_backend = REDIS_URL

# Single beat schedule definition
beat_schedule = {
    'ping-every-minute': {
        'task': 'worker.tasks.ping',
        'schedule': 60.0,
    }
}

timezone = 'UTC'