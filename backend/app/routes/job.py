"""Job status + result routes (spec §6)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..models import Job, JobStatus
from .common import JobResultResponse, JobStatusResponse

router = APIRouter()

# Friendly, human stage messages (spec §7 -- "no spinner-only screens").
STAGE_MESSAGES = {
    JobStatus.QUEUED: "Getting ready…",
    JobStatus.INGESTING: "Cleaning up your photos…",
    JobStatus.SHOTS: "Finding your best moments…",
    JobStatus.SCORING: "Picking the highlights…",
    JobStatus.EDITING: "Cutting to the beat…",
    JobStatus.RENDERING: "Polishing your reel…",
    JobStatus.DONE: "Done!",
    JobStatus.FAILED: "Something went wrong.",
}


@router.get("/job/{job_id}/status", response_model=JobStatusResponse)
def job_status(job_id: str, db: DbSession = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        stage_progress=job.stage_progress,
        stage_message=STAGE_MESSAGES.get(job.status, "Working…"),
        error=job.error,
    )


@router.get("/job/{job_id}/result", response_model=JobResultResponse)
def job_result(job_id: str, db: DbSession = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    edl = json.loads(job.edl_json) if job.edl_json else None
    return JobResultResponse(
        job_id=job.id,
        status=job.status,
        result_url=job.result_url,
        vibe=job.vibe,
        track_id=job.track_id,
        edl=edl,
    )
