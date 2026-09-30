"""Tiered certification of the real Unified Final Package 2.0 corpus.

Level A  Structural     ZIP + strict schema + references + ids + images
Level B  Semantic       canonical mapping preserves semantic truth
Level C  Visual plan    Vision + Pass1 + Pass2 + Story (carrier + hidden-art gates)
Level D  Montage plan   Choreography + Composition + Motion + Text + RenderPlan
Level E  Encoded        FFmpeg encode + ffprobe + decode + encoded motion QA

A-D run whenever ``HEXA_REAL_PACKAGE_CORPUS`` is set. E is heavy (a full-length
encode per package) and additionally requires ``HEXA_REAL_PACKAGE_ENCODE=1``.
Failures are labelled with their level so CI shows which stage broke.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.final_package import FinalPackageLoader
from app.models import RenderPlan
from app.render.renderer import FFmpegRenderer
from app.render.verification import EncodedMotionVerifier
from app.shared.errors import HexaError
from tests.test1.certification.test_real_package_planning import (
    _REAL_PACKAGES,
    _corpus_root,
    certify_real_package_to_render_plan,
)


def _corpus() -> Path:
    corpus = _corpus_root()
    if corpus is None:
        pytest.skip("real Final Package corpus is not installed in this CI environment")
    return corpus


def _level(level: str, filename: str, exc: Exception) -> None:
    details = getattr(exc, "details", None)
    pytest.fail(f"LEVEL {level} FAILED for {filename}: {exc} {json.dumps(details, default=str)[:4000]}")


@pytest.mark.parametrize("filename", _REAL_PACKAGES)
def test_level_a_structural(tmp_path: Path, filename: str) -> None:
    source = _corpus() / filename
    if not source.is_file():
        pytest.fail(f"LEVEL A FAILED: missing {filename}")
    with zipfile.ZipFile(source) as archive:
        assert archive.testzip() is None, f"LEVEL A FAILED: corrupt entry in {filename}"
        names = [name for name in archive.namelist() if not name.endswith("/")]
    assert "package.json" in names
    assert all(name == "package.json" or name.startswith("images/") for name in names)
    try:
        package = FinalPackageLoader().load(source, tmp_path / "load")
    except HexaError as exc:
        _level("A", filename, exc)
    assert all(scene.image_path.is_file() for scene in package.scenes)


@pytest.mark.parametrize("filename", _REAL_PACKAGES)
def test_level_b_semantic(tmp_path: Path, filename: str) -> None:
    source = _corpus() / filename
    package = FinalPackageLoader().load(source, tmp_path / "load")
    with zipfile.ZipFile(source) as archive:
        raw = json.loads(archive.read("package.json"))
    raw_objects = [row for scene in raw["scenes"] for row in scene["objects"]]
    raw_events = [row for scene in raw["scenes"] for row in scene["semantic_events"]]
    raw_relations = [row for scene in raw["scenes"] for row in scene["relations"]]
    assert len(package.scenes) == len(raw["scenes"])
    assert sum(len(scene.units) for scene in package.scenes) == len(raw_objects)
    assert len(package.event_by_id) == len(raw_events)
    assert sum(len(scene.relations) for scene in package.scenes) == len(raw_relations)
    for scene in package.scenes:
        unit_ids = {unit.asset_id for unit in scene.units}
        assert set(scene.semantic_carrier_roles) <= unit_ids, f"LEVEL B FAILED: {scene.id}"


@pytest.mark.parametrize("filename", _REAL_PACKAGES)
def test_level_c_d_visual_and_montage_planning(tmp_path: Path, filename: str) -> None:
    try:
        result = certify_real_package_to_render_plan(_corpus(), filename, tmp_path / filename)
    except HexaError as exc:
        _level("C/D", filename, exc)
    assert result.story_beats == result.scenes
    assert result.motion_cues == result.runtime_assets


@pytest.mark.skipif(
    os.getenv("HEXA_REAL_PACKAGE_ENCODE") != "1" or shutil.which("ffprobe") is None,
    reason="Level E full-length encode requires HEXA_REAL_PACKAGE_ENCODE=1 and ffmpeg",
)
@pytest.mark.parametrize("filename", _REAL_PACKAGES)
def test_level_e_encoded_render(tmp_path: Path, filename: str) -> None:
    workspace = tmp_path / filename
    try:
        result = certify_real_package_to_render_plan(_corpus(), filename, workspace)
    except HexaError as exc:
        _level("C/D", filename, exc)
    assert result.plan_path is not None and result.plan_path.is_file()
    plan = RenderPlan.model_validate_json(result.plan_path.read_text(encoding="utf-8"))
    video = tmp_path / "certified.mp4"
    try:
        FFmpegRenderer("ffmpeg").render(plan, video)
    except HexaError as exc:
        _level("E", filename, exc)

    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_streams", "-show_entries", "packet=pts_time", "-of", "json", str(video)],
        check=True, capture_output=True, text=True,
    ).stdout)
    stream = probe["streams"][0]
    assert stream["codec_name"] == "h264"
    assert (stream["width"], stream["height"]) == (1920, 1080)
    assert stream["r_frame_rate"] == "30/1" and stream["avg_frame_rate"] == "30/1"
    assert abs(int(stream["nb_read_frames"]) - round(plan.duration * plan.fps)) <= 1
    assert min(float(row["pts_time"]) for row in probe["packets"]) >= 0.0
    decode = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert decode.returncode == 0 and not decode.stderr.strip(), decode.stderr[:2000]
    report = EncodedMotionVerifier().inspect(video=video, plan=plan)
    assert report.ok, f"LEVEL E FAILED for {filename}: {report.violations[:5]}"
