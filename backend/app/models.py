"""ORM models (see spec §5).

UserAction + the stored edl_json is the proprietary "editing taste" dataset --
the only compounding moat -- so it is logged on day one.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Job status constants (single source of truth, shared with the frontend) ---
class JobStatus:
    QUEUED = "queued"
    INGESTING = "ingesting"
    SHOTS = "shots"
    SCORING = "scoring"
    EDITING = "editing"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"

    # Ordered for progress percentage in the UI.
    ORDER = [QUEUED, INGESTING, SHOTS, SCORING, EDITING, RENDERING, DONE]


VIBES = ("energetic", "cinematic", "aesthetic")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    jobs: Mapped[list["Job"]] = relationship(back_populates="session")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)

    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED, index=True)
    stage_progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    vibe: Mapped[str] = mapped_column(String(20), default="energetic")
    track_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    edl_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # For re-rolls: nudges the edit brain to a different cut each time.
    reroll_seed: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    session: Mapped["Session"] = relationship(back_populates="jobs")
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    moments: Mapped[list["Moment"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    actions: Mapped[list["UserAction"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)

    kind: Mapped[str] = mapped_column(String(10))  # photo | video
    storage_path: Mapped[str] = mapped_column(String(1024))
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ingest results
    blur_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    phash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    kept: Mapped[bool] = mapped_column(Boolean, default=True)
    drop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    job: Mapped["Job"] = relationship(back_populates="assets")
    moments: Mapped[list["Moment"]] = relationship(back_populates="asset")


class Moment(Base):
    """An atomic editable unit: one photo, or one shot from a video."""

    __tablename__ = "moments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)

    kind: Mapped[str] = mapped_column(String(10))  # photo | video
    start_s: Mapped[float] = mapped_column(Float, default=0.0)
    end_s: Mapped[float] = mapped_column(Float, default=0.0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)

    aesthetic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    smile_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    motion_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_people: Mapped[bool] = mapped_column(Boolean, default=False)
    face_count: Mapped[int] = mapped_column(Integer, default=0)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    used_in_edit: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    job: Mapped["Job"] = relationship(back_populates="moments")
    asset: Mapped["Asset"] = relationship(back_populates="moments")


class UserAction(Base):
    """THE FLYWHEEL. Log every signal of editing taste."""

    __tablename__ = "user_actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)

    # accepted | rerolled | reordered | trimmed | deleted_clip | downloaded | shared
    action: Mapped[str] = mapped_column(String(32), index=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    job: Mapped["Job"] = relationship(back_populates="actions")


class SpendLedger(Base):
    """Rolling daily spend so the global ceiling kill-switch can be enforced."""

    __tablename__ = "spend_ledger"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (UTC)
    usd: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
