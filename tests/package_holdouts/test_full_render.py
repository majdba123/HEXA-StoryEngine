from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.cutout import CutoutService, Pass2CutoutService
from app.final import FinalExporter, FinalMediaVerifier
from app.final_package import FinalPackageLoader
from app.motion import MotionPlanner
from app.pipeline import StoryEnginePipeline
from app.render import RenderPlanner
from app.render.renderer import FFmpegRenderer
from app.render.verification import EncodedMotionVerifier
from app.story import StoryPlanner
from app.text import TextPlanner
from app.vision import VisionService
from tests.package_holdouts.cases import encoded_cases, full_render_cases, structural_cases
from tests.package_holdouts.generator import generate
from tests.test1.factory import deterministic_transcript


@pytest.mark.parametrize("case", structural_cases(), ids=lambda case: str(case.seed))
def test_large_structural_matrix_is_valid_unified_2(tmp_path: Path, case) -> None:
    generated = generate(case, tmp_path / "source")
    package = FinalPackageLoader().load(generated.root, tmp_path / "load")
    assert len(package.scenes) == case.scene_count
    assert package.has_authoritative_semantics
    assert all(scene.units and scene.semantic_events for scene in package.scenes)


def _plan(case, tmp_path: Path):
    generated = generate(case, tmp_path / "source")
    package = FinalPackageLoader().load(generated.root, tmp_path / "load")
    transcript = deterministic_transcript(package)
    detections = VisionService().analyze(package)
    assets = CutoutService().extract(package, detections, tmp_path / "pass1")
    pipeline = StoryEnginePipeline.__new__(StoryEnginePipeline)
    pipeline.settings = type("Settings", (), {"refinement_mode": "pass2_vnext"})()
    pipeline.cutout_pass2, pipeline.refinement = Pass2CutoutService(), None
    assets = pipeline._apply_refinement(package, assets, tmp_path / "pass2")
    story = StoryPlanner().plan(package, transcript, assets)
    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    text = TextPlanner().plan(transcript=transcript, story=story, assets=assets, package=package, choreography=choreography)
    workspace = tmp_path / "render"
    workspace.mkdir()
    plan, _ = RenderPlanner().compile(transcript, assets, story, composition, motion, workspace, text=text)
    return plan


@pytest.mark.parametrize("case", encoded_cases(), ids=lambda case: str(case.seed))
def test_many_short_real_ffmpeg_encodes(tmp_path: Path, case) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.fail("Sprint 3.75 certification requires ffmpeg")
    plan = _plan(case, tmp_path)
    video = FFmpegRenderer("ffmpeg").render(plan, tmp_path / "encoded.mp4")
    assert video.stat().st_size > 0
    assert EncodedMotionVerifier().inspect(video=video, plan=plan).ok


@pytest.mark.parametrize("case", full_render_cases(), ids=lambda case: str(case.seed))
def test_representative_full_muxed_renders(tmp_path: Path, case) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.fail("Sprint 3.75 certification requires ffmpeg and ffprobe")
    plan = _plan(case, tmp_path)
    video = FFmpegRenderer("ffmpeg").render(plan, tmp_path / "video.mp4")
    audio = tmp_path / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{plan.duration:.3f}", "-c:a", "pcm_s16le", str(audio)], check=True)
    final = FinalExporter("ffmpeg").mux(video, audio, tmp_path / "final.mp4")
    issues = FinalMediaVerifier("ffprobe", "ffmpeg").inspect(
        final, audio, first_spoken_start=plan.story[0].audio_start,
    )
    assert issues == []
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(final)], check=True, capture_output=True, text=True).stdout)
    assert {row["codec_type"] for row in probe["streams"]} >= {"video", "audio"}
    stream = next(row for row in probe["streams"] if row["codec_type"] == "video")
    assert stream["codec_name"] == "h264" and stream["r_frame_rate"] == "30/1"
    decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", str(final), "-f", "null", "-"], capture_output=True, text=True)
    assert decoded.returncode == 0 and not decoded.stderr.strip()
    assert EncodedMotionVerifier().inspect(video=final, plan=plan).ok
