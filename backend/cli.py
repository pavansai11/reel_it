"""Pipeline CLI -- run/inspect each stage in isolation, or the whole thing.

Stages are pure functions, so this drives them directly on a folder of media
(no DB, no web app). Used for the phase acceptance checks in the spec.

    python cli.py all     ./my_trip --vibe energetic --out reel.mp4
    python cli.py ingest  ./my_trip
    python cli.py shots   ./my_trip
    python cli.py score   ./my_trip
    python cli.py beatmap --vibe cinematic
    python cli.py editbrain ./my_trip --vibe energetic
    python cli.py render  ./my_trip --vibe energetic --out reel.mp4
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.pipeline.media import kind_for_path
from app.pipeline.s1_ingest import IngestInput, ingest
from app.pipeline.s2_shots import ShotInput, detect_moments
from app.pipeline.s3_score import ScoreInput, score_moments
from app.pipeline.s4_beatmap import load_beatmap_for_vibe
from app.pipeline.s5_editbrain import generate_edl
from app.pipeline.s6_render import RenderInput, render_reel
from app.pipeline.schemas import Moment, MomentKind


def _collect(folder: str) -> list[tuple[str, str, str]]:
    """Return [(asset_id, path, kind)] for supported media in a folder."""
    out = []
    for i, p in enumerate(sorted(Path(folder).rglob("*"))):
        if not p.is_file():
            continue
        kind = kind_for_path(str(p))
        if kind:
            out.append((f"a_{i}", str(p), kind))
    return out


def _run_ingest(folder: str):
    inputs = [IngestInput(aid, path, kind) for aid, path, kind in _collect(folder)]
    results = ingest(inputs)
    return results


def _run_shots(folder: str):
    ing = {r.asset_id: r for r in _run_ingest(folder)}
    paths = {aid: path for aid, path, _ in _collect(folder)}
    shot_inputs = [
        ShotInput(r.asset_id, paths[r.asset_id], r.kind, r.duration_s or 0.0)
        for r in ing.values()
        if r.kept
    ]
    return detect_moments(shot_inputs), paths


def _run_score(folder: str):
    specs, paths = _run_shots(folder)
    moment_ids = [f"m_{i}" for i in range(len(specs))]
    score_inputs = [
        ScoreInput(mid, sp.asset_id, paths[sp.asset_id], sp.kind, sp.start_s, sp.end_s)
        for mid, sp in zip(moment_ids, specs)
    ]
    scores = score_moments(score_inputs)
    return specs, scores, paths, moment_ids


def _to_moments(specs, scores, paths, moment_ids) -> list[Moment]:
    score_by_id = {s.moment_id: s for s in scores}
    moments = []
    for mid, sp in zip(moment_ids, specs):
        s = score_by_id[mid]
        if not s.kept:
            continue
        moments.append(
            Moment(
                id=mid,
                asset_id=sp.asset_id,
                kind=MomentKind(sp.kind),
                source_path=paths[sp.asset_id],
                start_s=sp.start_s,
                end_s=sp.end_s,
                duration_s=sp.duration_s,
                aesthetic_score=s.aesthetic_score,
                smile_score=s.smile_score,
                motion_score=s.motion_score,
                has_people=s.has_people,
                face_count=s.face_count,
                tags=s.tags,
            )
        )
    return moments


def main() -> int:
    ap = argparse.ArgumentParser(description="ReelMagic pipeline CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ingest", "shots", "score", "editbrain", "render", "all"):
        sp = sub.add_parser(name)
        if name != "beatmap":
            sp.add_argument("folder")
        sp.add_argument("--vibe", default="energetic")
        sp.add_argument("--out", default="reel.mp4")
        sp.add_argument("--seed", type=int, default=0)
    bm = sub.add_parser("beatmap")
    bm.add_argument("--vibe", default="energetic")
    bm.add_argument("--seed", type=int, default=0)

    args = ap.parse_args()

    if args.cmd == "ingest":
        results = _run_ingest(args.folder)
        print(json.dumps([{k: v for k, v in asdict(r).items() if k != "probe"} for r in results], indent=2))

    elif args.cmd == "shots":
        specs, _ = _run_shots(args.folder)
        print(json.dumps([asdict(s) for s in specs], indent=2))

    elif args.cmd == "score":
        specs, scores, *_ = _run_score(args.folder)
        print(json.dumps([asdict(s) for s in scores], indent=2))

    elif args.cmd == "beatmap":
        bm = load_beatmap_for_vibe(args.vibe, args.seed)
        print(bm.model_dump_json(indent=2))

    elif args.cmd == "editbrain":
        specs, scores, paths, mids = _run_score(args.folder)
        moments = _to_moments(specs, scores, paths, mids)
        bm = load_beatmap_for_vibe(args.vibe, args.seed)
        edit = generate_edl(moments, bm, args.vibe, seed=args.seed)
        print(f"# brain={edit.brain} tokens={edit.input_tokens}/{edit.output_tokens}", file=sys.stderr)
        print(edit.edl.model_dump_json(indent=2))

    elif args.cmd in ("render", "all"):
        specs, scores, paths, mids = _run_score(args.folder)
        moments = _to_moments(specs, scores, paths, mids)
        bm = load_beatmap_for_vibe(args.vibe, args.seed)
        edit = generate_edl(moments, bm, args.vibe, seed=args.seed)
        print(f"# brain={edit.brain}, {len(edit.edl.decisions)} decisions, {edit.edl.total_duration_s}s", file=sys.stderr)
        sources = {
            m.id: RenderInput(m.id, m.source_path, m.kind.value, m.start_s) for m in moments
        }
        out = render_reel(edit.edl, sources, bm, args.out, watermark=True)
        print(out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
