"""RQ worker entrypoint.

    python -m backend.worker      # from repo root
    python worker.py              # from backend/

Drains the 'reelmagic' queue. Run one or more of these alongside the API.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.db import init_db
from app.queue import get_redis


def main() -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    init_db()
    from rq import Queue, Worker

    redis = get_redis()
    queue = Queue("reelmagic", connection=redis)
    worker = Worker([queue], connection=redis)
    logging.getLogger(__name__).info("ReelMagic worker started; waiting for jobs…")
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
