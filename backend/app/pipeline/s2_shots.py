"""Stage 2 -- Shot detection.

Split each video into content-aware shots with PySceneDetect; each shot and each
surviving photo becomes a ``MomentSpec`` (the atomic editable unit).

Pure function: list[ShotInput] -> list[MomentSpec].
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Nominal still duration; the edit brain overrides per-decision.
PHOTO_NOMINAL_S = 3.0
# Ignore micro-shots shorter than this (flicker / detector noise).
MIN_SHOT_S = 0.6
# Detector sensitivity (lower = more cuts).
SCENE_THRESHOLD = 27.0


@dataclass
class ShotInput:
    asset_id: str
    path: str
    kind: str  # photo | video
    duration_s: float = 0.0  # for video, from stage 1 probe


@dataclass
class MomentSpec:
    asset_id: str
    kind: str
    start_s: float
    end_s: float
    duration_s: float


def detect_moments(inputs: list[ShotInput]) -> list[MomentSpec]:
    moments: list[MomentSpec] = []
    for item in inputs:
        if item.kind == "photo":
            moments.append(
                MomentSpec(item.asset_id, "photo", 0.0, 0.0, PHOTO_NOMINAL_S)
            )
            continue
        moments.extend(_shots_for_video(item))
    log.info("Shot detection: %d assets -> %d moments", len(inputs), len(moments))
    return moments


def _shots_for_video(item: ShotInput) -> list[MomentSpec]:
    try:
        from scenedetect import ContentDetector, detect

        scenes = detect(item.path, ContentDetector(threshold=SCENE_THRESHOLD))
    except Exception as e:
        log.warning("Scene detect failed for %s (%s); using whole clip", item.path, e)
        scenes = []

    out: list[MomentSpec] = []
    if scenes:
        for start, end in scenes:
            s, e = start.get_seconds(), end.get_seconds()
            if e - s >= MIN_SHOT_S:
                out.append(MomentSpec(item.asset_id, "video", s, e, e - s))

    if not out:
        # Single-shot clip (no detected cuts) -> use the whole thing.
        dur = item.duration_s
        if dur <= 0:
            from .media import ffprobe

            try:
                dur = ffprobe(item.path).duration_s
            except Exception:
                dur = 0.0
        if dur >= MIN_SHOT_S:
            out.append(MomentSpec(item.asset_id, "video", 0.0, dur, dur))
    return out
