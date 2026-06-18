"""Flywheel route: log every user action (spec §5, §6). ⭐

UserAction + the stored EDL is the proprietary editing-taste dataset. Every
accept / re-roll / reorder / trim / download / share is logged here. A re-roll
also re-enqueues the job with a bumped seed so the brain produces a new cut.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..guards import rate_limited
from ..models import Job, JobStatus, UserAction
from ..queue import enqueue_job
from .common import ActionRequest, JobResponse

log = logging.getLogger(__name__)
router = APIRouter()

VALID_ACTIONS = {
    "accepted",
    "rerolled",
    "reordered",
    "trimmed",
    "deleted_clip",
    "downloaded",
    "shared",
}


@router.post("/job/{job_id}/action", response_model=JobResponse)
def log_action(job_id: str, payload: ActionRequest, db: DbSession = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if payload.action not in VALID_ACTIONS:
        raise HTTPException(400, f"Unknown action '{payload.action}'")

    db.add(
        UserAction(
            job_id=job_id,
            action=payload.action,
            detail_json=json.dumps(payload.detail) if payload.detail else None,
        )
    )
    db.commit()
    log.info("Action logged: job=%s action=%s", job_id, payload.action)

    # A re-roll regenerates a different cut from the same moment pool.
    if payload.action == "rerolled":
        if rate_limited(job.session_id):
            raise HTTPException(429, "Daily limit reached")
        job.reroll_seed += 1
        job.status = JobStatus.QUEUED
        job.error = None
        db.add(job)
        db.commit()
        enqueue_job(job.id)

    return JobResponse(job_id=job.id, status=job.status)
