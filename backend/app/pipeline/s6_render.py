"""Stage 6 -- Render. The "hands".

Walk the EDL and build the final 1080x1920 H.264 MP4 with ffmpeg:
  * Photos  -> Ken Burns (zoompan), cover-cropped to frame.
  * Videos  -> trim to [start, start+dur], cover-crop, optional 1.5x speed.
  * Overlay text + corner watermark baked per segment.
  * Segments concatenated (hard cuts; crossfade = short fade-in), then the chosen
    music is laid underneath, trimmed to length with a fade-out, +faststart.

Each segment is encoded once (identical params) so the concat + audio-mux passes
can stream-copy the video -- cheap and fast (fractions of a cent on CPU).
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from .media import REEL_FPS, REEL_H, REEL_W, run_ffmpeg
from .schemas import EDL, BeatMap, EditDecision, Effect, Transition

log = logging.getLogger(__name__)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def _font() -> str | None:
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return None


@dataclass
class RenderInput:
    moment_id: str
    asset_path: str  # local path to the source photo/video
    kind: str  # photo | video
    source_start_s: float  # in-point within the source (video)


def render_reel(
    edl: EDL,
    moment_sources: dict[str, RenderInput],
    beatmap: BeatMap,
    out_path: str,
    watermark: bool = True,
) -> str:
    """Render the EDL to ``out_path``. Returns the path."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    font = _font()

    with tempfile.TemporaryDirectory(prefix="reelmagic_render_") as tmp:
        seg_paths: list[str] = []
        for dec in edl.ordered():
            src = moment_sources.get(dec.moment_id)
            if src is None:
                log.warning("No source for moment %s; skipping", dec.moment_id)
                continue
            seg = os.path.join(tmp, f"seg_{dec.order:03d}.mp4")
            try:
                _render_segment(dec, src, seg, font, watermark)
                seg_paths.append(seg)
            except Exception as e:
                log.exception("Segment %s failed (%s); skipping", dec.order, e)

        if not seg_paths:
            raise RuntimeError("No segments rendered; cannot build reel")

        silent = os.path.join(tmp, "silent.mp4")
        _concat(seg_paths, silent)

        total = edl.total_duration_s
        # Seek the music so its first downbeat aligns with reel t=0 (the edit
        # brain normalized the cut grid the same way).
        music_offset = beatmap.downbeats[0] if beatmap.downbeats else 0.0
        _mux_music(silent, beatmap.path, total, out_path, music_offset)

    log.info("Rendered reel -> %s (%d segments)", out_path, len(seg_paths))
    return out_path


# --------------------------------------------------------------------------
# Per-segment rendering
# --------------------------------------------------------------------------
def _overlay_filters(dec: EditDecision, font: str | None, watermark: bool) -> str:
    chain = []
    if dec.overlay_text and font:
        txt = _escape(dec.overlay_text)
        chain.append(
            f"drawtext=fontfile='{font}':text='{txt}':fontcolor=white:"
            f"fontsize=84:box=0:shadowcolor=black@0.55:shadowx=3:shadowy=3:"
            f"x=(w-text_w)/2:y=h*0.78:"
            f"alpha='if(lt(t,0.3),t/0.3,if(lt(t,{max(dec.duration_s-0.4,0.4):.2f}),1,"
            f"max(0,({dec.duration_s:.2f}-t)/0.4)))'"
        )
    if watermark and font:
        wm = _escape(settings.watermark_text)
        chain.append(
            f"drawtext=fontfile='{font}':text='{wm}':fontcolor=white@0.78:"
            f"fontsize=34:x=w-text_w-36:y=h-text_h-44:shadowcolor=black@0.4:"
            f"shadowx=2:shadowy=2"
        )
    return ",".join(chain)


def _fade_filter(dec: EditDecision) -> str:
    if dec.transition_in in (Transition.crossfade, Transition.whip):
        return f"fade=t=in:st=0:d=0.22"
    return ""


