"""Auto-delete user media + outputs after the TTL (spec §8, default 48h).

Run on a schedule (cron / Railway cron / Modal scheduled function):

    python scripts/cleanup.py

Deletes the media blobs (uploads + rendered reels) for expired jobs but KEEPS
the flywheel data (UserAction rows + edl_json text) -- that is the moat and costs
nothing to retain.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import Job  # noqa: E402
from app.storage import get_storage  # noqa: E402


def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.asset_ttl_hours)
    storage = get_storage()
    purged = 0
    with session_scope() as session:
        jobs = session.query(Job).filter(Job.created_at < cutoff).all()
        for job in jobs:
            # created_at may be tz-naive from SQLite; normalize for safety.
            n = storage.delete_prefix(f"jobs/{job.id}/")
            if job.result_url:
                job.result_url = None
                session.add(job)
            if n:
                purged += 1
    print(f"Purged media for {purged} expired job(s) (older than {settings.asset_ttl_hours}h).")


if __name__ == "__main__":
    main()
