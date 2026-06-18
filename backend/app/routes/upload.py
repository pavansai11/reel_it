"""Upload + job creation routes (spec §6)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..db import get_db
from ..guards import rate_limited, spend_ceiling_exceeded
from ..models import Asset, Job, JobStatus, VIBES
from ..pipeline.media import kind_for_path
from ..queue import enqueue_job
from ..storage import get_storage, upload_key
from .common import (
    AssetOut,
    JobCreateRequest,
    JobResponse,
    UploadResponse,
    get_or_create_session,
)

log = logging.getLogger(__name__)
router = APIRouter()

MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024


@router.post("/upload", response_model=UploadResponse)
async def upload(
    request: Request,
    response: Response,
    files: list[UploadFile] = File(...),
    db: DbSession = Depends(get_db),
):
    sess = get_or_create_session(request, response, db)
    if len(files) > settings.max_files_per_job:
        raise HTTPException(413, f"Too many files (max {settings.max_files_per_job})")

    storage = get_storage()
    # Stage uploads under a provisional job so storage keys are namespaced.
    job = Job(session_id=sess.id, status=JobStatus.QUEUED, stage_progress=0.0)
    db.add(job)
    db.commit()

    out: list[AssetOut] = []
    total_bytes = 0
    for f in files:
        kind = kind_for_path(f.filename or "")
        if kind is None:
            log.info("Skipping unsupported file %s", f.filename)
            continue
        data = await f.read()
        total_bytes += len(data)
        if total_bytes > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Upload exceeds {settings.max_upload_mb} MB cap")
        key = upload_key(job.id, f.filename or f"file.{ 'jpg' if kind=='photo' else 'mp4'}")
        storage.save_bytes(key, data, content_type=f.content_type)
        asset = Asset(
            job_id=job.id,
            kind=kind,
            storage_path=key,
            original_filename=f.filename,
        )
        db.add(asset)
        out.append(AssetOut(id="", kind=kind, original_filename=f.filename))
    db.commit()

    # Re-read assets to return their generated ids in order.
    assets = db.query(Asset).filter(Asset.job_id == job.id).all()
    out = [
        AssetOut(id=a.id, kind=a.kind, original_filename=a.original_filename)
        for a in assets
    ]
    if not out:
        raise HTTPException(400, "No supported photo/video files were uploaded")

    # Stash the provisional job id on the cookie response via header for the client
    response.headers["X-Reelmagic-Job"] = job.id
    return UploadResponse(session_id=sess.id, assets=out)


@router.post("/job", response_model=JobResponse)
async def create_job(
    request: Request,
    response: Response,
    payload: JobCreateRequest,
    db: DbSession = Depends(get_db),
):
    sess = get_or_create_session(request, response, db)

    if spend_ceiling_exceeded():
        raise HTTPException(503, "Service is temporarily paused (daily capacity reached). Try later.")
    if rate_limited(sess.id):
        raise HTTPException(429, f"Daily limit reached (max {settings.max_reels_per_session_per_day} reels/day)")

    if payload.vibe not in VIBES:
        raise HTTPException(400, f"Unknown vibe '{payload.vibe}'. Choose one of {VIBES}.")
    if not payload.asset_ids:
        raise HTTPException(400, "No assets provided")

    assets = db.query(Asset).filter(Asset.id.in_(payload.asset_ids)).all()
    if not assets:
        raise HTTPException(404, "Assets not found")

    # The assets were uploaded under a provisional job; reuse that job record.
    job_id = assets[0].job_id
    if any(a.job_id != job_id for a in assets):
        raise HTTPException(400, "Assets span multiple jobs")
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.session_id != sess.id:
        raise HTTPException(403, "Not your job")

    job.vibe = payload.vibe
    job.status = JobStatus.QUEUED
    db.add(job)
    db.commit()

    enqueue_job(job.id)
    return JobResponse(job_id=job.id, status=job.status)
