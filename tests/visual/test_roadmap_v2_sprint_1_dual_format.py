"""Roadmap V2 Sprint 1.1 - one YouTube edit, uniformly projected to Reels.

One Final Package generation produces YOUTUBE_16_9 (1920x1080) and REELS_9_16
(1080x1920) through the same Story, Choreography, Composition, Motion, Text, Boundary
and Render engines. Reels projects the finished reference RenderPlan with one affine
transform. Semantics, narration timing, text
wording/timing/ownership and Motion grammar are identical. Every target-sensitive check
here parameterizes over ``SUPPORTED_VISUAL_TARGETS`` so a future change to any shared
visual layer is exercised against every format automatically.
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.config import RenderResourceSettings, Settings
from app.final.bundle import INCOMPLETE_MARKER, ExportBundleWriter
from app.layout.footprint import AlphaFootprintResolver
from app.render.connection import connection_specs
from app.models import RenderPlan
from app.pipeline import StoryEnginePipeline
from app.render.renderer import FFmpegRenderer
from app.render.resources import RenderConcurrencyPolicy
from app.shared.errors import GenerationCancelledError, StageFailedError
from app.targets import (
    REFERENCE_TARGET,
    REELS_9_16,
    SUPPORTED_VISUAL_TARGETS,
    YOUTUBE_16_9,
    VisualTargetProfile,
    target_by_id,
)
from app.targets.parity import motion_semantics, semantic_differences, semantic_signature
from tests.support.unified_package import write_unified_package

ROOT = Path(__file__).resolve().parents[2]
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe required")
TARGET_IDS = [target.target_id for target in SUPPORTED_VISUAL_TARGETS]
by_target = pytest.mark.parametrize("target_id", TARGET_IDS)

SCRIPT = (
    "The red block starts the idea. The green circle and the blue bar follow it. "
    "Then the orange result appears with a purple support."
)
SCENE_1 = "The red block starts the idea. The green circle and the blue bar follow it."
SCENE_2 = "Then the orange result appears with a purple support."
IMAGE = (640, 360)
# (asset_id, role, semantic role, phrase, shape, colour, cx, cy, w, h) in normalized scene units.
SHAPES = {
    "s1": [
        ("a_red", "primary", "CHARACTER", "red block", "rect", (220, 30, 30), 0.20, 0.52, 0.22, 0.62),
        ("a_green", "support", "OBJECT", "green circle", "ellipse", (30, 170, 60), 0.52, 0.50, 0.18, 0.32),
        ("a_blue", "support", "OBJECT", "blue bar", "rect", (30, 60, 220), 0.81, 0.55, 0.16, 0.24),
    ],
    "s2": [
        ("b_orange", "result", "RESULT", "orange result", "ellipse", (240, 140, 20), 0.33, 0.50, 0.26, 0.52),
        ("b_purple", "support", "OBJECT", "purple support", "rect", (140, 40, 170), 0.72, 0.52, 0.18, 0.30),
    ],
}


def _span(text: str, start: int) -> dict:
    return {"text": text, "global_char_start": start, "global_char_end": start + len(text)}


def _write_package(root: Path) -> Path:
    scenes = []
    for order, (scene_id, sentence) in enumerate((("s1", SCENE_1), ("s2", SCENE_2))):
        start = SCRIPT.index(sentence)
        assets = []
        for asset_id, role, semantic, phrase, _, _, cx, cy, w, h in SHAPES[scene_id]:
            at = SCRIPT.index(phrase)
            assets.append({
                "asset_id": asset_id, "role": role, "semantic_role": semantic,
                "script_text": phrase, "script_span": _span(phrase, at),
                "appear_trigger": _span(phrase, at), "binding_type": "EXPLICIT",
                "visual_focus": "PRIMARY" if role == "primary" else role.upper(),
                "visual_locator": {"coordinate_space": "normalized_scene",
                                   "cx": cx, "cy": cy, "width": w, "height": h},
            })
        scenes.append({"scene_id": scene_id, "order": order,
                       "script_span": _span(sentence, start), "assets": assets})
    package = write_unified_package(root, script=SCRIPT, package_id="dual-format-gate",
                                    image_size=IMAGE, scenes=scenes)
    for scene_id, rows in SHAPES.items():
        image = Image.new("RGB", IMAGE, "white")
        draw = ImageDraw.Draw(image)
        for *_, shape, colour, cx, cy, w, h in rows:
            box = ((cx - w / 2) * IMAGE[0] + 6, (cy - h / 2) * IMAGE[1] + 6,
                   (cx + w / 2) * IMAGE[0] - 6, (cy + h / 2) * IMAGE[1] - 6)
            (draw.ellipse if shape == "ellipse" else draw.rectangle)(box, fill=colour)
        image.save(package / "images" / f"{scene_id}.png")
    return package


def _write_wav(path: Path, seconds: float = 7.0, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(struct.pack("<h", 0) for _ in range(int(seconds * rate))))


def _settings(tmp: Path, export_root: Path) -> Settings:
    return Settings(
        work_root=tmp / "work", output_root=tmp / "outputs", ffmpeg_bin="ffmpeg",
        ffprobe_bin="ffprobe", whisper_model="small", engine_host="127.0.0.1",
        engine_port=8765, allow_scene_fallback=False,
        render_resources=RenderResourceSettings(workers_override=1),
        export_root=export_root, export_min_free_bytes=0, work_min_free_bytes=0,
    )


def _ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(out.stdout)


def _frame_times(path: Path) -> list[float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "packet=pts_time", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return sorted(float(row) for row in out.stdout.split() if row.strip())


def _decode_frame(path: Path, seconds: float, size: tuple[int, int]) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{seconds:.4f}", "-i", str(path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(size[1], size[0], 3)


# -- generation (once per module) -------------------------------------------------------
@pytest.fixture(scope="module")
def bundle_run(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg/ffprobe required")
    tmp = tmp_path_factory.mktemp("dual-format")
    package = _write_package(tmp / "package")
    audio = tmp / "voice.wav"
    _write_wav(audio)
    export_root = tmp / "HEXA" / "Exports"
    pipeline = StoryEnginePipeline(_settings(tmp, export_root))
    first = pipeline.generate_bundle(package_path=package, audio_path=audio, job_id="gate-1")
    v1_files = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in first.directory.iterdir()}
    second = pipeline.generate_bundle(package_path=package, audio_path=audio, job_id="gate-2")
    plans = {
        target_id: RenderPlan.model_validate_json(output.render_plan_path.read_text(encoding="utf-8"))
        for target_id, output in first.outputs.items()
    }
    return {"tmp": tmp, "package": package, "audio": audio, "export_root": export_root,
            "pipeline": pipeline, "first": first, "second": second, "v1_files": v1_files,
            "plans": plans}


# -- target registry ---------------------------------------------------------------------
def test_registry_holds_both_formats() -> None:
    assert TARGET_IDS == ["YOUTUBE_16_9", "REELS_9_16"]
    assert REFERENCE_TARGET is YOUTUBE_16_9
    assert {(t.width, t.height, t.fps) for t in SUPPORTED_VISUAL_TARGETS} == {
        (1920, 1080, 30), (1080, 1920, 30),
    }


@by_target
def test_target_safe_regions_are_valid(target_id: str) -> None:
    zones = target_by_id(target_id).safe_zones
    for rect in (zones.content, zones.text):
        assert rect.width > 0.5 and rect.height > 0.5
        assert not any(r.intersects((rect.left, rect.top, rect.right, rect.bottom)) for r in zones.reserved)


# -- architecture: one engine ------------------------------------------------------------
SHARED_VISUAL_PACKAGES = ("choreography", "composition", "motion", "text", "boundary", "render", "story")


def test_no_format_branches_or_forks_in_shared_engines() -> None:
    """Shared engines read frame facts from the active target, never format names."""
    offenders = []
    for package in SHARED_VISUAL_PACKAGES:
        for path in (ROOT / "app" / package).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"REELS|YOUTUBE|[Rr]eels|[Yy]ou[Tt]ube|9_16|16_9", text):
                offenders.append(f"{path.relative_to(ROOT)}: format name")
            for number in re.findall(r"(?<![\w.])(1920|1080)(?:\.0)?(?![\w.])", text):
                offenders.append(f"{path.relative_to(ROOT)}: hard-coded {number}")
    # The renderer's resource policy measures against the certified 1080p reference.
    offenders = [row for row in offenders if not row.startswith(str(Path("app/render/resources.py")))
                 and "verification.py: hard-coded" not in row]
    assert offenders == []
    for forbidden in ("reels/story.py", "reels/choreography.py", "reels/motion.py",
                      "youtube/story.py", "youtube/motion.py"):
        assert not (ROOT / "app" / "targets" / forbidden).exists()
    assert not (ROOT / "app" / "reels").exists()


def test_renderer_is_format_blind() -> None:
    source = (ROOT / "app" / "render" / "renderer.py").read_text(encoding="utf-8")
    assert "target_id" not in source and "app.targets" not in source


# -- shared semantics --------------------------------------------------------------------
@needs_ffmpeg
def test_both_formats_share_every_semantic(bundle_run) -> None:
    plans = bundle_run["plans"]
    reference = plans[REFERENCE_TARGET.target_id]
    for target_id, plan in plans.items():
        assert semantic_differences(reference, plan) == [], target_id
    signature = semantic_signature(reference)
    assert signature["story"] and signature["motion"]
    for plan in plans.values():
        assert [b.id for b in plan.story] == [b.id for b in reference.story]
        assert [(b.audio_start, b.audio_end, b.start, b.end) for b in plan.story] == [
            (b.audio_start, b.audio_end, b.start, b.end) for b in reference.story]
        assert [c.text for c in plan.text.cues] == [c.text for c in reference.text.cues]
        assert [(c.spoken_start, c.spoken_end, c.anchor_asset_id) for c in plan.text.cues] == [
            (c.spoken_start, c.spoken_end, c.anchor_asset_id) for c in reference.text.cues]
        assert [b.semantic_focus_asset_id for b in plan.composition] == [
            b.semantic_focus_asset_id for b in reference.composition]
        assert sorted(motion_semantics(c)["kind"] for c in plan.motion) == sorted(
            motion_semantics(c)["kind"] for c in reference.motion)


# -- target geometry ---------------------------------------------------------------------
@needs_ffmpeg
@by_target
def test_target_geometry_is_valid(bundle_run, target_id: str) -> None:
    plan = bundle_run["plans"][target_id]
    target = target_by_id(target_id)
    assert (plan.width, plan.height, plan.fps, plan.target_id) == (target.width, target.height, 30, target_id)
    feet = AlphaFootprintResolver()
    assets = {a.id: a for a in plan.assets}
    for layout in plan.composition:
        boxes = []
        for item in layout.items:
            assert item.width > 0 and item.height > 0
            box = feet.resolve(item, assets[item.asset_id]).box
            assert target.safe_zones.content.contains(box, tolerance=0.004), (target_id, item.asset_id)
            assert not any(r.intersects(box) for r in target.safe_zones.reserved)
            boxes.append(box)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                overlap = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
                assert not (overlap[0] > 0.002 and overlap[1] > 0.002), "illegal overlap"


@needs_ffmpeg
def test_reels_is_exact_uniform_reference_projection(bundle_run) -> None:
    youtube, reels = bundle_run["plans"]["YOUTUBE_16_9"], bundle_run["plans"]["REELS_9_16"]
    projection = reels.projection
    assert youtube.projection is None and projection is not None
    safe = REELS_9_16.safe_zones.content
    expected_scale = min(safe.width * 1080 / 1920, safe.height * 1920 / 1080)
    assert projection.scale == pytest.approx(expected_scale, abs=1e-12)
    assert projection.offset_x == pytest.approx(
        safe.left * 1080 + (safe.width * 1080 - 1920 * expected_scale) / 2, abs=1e-9)
    assert projection.offset_y == pytest.approx(
        safe.top * 1920 + (safe.height * 1920 - 1080 * expected_scale) / 2, abs=1e-9)
    for reference_beat, target_beat in zip(youtube.composition, reels.composition):
        assert reference_beat.beat_id == target_beat.beat_id
        assert reference_beat.semantic_focus_asset_id == target_beat.semantic_focus_asset_id
        assert [item.asset_id for item in reference_beat.items] == [item.asset_id for item in target_beat.items]
        for ref, item in zip(reference_beat.items, target_beat.items):
            assert item.x * 1080 == pytest.approx(projection.offset_x + ref.x * 1920 * expected_scale, abs=1e-7)
            assert item.y * 1920 == pytest.approx(projection.offset_y + ref.y * 1080 * expected_scale, abs=1e-7)
            assert item.width * 1080 == pytest.approx(ref.width * 1920 * expected_scale, abs=1e-7)
            assert item.height * 1920 == pytest.approx(ref.height * 1080 * expected_scale, abs=1e-7)
            assert item.z == ref.z and item.placement_source == "projected_reference"
        for index, a in enumerate(reference_beat.items):
            for j, b in enumerate(reference_beat.items[index + 1:], start=index + 1):
                ra, rb = target_beat.items[index], target_beat.items[j]
                for axis in ("x", "y"):
                    delta = getattr(a, axis) - getattr(b, axis)
                    projected_delta = getattr(ra, axis) - getattr(rb, axis)
                    assert np.sign(delta) == np.sign(projected_delta)
                source_distance = np.hypot((a.x - b.x) * 1920, (a.y - b.y) * 1080)
                target_distance = np.hypot((ra.x - rb.x) * 1080, (ra.y - rb.y) * 1920)
                assert target_distance == pytest.approx(source_distance * expected_scale, abs=1e-7)
                assert (ra.width / rb.width) == pytest.approx(a.width / b.width, abs=1e-9)
    assert reels.scene_boundaries == youtube.scene_boundaries
    assert reels.text == youtube.text and reels.text_motion == youtube.text_motion
    for reference_beat, target_beat in zip(youtube.text_composition, reels.text_composition):
        assert reference_beat.beat_id == target_beat.beat_id
        for ref, item in zip(reference_beat.items, target_beat.items):
            assert item.text_cue_id == ref.text_cue_id and item.anchor_asset_id == ref.anchor_asset_id
            assert item.x * 1080 == pytest.approx(projection.offset_x + ref.x * 1920 * expected_scale, abs=1e-7)
            assert item.y * 1920 == pytest.approx(projection.offset_y + ref.y * 1080 * expected_scale, abs=1e-7)
            assert item.max_width * 1080 == pytest.approx(ref.max_width * 1920 * expected_scale, abs=1e-7)
            assert item.font_scale == ref.font_scale and item.z == ref.z
    for ref, cue in zip(youtube.motion, reels.motion):
        assert (ref.beat_id, ref.asset_id, ref.kind, ref.start, ref.end) == (
            cue.beat_id, cue.asset_id, cue.kind, cue.start, cue.end)
        for ref_program, target_program in zip(_programs(ref), _programs(cue)):
            for a, b in zip(ref_program.get("keyframes", []), target_program.get("keyframes", [])):
                assert b["dx"] * 1080 == pytest.approx(a["dx"] * 1920 * expected_scale, abs=1e-7)
                assert b["dy"] * 1920 == pytest.approx(a["dy"] * 1080 * expected_scale, abs=1e-7)
                assert {k: v for k, v in b.items() if k not in {"dx", "dy"}} == {
                    k: v for k, v in a.items() if k not in {"dx", "dy"}}
    assert all(i.placement_source.startswith("authored_scene") or i.placement_source.startswith("authored_semantic")
               for b in youtube.composition for i in b.items)


@needs_ffmpeg
def test_connectors_are_projected_without_rerouting(bundle_run) -> None:
    youtube, reels = bundle_run["plans"]["YOUTUBE_16_9"], bundle_run["plans"]["REELS_9_16"]
    scale = reels.projection.scale
    for ref_beat, target_beat, ref_layout, target_layout in zip(
        youtube.story, reels.story, youtube.composition, reels.composition,
    ):
        def specs(beat, layout, plan):
            items = {
                item.asset_id: (
                    (item.x - item.width / 2) * plan.width,
                    (item.y - item.height / 2) * plan.height,
                    (item.x + item.width / 2) * plan.width,
                    (item.y + item.height / 2) * plan.height,
                ) for item in layout.items
            }
            cues = {cue.asset_id: cue for cue in plan.motion if cue.beat_id == beat.id}
            return connection_specs(
                beat=beat, items=items, cues=cues, segment_start=beat.start,
                duration=beat.end - beat.start,
                spatial_scale=plan.projection.scale if plan.projection else 1.0,
            )
        source = specs(ref_beat, ref_layout, youtube)
        projected = specs(target_beat, target_layout, reels)
        assert len(source) == len(projected), ref_beat.id
        for a, b in zip(source, projected):
            assert (a.start, a.end) == (b.start, b.end)
            for p, q in ((a.p0, b.p0), (a.p1, b.p1)):
                assert q[0] == pytest.approx(reels.projection.offset_x + p[0] * scale, abs=1e-6)
                assert q[1] == pytest.approx(reels.projection.offset_y + p[1] * scale, abs=1e-6)


@needs_ffmpeg
def test_production_reels_never_invokes_reflow_or_second_visual_authoring(bundle_run, tmp_path, monkeypatch) -> None:
    from app.targets.reels.composition import ReelsCompositionPolicy

    def forbidden(*_args, **_kwargs):
        pytest.fail("responsive Reels policy entered production")

    monkeypatch.setattr(ReelsCompositionPolicy, "project", forbidden)
    pipeline = StoryEnginePipeline(_settings(tmp_path, tmp_path / "exports"))
    counts = {name: 0 for name in ("composition", "motion", "text_composition", "boundary")}
    for name, owner in (("composition", pipeline.composition), ("motion", pipeline.motion),
                        ("text_composition", pipeline.text_composition),
                        ("boundary", pipeline.scene_boundaries)):
        original = owner.plan
        def counted(*args, _name=name, _original=original, **kwargs):
            counts[_name] += 1
            return _original(*args, **kwargs)
        monkeypatch.setattr(owner, "plan", counted)
    pipeline.generate_bundle(
        package_path=bundle_run["package"], audio_path=bundle_run["audio"], job_id="no-relayout",
    )
    assert counts == {name: 1 for name in counts}


@needs_ffmpeg
@by_target
def test_text_stays_in_text_safe_frame(bundle_run, target_id: str) -> None:
    from app.composition.text_director import TextPlacementDirector
    from app.targets import visual_target

    plan = bundle_run["plans"][target_id]
    target = target_by_id(target_id)
    cues = {c.id: c for c in plan.text.cues}
    with visual_target(REFERENCE_TARGET if plan.projection else target):
        for beat in plan.text_composition:
            for item in beat.items:
                w, h = TextPlacementDirector.estimated_box(cues[item.text_cue_id], scale=item.font_scale)
                if plan.projection:
                    w *= plan.projection.reference_width * plan.projection.scale / plan.width
                    h *= plan.projection.reference_height * plan.projection.scale / plan.height
                box = (item.x - w / 2, item.y - h / 2, item.x + w / 2, item.y + h / 2)
                text_safe = target.safe_zones.text if not plan.projection else target.safe_zones.content
                assert text_safe.contains(box, tolerance=0.002)
                assert not any(r.intersects(box) for r in target.safe_zones.reserved)


# -- final settle ------------------------------------------------------------------------
def _programs(cue):
    program = cue.params.get("program")
    if isinstance(program, dict):
        yield program
    for segment in cue.segments:
        if segment.program:
            yield segment.program


@needs_ffmpeg
@by_target
def test_motion_settles_exactly_on_target_composition(bundle_run, target_id: str) -> None:
    plan = bundle_run["plans"][target_id]
    for cue in plan.motion:
        for program in _programs(cue):
            frames = program.get("keyframes") or []
            if not frames:
                continue
            final = max(frames, key=lambda f: float(f.get("progress", 0.0)))
            assert abs(float(final.get("dx", 0.0))) < 1e-9, (cue.asset_id, program.get("name"))
            assert abs(float(final.get("dy", 0.0))) < 1e-9
            assert abs(float(final.get("scale", 1.0)) - 1.0) < 1e-9


@needs_ffmpeg
@by_target
def test_encoded_settled_geometry_matches_composition(bundle_run, target_id: str) -> None:
    """Decoded settled frame: each coloured asset sits exactly on its Composition box."""
    output = bundle_run["first"].outputs[target_id]
    plan = bundle_run["plans"][target_id]
    beat = plan.story[-1]
    layout = next(b for b in plan.composition if b.beat_id == beat.id)
    when = min(plan.duration, beat.end) - 2.0 / plan.fps
    frame = _decode_frame(output.path, when, (plan.width, plan.height)).astype(int)
    colours = {row[0]: row[5] for rows in SHAPES.values() for row in rows}
    feet = AlphaFootprintResolver()
    assets = {a.id: a for a in plan.assets}
    for item in layout.items:
        colour = next((c for key, c in colours.items() if key in item.asset_id), None)
        if colour is None:
            continue
        mask = (np.abs(frame - np.array(colour)).sum(axis=2) < 60)
        ys, xs = np.nonzero(mask)
        assert xs.size > 200, (target_id, item.asset_id)
        box = feet.resolve(item, assets[item.asset_id]).box
        expected = (box[0] * plan.width, box[1] * plan.height, box[2] * plan.width, box[3] * plan.height)
        found = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
        for got, want in zip(found, expected):
            assert abs(got - want) <= 4.0, (target_id, item.asset_id, found, expected)


# -- RenderPlan --------------------------------------------------------------------------
@needs_ffmpeg
def test_render_plans_share_duration_and_frame_grid(bundle_run) -> None:
    plans = bundle_run["plans"]
    assert {(p.duration, p.fps, round(p.duration * p.fps)) for p in plans.values()}.__len__() == 1
    assert {p.target_id for p in plans.values()} == set(TARGET_IDS)
    assert plans["YOUTUBE_16_9"].story == plans["REELS_9_16"].story


# -- encode + media ----------------------------------------------------------------------
@needs_ffmpeg
@by_target
def test_encoded_output_contract(bundle_run, target_id: str) -> None:
    output = bundle_run["first"].outputs[target_id]
    target = target_by_id(target_id)
    probe = _ffprobe(output.path)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert video["codec_name"] == "h264" and audio["codec_name"] == "aac"
    assert (video["width"], video["height"]) == (target.width, target.height)
    assert video["r_frame_rate"] == video["avg_frame_rate"] == "30/1"  # CFR
    times = _frame_times(output.path)
    assert times[0] >= 0.0 and all(b > a for a, b in zip(times, times[1:]))
    assert len(times) == output.frame_count
    deltas = np.diff(times)
    assert np.allclose(deltas, 1 / 30, atol=1e-3)
    decode = subprocess.run(["ffmpeg", "-v", "error", "-i", str(output.path), "-f", "null", "-"],
                            capture_output=True, text=True)
    assert decode.returncode == 0 and decode.stderr.strip() == ""
    assert output.encoded_motion_ok and output.final_media_ok
    assert bundle_run["pipeline"].final_media.inspect(output.path, bundle_run["audio"]) == []


@needs_ffmpeg
def test_no_second_video_encode(bundle_run) -> None:
    source = (ROOT / "app" / "final" / "exporter.py").read_text(encoding="utf-8")
    assert source.count('"-c:v", "copy"') >= 2
    pipeline_source = (ROOT / "app" / "pipeline.py").read_text(encoding="utf-8")
    assert "crop=" not in pipeline_source and "pad=" not in pipeline_source


# -- export bundle -----------------------------------------------------------------------
@needs_ffmpeg
def test_bundle_versions_and_manifest(bundle_run) -> None:
    first, second = bundle_run["first"], bundle_run["second"]
    root = bundle_run["export_root"]
    assert first.directory == root / first.slug / "v1"
    assert second.directory == root / first.slug / "v2"
    assert first.slug == "DUAL-FORMAT-GATE"
    assert {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in first.directory.iterdir()} == bundle_run["v1_files"]
    for bundle in (first, second):
        assert ExportBundleWriter.is_complete(bundle.directory)
        assert not (bundle.directory / INCOMPLETE_MARKER).exists()
        names = sorted(p.name for p in bundle.directory.iterdir())
        assert names == [f"{first.slug}_REELS.mp4", f"{first.slug}_YOUTUBE.mp4", "export.json"]
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["completed"] is True and manifest["export_version"] == 1
    for key in ("package_id", "project_slug", "source_package_fingerprint", "generated_at",
                "shared_story_fingerprint", "shared_choreography_fingerprint", "engine_git_sha"):
        assert key in manifest
    assert set(manifest["outputs"]) == set(TARGET_IDS)
    for target_id, row in manifest["outputs"].items():
        target = target_by_id(target_id)
        assert (row["width"], row["height"], row["fps"]) == (target.width, target.height, 30)
        assert row["video_codec"] == "h264" and row["audio_codec"] == "aac"
        assert row["encoded_motion_verification"] == row["final_media_verification"] == "PASS"
        assert len(row["render_plan_fingerprint"]) == 64
    assert "token" not in json.dumps(manifest).lower()


def _run_failing(bundle_run, tmp: Path, monkeypatch, *, fail_target: VisualTargetProfile | None,
                 cancel_after_first: bool = False):
    pipeline = StoryEnginePipeline(_settings(tmp, bundle_run["export_root"]))
    real = pipeline._render_target
    calls = {"n": 0}

    def render(shared, target, *args, **kwargs):
        calls["n"] += 1
        if target is fail_target:
            raise StageFailedError("simulated render failure", details={"code": "SIMULATED"})
        return real(shared, target, *args, **kwargs)

    monkeypatch.setattr(pipeline, "_render_target", render)
    state = {"cancel": False}
    if cancel_after_first:
        def cancelled() -> bool:
            return calls["n"] >= 1 and state.setdefault("armed", True)
    else:
        def cancelled() -> bool:
            return False
    return pipeline, cancelled


@needs_ffmpeg
@pytest.mark.parametrize("fail_id", TARGET_IDS)
def test_partial_failure_never_publishes(bundle_run, tmp_path: Path, monkeypatch, fail_id: str) -> None:
    pipeline, _ = _run_failing(bundle_run, tmp_path, monkeypatch, fail_target=target_by_id(fail_id))
    package_dir = bundle_run["export_root"] / bundle_run["first"].slug
    before = sorted(p.name for p in package_dir.iterdir())
    with pytest.raises(StageFailedError):
        pipeline.generate_bundle(package_path=bundle_run["package"], audio_path=bundle_run["audio"],
                                 job_id=f"fail-{fail_id}")
    created = sorted(set(p.name for p in package_dir.iterdir()) - set(before))
    assert len(created) == 1 and re.fullmatch(r"v\d+\.failed-[0-9a-f]{8}", created[0])
    assert not ExportBundleWriter.is_complete(package_dir / created[0])
    for name in before:
        if re.fullmatch(r"v\d+", name):
            assert ExportBundleWriter.is_complete(package_dir / name)


@needs_ffmpeg
def test_cancellation_between_targets_stops_cleanly(bundle_run, tmp_path: Path, monkeypatch) -> None:
    pipeline, cancelled = _run_failing(bundle_run, tmp_path, monkeypatch, fail_target=None,
                                       cancel_after_first=True)
    package_dir = bundle_run["export_root"] / bundle_run["first"].slug
    before = set(p.name for p in package_dir.iterdir())
    with pytest.raises(GenerationCancelledError):
        pipeline.generate_bundle(package_path=bundle_run["package"], audio_path=bundle_run["audio"],
                                 job_id="cancel-1", cancelled=cancelled)
    created = sorted(set(p.name for p in package_dir.iterdir()) - before)
    assert len(created) == 1 and ".failed-" in created[0]
    assert not ExportBundleWriter.is_complete(package_dir / created[0])
    psutil = pytest.importorskip("psutil")
    children = [p.name().lower() for p in psutil.Process().children(recursive=True)]
    assert not any(name.startswith("ffmpeg") for name in children)  # no orphan encoders


@needs_ffmpeg
def test_unavailable_export_root_fails_before_work(bundle_run, tmp_path: Path) -> None:
    blocked = tmp_path / "file-not-dir"
    blocked.write_text("x")
    pipeline = StoryEnginePipeline(_settings(tmp_path, blocked / "Exports"))
    with pytest.raises(StageFailedError) as error:
        pipeline.generate_bundle(package_path=bundle_run["package"], audio_path=bundle_run["audio"],
                                 job_id="no-root")
    assert error.value.details["code"] == "EXPORT_ROOT_UNAVAILABLE"
    assert not (tmp_path / "work" / "no-root" / "render-plan.json").exists()


def test_missing_export_root_fails_before_planning_without_fallback(tmp_path: Path, monkeypatch) -> None:
    from dataclasses import replace

    settings = replace(_settings(tmp_path, tmp_path / "configured"), export_root=None)
    pipeline = StoryEnginePipeline(settings)

    def unexpected_plan(**kwargs):
        pytest.fail("semantic planning started without a production export root")

    monkeypatch.setattr(pipeline, "_plan_shared", unexpected_plan)
    with pytest.raises(StageFailedError) as error:
        pipeline.generate_bundle(
            package_path=tmp_path / "package", audio_path=tmp_path / "voice.wav",
            job_id="missing-root",
        )
    assert error.value.effective_code == "EXPORT_ROOT_UNAVAILABLE"
    assert "not configured" in str(error.value)
    assert not (settings.output_root / "exports").exists()
    assert not (settings.work_root / "missing-root").exists()


# -- resource control --------------------------------------------------------------------
@by_target
def test_sprint_5_1_worker_policy_applies_per_target(target_id: str) -> None:
    target = target_by_id(target_id)
    policy = RenderConcurrencyPolicy(RenderResourceSettings(workers_override=None))
    workers = policy.workers(width=target.width, height=target.height)
    assert 1 <= workers <= 4
    assert RenderConcurrencyPolicy(RenderResourceSettings(workers_override=3)).workers(
        width=target.width, height=target.height) == 3


@needs_ffmpeg
@by_target
def test_intermediates_cleaned_and_sources_kept(bundle_run, target_id: str) -> None:
    output = bundle_run["first"].outputs[target_id]
    render_dir = output.render_plan_path.parent / "render"
    leftovers = [p for p in render_dir.rglob("*") if p.is_file()] if render_dir.exists() else []
    assert leftovers == []
    plan = bundle_run["plans"][target_id]
    assert all(asset.image_path.is_file() for asset in plan.assets)
    assert output.path.is_file() and output.path.stat().st_size > 0


def test_renderer_cleanup_is_resolution_independent(tmp_path: Path) -> None:
    for target in SUPPORTED_VISUAL_TARGETS:
        out = tmp_path / target.target_id / "video-only.mp4"
        segments = out.parent / "video-only-segments"
        segments.mkdir(parents=True)
        (segments / "0001-beat-001.mp4").write_bytes(b"x")
        keep = out.parent / "source.png"
        keep.write_bytes(b"src")
        FFmpegRenderer.cleanup_intermediates(out, source_paths={keep})
        assert keep.is_file() and not (segments / "0001-beat-001.mp4").exists()
