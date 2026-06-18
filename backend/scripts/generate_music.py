"""Generate the bundled royalty-free-style tracks (deterministic synthesis).

These are simple, clean, copyright-free synth beds with a clear four-on-the-floor
pulse and an intro -> build -> drop -> outro energy arc, so beat detection and
on-beat cutting are demonstrable out of the box and the dev pipeline is fully
deterministic.

To ship real licensed music instead: drop your audio files into assets/music/
using the `file` names in app/pipeline/tracks.py, then run build_beatmaps.py.

    python scripts/generate_music.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import MUSIC_DIR  # noqa: E402
from app.pipeline.tracks import TRACKS  # noqa: E402

SR = 44100
DURATION = 35.0

# Per-vibe overall loudness/energy character.
VIBE_GAIN = {"energetic": 1.0, "cinematic": 0.8, "aesthetic": 0.62}
# Minor pentatonic-ish roots (Hz) per vibe for a pleasant bed.
VIBE_ROOT = {"energetic": 110.0, "cinematic": 98.0, "aesthetic": 130.81}


def _energy_envelope(t: np.ndarray) -> np.ndarray:
    """Intro -> build -> drop (peak) -> sustain -> outro, in 0..1."""
    env = np.zeros_like(t)
    d = DURATION
    for i, x in enumerate(t):
        if x < 0.12 * d:  # intro
            env[i] = 0.20 + 0.20 * (x / (0.12 * d))
        elif x < 0.34 * d:  # build
            env[i] = 0.40 + 0.35 * ((x - 0.12 * d) / (0.22 * d))
        elif x < 0.66 * d:  # DROP (peak)
            env[i] = 1.0
        elif x < 0.86 * d:  # sustain
            env[i] = 0.70
        else:  # outro
            env[i] = 0.70 - 0.50 * ((x - 0.86 * d) / (0.14 * d))
    return np.clip(env, 0, 1)


def _kick(n: int, beat_samples: list[int]) -> np.ndarray:
    out = np.zeros(n)
    dur = int(0.14 * SR)
    idx = np.arange(dur)
    # Pitch-swept sine 110->45 Hz with fast decay = punchy kick + clean onset.
    freq = np.linspace(110, 45, dur)
    phase = np.cumsum(2 * np.pi * freq / SR)
    body = np.sin(phase) * np.exp(-idx / (0.05 * SR))
    click = (np.random.RandomState(0).randn(dur) * np.exp(-idx / (0.002 * SR))) * 0.3
    sample = body + click
    for b in beat_samples:
        if b + dur <= n:
            out[b : b + dur] += sample
    return out


def _hats(n: int, eighth_samples: list[int], env: np.ndarray) -> np.ndarray:
    out = np.zeros(n)
    dur = int(0.04 * SR)
    idx = np.arange(dur)
    rs = np.random.RandomState(7)
    for j, s in enumerate(eighth_samples):
        if s + dur > n:
            continue
        if env[s] < 0.55:  # hats only in busier sections
            continue
        gain = 0.12 if j % 2 == 0 else 0.20  # accent offbeats
        out[s : s + dur] += rs.randn(dur) * np.exp(-idx / (0.01 * SR)) * gain
    return out


def _bass_pad(t: np.ndarray, root: float, env: np.ndarray) -> np.ndarray:
    # Simple 4-chord loop (root, b3, 4, 5 scale degrees) over the track.
    degrees = [1.0, 6 / 5, 4 / 3, 3 / 2]
    seg = len(t) // len(degrees)
    bass = np.zeros_like(t)
    pad = np.zeros_like(t)
    for i, deg in enumerate(degrees):
        s, e = i * seg, (i + 1) * seg if i < len(degrees) - 1 else len(t)
        f = root * deg
        tt = t[s:e]
        # Bass: root + slight saw shimmer.
        bass[s:e] = 0.5 * np.sin(2 * np.pi * f * tt) + 0.15 * np.sin(2 * np.pi * 2 * f * tt)
        # Pad: triad harmonics, soft.
        pad[s:e] = (
            0.2 * np.sin(2 * np.pi * f * 2 * tt)
            + 0.15 * np.sin(2 * np.pi * f * 2 * 5 / 4 * tt)
            + 0.12 * np.sin(2 * np.pi * f * 3 * tt)
        )
    return bass * (0.4 + 0.6 * env) + pad * env


def synth_track(bpm: float, vibe: str, seed: int) -> np.ndarray:
    np.random.seed(seed)
    n = int(DURATION * SR)
    t = np.linspace(0, DURATION, n, endpoint=False)
    env = _energy_envelope(t)

    spb = 60.0 / bpm
    beat_times = np.arange(0, DURATION, spb)
    beat_samples = [int(x * SR) for x in beat_times]
    eighth_times = np.arange(0, DURATION, spb / 2)
    eighth_samples = [int(x * SR) for x in eighth_times]

    mix = (
        0.9 * _kick(n, beat_samples)
        + 0.5 * _hats(n, eighth_samples, env)
        + 0.6 * _bass_pad(t, VIBE_ROOT[vibe], env)
    )
    mix *= VIBE_GAIN[vibe]
    # Soft limiter + normalize.
    mix = np.tanh(1.2 * mix)
    mix /= np.max(np.abs(mix)) + 1e-9
    mix *= 0.92
    return mix.astype(np.float32)


def main() -> None:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    for i, track in enumerate(TRACKS):
        audio = synth_track(track.bpm, track.vibe, seed=1000 + i)
        out = MUSIC_DIR / track.file
        sf.write(str(out), audio, SR)
        print(f"wrote {out}  ({track.title}, {track.bpm} bpm, {track.vibe})")
    print(f"\n{len(TRACKS)} tracks written to {MUSIC_DIR}")
    print("Next: python scripts/build_beatmaps.py")


if __name__ == "__main__":
    main()
