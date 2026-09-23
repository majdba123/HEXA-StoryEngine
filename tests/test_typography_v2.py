from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.composition import TextCompositionPlanner
from app.composition.text_director import TextPlacementDirector
from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    StoryBeat,
    TextCue,
    Transcript,
    TranscriptWord,
    VisualAsset,
)
from app.motion import TextMotionPlanner
from app.text import TextPlanner
from app.text.typography import TypographyMetrics


def _opaque(path: Path, *, size: tuple[int, int] = (200, 200)) -> Path:
    Image.new("RGBA", size, (30, 80, 180, 255)).save(path)
    return path


def _beat(*, end: float = 4.0) -> StoryBeat:
    return StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=end,
        audio_start=0.0,
        audio_end=end,
        narration="المشكلة مو بالرصيد المشكلة بالحد اليومي",
        primary_asset_ids=["primary"],
        support_asset_ids=["support"],
        action="EMPHASIZE",
    )


def _cue(
    cue_id: str = "text-001",
    *,
    text: str = "الحد اليومي",
    start: float = 0.5,
    end: float = 1.0,
    anchor: str | None = "primary",
    priority: int = 90,
) -> TextCue:
    return TextCue(
        id=cue_id,
        beat_id="beat-001",
        text=text,
        semantic_type="emphasis",
        source_char_start=0,
        source_char_end=max(1, len(text)),
        spoken_start=start,
        spoken_end=end,
        emphasis_time=start,
        anchor_asset_id=anchor,
        priority=priority,
        style_id="emphasis",
    )


def _box(item, cue: TextCue) -> tuple[float, float, float, float]:
    _, height = TextPlacementDirector.estimated_box(
        cue,
        font_size_ratio=item.font_size_ratio,
    )
    return (
        item.x - item.max_width / 2,
        item.y - height / 2,
        item.x + item.max_width / 2,
        item.y + height / 2,
    )


def test_character_right_object_left_uses_safe_negative_space(tmp_path: Path) -> None:
    character = VisualAsset(
        id="character",
        scene_id="scene-001",
        role="character",
        image_path=_opaque(tmp_path / "character.png"),
        extraction_method="fixture",
    )
    obj = VisualAsset(
        id="primary",
        scene_id="scene-001",
        role="primary",
        image_path=_opaque(tmp_path / "object.png"),
        extraction_method="fixture",
    )
    visual = [CompositionBeat(
        beat_id="beat-001",
        items=[
            LayoutItem(asset_id="primary", x=0.22, y=0.58, width=0.24, height=0.34),
            LayoutItem(asset_id="character", x=0.82, y=0.55, width=0.22, height=0.70),
        ],
    )]
    cue = _cue()

    result = TextCompositionPlanner().plan(
        [_beat()], visual, [cue], [obj, character]
    )

    assert result and result[0].items
    text_box = _box(result[0].items[0], cue)
    assert text_box[2] < 0.70 or text_box[0] > 0.94 or text_box[3] < 0.18


def test_large_center_object_is_never_covered(tmp_path: Path) -> None:
    asset = VisualAsset(
        id="primary",
        scene_id="scene-001",
        role="primary",
        image_path=_opaque(tmp_path / "center.png"),
        extraction_method="fixture",
    )
    visual = [CompositionBeat(
        beat_id="beat-001",
        items=[LayoutItem(asset_id="primary", x=0.5, y=0.5, width=0.48, height=0.55)],
    )]
    cue = _cue()
    result = TextCompositionPlanner().plan([_beat()], visual, [cue], [asset])

    assert result and result[0].items
    box = _box(result[0].items[0], cue)
    center = (0.26, 0.225, 0.74, 0.775)
    assert TextPlacementDirector._intersection_ratio(box, center) <= 0.006


