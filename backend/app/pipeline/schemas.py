"""Pipeline data contracts.

The EDL (Edit Decision List) is THE contract between the edit brain (stage 5)
and the renderer (stage 6). Lock this schema early; both sides depend on it.

All of these are plain pydantic models so each stage can be a pure function:
JSON/files in -> JSON/files out, and so the LLM output can be validated strictly.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

# Fixed zero-shot tag vocabulary (spec §, stage 3).
CONTENT_TAGS = [
    "beach",
    "sunset",
    "mountains",
    "food",
    "city",
    "nature",
    "group",
    "selfie",
    "action",
    "scenery",
    "night",
    "water",
]


class MomentKind(str, Enum):
    photo = "photo"
    video = "video"


class Effect(str, Enum):
    none = "none"
    ken_burns_in = "ken_burns_in"
    ken_burns_out = "ken_burns_out"
    ken_burns_pan = "ken_burns_pan"
    speed_1_5 = "speed_1.5"


class Transition(str, Enum):
    hard_cut = "hard_cut"
    crossfade = "crossfade"
    whip = "whip"


# --- Stage 1-3 output: the scored moment pool ------------------------------
class Moment(BaseModel):
    """Atomic editable unit, scored and tagged. This is what the LLM sees."""

    id: str
    asset_id: str
    kind: MomentKind
    source_path: str  # storage key of the underlying asset
    start_s: float = 0.0  # for video: in-point within the source
    end_s: float = 0.0
    duration_s: float = 0.0

    aesthetic_score: float = 0.0  # 0..1
    smile_score: float = 0.0  # 0..1
    motion_score: float = 0.0  # 0..1 (calm -> energetic)
    has_people: bool = False
    face_count: int = 0
    tags: list[str] = Field(default_factory=list)

    def for_llm(self) -> dict:
        """Compact, source-path-free view handed to the edit brain."""
        return {
            "id": self.id,
            "type": self.kind.value,
            "duration": round(self.duration_s, 2),
            "aesthetic": round(self.aesthetic_score, 2),
            "smile": round(self.smile_score, 2),
            "motion": round(self.motion_score, 2),
            "people": self.face_count,
            "tags": self.tags,
        }


# --- Stage 4 output: the beat map ------------------------------------------
class EnergySection(BaseModel):
    start: float
    end: float
    level: float  # 0..1


class BeatMap(BaseModel):
    track_id: str
    path: str  # storage/asset path to the audio file
    bpm: float
    duration_s: float
    beats: list[float] = Field(default_factory=list)
    downbeats: list[float] = Field(default_factory=list)
    energy_sections: list[EnergySection] = Field(default_factory=list)

    def downbeats_for_llm(self, max_n: int = 64) -> list[float]:
        return [round(t, 2) for t in self.downbeats[:max_n]]


# --- Stage 5 output: the EDL -----------------------------------------------
class EditDecision(BaseModel):
    moment_id: str
    order: int
    start_at_s: float = Field(ge=0)  # position on the reel timeline
    duration_s: float = Field(gt=0)
    cut_on_beat_index: int = 0
    effect: Effect = Effect.none
    transition_in: Transition = Transition.hard_cut
    overlay_text: str | None = None
    reason: str = ""

    @field_validator("overlay_text")
    @classmethod
    def _clean_text(cls, v):
        if v is None:
            return None
        v = v.strip()
        if not v or v.lower() in {"null", "none"}:
            return None
        return v[:40]  # keep overlays short/tasteful


class EDL(BaseModel):
    track_id: str
    total_duration_s: float = Field(gt=0)
    decisions: list[EditDecision]

    @field_validator("decisions")
    @classmethod
    def _non_empty(cls, v):
        if not v:
            raise ValueError("EDL must contain at least one decision")
        return v

    def ordered(self) -> list[EditDecision]:
        return sorted(self.decisions, key=lambda d: d.order)

    # JSON schema string embedded in the LLM prompt so the model knows the shape.
    @staticmethod
    def prompt_schema() -> str:
        return (
            "{\n"
            '  "track_id": "<string>",\n'
            '  "total_duration_s": <float 25-35>,\n'
            '  "decisions": [\n'
            "    {\n"
            '      "moment_id": "<id from the pool>",\n'
            '      "order": <int, 0-based, contiguous>,\n'
            '      "start_at_s": <float, position on reel timeline>,\n'
            '      "duration_s": <float, >0>,\n'
            '      "cut_on_beat_index": <int, index into downbeats[]>,\n'
            '      "effect": "none|ken_burns_in|ken_burns_out|ken_burns_pan|speed_1.5",\n'
            '      "transition_in": "hard_cut|crossfade|whip",\n'
            '      "overlay_text": "<short text or null>",\n'
            '      "reason": "<one short clause>"\n'
            "    }\n"
            "  ]\n"
            "}"
        )
