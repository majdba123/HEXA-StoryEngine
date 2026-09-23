from app.composition.text_director import PlacedTextRegion, TextPlacementDirector
from app.models import CompositionBeat, LayoutItem, StoryBeat, TextCue


def _beat() -> StoryBeat:
    return StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=4.0,
        audio_start=0.0,
        audio_end=4.0,
        narration="الرصيد 1000 ريال و300 ريال محجوزة",
        primary_asset_ids=["hero"],
        support_asset_ids=["support"],
        action="EMPHASIZE",
    )


def _cue(cue_id: str, text: str, start: float, end: float, priority: int = 90) -> TextCue:
    return TextCue(
        id=cue_id,
        beat_id="beat-001",
        text=text,
        semantic_type="amount",
        source_char_start=0,
        source_char_end=max(1, len(text)),
        spoken_start=start,
        spoken_end=end,
        emphasis_time=start,
        anchor_asset_id="hero",
        priority=priority,
        style_id="amount",
    )


def test_director_keeps_text_off_large_primary_artwork() -> None:
    director = TextPlacementDirector()
    visual = CompositionBeat(
        beat_id="beat-001",
        items=[
            LayoutItem(asset_id="hero", x=0.50, y=0.52, width=0.56, height=0.62, z=20),
            LayoutItem(asset_id="support", x=0.80, y=0.68, width=0.12, height=0.15, z=15),
        ],
    )

    result = director.place(
        beat=_beat(),
        visual=visual,
        cue=_cue("text-001", "1000 ريال", 0.5, 1.1),
        concurrent_text=[],
        preferred_zone=None,
    )

    assert result.visual_overlap <= 0.001
    assert 0.04 < result.item.x < 0.96
    assert 0.05 < result.item.y < 0.95


def test_director_separates_concurrent_text_regions() -> None:
    director = TextPlacementDirector()
    visual = CompositionBeat(
        beat_id="beat-001",
        items=[LayoutItem(asset_id="hero", x=0.50, y=0.50, width=0.42, height=0.48, z=20)],
    )
    first = director.place(
        beat=_beat(),
        visual=visual,
        cue=_cue("text-001", "1000 ريال", 0.5, 1.2),
        concurrent_text=[],
        preferred_zone=None,
    )
    occupied = [
        PlacedTextRegion(
            cue_id="text-001",
            start=0.5,
            end=1.8,
            box=first.box,
            zone=first.zone,
        )
    ]
    second = director.place(
        beat=_beat(),
        visual=visual,
        cue=_cue("text-002", "300 محجوزة", 0.8, 1.5),
        concurrent_text=occupied,
        preferred_zone=None,
    )

    assert director._intersection_ratio(first.box, second.box) <= 0.001
    assert second.visual_overlap <= 0.001


def test_director_uses_soft_zone_continuity_without_forcing_overlap() -> None:
    director = TextPlacementDirector()
    visual = CompositionBeat(
        beat_id="beat-001",
        items=[LayoutItem(asset_id="hero", x=0.58, y=0.52, width=0.48, height=0.50, z=20)],
    )
    first = director.place(
        beat=_beat(),
        visual=visual,
        cue=_cue("text-001", "1000 ريال", 0.4, 0.9),
        concurrent_text=[],
        preferred_zone=None,
    )
    preferred = director._zone_family(first.zone)
    second = director.place(
        beat=_beat(),
        visual=visual,
        cue=_cue("text-002", "500 ريال", 2.0, 2.4),
        concurrent_text=[],
        preferred_zone=preferred,
    )

    assert director._zone_family(second.zone) == preferred
    assert second.visual_overlap <= 0.001


def test_director_uses_actual_alpha_footprint_for_negative_space(tmp_path) -> None:
    from PIL import Image, ImageDraw
    from app.models import VisualAsset

    path = tmp_path / "sparse.png"
    image = Image.new("RGBA", (400, 240), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    # Artwork occupies the left 62% of a broad authored canvas. The right side is real
    # negative space and should be available to text even though LayoutItem is large.
    draw.rounded_rectangle((0, 15, 245, 225), radius=20, fill=(20, 100, 220, 255))
    image.save(path)

    asset = VisualAsset(
        id="hero",
        scene_id="scene-001",
        role="primary",
        image_path=path,
        extraction_method="fixture",
    )
    visual = CompositionBeat(
        beat_id="beat-001",
        items=[LayoutItem(asset_id="hero", x=0.50, y=0.50, width=0.90, height=0.78, z=20)],
    )
    director = TextPlacementDirector()
    result = director.place(
        beat=_beat(),
        visual=visual,
        cue=_cue("text-001", "300 محجوزة", 0.5, 1.1),
        concurrent_text=[],
        preferred_zone=None,
        assets_by_id={"hero": asset},
    )

    assert result.visual_overlap <= 0.001
    # The clean right-hand negative space should beat covering the opaque left cluster.
    assert result.item.x >= 0.65


def test_authoring_qa_checks_text_against_locked_visual_geometry(tmp_path) -> None:
    from PIL import Image, ImageDraw
    from app.models import TextCompositionBeat, TextLayoutItem, TextPlan, Transcript, VisualAsset
    from app.qa import AuthoringVisualQA

    path = tmp_path / "opaque.png"
    image = Image.new("RGBA", (200, 200), (255, 255, 255, 0))
    ImageDraw.Draw(image).rectangle((0, 0, 199, 199), fill=(20, 80, 180, 255))
    image.save(path)
    asset = VisualAsset(
        id="hero", scene_id="scene-001", role="primary", image_path=path,
        extraction_method="test",
    )
    visual = [CompositionBeat(
        beat_id="beat-001",
        items=[LayoutItem(asset_id="hero", x=0.5, y=0.5, width=0.5, height=0.5, placement_source="authored_scene_geometry")],
    )]
    cue = _cue("text-001", "1000 ريال", 0.2, 0.8)
    text = TextPlan(cues=[cue], styles=[])
    text_comp = [TextCompositionBeat(
        beat_id="beat-001",
        items=[TextLayoutItem(text_cue_id=cue.id, x=0.5, y=0.5, max_width=0.3)],
    )]
    report = AuthoringVisualQA().inspect(
        transcript=Transcript(language="ar", duration=1.0, segments=[], timing_source="forced_alignment"),
        composition=visual,
        motion=[],
        text=text,
        text_composition=text_comp,
        assets=[asset],
    )
    assert report.text_layout_violations


def test_arabic_kufi_measurement_reserves_real_glyph_width_and_entry_motion() -> None:
    cue = _cue("text-wide", "يكتب وبسرعة", 0.2, 0.8)
    width, height = TextPlacementDirector.estimated_box(cue, scale=1.0)

    assert width > 0.55
    assert height > 0.14