def test_dense_scene_either_places_safely_or_suppresses_without_moving_assets(
    tmp_path: Path,
) -> None:
    assets: list[VisualAsset] = []
    items: list[LayoutItem] = []
    for index in range(6):
        asset_id = "primary" if index == 0 else f"asset-{index}"
        assets.append(VisualAsset(
            id=asset_id,
            scene_id="scene-001",
            role="primary" if index == 0 else "object",
            image_path=_opaque(tmp_path / f"{asset_id}.png"),
            extraction_method="fixture",
        ))
        items.append(LayoutItem(
            asset_id=asset_id,
            x=0.14 + (index % 3) * 0.34,
            y=0.30 + (index // 3) * 0.42,
            width=0.22,
            height=0.25,
        ))
    visual = [CompositionBeat(beat_id="beat-001", items=items)]
    before = [row.model_dump() for row in visual[0].items]
    cues = [
        _cue("text-001", text="الخطر الحقيقي", start=0.3, end=0.7),
        _cue("text-002", text="نقطة الضعف", start=1.0, end=1.4),
    ]

    result = TextCompositionPlanner().plan([_beat()], visual, cues, assets)

    assert [row.model_dump() for row in visual[0].items] == before
    assert sum(len(row.items) for row in result) <= len(cues)


def test_long_arabic_phrase_uses_shaped_measurement_and_never_overflows() -> None:
    metrics = TypographyMetrics()
    measurement = metrics.measure(
        "المشكلة بالحد اليومي المسموح",
        size_ratio=158 / 1080,
    )
    assert measurement.width > 0.0
    assert 0.0 < measurement.height < 0.35
    assert measurement.method in {"pillow_raqm", "pillow", "conservative_fallback"}

    cue = _cue(text="المشكلة بالحد اليومي المسموح", anchor=None)
    result = TextCompositionPlanner().plan(
        [_beat()], [CompositionBeat(beat_id="beat-001", items=[])], [cue], []
    )
    if result:
        box = _box(result[0].items[0], cue)
        assert min(box) >= 0.0
        assert max(box) <= 1.0
    else:
        assert measurement.width > 0.90


def test_overlapping_text_cues_are_spatially_separated() -> None:
    cues = [
        _cue("text-001", text="الخطر الحقيقي", start=0.5, end=1.2, anchor=None),
        _cue("text-002", text="نقطة الضعف", start=0.65, end=1.3, anchor=None),
    ]
    result = TextCompositionPlanner().plan(
        [_beat()], [CompositionBeat(beat_id="beat-001", items=[])], cues, []
    )

    assert result and len(result[0].items) == 2
    by_id = {cue.id: cue for cue in cues}
    boxes = [_box(item, by_id[item.text_cue_id]) for item in result[0].items]
    assert TextPlacementDirector._intersection_ratio(boxes[0], boxes[1]) <= 0.01


def test_semantic_activation_becomes_text_anchor_without_changing_timing() -> None:
    transcript = Transcript(
        language="ar",
        duration=2.0,
        segments=[],
        timing_source="forced_alignment",
        words=[
            TranscriptWord(text="الحد", start=0.4, end=0.65, char_start=0, char_end=4),
            TranscriptWord(text="اليومي", start=0.7, end=1.0, char_start=5, char_end=11),
        ],
    )
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=1.5,
        audio_start=0.4,
        audio_end=1.0,
        narration="الحد اليومي",
        primary_asset_ids=["fallback-primary"],
        action="EMPHASIZE",
        asset_activations=[AssetActivation(
            asset_id="semantic-icon",
            semantic_unit_id="limit-intent",
            trigger_text="الحد اليومي",
            trigger_char_start=0,
            trigger_char_end=11,
            spoken_start=0.4,
            spoken_end=1.0,
            confidence=0.98,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
        )],
    )

    plan = TextPlanner().plan(transcript=transcript, story=[beat])

    assert plan.cues
    assert plan.cues[0].anchor_asset_id == "semantic-icon"
    assert plan.cues[0].spoken_start == 0.4


def test_very_short_beat_never_extends_text_entrance_past_visible_window() -> None:
    beat = _beat(end=0.55)
    cue = _cue(start=0.42, end=0.50, anchor=None)
    composition = TextCompositionPlanner().plan(
        [beat], [CompositionBeat(beat_id=beat.id, items=[])], [cue], []
    )
    motion = TextMotionPlanner().plan([beat], [cue], composition)

    assert motion
    assert motion[0].start == cue.spoken_start
    assert motion[0].end <= beat.end
    assert all(token.end <= beat.end for token in motion[0].tokens)


def test_character_role_receives_stronger_protected_halo(tmp_path: Path) -> None:
    character = VisualAsset(
        id="primary",
        scene_id="scene-001",
        role="character",
        image_path=_opaque(tmp_path / "face.png"),
        extraction_method="fixture",
    )
    visual = [CompositionBeat(
        beat_id="beat-001",
        items=[LayoutItem(asset_id="primary", x=0.78, y=0.48, width=0.24, height=0.62)],
    )]
    cue = _cue(anchor="primary")
    result = TextCompositionPlanner().plan([_beat()], visual, [cue], [character])

    assert result and result[0].items
    box = _box(result[0].items[0], cue)
    face_region = (0.66, 0.17, 0.90, 0.79)
    assert TextPlacementDirector._intersection_ratio(box, face_region) <= 0.002


def test_no_safe_position_suppresses_cue_without_moving_scene(tmp_path: Path) -> None:
    full = VisualAsset(
        id="primary",
        scene_id="scene-001",
        role="primary",
        image_path=_opaque(tmp_path / "full.png"),
        extraction_method="fixture",
    )
    visual = [CompositionBeat(
        beat_id="beat-001",
        items=[LayoutItem(asset_id="primary", x=0.5, y=0.5, width=1.0, height=1.0)],
    )]
    before = visual[0].items[0].model_dump()

    result = TextCompositionPlanner().plan([_beat()], visual, [_cue()], [full])

    assert result == []
    assert visual[0].items[0].model_dump() == before
