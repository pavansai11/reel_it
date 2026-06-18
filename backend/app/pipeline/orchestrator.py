"""Pipeline orchestrator: runs stages 1->6, persisting progress after each.

This is the only place that touches both the DB and the pure stage functions.
Each stage stays a pure function (files/JSON in -> JSON out); the orchestrator
adapts ORM rows to/from those functions and writes status so the UI can show a
live stage.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from ..db import session_scope
from ..models import Asset, Job, JobStatus, Moment
from ..storage import get_storage, result_key
from .s1_ingest import IngestInput, ingest
from .s2_shots import ShotInput, detect_moments
from .s3_score import ScoreInput, score_moments
from .s4_beatmap import load_beatmap_for_vibe
from .s5_editbrain import generate_edl
from .s6_render import RenderInput, render_reel
from .schemas import Moment as MomentSchema
from .schemas import MomentKind

log = logging.getLogger(__name__)


def _set_status(session, job: Job, status: str, progress: float | None = None) -> None:
    job.status = status
    if progress is not None:
        job.stage_progress = progress
    session.add(job)
    session.commit()
    log.info("Job %s -> %s", job.id, status)


def run_job(job_id: str) -> None:
    """Entry point enqueued onto RQ (or run inline)."""
    storage = get_storage()
    try:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                log.error("Job %s not found", job_id)
                return

            # ---- Stage 1: ingest ----
            _set_status(session, job, JobStatus.INGESTING, 0.05)
            assets = session.query(Asset).filter(Asset.job_id == job_id).all()
            ingest_inputs = [
                IngestInput(a.id, storage.local_path(a.storage_path), a.kind) for a in assets
            ]
            results = ingest(ingest_inputs)
            by_id = {a.id: a for a in assets}
            for r in results:
                a = by_id[r.asset_id]
                a.kind = r.kind
                a.kept = r.kept
                a.blur_score = r.blur_score
                a.phash = r.phash
                a.drop_reason = r.drop_reason
                if r.probe:
                    a.width, a.height = r.width, r.height
                    a.duration_s, a.fps = r.duration_s, r.fps
                session.add(a)
            session.commit()
            kept_assets = [a for a in assets if a.kept]
            if not kept_assets:
                raise RuntimeError("All uploads were filtered out (blurry/duplicate/unreadable)")

            # ---- Stage 2: shots ----
            _set_status(session, job, JobStatus.SHOTS, 0.2)
            shot_inputs = [
                ShotInput(a.id, storage.local_path(a.storage_path), a.kind, a.duration_s or 0.0)
                for a in kept_assets
            ]
            specs = detect_moments(shot_inputs)
            session.query(Moment).filter(Moment.job_id == job_id).delete()
            moment_rows: list[Moment] = []
            for sp in specs:
                m = Moment(
                    job_id=job_id,
                    asset_id=sp.asset_id,
                    kind=sp.kind,
                    start_s=sp.start_s,
                    end_s=sp.end_s,
                    duration_s=sp.duration_s,
                )
                session.add(m)
                moment_rows.append(m)
            session.commit()

            # ---- Stage 3: score ----
            _set_status(session, job, JobStatus.SCORING, 0.35)
            asset_path = {a.id: storage.local_path(a.storage_path) for a in kept_assets}
            score_inputs = [
                ScoreInput(m.id, m.asset_id, asset_path[m.asset_id], m.kind, m.start_s, m.end_s)
                for m in moment_rows
            ]
            scores = score_moments(score_inputs)
            score_by_id = {s.moment_id: s for s in scores}
            for m in moment_rows:
                s = score_by_id.get(m.id)
                if not s:
                    continue
                m.aesthetic_score = s.aesthetic_score
                m.smile_score = s.smile_score
                m.motion_score = s.motion_score
                m.has_people = s.has_people
                m.face_count = s.face_count
                m.tags_json = json.dumps(s.tags)
                m.used_in_edit = False
                session.add(m)
            session.commit()

            kept_ids = {s.moment_id for s in scores if s.kept}
            kept_moments = [m for m in moment_rows if m.id in kept_ids]
            if not kept_moments:
                raise RuntimeError("Scoring produced no usable moments")

            # ---- Stage 4: beat map ----
            beatmap = load_beatmap_for_vibe(job.vibe, job.reroll_seed)
            job.track_id = beatmap.track_id
            session.add(job)
            session.commit()

            # ---- Stage 5: edit brain ----
            _set_status(session, job, JobStatus.EDITING, 0.55)
            schema_moments = [_to_schema_moment(m, by_id[m.asset_id]) for m in kept_moments]
            edit = generate_edl(
                schema_moments, beatmap, job.vibe, seed=job.reroll_seed
            )
            job.edl_json = edit.edl.model_dump_json()
            session.add(job)
            session.commit()

            # Mark which moments were used + record spend.
            used_ids = {d.moment_id for d in edit.edl.decisions}
            for m in moment_rows:
                m.used_in_edit = m.id in used_ids
                session.add(m)
            session.commit()
            if edit.brain == "claude" and (edit.input_tokens or edit.output_tokens):
                from ..guards import record_llm_spend

                record_llm_spend(edit.input_tokens, edit.output_tokens)

            # ---- Stage 6: render ----
            _set_status(session, job, JobStatus.RENDERING, 0.75)
            sources = {
                m.id: RenderInput(
                    moment_id=m.id,
                    asset_path=asset_path[m.asset_id],
                    kind=m.kind,
                    source_start_s=m.start_s,
                )
                for m in kept_moments
            }
            with tempfile.TemporaryDirectory(prefix="reelmagic_out_") as tmp:
                local_out = os.path.join(tmp, "reel.mp4")
                render_reel(edit.edl, sources, beatmap, local_out, watermark=True)
                key = result_key(job_id)
                storage.save_file(key, local_out, content_type="video/mp4")
            job.result_url = storage.public_url(key)
            session.add(job)
            session.commit()

            # ---- Done ----
            from ..guards import record_compute_spend

            record_compute_spend()
            _set_status(session, job, JobStatus.DONE, 1.0)

    except Exception as e:  # noqa: BLE001
        log.exception("Job %s failed", job_id)
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED
                job.error = str(e)[:1000]
                session.add(job)


def _to_schema_moment(m: Moment, asset: Asset) -> MomentSchema:
    tags = json.loads(m.tags_json) if m.tags_json else []
    return MomentSchema(
        id=m.id,
        asset_id=m.asset_id,
        kind=MomentKind(m.kind),
        source_path=asset.storage_path,
        start_s=m.start_s,
        end_s=m.end_s,
        duration_s=m.duration_s,
        aesthetic_score=m.aesthetic_score or 0.0,
        smile_score=m.smile_score or 0.0,
        motion_score=m.motion_score or 0.0,
        has_people=bool(m.has_people),
        face_count=m.face_count or 0,
        tags=tags,
    )
