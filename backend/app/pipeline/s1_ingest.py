"""Stage 1 -- Ingest & pre-filter.

* Validate + probe every asset.
* Drop blurry photos (variance-of-Laplacian threshold).
* Remove near-duplicate photos (pHash clustering), keeping the sharpest of each
  burst so we don't spam the edit with 20 frames of the same moment.

Pure function: list[IngestInput] -> list[IngestResult]. The orchestrator maps
these onto Asset rows.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .media import ProbeResult, ffprobe, kind_for_path

log = logging.getLogger(__name__)

# Variance-of-Laplacian below this = too blurry to use. Tuned conservatively so
# we drop only obvious junk.
BLUR_THRESHOLD = 45.0
# pHash Hamming distance below this = "the same shot".
PHASH_DUP_DISTANCE = 6


@dataclass
class IngestInput:
    asset_id: str
    path: str  # local filesystem path (resolved via storage)
    kind: str | None = None  # photo|video, inferred if None


@dataclass
class IngestResult:
    asset_id: str
    kind: str
    kept: bool
    blur_score: float | None = None
    phash: str | None = None
    drop_reason: str | None = None
    probe: ProbeResult | None = None
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    fps: float | None = None


def _laplacian_variance(path: str) -> float:
    import cv2

    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    # Downscale large images so the metric is resolution-independent.
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest > 1024:
        scale = 1024.0 / longest
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def _phash(path: str) -> str | None:
    try:
        import imagehash
        from PIL import Image

        with Image.open(path) as im:
            return str(imagehash.phash(im))
    except Exception:
        return None


def _hamming(a: str, b: str) -> int:
    import imagehash

    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)


def ingest(
    inputs: list[IngestInput],
    blur_threshold: float = BLUR_THRESHOLD,
    dup_distance: int = PHASH_DUP_DISTANCE,
) -> list[IngestResult]:
    results: list[IngestResult] = []

    for item in inputs:
        kind = item.kind or kind_for_path(item.path)
        if kind is None:
            results.append(
                IngestResult(item.asset_id, "photo", kept=False, drop_reason="unsupported_type")
            )
            continue

        if kind == "video":
            try:
                probe = ffprobe(item.path)
            except Exception as e:  # corrupt/unreadable
                log.warning("ffprobe failed for %s: %s", item.path, e)
                results.append(
                    IngestResult(item.asset_id, "video", kept=False, drop_reason="unreadable")
                )
                continue
            results.append(
                IngestResult(
                    item.asset_id,
                    "video",
                    kept=probe.duration_s > 0.3,
                    drop_reason=None if probe.duration_s > 0.3 else "too_short",
                    probe=probe,
                    width=probe.width,
                    height=probe.height,
                    duration_s=probe.duration_s,
                    fps=probe.fps,
                )
            )
            continue

        # --- photo ---
        blur = _laplacian_variance(item.path)
        phash = _phash(item.path)
        if blur < blur_threshold:
            results.append(
                IngestResult(
                    item.asset_id,
                    "photo",
                    kept=False,
                    blur_score=blur,
                    phash=phash,
                    drop_reason="blurry",
                )
            )
        else:
            results.append(
                IngestResult(
                    item.asset_id, "photo", kept=True, blur_score=blur, phash=phash
                )
            )

    _dedup_photos(results, dup_distance)
    kept = sum(1 for r in results if r.kept)
    log.info("Ingest: %d inputs -> %d kept", len(inputs), kept)
    return results


def _dedup_photos(results: list[IngestResult], dup_distance: int) -> None:
    """Cluster near-duplicate photos; keep the sharpest per cluster."""
    photos = [
        r for r in results if r.kind == "photo" and r.kept and r.phash is not None
    ]
    clusters: list[list[IngestResult]] = []
    for r in photos:
        placed = False
        for cluster in clusters:
            # Single-linkage: join if close to ANY member (robust to a burst
            # drifting gradually across exposures).
            if any(_hamming(r.phash, m.phash) <= dup_distance for m in cluster):
                cluster.append(r)
                placed = True
                break
        if not placed:
            clusters.append([r])

    for cluster in clusters:
        if len(cluster) == 1:
            continue
        # Keep the sharpest (highest blur/Laplacian variance).
        cluster.sort(key=lambda r: r.blur_score or 0.0, reverse=True)
        for dup in cluster[1:]:
            dup.kept = False
            dup.drop_reason = "near_duplicate"
