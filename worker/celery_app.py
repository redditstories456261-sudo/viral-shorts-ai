"""Celery application for the Viral Shorts AI GPU worker."""

from celery import Celery

from shared.config import settings

celery_app = Celery("viral_shorts", broker=settings.redis_url)

celery_app.conf.update(
    task_routes={"process_video_job": {"queue": "gpu"}},
    task_acks_late=True,          # requeue if a worker dies mid-job
    worker_prefetch_multiplier=1,  # one heavy GPU job at a time per worker
    task_time_limit=6 * 3600,
    task_soft_time_limit=5 * 3600,
    result_backend=settings.redis_url,
    result_extended=True,
    include=["worker.tasks"],     # task module imported at worker startup
)
