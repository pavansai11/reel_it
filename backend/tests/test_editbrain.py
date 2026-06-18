"""Edit-brain tests: valid EDL + every cut on a downbeat (the on-beat guarantee)."""
from app.pipeline.s4_beatmap import load_beatmap_for_vibe
from app.pipeline.s5_editbrain import generate_edl
from app.pipeline.schemas import Moment, MomentKind


def _fake_moments(n=14):
    moments = []
    for i in range(n):
        kind = MomentKind.photo if i % 3 else MomentKind.video
        moments.append(
            Moment(
                id=f"m_{i}",
                asset_id=f"a_{i}",
                kind=kind,
                source_path=f"/x/{i}.jpg",
                start_s=0,
                end_s=4 if kind == MomentKind.video else 0,
                duration_s=4 if kind == MomentKind.video else 3,
                aesthetic_score=0.4 + (i % 5) * 0.1,
                smile_score=0.2 * (i % 2),
                motion_score=0.1 * (i % 6),
                has_people=i % 4 == 0,
                face_count=i % 4,
                tags=["scenery"] if i % 2 else ["beach"],
            )
        )
    return moments


def test_heuristic_edl_is_valid_and_on_beat():
    bm = load_beatmap_for_vibe("energetic", 0)
    result = generate_edl(_fake_moments(), bm, "energetic", seed=0)
    assert result.brain == "heuristic"
    edl = result.edl
    assert len(edl.decisions) >= 5

    grid = [round(d - bm.downbeats[0], 4) for d in bm.downbeats]
    for d in edl.decisions:
        off = min(abs(d.start_at_s - g) for g in grid)
        assert off < 0.05, f"cut at {d.start_at_s} not on a downbeat (off {off})"


def test_edl_respects_duration_bounds():
    bm = load_beatmap_for_vibe("cinematic", 0)
    edl = generate_edl(_fake_moments(), bm, "cinematic", seed=0).edl
    # Total should be in a sane reel range.
    assert 6 <= edl.total_duration_s <= 36


def test_rerolls_differ():
    bm0 = load_beatmap_for_vibe("energetic", 0)
    bm1 = load_beatmap_for_vibe("energetic", 1)
    order0 = [d.moment_id for d in generate_edl(_fake_moments(), bm0, "energetic", seed=0).edl.ordered()]
    order1 = [d.moment_id for d in generate_edl(_fake_moments(), bm1, "energetic", seed=1).edl.ordered()]
    assert order0 != order1


def test_photos_get_ken_burns():
    bm = load_beatmap_for_vibe("aesthetic", 0)
    edl = generate_edl(_fake_moments(), bm, "aesthetic", seed=0).edl
    # Every photo decision must have a non-"none" effect (stills feel alive).
    photo_ids = {m.id for m in _fake_moments() if m.kind == MomentKind.photo}
    for d in edl.decisions:
        if d.moment_id in photo_ids:
            assert d.effect.value.startswith("ken_burns")
