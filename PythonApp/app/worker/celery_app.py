# app/worker/celery_app.py

from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv()

REDIS_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379")
REDIS_BACKEND_URL = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379")

celery_app = Celery(
    "techstep_app",
    broker=REDIS_BROKER_URL,
    backend=REDIS_BACKEND_URL,
    # REMOVA OU COMENTE ESTA LINHA: include=["app.worker.tasks"]
)

celery_app.conf.timezone = "America/Sao_Paulo"