"""Background job queue (Redis + RQ).

The frontend polls ``/job/{id}/status`` while a worker drains the queue. When
``RUN_JOBS_INLINE=true`` (tests, or zero-Redis local dev) the job executes
synchronously in-process instead.
"""
from __future__ import annotations

import logging

from .config import settings

log = logging.getLogger(__name__)

_redis = None
_queue = None


def get_redis():
    global _redis
    if _redis is None:
        from redis import Redis

        _redis = Redis.from_url(settings.redis_url)
    return _redis


def get_queue():
    global _queue
    if _queue is None:
        from rq import Queue

        _queue = Queue("reelmagic", connection=get_redis(), default_timeout=1800)
    return _queue


def enqueue_job(job_id: str) -> None:
    """Enqueue a pipeline run for ``job_id`` (or run it inline)."""
    # Import here to avoid importing heavy pipeline deps at web-app startup.
    from .pipeline.orchestrator import run_job

    if settings.run_jobs_inline:
        log.info("Running job %s inline", job_id)
        run_job(job_id)
        return

    try:
        get_queue().enqueue(run_job, job_id, job_timeout=1800)
        log.info("Enqueued job %s", job_id)
    except Exception:  # pragma: no cover - redis down in dev
        log.exception("Failed to enqueue job %s; running inline as fallback", job_id)
        run_job(job_id)
