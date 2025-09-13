from celery import Celery
import os

# Single source of truth for broker/backend
redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = Celery('worker', broker=redis_url, backend=redis_url)

app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

app.autodiscover_tasks(['worker.jobs', 'worker'])

# Import tasks to ensure beat schedule is registered
from . import tasks

# 注册周期任务：每 20 秒跑一次 outbox 批处理
from celery.schedules import schedule
from worker.tasks import outbox_process_batch

@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # 20 秒一次，名字别和现有的冲突
    sender.add_periodic_task(
        schedule(20.0),
        outbox_process_batch.s(),
        name="outbox-process-every-20s",
    )

if __name__ == "__main__":
    print("Celery app loaded:", app)