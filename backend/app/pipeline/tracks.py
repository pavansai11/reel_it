"""Bundled music registry: vibe -> tracks.

Each vibe maps to a small set of tracks so re-rolls can vary the music. Beat maps
are precomputed once (see ``scripts/build_beatmaps.py``) and committed alongside
the audio so the pipeline is deterministic and never recomputes beats per job.

To use real licensed music, drop the audio files into ``assets/music/`` under the
``file`` names below, rebuild beat maps, and you're done -- no code changes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    track_id: str
    vibe: str
    file: str  # filename within assets/music/
    bpm: float  # nominal; the committed beat map is authoritative
    title: str


TRACKS: list[Track] = [
    # Energetic: fast, punchy, clear drop.
    Track("energetic_01", "energetic", "energetic_01.wav", 128, "Sun Chasers"),
    Track("energetic_02", "energetic", "energetic_02.wav", 124, "Coast Run"),
    Track("energetic_03", "energetic", "energetic_03.wav", 132, "Night Out"),
    # Cinematic: mid-tempo, building, emotional.
    Track("cinematic_01", "cinematic", "cinematic_01.wav", 100, "Wide Horizons"),
    Track("cinematic_02", "cinematic", "cinematic_02.wav", 96, "First Light"),
    Track("cinematic_03", "cinematic", "cinematic_03.wav", 104, "Long Way Home"),
    # Aesthetic: relaxed, dreamy, lo-fi.
    Track("aesthetic_01", "aesthetic", "aesthetic_01.wav", 84, "Soft Focus"),
    Track("aesthetic_02", "aesthetic", "aesthetic_02.wav", 90, "Golden Hour"),
    Track("aesthetic_03", "aesthetic", "aesthetic_03.wav", 88, "Slow Days"),
]

_BY_VIBE: dict[str, list[Track]] = {}
for _t in TRACKS:
    _BY_VIBE.setdefault(_t.vibe, []).append(_t)

_BY_ID = {t.track_id: t for t in TRACKS}


def tracks_for_vibe(vibe: str) -> list[Track]:
    return _BY_VIBE.get(vibe, _BY_VIBE["energetic"])


def select_track(vibe: str, seed: int = 0) -> Track:
    """Pick a track for a vibe. ``seed`` (the reroll counter) rotates choices."""
    pool = tracks_for_vibe(vibe)
    return pool[seed % len(pool)]


def get_track(track_id: str) -> Track | None:
    return _BY_ID.get(track_id)
