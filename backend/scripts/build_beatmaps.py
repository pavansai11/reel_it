"""Offline beat-map builder (spec stage 4).

Runs librosa ONCE per bundled track to extract bpm, beats, downbeats, and energy
sections, then writes ``<track_id>.beatmap.json`` next to the audio. The runtime
pipeline only ever loads these JSONs -- it never recomputes beats per job.

    python scripts/build_beatmaps.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import librosa
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import MUSIC_DIR  # noqa: E402
from app.pipeline.tracks import TRACKS  # noqa: E402


def _energy_sections(y: np.ndarray, sr: int, win_s: float = 2.0) -> list[dict]:
    """RMS energy bucketed into ~win_s windows, normalized to 0..1."""
    hop = 512
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
    if rms.max() > rms.min():
        rms_n = (rms - rms.min()) / (rms.max() - rms.min())
    else:
        rms_n = np.zeros_like(rms)

    sections = []
    total = times[-1] if len(times) else 0.0
    start = 0.0
    while start < total:
        end = min(start + win_s, total)
        mask = (times >= start) & (times < end)
        level = float(rms_n[mask].mean()) if mask.any() else 0.0
        sections.append({"start": round(start, 2), "end": round(end, 2), "level": round(level, 3)})
        start = end
    return sections


def build_one(path: Path) -> dict:
    y, sr = librosa.load(str(path), sr=None, mono=True)
    duration = float(len(y) / sr)

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beats = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    bpm = float(np.atleast_1d(tempo)[0])

    # Downbeats: every 4th beat (4/4). Anchor to the strongest of the first 4.
    if beats:
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onset_times = librosa.times_like(onset_env, sr=sr)
        first4 = beats[:4] if len(beats) >= 4 else beats
        strengths = [float(np.interp(b, onset_times, onset_env)) for b in first4]
        anchor = int(np.argmax(strengths))
        downbeats = beats[anchor::4]
    else:
        downbeats = []

    return {
        "bpm": round(bpm, 2),
        "duration_s": round(duration, 3),
        "beats": [round(b, 3) for b in beats],
        "downbeats": [round(b, 3) for b in downbeats],
        "energy_sections": _energy_sections(y, sr),
    }


def main() -> None:
    missing = []
    for track in TRACKS:
        audio = MUSIC_DIR / track.file
        if not audio.exists():
            missing.append(track.file)
            continue
        data = build_one(audio)
        out = MUSIC_DIR / f"{track.track_id}.beatmap.json"
        out.write_text(json.dumps(data, indent=2))
        print(
            f"{track.track_id}: bpm={data['bpm']}, "
            f"{len(data['downbeats'])} downbeats, {data['duration_s']}s -> {out.name}"
        )
    if missing:
        print(f"\nMissing audio files: {missing}. Run scripts/generate_music.py first.")


if __name__ == "__main__":
    main()
