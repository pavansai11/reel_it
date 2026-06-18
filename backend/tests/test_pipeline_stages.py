"""Stage-level tests for the pure pipeline functions."""
from pathlib import Path

from app.pipeline.media import kind_for_path
from app.pipeline.s1_ingest import IngestInput, ingest
from app.pipeline.s2_shots import ShotInput, detect_moments
from app.pipeline.s3_score import ScoreInput, score_moments


def _collect(sample_dir: Path):
    items = []
    for i, p in enumerate(sorted(sample_dir.iterdir())):
        k = kind_for_path(str(p))
        if k:
            items.append((f"a_{i}", str(p), k))
    return items


def test_ingest_drops_blurry_and_dupes(sample_dir):
    inputs = [IngestInput(aid, path, kind) for aid, path, kind in _collect(sample_dir)]
    results = ingest(inputs)
    by_id = {r.asset_id: r for r in results}
    # the deliberately blurry file should be dropped
    blurry = next(r for r in results if "blurry" in dict(_name(sample_dir)).get(r.asset_id, ""))
    assert not blurry.kept and blurry.drop_reason == "blurry"
    # exactly one of the dup pair survives
    dup_ids = [aid for aid, name in _name(sample_dir) if name.startswith("dup_")]
    kept_dupes = [by_id[i].kept for i in dup_ids]
    assert sum(kept_dupes) == 1


def _name(sample_dir):
    return [(f"a_{i}", p.name) for i, p in enumerate(sorted(sample_dir.iterdir()))]


def test_shots_split_and_photos_passthrough(sample_dir):
    items = _collect(sample_dir)
    ing = {r.asset_id: r for r in ingest([IngestInput(a, p, k) for a, p, k in items])}
    paths = {a: p for a, p, _ in items}
    shot_inputs = [
        ShotInput(r.asset_id, paths[r.asset_id], r.kind, r.duration_s or 0.0)
        for r in ing.values()
        if r.kept
    ]
    moments = detect_moments(shot_inputs)
    assert len(moments) >= 1
    assert all(m.duration_s > 0 for m in moments)


def test_scoring_produces_bounded_scores(sample_dir):
    items = _collect(sample_dir)
    ing = {r.asset_id: r for r in ingest([IngestInput(a, p, k) for a, p, k in items])}
    paths = {a: p for a, p, _ in items}
    shot_inputs = [
        ShotInput(r.asset_id, paths[r.asset_id], r.kind, r.duration_s or 0.0)
        for r in ing.values()
        if r.kept
    ]
    moments = detect_moments(shot_inputs)
    score_inputs = [
        ScoreInput(f"m_{i}", m.asset_id, paths[m.asset_id], m.kind, m.start_s, m.end_s)
        for i, m in enumerate(moments)
    ]
    scores = score_moments(score_inputs)
    assert scores
    for s in scores:
        assert 0.0 <= s.aesthetic_score <= 1.0
        assert 0.0 <= s.motion_score <= 1.0
        assert isinstance(s.tags, list)
