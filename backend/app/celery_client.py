"""Celery client used only to enqueue video jobs.

No worker code lives here: this module creates a Celery application bound to
the Redis broker and exposes a single ``enqueue_video_job`` helper that sends
the ``process_video_job`` task. The actual task implementation runs in the
worker process.
"""
from __future__ import annotations

from celery import Celery

from shared.config import settings

celery_app = Celery("viral_shorts_ai", broker=settings.redis_url)
celery_app.conf.update(
    task_default_queue="video",
    task_acks_late=True,
)


def enqueue_video_job(job_id: str) -> None:
    """Enqueue the ``process_video_job`` task for the given job id."""
    celery_app.send_task("process_video_job", args=[job_id])