def _render_segment(
    dec: EditDecision,
    src: RenderInput,
    out: str,
    font: str | None,
    watermark: bool,
) -> None:
    dur = dec.duration_s
    overlay = _overlay_filters(dec, font, watermark)
    fade = _fade_filter(dec)
    cover = f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,crop={REEL_W}:{REEL_H},setsar=1"

    if src.kind == "photo":
        kb = _ken_burns(dec.effect, dur)
        vf_parts = [
            f"scale={int(REEL_W*1.25)}:{int(REEL_H*1.25)}:force_original_aspect_ratio=increase",
            f"crop={int(REEL_W*1.25)}:{int(REEL_H*1.25)}",
            kb,
            "setsar=1",
            f"fps={REEL_FPS}",
        ]
        vf = ",".join(p for p in (vf_parts + [fade, overlay]) if p)
        args = [
            "-loop", "1", "-t", f"{dur:.3f}", "-i", src.asset_path,
            "-vf", vf,
            "-frames:v", str(max(1, round(dur * REEL_FPS))),
            *_x264_args(),
            "-t", f"{dur:.3f}",
            out,
        ]
    else:
        speed = 1.5 if dec.effect == Effect.speed_1_5 else 1.0
        take = dur * speed
        pts = f",setpts=PTS/{speed}" if speed != 1.0 else ""
        vf = ",".join(
            p for p in (f"{cover},fps={REEL_FPS}{pts}", fade, overlay) if p
        )
        args = [
            "-ss", f"{src.source_start_s:.3f}", "-t", f"{take:.3f}",
            "-i", src.asset_path,
            "-an",
            "-vf", vf,
            *_x264_args(),
            "-t", f"{dur:.3f}",
            out,
        ]
    run_ffmpeg(args, desc=f"segment {dec.order}")


def _ken_burns(effect: Effect, dur: float) -> str:
    frames = max(1, round(dur * REEL_FPS))
    s = f"{REEL_W}x{REEL_H}"
    # Per-frame zoom rate to travel ~12% over the clip.
    rate = 0.12 / frames
    cx = "x='iw/2-(iw/zoom/2)'"
    cy = "y='ih/2-(ih/zoom/2)'"
    if effect == Effect.ken_burns_out:
        z = f"z='if(lte(zoom,1.0),1.12,max(1.0,zoom-{rate:.6f}))'"
        # start zoomed-in: prime zoom on first frame
        z = f"z='max(1.001,1.12-{rate:.6f}*on)'"
    elif effect == Effect.ken_burns_pan:
        z = "z='1.08'"
        cx = f"x='(iw-iw/zoom)*on/{frames}'"
    else:  # ken_burns_in (default for stills)
        z = f"z='min(1.12,1.0+{rate:.6f}*on)'"
    return f"zoompan={z}:d={frames}:{cx}:{cy}:s={s}:fps={REEL_FPS}"


def _x264_args() -> list[str]:
    return [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", str(REEL_FPS),
        "-g", str(REEL_FPS * 2),
    ]


# --------------------------------------------------------------------------
# Concat + audio mux
# --------------------------------------------------------------------------
def _concat(seg_paths: list[str], out: str) -> None:
    listfile = out + ".txt"
    with open(listfile, "w") as f:
        for p in seg_paths:
            f.write(f"file '{p}'\n")
    # All segments share codec/params -> stream copy (no re-encode).
    run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", out],
        desc="concat",
    )
    os.remove(listfile)


def _mux_music(
    video: str, music_path: str, total: float, out: str, music_offset: float = 0.0
) -> None:
    fade_start = max(total - 1.0, 0.1)
    has_music = music_path and os.path.exists(music_path)
    if not has_music:
        log.warning("Music file %s missing; rendering silent reel", music_path)
        run_ffmpeg(
            ["-i", video, "-c:v", "copy", "-movflags", "+faststart", "-t", f"{total:.3f}", out],
            desc="finalize (no music)",
        )
        return
    af = f"afade=t=in:st=0:d=0.3,afade=t=out:st={fade_start:.3f}:d=1.0"
    # -ss before -i seeks the music so its first downbeat sits at reel t=0.
    run_ffmpeg(
        [
            "-i", video,
            "-ss", f"{music_offset:.3f}", "-stream_loop", "-1", "-i", music_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-af", af,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-t", f"{total:.3f}",
            "-movflags", "+faststart",
            out,
        ],
        desc="mux music",
    )


def _escape(text: str) -> str:
    # Escape characters that are special inside ffmpeg drawtext.
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "’")
        .replace("%", "\\%")
    )
