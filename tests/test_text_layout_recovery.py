from pathlib import Path
from types import SimpleNamespace

from app.models import TextCue, TextLayoutItem, TextPlan
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

class _CascadingTextQA:
    def inspect(self, *, text, **_kwargs):
        cue_ids = {cue.id for cue in text.cues}
        if "text-a" in cue_ids:
            violations = ("beat-001:text_visual_overlap:text-a:0.080",)
        elif "text-b" in cue_ids:
            # This second collision appears only after text-a has been removed,
            # reproducing the production failure where reflow exposed text-028.
            violations = ("beat-001:text_visual_overlap:text-b:0.051",)
        else:
            violations = ()
        return SimpleNamespace(text_layout_violations=violations)


class _NoopTextComposition:
    def plan(self, *_args, **_kwargs):
        return []


class _NoopTextMotion:
    def plan(self, *_args, **_kwargs):
        return []


def _recovery_cue(cue_id: str, priority: int) -> TextCue:
    return TextCue(
        id=cue_id,
        beat_id="beat-001",
        text=cue_id,
        semantic_type="keyword",
        source_char_start=0,
        source_char_end=1,
        spoken_start=0.1,
        spoken_end=0.3,
        emphasis_time=0.1,
        priority=priority,
        style_id="keyword",
    )


def test_optional_text_recovery_converges_when_reflow_exposes_new_collision(
    tmp_path: Path,
) -> None:
    pipeline = StoryEnginePipeline.__new__(StoryEnginePipeline)
    pipeline.settings = SimpleNamespace(require_text_layer=False)
    pipeline.recovery = RecoveryManager(tmp_path)
    pipeline.text_composition = _NoopTextComposition()
    pipeline.text_motion = _NoopTextMotion()
    pipeline.authoring_qa = _CascadingTextQA()

    text = TextPlan(
        cues=[
            _recovery_cue("text-a", 80),
            _recovery_cue("text-b", 90),
        ],
        styles=[],
    )
    initial_report = SimpleNamespace(
        text_layout_violations=(
            "beat-001:text_visual_overlap:text-a:0.080",
        )
    )

    repaired_text, _composition, _motion, report = pipeline._recover_text_layout(
        package_id="fixture",
        job_id="job",
        transcript=SimpleNamespace(),
        story=[],
        composition=[],
        motion=[],
        text=text,
        text_composition=[],
        text_motion=[],
        assets=[],
        choreography=[],
        progress=None,
        cancelled=None,
        initial_report=initial_report,
    )

    assert report.text_layout_violations == ()
    assert repaired_text.cues == []



class _CaptureTextComposition:
    def __init__(self) -> None:
        self.visual_motion = None

    def plan(self, *_args, visual_motion=None, **_kwargs):
        self.visual_motion = visual_motion
        return ["text-composition"]


class _CaptureTextMotion:
    def __init__(self) -> None:
        self.visual_motion = None

    def plan(self, *_args, visual_motion=None, **_kwargs):
        self.visual_motion = visual_motion
        return ["text-motion"]


def test_primary_text_authoring_consumes_final_visual_motion() -> None:
    pipeline = StoryEnginePipeline.__new__(StoryEnginePipeline)
    pipeline.text_composition = _CaptureTextComposition()
    pipeline.text_motion = _CaptureTextMotion()
    motion = [SimpleNamespace(asset_id="hero")]
    text = TextPlan(cues=[_recovery_cue("text-a", 90)], styles=[])

    composition, text_motion = pipeline._compose_text_against_visual_motion(
        story=[],
        composition=[],
        motion=motion,
        text=text,
        assets=[],
        choreography=[],
    )

    assert composition == ["text-composition"]
    assert text_motion == ["text-motion"]
    assert pipeline.text_composition.visual_motion is motion
    assert pipeline.text_motion.visual_motion is motion
