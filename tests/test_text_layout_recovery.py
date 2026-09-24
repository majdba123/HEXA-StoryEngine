from pathlib import Path

from app.models import TextLayoutItem
from app.pipeline import StoryEnginePipeline
from app.recovery.manager import RecoveryManager


def test_text_layout_violation_has_proven_recovery_handler(tmp_path: Path) -> None:
    recovery = RecoveryManager(tmp_path)

    result = recovery.handle(
        code="TEXT_LAYOUT_REFERENCE_VIOLATION",
        context={"violations": ["beat-001:text_visual_overlap:text-001:0.20"]},
        attempt=1,
    )

    assert result is not None
    assert result.success is True
    assert result.invalidate_from_stage == "composition"


def test_text_layout_recovery_is_bounded_to_three_attempts(tmp_path: Path) -> None:
    recovery = RecoveryManager(tmp_path)

    assert recovery.handle(
        code="TEXT_LAYOUT_REFERENCE_VIOLATION",
        context={},
        attempt=3,
    ) is not None
    assert recovery.handle(
        code="TEXT_LAYOUT_REFERENCE_VIOLATION",
        context={},
        attempt=4,
    ) is None


def test_text_layout_violation_parser_collects_only_known_cues() -> None:
    violations = (
        "beat-001:text_visual_overlap:text-001:0.225",
        "beat-002:text_text_overlap:text-002:text-003:0.120:time=1.0-1.2",
        "beat-004:text_offscreen:text-999",
    )

    unsafe = StoryEnginePipeline._text_violation_cue_ids(
        violations,
        {"text-001", "text-002", "text-003"},
    )

    assert unsafe == {"text-001", "text-002", "text-003"}


def test_emergency_text_scale_floor_is_model_valid() -> None:
    item = TextLayoutItem(
        text_cue_id="text-001",
        x=0.5,
        y=0.5,
        max_width=0.4,
        font_scale=0.50,
    )

    assert item.font_scale == 0.50
