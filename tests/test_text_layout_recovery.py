from pathlib import Path

from app.models import TextCue, TextLayoutItem
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


def test_text_layout_violation_parser_preserves_stronger_collision_cue() -> None:
    violations = (
        "beat-001:text_visual_overlap:text-001:0.225",
        "beat-002:text_text_overlap:text-002:text-003:0.120:time=1.0-1.2",
        "beat-004:text_offscreen:text-999",
    )
    cues = [
        TextCue(
            id="text-001", beat_id="beat-001", text="weak visual",
            semantic_type="keyword", source_char_start=0, source_char_end=4,
            spoken_start=0.2, spoken_end=0.5, emphasis_time=0.2,
            priority=60, style_id="keyword",
        ),
        TextCue(
            id="text-002", beat_id="beat-002", text="strong result",
            semantic_type="emphasis", source_char_start=5, source_char_end=10,
            spoken_start=1.0, spoken_end=1.3, emphasis_time=1.0,
            priority=92, style_id="emphasis",
        ),
        TextCue(
            id="text-003", beat_id="beat-002", text="support phrase",
            semantic_type="emphasis", source_char_start=11, source_char_end=16,
            spoken_start=1.0, spoken_end=1.3, emphasis_time=1.0,
            priority=76, style_id="emphasis",
        ),
    ]

    unsafe = StoryEnginePipeline._text_violation_cue_ids(
        violations,
        cues,
    )

    assert unsafe == {"text-001", "text-003"}


def test_emergency_text_scale_floor_is_model_valid() -> None:
    item = TextLayoutItem(
        text_cue_id="text-001",
        x=0.5,
        y=0.5,
        max_width=0.4,
        font_scale=0.50,
    )

    assert item.font_scale == 0.50

def test_true_white_flash_has_strict_recovery_handler(tmp_path: Path) -> None:
    recovery = RecoveryManager(tmp_path)

    result = recovery.handle(
        code="VISUAL_WHITE_FLASH",
        context={"count": 1, "first_frames": [{"frame": 15, "time": 0.5}]},
        attempt=1,
    )

    assert result is not None
    assert result.success is True
    assert result.invalidate_from_stage == "render"
    assert recovery.handle(
        code="VISUAL_WHITE_FLASH",
        context={},
        attempt=2,
    ) is None

