import shutil
from pathlib import Path

import pytest
from PIL import Image

from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    RenderPlan,
    StoryBeat,
    TextCompositionBeat,
    TextCue,
    TextLayoutItem,
    TextMotionCue,
    TextPlan,
    TextStyle,
    VisualAsset,
)
from app.render.renderer import FFmpegRenderer
from app.render.text import TextRenderer


def _plan(tmp_path: Path) -> RenderPlan:
    asset_path = tmp_path / "wallet.png"
    Image.new("RGBA", (180, 180), (20, 120, 230, 255)).save(asset_path)
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=1.5,
        audio_start=0.0,
        audio_end=1.5,
        narration="الرصيد 1000 ريال",
        primary_asset_ids=["wallet"],
        action="EMPHASIZE",
    )
    text = TextCue(
        id="text-001",
        beat_id=beat.id,
        text="1000 ريال",
        semantic_type="amount",
        source_char_start=7,
        source_char_end=16,
        spoken_start=0.35,
        spoken_end=0.92,
        emphasis_time=0.35,
        anchor_asset_id="wallet",
        priority=90,
        style_id="amount",
    )
    return RenderPlan(
        duration=1.5,
        story=[beat],
        assets=[VisualAsset(
            id="wallet",
            scene_id="scene-001",
            role="primary",
            image_path=asset_path,
            extraction_method="fixture",
        )],
        composition=[CompositionBeat(
            beat_id=beat.id,
            items=[LayoutItem(asset_id="wallet", x=0.5, y=0.58, width=0.28, height=0.34, z=20)],
        )],
        motion=[MotionCue(
            beat_id=beat.id,
            asset_id="wallet",
            kind="soft_in",
            start=0.0,
            end=0.22,
        )],
        text=TextPlan(
            cues=[text],
            styles=[TextStyle(
                id="amount",
                role="amount",
                font_role="display",
                size_role="large",
                color_role="primary",
                background_role="none",
                emphasis_role="numeric",
            )],
        ),
        text_composition=[TextCompositionBeat(
            beat_id=beat.id,
            items=[TextLayoutItem(
                text_cue_id=text.id,
                x=0.5,
                y=0.20,
                max_width=0.36,
                anchor_asset_id="wallet",
                placement="above_anchor",
            )],
        )],
        text_motion=[TextMotionCue(
            beat_id=beat.id,
            text_cue_id=text.id,
            kind="text_number_in",
            start=0.35,
            end=0.55,
            params={"visible_end": 1.18, "emphasis_time": 0.35},
        )],
    )


def test_text_renderer_writes_native_arabic_ass_without_string_reversal(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    path = TextRenderer().write_beat_ass(
        plan,
        plan.story[0],
        segment_start=0.0,
        duration=1.5,
        output=tmp_path / "beat.ass",
    )

    assert path is not None
    payload = path.read_text(encoding="utf-8")
    assert "1000 ريال" in payload
    assert "لاير" not in payload
    assert "Noto Kufi Arabic" in payload
    assert "\\pos(960,216)" in payload
    assert "\\t(" in payload


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_ffmpeg_renderer_burns_text_in_same_segment_encode(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    target = tmp_path / "out.mp4"

    FFmpegRenderer().render(plan, target)

    assert target.is_file()
    assert target.stat().st_size > 0
    ass_files = list((tmp_path / "out-segments").glob("*-text.ass"))
    assert len(ass_files) == 1
    assert "1000 ريال" in ass_files[0].read_text(encoding="utf-8")
