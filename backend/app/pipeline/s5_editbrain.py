"""Stage 5 -- The edit brain. ⭐ THE MOAT.

Turns a pool of scored moments + a beat map into an Edit Decision List: which
moments, in what order, with what pacing, effects and overlays.

Design:
  * Claude (forced structured tool output) proposes selection/order/effects/text,
    validated against the EDL schema with one retry on invalid JSON.
  * A deterministic heuristic brain is used when no API key is configured (so the
    whole product runs with zero spend) and as a fallback if the API errors.
  * EITHER way, the result is snapped to the downbeat grid so every cut lands on
    a beat -- we never trust the model for exact timing.

Returns the EDL plus metadata (token usage, brain used) for the flywheel/cost
ledger.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass

from ..config import settings
from .schemas import EDL, BeatMap, EditDecision, Effect, Moment, Transition

log = logging.getLogger(__name__)

# Pacing per energy level: (min_dur, max_dur) seconds.
PACE_HIGH = (0.7, 1.3)
PACE_MID = (1.2, 2.2)
PACE_CALM = (2.0, 3.2)

ESTABLISHING_TAGS = {
    "scenery",
    "beach",
    "mountains",
    "city",
    "nature",
    "water",
    "sunset",
}


@dataclass
class EditResult:
    edl: EDL
    brain: str  # "claude" | "heuristic"
    input_tokens: int = 0
    output_tokens: int = 0


SYSTEM_PROMPT = """\
You are a world-class short-form video editor specializing in travel and
friends-trip reels for Instagram. You receive a pool of candidate moments
(photos and video shots) with quality scores and tags, plus a music beat map.

Produce an Edit Decision List that:
- Selects the strongest ~10-16 moments for a {duration}s reel.
- Opens with a strong establishing/scenery shot to set place.
- Builds energy toward the biggest musical drop (the peak), then winds down.
- Places every cut on a downbeat from the beat map.
- Matches energetic/action moments to high-energy music sections, and calm
  moments to calm sections.
- Gives photos a ken_burns effect so stills feel alive.
- Varies shot length: faster cuts in high-energy sections, longer in calm ones.
- Avoids putting near-identical shots back to back.
- Adds short, tasteful overlay_text only where it helps (or null).

