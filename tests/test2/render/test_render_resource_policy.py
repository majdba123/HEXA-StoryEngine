from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.config import RenderResourceSettings
from app.models import CompositionBeat, LayoutItem, RenderPlan, StoryBeat, VisualAsset
from app.render.renderer import FFmpegRenderer
from app.render.resources import RenderConcurrencyPolicy
from app.shared.errors import StageFailedError

GIB = 1 << 30


def test_worker_policy_bounds_override_and_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEXA_RENDER_WORKERS", "6")
    assert RenderResourceSettings.from_env().workers_override == 6
    monkeypatch.setenv("HEXA_RENDER_WORKERS", "invalid")
    assert RenderResourceSettings.from_env().workers_override == 1
    monkeypatch.setenv("HEXA_RENDER_WORKERS", "99")
    assert RenderResourceSettings.from_env().workers_override == 8
    policy = RenderConcurrencyPolicy(RenderResourceSettings(workers_override=8))
    assert policy.workers(width=1920, height=1080, cpu_count=2, available_bytes=0) == 8


@pytest.mark.parametrize(("free", "expected"), [
    (9 * GIB, 4), (7 * GIB, 3), (5 * GIB, 2), (3 * GIB, 1),
])
def test_auto_memory_downgrade_is_deterministic(free: int, expected: int) -> None:
    policy = RenderConcurrencyPolicy(RenderResourceSettings())
    assert policy.workers(width=1920, height=1080, cpu_count=16, available_bytes=free) == expected
    assert policy.workers(width=1920, height=1080, cpu_count=16, available_bytes=free) == expected


def test_auto_cpu_limit_probe_failure_and_large_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = RenderConcurrencyPolicy(RenderResourceSettings())
    assert policy.workers(width=1920, height=1080, cpu_count=2, available_bytes=20 * GIB) == 1
    assert policy.workers(width=1920, height=1080, cpu_count=6, available_bytes=20 * GIB) == 3
    assert policy.workers(width=3840, height=2160, cpu_count=16, available_bytes=9 * GIB) == 1
    monkeypatch.setattr("app.render.resources.available_memory_bytes", lambda: None)
    assert policy.workers(width=1920, height=1080, cpu_count=16) == 1


def _plan(tmp_path: Path) -> RenderPlan:
    from PIL import Image

    image = tmp_path / "asset.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(image)
    beat = StoryBeat(id="beat-001", scene_id="scene-001", start=0, end=0.5,
                     audio_start=0, audio_end=0.5, narration="test",
                     primary_asset_ids=["a"], action="INTRODUCE")
    return RenderPlan(width=320, height=180, fps=30, duration=0.5, story=[beat],
                      composition=[CompositionBeat(beat_id=beat.id, items=[
                          LayoutItem(asset_id="a", x=0.5, y=0.5, width=0.3, height=0.5, z=1)])],
                      motion=[], assets=[VisualAsset(id="a", scene_id="scene-001", role="primary",
                                                     image_path=image, extraction_method="test")])


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
@pytest.mark.parametrize("retain", [False, True])
def test_real_render_cleanup_and_diagnostic_retention(tmp_path: Path, retain: bool) -> None:
    plan = _plan(tmp_path)
    output = tmp_path / "video.mp4"
    renderer = FFmpegRenderer(resources=RenderResourceSettings(workers_override=1,
                                                                keep_intermediates=retain))
    assert renderer.render(plan, output) == output
    assert output.is_file() and output.stat().st_size > 0
    assert plan.assets[0].image_path.is_file()
    assert (tmp_path / "video-segments").exists() is retain
    assert (tmp_path / "video-concat.txt").exists() is retain


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_cleanup_can_wait_for_pipeline_verification(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    output = tmp_path / "video.mp4"
    renderer = FFmpegRenderer(resources=RenderResourceSettings(workers_override=1),
                              defer_cleanup=True)
    renderer.render(plan, output)
    assert (tmp_path / "video-segments").is_dir()
    assert (tmp_path / "video-concat.txt").is_file()
    renderer.cleanup_intermediates(output, source_paths={plan.assets[0].image_path})
    assert output.is_file()
    assert plan.assets[0].image_path.is_file()
    assert not (tmp_path / "video-segments").exists()
    assert not (tmp_path / "video-concat.txt").exists()


def test_failed_render_keeps_evidence_and_cleanup_rejects_unsafe_paths(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    output = tmp_path / "video.mp4"

    class FailingRenderer(FFmpegRenderer):
        def _render_beat_segment(self, *args, **kwargs):
            raise StageFailedError("original worker failure")

    renderer = FailingRenderer(resources=RenderResourceSettings(workers_override=1))
    with pytest.raises(StageFailedError, match="original worker failure"):
        renderer.render(plan, output)
    assert (tmp_path / "video-segments/ffmpeg-filter-option-probe.ffgraph").is_file()
    assert not output.exists()
    with pytest.raises(StageFailedError, match="overlaps a source asset"):
        FFmpegRenderer.cleanup_intermediates(output, source_paths={tmp_path / "video-segments/source.png"})
    assert (tmp_path / "video-segments/ffmpeg-filter-option-probe.ffgraph").is_file()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_concat_failure_keeps_encoded_segment(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    output = tmp_path / "video.mp4"

    class FailingConcat(FFmpegRenderer):
        def _concat_segments(self, segments, target):
            raise StageFailedError("concat failed")

    renderer = FailingConcat(resources=RenderResourceSettings(workers_override=1))
    with pytest.raises(StageFailedError, match="concat failed"):
        renderer.render(plan, output)
    assert list((tmp_path / "video-segments").glob("*.mp4"))
    assert not output.exists()
