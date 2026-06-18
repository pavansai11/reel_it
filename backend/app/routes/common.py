"""Shared route helpers: anonymous session handling + API response models."""
from __future__ import annotations

from fastapi import Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from ..models import Session as SessionModel

SESSION_COOKIE = "rm_session"


def get_or_create_session(request: Request, response: Response, db: DbSession) -> SessionModel:
    """Anonymous session via cookie (no auth in the MVP, spec §1)."""
    sid = request.cookies.get(SESSION_COOKIE)
    sess = db.get(SessionModel, sid) if sid else None
    if sess is None:
        sess = SessionModel()
        db.add(sess)
        db.commit()
        response.set_cookie(
            SESSION_COOKIE,
            sess.id,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite="lax",
        )
    return sess


# --- API response models ---------------------------------------------------
class AssetOut(BaseModel):
    id: str
    kind: str
    original_filename: str | None = None


class UploadResponse(BaseModel):
    session_id: str
    assets: list[AssetOut]


class JobCreateRequest(BaseModel):
    vibe: str = "energetic"
    asset_ids: list[str]


class JobResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    stage_progress: float
    stage_message: str
    error: str | None = None


class JobResultResponse(BaseModel):
    job_id: str
    status: str
    result_url: str | None = None
    vibe: str
    track_id: str | None = None
    edl: dict | None = None


class ActionRequest(BaseModel):
    action: str
    detail: dict | None = None