Return ONLY the EDL via the submit_edl tool. Prioritize emotional flow and
rhythm over showing every clip.\
"""


# --------------------------------------------------------------------------
# Public entrypoint
# --------------------------------------------------------------------------
def generate_edl(
    moments: list[Moment],
    beatmap: BeatMap,
    vibe: str,
    target_s: float | None = None,
    seed: int = 0,
) -> EditResult:
    target = target_s or settings.target_duration_s
    pool = [m for m in moments if m.duration_s > 0 or m.kind.value == "photo"]
    if not pool:
        raise ValueError("Edit brain received an empty moment pool")

    if settings.anthropic_api_key:
        try:
            return _claude_edl(pool, beatmap, vibe, target, seed)
        except Exception as e:
            log.exception("Claude edit brain failed (%s); falling back to heuristic", e)

    edl = _heuristic_edl(pool, beatmap, vibe, target, seed)
    return EditResult(edl=edl, brain="heuristic")


# --------------------------------------------------------------------------
# Claude brain
# --------------------------------------------------------------------------
def _build_user_prompt(
    moments: list[Moment], beatmap: BeatMap, vibe: str, target: float
) -> str:
    payload = {
        "vibe": vibe,
        "target_duration_s": target,
        "track_id": beatmap.track_id,
        "music": {
            "bpm": round(beatmap.bpm, 1),
            "duration_s": round(beatmap.duration_s, 1),
            "downbeats": beatmap.downbeats_for_llm(),
            "energy_sections": [
                {"start": round(s.start, 1), "end": round(s.end, 1), "level": round(s.level, 2)}
                for s in beatmap.energy_sections
            ],
        },
        "moments": [m.for_llm() for m in moments],
    }
    return (
        "Here is the candidate moment pool and the music beat map. Build the reel.\n\n"
        f"```json\n{json.dumps(payload, indent=2)}\n```\n\n"
        "Use only moment ids that appear in the pool. order must be 0-based and "
        "contiguous. cut_on_beat_index indexes into music.downbeats. "
        "Submit via the submit_edl tool."
    )


def _claude_edl(
    moments: list[Moment], beatmap: BeatMap, vibe: str, target: float, seed: int
) -> EditResult:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    tool = {
        "name": "submit_edl",
        "description": "Submit the finished Edit Decision List for the reel.",
        "input_schema": EDL.model_json_schema(),
    }
    system = SYSTEM_PROMPT.format(duration=int(target))
    user = _build_user_prompt(moments, beatmap, vibe, target)
    if seed:
        user += f"\n\nThis is re-roll #{seed}: produce a meaningfully different cut."

    valid_ids = {m.id for m in moments}
    messages = [{"role": "user", "content": user}]

    last_err = None
    in_tok = out_tok = 0
    for attempt in range(2):  # original + one retry on invalid JSON
        resp = client.messages.create(
            model=settings.edit_brain_model,
            max_tokens=settings.edit_brain_max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": "submit_edl"},
            messages=messages,
        )
        in_tok += resp.usage.input_tokens
        out_tok += resp.usage.output_tokens

        tool_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "tool_use"), None
        )
        if tool_block is None:
            last_err = "model did not call submit_edl"
        else:
            try:
                edl = EDL.model_validate(tool_block.input)
                _coerce_valid_ids(edl, valid_ids)
                edl = _snap_to_beatgrid(edl, moments, beatmap, target)
                log.info("Claude EDL: %d decisions, %.1fs", len(edl.decisions), edl.total_duration_s)
                return EditResult(edl, "claude", in_tok, out_tok)
            except Exception as e:  # validation / id errors
                last_err = str(e)

        # Retry once with the error appended.
        messages.append({"role": "assistant", "content": resp.content})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"The submission was invalid: {last_err}. "
                    "Fix it and resubmit via submit_edl. Use only valid moment ids."
                ),
            }
        )

    raise RuntimeError(f"Claude failed to produce a valid EDL: {last_err}")


def _coerce_valid_ids(edl: EDL, valid_ids: set[str]) -> None:
    edl.decisions = [d for d in edl.decisions if d.moment_id in valid_ids]
    if not edl.decisions:
        raise ValueError("no valid moment ids in EDL")


# --------------------------------------------------------------------------
# Heuristic brain (deterministic, zero-cost)
# --------------------------------------------------------------------------
def _selection_score(m: Moment) -> float:
    return (
        0.55 * m.aesthetic_score
        + 0.25 * m.smile_score
        + 0.20 * (1.0 if m.has_people else 0.0)
    )


def _is_establishing(m: Moment) -> bool:
    return (
        m.face_count == 0
        and m.motion_score < 0.45
        and bool(set(m.tags) & ESTABLISHING_TAGS)
    )


def _heuristic_edl(
    moments: list[Moment], beatmap: BeatMap, vibe: str, target: float, seed: int
) -> EDL:
    rng = random.Random(f"{beatmap.track_id}:{seed}")

    # Roughly how many moments fit: target / average shot length.
    avg_shot = 1.8 if vibe == "energetic" else (2.4 if vibe == "cinematic" else 2.8)
    want = max(6, min(16, int(round(target / avg_shot)) + 1))

    # Seed 0 is deterministic; re-rolls add bounded jitter so selection + order
    # genuinely change while staying high-quality.
    jitter = {m.id: (rng.uniform(-0.12, 0.12) if seed else 0.0) for m in moments}
    ranked = sorted(
        moments, key=lambda m: _selection_score(m) + jitter[m.id], reverse=True
    )
    chosen = ranked[:want]

    # Opening: best establishing shot; re-rolls rotate to the next-best opener.
    establishers = sorted(
        (m for m in chosen if _is_establishing(m)),
        key=lambda m: m.aesthetic_score,
        reverse=True,
    )
    if establishers:
        opener = establishers[min(seed, len(establishers) - 1)]
    else:
        opener = max(chosen, key=lambda m: m.aesthetic_score)
    rest = [m for m in chosen if m.id != opener.id]

    # Closing: a calm, pretty wind-down (low motion, decent aesthetic).
    closer = min(rest, key=lambda m: (m.motion_score, -m.aesthetic_score)) if rest else None
    middle = [m for m in rest if closer is None or m.id != closer.id]

    # Middle ordered to build energy toward the musical peak, then ease off.
    peak_t = _peak_time(beatmap, target)
    middle_sorted = sorted(middle, key=lambda m: (m.motion_score, m.smile_score))
    # Arrange as a rise-then-fall around the peak.
    sequence = [opener] + _rise_fall(middle_sorted) + ([closer] if closer else [])
    sequence = _avoid_adjacent_dupes(sequence)

    decisions: list[EditDecision] = []
    for i, m in enumerate(sequence):
        decisions.append(
            EditDecision(
                moment_id=m.id,
                order=i,
                start_at_s=0.0,  # set by snap
                duration_s=2.0,  # desired pacing; refined by snap
                effect=_default_effect(m),
                transition_in=Transition.hard_cut,
                overlay_text="DAY 1" if i == 0 and vibe != "aesthetic" else None,
                reason=("establishing shot" if i == 0 else "energy build"),
            )
        )

    edl = EDL(track_id=beatmap.track_id, total_duration_s=target, decisions=decisions)
    return _snap_to_beatgrid(edl, moments, beatmap, target)


def _rise_fall(items: list[Moment]) -> list[Moment]:
    """Place lowest energy at the ends, highest in the middle (rise then fall)."""
    out: list[Moment | None] = [None] * len(items)
    lo, hi = 0, len(items) - 1
    for idx, m in enumerate(items):  # items sorted ascending by energy
        if idx % 2 == 0:
            out[lo] = m
            lo += 1
        else:
            out[hi] = m
            hi -= 1
    return [m for m in out if m is not None]


def _avoid_adjacent_dupes(seq: list[Moment]) -> list[Moment]:
    out: list[Moment] = []
    for m in seq:
        if out and out[-1].id == m.id:
            continue
        if (
            len(out) >= 1
            and out[-1].tags
            and m.tags
            and out[-1].tags == m.tags
            and out[-1].kind == m.kind
        ):
            # try to swap with a later, different moment is overkill here; just keep
            pass
        out.append(m)
    return out


def _default_effect(m: Moment) -> Effect:
    if m.kind.value == "photo":
        return Effect.ken_burns_in
    if m.motion_score > 0.6:
        return Effect.speed_1_5
    return Effect.none


# --------------------------------------------------------------------------
# Beat-grid snapping (shared by both brains)
# --------------------------------------------------------------------------
def _peak_time(beatmap: BeatMap, target: float) -> float:
    if beatmap.energy_sections:
        peak = max(beatmap.energy_sections, key=lambda s: s.level)
        return min((peak.start + peak.end) / 2.0, target)
    return target * 0.6


def _energy_at(beatmap: BeatMap, t: float) -> float:
    for s in beatmap.energy_sections:
        if s.start <= t < s.end:
            return s.level
    return 0.5


def _pace_for(level: float) -> tuple[float, float]:
    if level >= 0.66:
        return PACE_HIGH
    if level >= 0.4:
        return PACE_MID
    return PACE_CALM


def _snap_to_beatgrid(
    edl: EDL, moments: list[Moment], beatmap: BeatMap, target: float
) -> EDL:
    """Lay decisions on the downbeat grid so every cut lands on a beat.

    The model's ``duration_s`` is treated as desired pacing; we pick the nearest
    downbeat that honors it (clamped by the section's energy pace) and clamp the
    reel to [min, max] duration. Also trims durations to fit the underlying clip.
    """
    by_id = {m.id: m for m in moments}
    raw = beatmap.downbeats or _synth_downbeats(beatmap, target)
    # Normalize the grid to start at 0 so the first clip begins at reel t=0.
    # The renderer seeks the music by ``downbeats[0]`` so the audio's first
    # downbeat lands at reel t=0 -- keeping every cut genuinely on the beat.
    offset = raw[0] if raw else 0.0
    downbeats = [round(d - offset, 4) for d in raw]
    ordered = edl.ordered()

    max_dur = min(settings.max_duration_s, beatmap.duration_s, target + 4)
    min_dur = settings.min_duration_s

    out: list[EditDecision] = []
    t = 0.0
    bi = 0  # current downbeat index
    order = 0
    for dec in ordered:
        m = by_id.get(dec.moment_id)
        if m is None:
            continue
        level = _energy_at(beatmap, t)
        pmin, pmax = _pace_for(level)
        desired = float(min(max(dec.duration_s or 2.0, pmin), pmax))
        # For video, never exceed the available shot length.
        if m.kind.value == "video":
            avail = max(m.duration_s, 0.4)
            desired = min(desired, avail)

        start = downbeats[bi] if bi < len(downbeats) else t
        # Find the downbeat closest to start+desired.
        target_end = start + desired
        nj = _nearest_downbeat_index(downbeats, target_end, after=bi + 1)
        if nj is None:
            end = min(start + desired, max_dur)
        else:
            end = downbeats[nj]
            bi = nj
        dur = max(end - start, 0.45)

        if start >= max_dur:
            break
        if start + dur > max_dur:
            dur = max_dur - start
            if dur < 0.45:
                break

        out.append(
            EditDecision(
                moment_id=dec.moment_id,
                order=order,
                start_at_s=round(start, 3),
                duration_s=round(dur, 3),
                cut_on_beat_index=min(bi, len(downbeats) - 1) if downbeats else 0,
                effect=dec.effect if dec.effect != Effect.none else _default_effect(m),
                transition_in=dec.transition_in,
                overlay_text=dec.overlay_text,
                reason=dec.reason,
            )
        )
        order += 1
        t = start + dur

    if not out:
        raise RuntimeError("Beat-grid snapping produced an empty EDL")

    # Ensure we hit at least min_dur by stretching the last clip a touch.
    total = out[-1].start_at_s + out[-1].duration_s
    if total < min_dur and out:
        out[-1].duration_s += min(min_dur - total, 1.5)
        total = out[-1].start_at_s + out[-1].duration_s

    return EDL(
        track_id=beatmap.track_id,
        total_duration_s=round(total, 3),
        decisions=out,
    )


def _nearest_downbeat_index(downbeats: list[float], t: float, after: int) -> int | None:
    best = None
    best_d = 1e9
    for i in range(after, len(downbeats)):
        d = abs(downbeats[i] - t)
        if d < best_d:
            best_d, best = d, i
        elif downbeats[i] > t:
            break
    return best


def _synth_downbeats(beatmap: BeatMap, target: float) -> list[float]:
    """Fallback grid if a beat map somehow has no downbeats."""
    spb = 60.0 / max(beatmap.bpm, 1) * 4  # 4 beats per bar
    n = int(target / spb) + 4
    return [round(i * spb, 3) for i in range(n)]
