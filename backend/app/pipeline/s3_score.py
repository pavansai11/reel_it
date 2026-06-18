"""Stage 3 -- Score & understand each moment.

Per moment we compute: aesthetic (0..1), smile (0..1), motion (0..1),
has_people/face_count, and zero-shot content tags.

Two interchangeable backends:
  * ``clip``      -- open_clip ViT for aesthetic + zero-shot tags (best quality).
  * ``heuristic`` -- pure OpenCV/numpy proxies (no heavy deps, always available).
``auto`` uses CLIP if importable, else heuristic. Face/smile uses MediaPipe when
present, else OpenCV Haar cascades. This keeps the whole pipeline runnable on a
laptop while staying upgradeable to GPU-quality scoring in prod.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from ..config import settings
from .media import sample_frames_bgr
from .schemas import CONTENT_TAGS

log = logging.getLogger(__name__)

# Drop moments below this aesthetic floor, but always keep at least N so the
# edit never starves.
AESTHETIC_FLOOR = 0.30
MIN_KEEP = 12
FRAMES_PER_MOMENT = 3


@dataclass
class ScoreInput:
    moment_id: str
    asset_id: str
    path: str
    kind: str  # photo | video
    start_s: float = 0.0
    end_s: float = 0.0


@dataclass
class ScoreResult:
    moment_id: str
    aesthetic_score: float = 0.0
    smile_score: float = 0.0
    motion_score: float = 0.0
    has_people: bool = False
    face_count: int = 0
    tags: list[str] = field(default_factory=list)
    kept: bool = True


# --------------------------------------------------------------------------
# Frame loading
# --------------------------------------------------------------------------
def _load_frames(item: ScoreInput) -> list[np.ndarray]:
    import cv2

    if item.kind == "photo":
        img = cv2.imread(item.path)
        return [img] if img is not None else []
    return sample_frames_bgr(item.path, item.start_s, item.end_s, FRAMES_PER_MOMENT)


# --------------------------------------------------------------------------
# Heuristic aesthetic + tags (no heavy deps)
# --------------------------------------------------------------------------
def _colorfulness(bgr: np.ndarray) -> float:
    """Hasler-Susstrunk colorfulness metric, normalized to ~0..1."""
    b, g, r = bgr[..., 0].astype(float), bgr[..., 1].astype(float), bgr[..., 2].astype(float)
    rg = r - g
    yb = 0.5 * (r + g) - b
    std = np.sqrt(rg.std() ** 2 + yb.std() ** 2)
    mean = np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    return float(np.clip((std + 0.3 * mean) / 110.0, 0, 1))


def _heuristic_aesthetic(bgr: np.ndarray) -> float:
    import cv2

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    longest = max(h, w)
    if longest > 1024:
        s = 1024.0 / longest
        gray = cv2.resize(gray, (int(w * s), int(h * s)))
        bgr_s = cv2.resize(bgr, (int(w * s), int(h * s)))
    else:
        bgr_s = bgr

    # Sharpness (variance of Laplacian), log-compressed.
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharp_n = float(np.clip(np.log1p(sharp) / np.log1p(1500.0), 0, 1))

    # Exposure: prefer mid brightness, penalize clipped blacks/whites.
    mean_b = gray.mean() / 255.0
    exposure = 1.0 - min(abs(mean_b - 0.5) / 0.5, 1.0)

    # Contrast.
    contrast = float(np.clip(gray.std() / 80.0, 0, 1))

    colorful = _colorfulness(bgr_s)

    score = 0.40 * sharp_n + 0.20 * exposure + 0.20 * contrast + 0.20 * colorful
    return float(np.clip(score, 0, 1))


def _heuristic_tags(bgr: np.ndarray) -> list[str]:
    """Crude colour/region scene cues. Replaced by CLIP zero-shot when present."""
    import cv2

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, w = bgr.shape[:2]
    top = hsv[: h // 3]
    bottom = hsv[2 * h // 3 :]
    full = hsv

    def frac(region, lo, hi):
        mask = cv2.inRange(region, np.array(lo), np.array(hi))
        return float(mask.mean() / 255.0)

    tags: list[str] = []
    brightness = full[..., 2].mean() / 255.0
    blue_top = frac(top, (90, 60, 60), (130, 255, 255))
    blue_full = frac(full, (90, 60, 40), (130, 255, 255))
    green = frac(full, (35, 40, 40), (85, 255, 255))
    warm = frac(top, (5, 80, 120), (25, 255, 255))

    if brightness < 0.28:
        tags.append("night")
    if blue_top > 0.18:
        tags.append("scenery")
    if warm > 0.20 and brightness > 0.3:
        tags.append("sunset")
    if blue_full > 0.25:
        tags.append("water")
    if green > 0.30:
        tags.append("nature")
    if not tags:
        tags.append("scenery")
    return tags[:3]


# --------------------------------------------------------------------------
# CLIP backend (optional)
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _load_clip():
    import open_clip
    import torch

    device = settings.scoring_device if settings.scoring_device == "cuda" else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    model.eval().to(device)
    tokenizer = open_clip.get_tokenizer("ViT-B-32")

    quality_pos = ["a beautiful, high quality, well-composed photo"]
    quality_neg = ["a blurry, poorly composed, low quality snapshot"]
    tag_prompts = [f"a photo of {t}" for t in CONTENT_TAGS]

    with torch.no_grad():
        q_tokens = tokenizer(quality_pos + quality_neg).to(device)
        q_feat = model.encode_text(q_tokens)
        q_feat /= q_feat.norm(dim=-1, keepdim=True)
        t_tokens = tokenizer(tag_prompts).to(device)
        t_feat = model.encode_text(t_tokens)
        t_feat /= t_feat.norm(dim=-1, keepdim=True)

    return model, preprocess, device, q_feat, t_feat


def _clip_score(bgr: np.ndarray):
    import cv2
    import torch
    from PIL import Image

    model, preprocess, device, q_feat, t_feat = _load_clip()
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    img = preprocess(Image.fromarray(rgb)).unsqueeze(0).to(device)
    with torch.no_grad():
        feat = model.encode_image(img)
        feat /= feat.norm(dim=-1, keepdim=True)
        q_sim = (100.0 * feat @ q_feat.T).softmax(dim=-1)[0]
        aesthetic = float(q_sim[0])
        t_sim = (feat @ t_feat.T)[0]
        topk = t_sim.topk(3).indices.tolist()
        thresh = float(t_sim.mean() + 0.5 * t_sim.std())
        tags = [CONTENT_TAGS[i] for i in topk if float(t_sim[i]) >= thresh][:3]
        if not tags:
            tags = [CONTENT_TAGS[topk[0]]]
    return aesthetic, tags


def _clip_available() -> bool:
    if settings.scoring_backend == "heuristic":
        return False
    try:
        import open_clip  # noqa: F401
        import torch  # noqa: F401

        return True
    except Exception:
        if settings.scoring_backend == "clip":
            log.warning("SCORING_BACKEND=clip but open_clip not installed; using heuristic")
        return False


# --------------------------------------------------------------------------
# Faces / smiles
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _haar():
    import cv2

    base = cv2.data.haarcascades
    return (
        cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml"),
        cv2.CascadeClassifier(base + "haarcascade_smile.xml"),
    )


def _faces_haar(bgr: np.ndarray) -> tuple[int, float]:
    import cv2

    face_cc, smile_cc = _haar()
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    faces = face_cc.detectMultiScale(gray, 1.2, 5, minSize=(40, 40))
    if len(faces) == 0:
        return 0, 0.0
    smiles = 0
    for (x, y, w, h) in faces:
        roi = gray[y : y + h, x : x + w]
        if len(smile_cc.detectMultiScale(roi, 1.7, 18)) > 0:
            smiles += 1
    smile_score = smiles / max(len(faces), 1)
    return int(len(faces)), float(smile_score)


def _faces(bgr: np.ndarray) -> tuple[int, float]:
    try:
        import mediapipe  # noqa: F401  (real path lives behind heavier wiring)
    except Exception:
        pass
    return _faces_haar(bgr)


# --------------------------------------------------------------------------
# Motion (video only)
# --------------------------------------------------------------------------
def _motion(frames: list[np.ndarray]) -> float:
    import cv2

    if len(frames) < 2:
        return 0.2  # single still frame from a clip -> assume calm
    diffs = []
    prev = cv2.cvtColor(cv2.resize(frames[0], (160, 90)), cv2.COLOR_BGR2GRAY)
    for f in frames[1:]:
        cur = cv2.cvtColor(cv2.resize(f, (160, 90)), cv2.COLOR_BGR2GRAY)
        diffs.append(float(np.abs(cur.astype(int) - prev.astype(int)).mean()))
        prev = cur
    return float(np.clip(np.mean(diffs) / 40.0, 0, 1))


# --------------------------------------------------------------------------
# Orchestration of one moment + the pool
# --------------------------------------------------------------------------
def _score_one(item: ScoreInput, use_clip: bool) -> ScoreResult:
    frames = _load_frames(item)
    if not frames:
        return ScoreResult(item.moment_id, kept=False)

    aesthetics, tag_votes, face_counts, smiles = [], [], [], []
    for fr in frames:
        if use_clip:
            try:
                aes, tags = _clip_score(fr)
            except Exception as e:
                log.warning("CLIP scoring failed (%s); heuristic for this frame", e)
                aes, tags = _heuristic_aesthetic(fr), _heuristic_tags(fr)
        else:
            aes, tags = _heuristic_aesthetic(fr), _heuristic_tags(fr)
        aesthetics.append(aes)
        tag_votes.extend(tags)
        fc, sm = _faces(fr)
        face_counts.append(fc)
        smiles.append(sm)

    # Aggregate tags by vote.
    tag_rank: dict[str, int] = {}
    for t in tag_votes:
        tag_rank[t] = tag_rank.get(t, 0) + 1
    tags = [t for t, _ in sorted(tag_rank.items(), key=lambda kv: kv[1], reverse=True)][:3]

    face_count = int(max(face_counts)) if face_counts else 0
    if face_count > 0 and "group" not in tags:
        tags = (["group"] if face_count >= 3 else ["selfie"]) + tags
        tags = tags[:3]

    return ScoreResult(
        moment_id=item.moment_id,
        aesthetic_score=float(np.mean(aesthetics)),
        smile_score=float(max(smiles)) if smiles else 0.0,
        motion_score=_motion(frames) if item.kind == "video" else 0.0,
        has_people=face_count > 0,
        face_count=face_count,
        tags=tags,
    )


def score_moments(inputs: list[ScoreInput]) -> list[ScoreResult]:
    use_clip = _clip_available()
    log.info("Scoring %d moments (backend=%s)", len(inputs), "clip" if use_clip else "heuristic")

    results = [_score_one(item, use_clip) for item in inputs]

    # Apply aesthetic floor, but never starve the edit: keep the top MIN_KEEP.
    survivors = [r for r in results if r.kept and r.aesthetic_score >= AESTHETIC_FLOOR]
    if len(survivors) < MIN_KEEP:
        ranked = sorted(
            [r for r in results if r.kept], key=lambda r: r.aesthetic_score, reverse=True
        )
        keep_ids = {r.moment_id for r in ranked[:MIN_KEEP]}
    else:
        keep_ids = {r.moment_id for r in survivors}

    for r in results:
        r.kept = r.kept and r.moment_id in keep_ids
    log.info("Scoring kept %d/%d moments", len(keep_ids), len(results))
    return results
