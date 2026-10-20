"""Editable Premiere Pro project of a RenderPlan (user direction 2026-10-21).

The project is proven from the outside: an independent reader (tests.support.premiere_check)
composites frames from the XML alone and they must match the encoded video of the same
plan. The units, the keyframe reduction, the clip stacking and every failure path (a
missing cutout, a segment that cannot be authored) are covered too: a broken layer is
skipped and reported, never a stop.
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.final.premiere import (
    PremiereClip,
    PremiereExporter,
    _ass_window,
    _keyframes,
    _opacity,
    _url,
)
from app.render.renderer import FFmpegRenderer
from app.shared.errors import StageFailedError
from tests.support import premiere_check

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


def test_a_straight_line_needs_only_its_two_ends() -> None:
    line = [(float(k), 2.0 * k) for k in range(60)]
    assert _keyframes(line, (0.35, 0.35)) == [0, 59]


def test_an_eased_arrival_keeps_the_keyframes_its_curve_needs() -> None:
    curve = [(1 - (1 - k / 29) ** 3,) for k in range(30)] + [(1.0,)] * 30
    keep = _keyframes([(value * 400,) for (value,) in curve], (0.35,))
    assert keep[0] == 0 and keep[-1] == 59 and 2 < len(keep) < 30  # the flat hold needs no keys
    for left, right in zip(keep, keep[1:]):  # every sample within tolerance of its line
        for k in range(left, right + 1):
            u = (k - left) / max(1, right - left)
            line = curve[left][0] * 400 + (curve[right][0] - curve[left][0]) * 400 * u
            assert abs(curve[k][0] * 400 - line) <= 0.35 + 1e-9


def test_fades_multiply_like_the_renderer() -> None:
    fades = (("in", 1.0, 0.5), ("out", 3.0, 1.0))
    assert _opacity(fades, 0.9) == 0.0
    assert _opacity(fades, 1.25) == pytest.approx(0.5)
    assert _opacity(fades, 2.0) == 1.0
    assert _opacity(fades, 3.5) == pytest.approx(0.5)
    assert _opacity(fades, 4.5) == 0.0


def test_windows_paths_become_premiere_file_urls() -> None:
    url = _url(Path("C:/Users/INTEL CENTER/مشروع/a b.png"))
    assert url.startswith("file://localhost/C%3a/Users/INTEL%20CENTER/")
    assert premiere_check.local_path(url) == Path("C:/Users/INTEL CENTER/مشروع/a b.png")


def test_the_text_window_comes_from_the_dialogue_events(tmp_path: Path) -> None:
    ass = tmp_path / "t.ass"
    ass.write_text("[Events]\nDialogue: 0,0:00:01.20,0:00:02.50,Keyword,,0,0,0,,x\n"
                   "Dialogue: 0,0:00:00.80,0:00:01.90,Keyword,,0,0,0,,y\n", encoding="utf-8")
    assert _ass_window(ass) == pytest.approx((0.8, 2.5))
    (tmp_path / "none.ass").write_text("[Events]\n", encoding="utf-8")
    assert _ass_window(tmp_path / "none.ass") is None


def _clip(media: str, start: int, frames: int, x: float = 100.0, joinable: bool = True) -> PremiereClip:
    clip = PremiereClip(kind="still", name=media, media=Path(media), media_size=(10, 10), start=start,
                        joinable=joinable)
    clip.cx, clip.cy = [x] * frames, [50.0] * frames
    clip.scale, clip.opacity = [100.0] * frames, [100.0] * frames
    return clip


def test_a_continuing_element_stays_one_clip_and_drawing_order_is_kept() -> None:
    first = [_clip("a.png", 0, 10), _clip("b.png", 0, 10)]
    second = [_clip("b.png", 10, 10), _clip("c.png", 10, 10), _clip("a.png", 10, 10)]
    tracks = PremiereExporter._stack([first, second])
    where = {(clip.name, clip.start): (index, clip) for index, track in enumerate(tracks) for clip in track}
    assert where[("b.png", 0)][1].end == 20  # b continues: one clip over both beats
    assert where[("a.png", 0)][0] < where[("b.png", 0)][0]  # first beat: a under b
    # second beat: b under c under a, so a cannot continue its clip below b
    assert where[("b.png", 0)][0] < where[("c.png", 10)][0] < where[("a.png", 10)][0]
    assert sum(len(track) for track in tracks) == 4


def test_a_jump_between_beats_is_a_cut_not_a_slide() -> None:
    tracks = PremiereExporter._stack([[_clip("a.png", 0, 10, x=100)], [_clip("a.png", 10, 10, x=600)]])
    assert sum(len(track) for track in tracks) == 2


# -- real plans: the project reproduces the encoded video ----------------------------------
def _small_plan(tmp_path: Path):
    from app.choreography import ChoreographyDirector
    from app.composition import CompositionPlanner
    from app.motion import MotionPlanner
    from app.render import RenderPlanner
    from app.story import StoryPlanner
    from app.text import TextPlanner
    from tests.support.carrier_matrix import generate_case
    from tests.support.carrier_scene import build_package

    case = generate_case(7303)  # three scenes: entries, scene boundaries, keywords, arrows
    built = build_package(list(case.scenes), namespace="PRM", image_root=tmp_path / "images", write_images=True)
    story = StoryPlanner().plan(built.package, built.transcript, built.assets)
    choreography = ChoreographyDirector().plan(built.package, story, built.assets)
    composition = CompositionPlanner().plan(story, built.assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, built.assets)
    text = TextPlanner().plan(transcript=built.transcript, story=story, assets=built.assets,
                              package=built.package, choreography=choreography)
    workspace = tmp_path / "render"
    workspace.mkdir()
    plan, _ = RenderPlanner().compile(built.transcript, built.assets, story, composition, motion, workspace,
                                      text=text)
    return plan


def _audio(tmp_path: Path, seconds: float) -> Path:
    import subprocess

    audio = tmp_path / "narration.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds:.3f}",
                    str(audio)], check=True)
    return audio


@needs_ffmpeg
def test_the_project_reproduces_the_encoded_video(tmp_path: Path) -> None:
    plan = _small_plan(tmp_path)
    renderer = FFmpegRenderer("ffmpeg")
    video = renderer.render(plan, tmp_path / "video.mp4")
    project = PremiereExporter(renderer).export(
        plan, audio=_audio(tmp_path, plan.duration), xml_path=tmp_path / "out" / "p.xml",
        media_dir=tmp_path / "out" / "media", name="test")
    assert project.warnings == ()
    root = ET.parse(project.path).getroot()
    assert root.tag == "xmeml" and root.get("version") == "4"
    assert premiere_check.sequence_size(root) == (plan.width, plan.height)
    tracks = root.find("sequence/media/video").findall("track")
    assert len(tracks) == project.tracks >= 2
    assert root.find("sequence/media/audio/track/clipitem/file/pathurl") is not None
    for node in root.iter("file"):
        if node.find("pathurl") is not None:
            assert premiere_check.local_path(node.findtext("pathurl")).is_file()
    total = round(plan.duration * plan.fps)
    for frame in (total // 5, total // 2, total - 8):
        mean, share = premiere_check.frame_difference(project.path, video, frame)
        assert mean < 6.0 and share < 0.04, (frame, mean, share)


@needs_ffmpeg
def test_a_missing_cutout_is_skipped_and_reported_never_a_stop(tmp_path: Path) -> None:
    plan = _small_plan(tmp_path)
    renderer = FFmpegRenderer("ffmpeg")
    original = renderer.capture_layers

    def capture(plan, root):
        layers, problems = original(plan, root)
        for layer in layers:
            if layer.kind == "asset":
                layer.image = tmp_path / "gone.png"
                break
        return layers, problems

    renderer.capture_layers = capture
    project = PremiereExporter(renderer).export(
        plan, audio=_audio(tmp_path, plan.duration), xml_path=tmp_path / "p.xml",
        media_dir=tmp_path / "media", name="test")
    assert project.path.is_file()
    assert [row["code"] for row in project.warnings] == ["PREMIERE_LAYER_SKIPPED"]


@needs_ffmpeg
def test_a_segment_that_cannot_be_authored_is_reported_and_the_rest_exported(tmp_path: Path, monkeypatch) -> None:
    plan = _small_plan(tmp_path)
    renderer = FFmpegRenderer("ffmpeg")
    original = renderer._render_beat_segment
    broken = sorted(plan.story, key=lambda beat: beat.start)[0].id

    def segment(plan, beat, *args):
        if beat.id == broken:
            raise RuntimeError("authoring failed")
        return original(plan, beat, *args)

    monkeypatch.setattr(renderer, "_render_beat_segment", segment)
    project = PremiereExporter(renderer).export(
        plan, audio=_audio(tmp_path, plan.duration), xml_path=tmp_path / "p.xml",
        media_dir=tmp_path / "media", name="test")
    assert [row["code"] for row in project.warnings] == ["PREMIERE_SEGMENT_SKIPPED"]
    assert project.warnings[0]["beat_id"] == broken
    assert project.clips > 1


@needs_ffmpeg
def test_a_failed_beat_leaves_no_half_recorded_layers(tmp_path: Path, monkeypatch) -> None:
    plan = _small_plan(tmp_path)
    renderer = FFmpegRenderer("ffmpeg")
    original = renderer._render_beat_segment
    broken = sorted(plan.story, key=lambda beat: beat.start)[-1].id

    def segment(plan, beat, *args):
        original(plan, beat, *args)  # records its layers, then fails (e.g. a write error)
        if beat.id == broken:
            raise OSError("No such file or directory")

    monkeypatch.setattr(renderer, "_render_beat_segment", segment)
    layers, problems = renderer.capture_layers(plan, tmp_path / "capture")
    assert [row["beat_id"] for row in problems] == [broken]
    assert layers and all(layer.beat_id != broken for layer in layers)
    assert renderer.capture is None  # capture mode always ends


@needs_ffmpeg
def test_nothing_authored_is_a_failed_export_never_an_empty_project(tmp_path: Path, monkeypatch) -> None:
    """Hacktivist end-to-end run 2026-10-21: every beat failed on a too-long capture path and
    the old exporter published a project without its beats. Now: a typed failure."""
    plan = _small_plan(tmp_path)
    renderer = FFmpegRenderer("ffmpeg")

    def segment(*_args):
        raise OSError("[Errno 2] No such file or directory")

    monkeypatch.setattr(renderer, "_render_beat_segment", segment)
    with pytest.raises(StageFailedError) as error:
        PremiereExporter(renderer).export(plan, audio=_audio(tmp_path, plan.duration),
                                          xml_path=tmp_path / "p.xml", media_dir=tmp_path / "media", name="t")
    assert error.value.details["code"] == "PREMIERE_EXPORT_FAILED"
    assert not (tmp_path / "p.xml").exists()
