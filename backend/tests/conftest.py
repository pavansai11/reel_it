"""Shared test fixtures: an isolated DB + storage and a tiny media set.

Env is set BEFORE app modules import so settings pick up the temp paths.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


@pytest.fixture(scope="session", autouse=True)
def _isolate_env(tmp_path_factory):
    root = tmp_path_factory.mktemp("reelmagic_test")
    os.environ["ENV_FILE"] = str(root / "nonexistent.env")  # force defaults
    os.environ["DATABASE_URL"] = f"sqlite:///{root}/test.db"
    os.environ["STORAGE_LOCAL_DIR"] = str(root / "storage")
    os.environ["STORAGE_BACKEND"] = "local"
    os.environ["RUN_JOBS_INLINE"] = "true"
    os.environ["SCORING_BACKEND"] = "heuristic"
    os.environ["ANTHROPIC_API_KEY"] = ""  # heuristic edit brain
    os.environ["MIN_DURATION_S"] = "8"  # keep test reels short/fast
    os.environ["TARGET_DURATION_S"] = "10"
    os.environ["MAX_DURATION_S"] = "14"
    yield root


def _textured(path: Path, w=640, h=480, seed=0, blur=False):
    rs = np.random.RandomState(seed)
    base = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        base[y, :] = [(seed * 30) % 255, int(255 * y / h), 200 - int(120 * y / h)]
    if not blur:
        base = np.clip(base.astype(int) + rs.randint(-18, 18, base.shape), 0, 255).astype(np.uint8)
    img = Image.fromarray(base)
    if blur:
        from PIL import ImageFilter

        img = img.filter(ImageFilter.GaussianBlur(9))
    img.save(path, quality=90)


@pytest.fixture(scope="session")
def sample_dir(_isolate_env) -> Path:
    d = _isolate_env / "media"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        _textured(d / f"photo_{i}.jpg", seed=i + 1)
    _textured(d / "blurry.jpg", seed=99, blur=True)
    # two near-duplicates
    _textured(d / "dup_a.jpg", seed=7)
    _textured(d / "dup_b.jpg", seed=7)
    # one short video
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=30:duration=2",
            "-pix_fmt", "yuv420p", str(d / "clip.mp4"),
        ],
        check=True,
    )
    return d


@pytest.fixture(scope="session", autouse=True)
def _ensure_music(_isolate_env):
    """Make sure bundled music (audio + beat maps) exists for edit/render tests.

    Beat maps are committed; the WAVs are regenerated deterministically if a
    fresh clone hasn't created them yet.
    """
    from app.config import MUSIC_DIR

    repo = Path(__file__).resolve().parent.parent
    if not list(MUSIC_DIR.glob("*.wav")):
        subprocess.run(["python", "scripts/generate_music.py"], cwd=repo, check=True)
    if not list(MUSIC_DIR.glob("*.beatmap.json")):
        subprocess.run(["python", "scripts/build_beatmaps.py"], cwd=repo, check=True)
