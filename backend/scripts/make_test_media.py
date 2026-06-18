"""Generate a synthetic 'messy trip dump' to exercise the pipeline locally.

Creates a folder with: varied scenic-ish photos, a near-duplicate burst, a couple
of blurry shots, and a few short videos (one multi-shot) -- so ingest dedup/blur
filtering, shot detection, scoring, the edit brain and the renderer all get
exercised end-to-end. Not a substitute for real trip footage (spec §10), just a
smoke-test fixture.

    python scripts/make_test_media.py ./sample_trip
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _gradient(w, h, top, bottom):
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        f = y / h
        arr[y, :] = [int(top[i] * (1 - f) + bottom[i] * f) for i in range(3)]
    return Image.fromarray(arr)


def _add_texture(img, amount=14, seed=0):
    """Add fine grain so the shot has realistic high-frequency detail (a smooth
    gradient has near-zero Laplacian variance and would read as 'blurry')."""
    rs = np.random.RandomState(seed)
    arr = np.asarray(img).astype(np.int16)
    noise = rs.randint(-amount, amount + 1, arr.shape, dtype=np.int16)
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))


def scenic(w, h, top, bottom, sun=None, hills=False, stars=False, seed=0):
    img = _gradient(w, h, top, bottom)
    d = ImageDraw.Draw(img)
    if sun:
        cx, cy, r = sun
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 240, 200))
    if hills:
        d.polygon([(0, h), (w * 0.3, h * 0.6), (w * 0.6, h * 0.8), (w, h * 0.55), (w, h)], fill=(40, 70, 50))
        # tree silhouettes -> sharp edges
        for x in (int(w * 0.2), int(w * 0.5), int(w * 0.75)):
            d.line([(x, h), (x, h * 0.62)], fill=(20, 40, 30), width=4)
    if stars:
        rs = np.random.RandomState(seed + 99)
        for _ in range(180):
            x, y = rs.randint(0, w), rs.randint(0, int(h * 0.6))
            d.point((x, y), fill=(255, 255, 230))
    # foreground detail line (horizon/rocks) for crisp edges
    d.line([(0, int(h * 0.7)), (w, int(h * 0.72))], fill=(255, 255, 255), width=2)
    return _add_texture(img, seed=seed)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "./sample_trip")
    out.mkdir(parents=True, exist_ok=True)
    W, H = 1280, 960

    photos = {
        "01_beach.jpg": scenic(W, H, (120, 190, 255), (230, 220, 180), seed=1),
        "02_sunset.jpg": scenic(W, H, (255, 150, 60), (90, 40, 80), sun=(900, 350, 120), seed=2),
        "03_mountains.jpg": scenic(W, H, (150, 200, 255), (60, 90, 70), hills=True, seed=3),
        "04_city_night.jpg": scenic(W, H, (15, 15, 40), (40, 40, 70), stars=True, seed=4),
        "05_nature.jpg": scenic(W, H, (90, 230, 110), (30, 130, 50), seed=5),
        "06_water.jpg": scenic(W, H, (60, 160, 210), (20, 80, 140), seed=6),
        "07_scenery.jpg": scenic(W, H, (255, 200, 120), (120, 160, 90), sun=(300, 250, 90), seed=7),
    }
    for name, img in photos.items():
        img.save(out / name, quality=90)

    # A 'group selfie' burst: 3 near-identical frames (like a phone burst).
    # pHash should cluster them and keep only the sharpest.
    burst = scenic(W, H, (200, 180, 160), (120, 100, 90), seed=20)
    bd = ImageDraw.Draw(burst)
    for cx in (480, 660, 840):  # three 'people'
        bd.ellipse([cx - 60, 360, cx + 60, 520], fill=(180, 150, 130))  # heads
        bd.rectangle([cx - 80, 520, cx + 80, 760], fill=(70, 90, 140))  # bodies
    for i, q in enumerate((92, 88, 95)):
        burst.save(out / f"08_burst_{i}.jpg", quality=q)

    # Two blurry shots -> blur filter should drop them.
    photos["02_sunset.jpg"].filter(ImageFilter.GaussianBlur(8)).save(out / "09_blurry_a.jpg")
    photos["05_nature.jpg"].filter(ImageFilter.GaussianBlur(10)).save(out / "10_blurry_b.jpg")

    # Videos via ffmpeg lavfi. One is a 2-shot concat to test scene detection.
    def ff(args):
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)

    ff(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=4", "-pix_fmt", "yuv420p", str(out / "vid_action.mp4")])
    ff(["-f", "lavfi", "-i", "color=c=teal:size=1280x720:rate=30:duration=3,format=yuv420p", str(out / "vid_calm.mp4")])
    # Multi-shot: concat two visually different clips.
    a = out / "_a.mp4"
    b = out / "_b.mp4"
    ff(["-f", "lavfi", "-i", "smptebars=size=1280x720:rate=30:duration=2.5", "-pix_fmt", "yuv420p", str(a)])
    ff(["-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=2.5", "-pix_fmt", "yuv420p", str(b)])
    lst = out / "_list.txt"
    lst.write_text(f"file '{a.name}'\nfile '{b.name}'\n")
    ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out / "vid_multishot.mp4")])
    for p in (a, b, lst):
        p.unlink()

    files = sorted(p.name for p in out.iterdir())
    print(f"Wrote {len(files)} files to {out}:")
    for f in files:
        print(" ", f)


if __name__ == "__main__":
    main()
