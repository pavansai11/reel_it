"""EDL contract tests -- the schema both pipeline halves depend on."""
import pytest
from pydantic import ValidationError

from app.pipeline.schemas import EDL, EditDecision, Effect, Transition


def test_edl_requires_decisions():
    with pytest.raises(ValidationError):
        EDL(track_id="t", total_duration_s=10, decisions=[])


def test_overlay_text_null_strings_become_none():
    d = EditDecision(moment_id="m1", order=0, start_at_s=0, duration_s=1, overlay_text="null")
    assert d.overlay_text is None
    d2 = EditDecision(moment_id="m1", order=0, start_at_s=0, duration_s=1, overlay_text="  ")
    assert d2.overlay_text is None


def test_overlay_text_trimmed_to_40_chars():
    d = EditDecision(moment_id="m1", order=0, start_at_s=0, duration_s=1, overlay_text="x" * 80)
    assert len(d.overlay_text) == 40


def test_duration_must_be_positive():
    with pytest.raises(ValidationError):
        EditDecision(moment_id="m", order=0, start_at_s=0, duration_s=0)


def test_ordered_sorts_by_order():
    edl = EDL(
        track_id="t",
        total_duration_s=5,
        decisions=[
            EditDecision(moment_id="b", order=2, start_at_s=2, duration_s=1),
            EditDecision(moment_id="a", order=0, start_at_s=0, duration_s=1),
        ],
    )
    assert [d.moment_id for d in edl.ordered()] == ["a", "b"]


def test_json_schema_usable_as_tool_input():
    schema = EDL.model_json_schema()
    assert schema["type"] == "object"
    assert "decisions" in schema["properties"]
