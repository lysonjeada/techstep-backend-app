# celery_app.py

from celery import Celery

celery_app = Celery(
    "resume_tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

# 🔥 Garante que as tasks sejam registradas no worker
import worker.tasks
