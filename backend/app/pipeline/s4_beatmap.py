"""Stage 4 -- Beat map.

The chosen vibe maps to one bundled track; we load that track's *precomputed*
beat map JSON. Beats are never recomputed per job -- they are built once offline
by ``scripts/build_beatmaps.py`` and committed to ``assets/music/``.
"""
from __future__ import annotations

import json
import logging

from ..config import MUSIC_DIR
from .schemas import BeatMap, EnergySection
from .tracks import Track, select_track

log = logging.getLogger(__name__)


def beatmap_path(track_id: str) -> str:
    return str(MUSIC_DIR / f"{track_id}.beatmap.json")


def load_beatmap_for_vibe(vibe: str, seed: int = 0) -> BeatMap:
    track = select_track(vibe, seed)
    return load_beatmap(track)


def load_beatmap(track: Track) -> BeatMap:
    path = beatmap_path(track.track_id)
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"Missing beat map for {track.track_id}. Run scripts/build_beatmaps.py "
            f"(expected at {path})."
        ) from e

    bm = BeatMap(
        track_id=track.track_id,
        path=str(MUSIC_DIR / track.file),
        bpm=float(data["bpm"]),
        duration_s=float(data["duration_s"]),
        beats=[float(t) for t in data.get("beats", [])],
        downbeats=[float(t) for t in data.get("downbeats", [])],
        energy_sections=[EnergySection(**s) for s in data.get("energy_sections", [])],
    )
    log.info(
        "Loaded beat map %s: bpm=%.1f, %d downbeats, %.1fs",
        bm.track_id,
        bm.bpm,
        len(bm.downbeats),
        bm.duration_s,
    )
    return bm
