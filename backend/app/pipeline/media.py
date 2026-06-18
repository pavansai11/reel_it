"""Thin, dependency-light wrappers around ffmpeg/ffprobe and frame extraction.

Kept separate so every stage uses the same probing + sampling logic, and so the
render path can be exercised without the heavy ML stack installed.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".gif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp", ".hevc"}

REEL_W = 1080
REEL_H = 1920
REEL_FPS = 30


def kind_for_path(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    return None


@dataclass
class ProbeResult:
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool


def ffprobe(path: str) -> ProbeResult:
    """Probe a video/audio file for duration, resolution and fps."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    streams = data.get("streams", [])
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    duration = float(data.get("format", {}).get("duration", 0) or 0)
    width = int(vstream.get("width", 0)) if vstream else 0
    height = int(vstream.get("height", 0)) if vstream else 0

    fps = 0.0
    if vstream:
        rate = vstream.get("avg_frame_rate") or vstream.get("r_frame_rate") or "0/0"
        try:
            num, den = rate.split("/")
            fps = float(num) / float(den) if float(den) else 0.0
        except (ValueError, ZeroDivisionError):
            fps = 0.0
        if not duration:
            duration = float(vstream.get("duration", 0) or 0)
    return ProbeResult(duration, width, height, fps, has_audio)


def extract_frame(video_path: str, t: float, out_path: str) -> str:
    """Grab a single frame at time ``t`` seconds as a JPEG."""
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(t, 0):.3f}",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "3",
        out_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_path


def sample_frames_bgr(
    video_path: str, start_s: float, end_s: float, n: int = 3
) -> list[np.ndarray]:
    """Return up to ``n`` evenly spaced frames as BGR numpy arrays (OpenCV)."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    frames: list[np.ndarray] = []
    span = max(end_s - start_s, 0.0)
    # Sample at the interior of the shot, skipping hard cut edges.
    for i in range(n):
        frac = (i + 1) / (n + 1)
        t = start_s + frac * span if span > 0 else start_s
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(frame)
    cap.release()
    return frames


def run_ffmpeg(args: list[str], desc: str = "") -> None:
    """Run an ffmpeg command, raising a readable error on failure."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    log.debug("ffmpeg %s: %s", desc, " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed ({desc}): {proc.stderr.strip()[-1500:]}"
        )
