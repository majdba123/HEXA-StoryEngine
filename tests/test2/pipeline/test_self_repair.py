"""Repair instead of stopping (user direction 2026-10-21): no QA finding stops a render.

Each case starts from a plan or result the old contract rejected (the real Black Hat
PAYOFF that stopped job f96ba7e0, an encoded check that reports weak motion, a final
media finding, a beat segment whose encode fails, a target that cannot be planned) and
proves the repair, the record it leaves, and that strict mode (switch off) still fails
closed exactly as before.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.final import verification as final_media_rules
from app.final.verification import FinalMediaIssue
from app.models import MotionCue, MotionSegment, RenderPlan
from app.pipeline import StoryEnginePipeline
from app.render import motion_repair
from app.render.renderer import FFmpegRenderer
from app.render.verification import EncodedMotionVerifier
from app.shared import safe_mode
from app.shared.errors import DependencyUnavailableError, GenerationCancelledError, StageFailedError
from app.targets import REFERENCE_TARGET
from tests.test2.motion.test_real_package_payoff_final_plan import RESULT, _fixture


def _rejected_plan(tmp_path: Path) -> RenderPlan:
    """The production PAYOFF program pre-encode QA rejected (MOTION_BELOW_PERCEPTUAL_FLOOR)."""
    data, story, composition, _motion, assets = _fixture(tmp_path)
    final = [MotionCue.model_validate(row) for row in data["production_final_motion"]]
    return RenderPlan(target_id=REFERENCE_TARGET.target_id, duration=data["duration"], story=story,
                      composition=composition, motion=[row for row in final if row.asset_id == RESULT],
                      assets=assets)


# -- pre-encode motion QA ------------------------------------------------------------------
def test_the_rejected_gesture_becomes_still_and_qa_passes(tmp_path: Path) -> None:
    plan = _rejected_plan(tmp_path)
    report = EncodedMotionVerifier().preflight(plan)
    assert [row.code for row in report.violations] == ["MOTION_BELOW_PERCEPTUAL_FLOOR"]  # expected failure
    repaired, rows = motion_repair.neutralize(plan, motion_repair.offenders(report.violations))
    assert EncodedMotionVerifier().preflight(repaired).violations == ()
    assert rows == [{"beat_id": plan.motion[0].beat_id, "asset_id": RESULT, "phases": ["PAYOFF"],
                     "repair": "still", "follower_of": None}]
    cue = repaired.motion[0]
    payoff = next(row for row in cue.segments if row.phase == "PAYOFF")
    assert payoff.program["name"] == "reference_still_payoff"
    assert payoff.program["stilled_from"] == "reference_icon_hit_payoff"
    # place, window and every other phase are untouched
    original = plan.motion[0]
    assert (cue.start, cue.end) == (original.start, original.end)
    assert [(row.phase, row.start, row.end) for row in cue.segments] == [
        (row.phase, row.start, row.end) for row in original.segments]
    assert [row.program for row in cue.segments if row.phase != "PAYOFF"] == [
        row.program for row in original.segments if row.phase != "PAYOFF"]


def test_an_entry_becomes_an_alpha_reveal_and_drops_arrival_extras() -> None:
    frames = [{"progress": 0.0, "dx": -0.3, "dy": 0.0, "scale": 1.2, "easing": "ease_out_cubic"},
              {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"}]
    cue = MotionCue(beat_id="b", asset_id="a", kind="program_v3", start=1.0, end=2.0,
                    params={"program": {"name": "whip", "keyframes": frames}, "reference_landing": {"seconds": 0.3},
                            "reference_slide": {"from": "left"}, "entry_opacity": {"initial": 0.0}},
                    segments=[MotionSegment(phase="ENTRY", start=1.0, end=1.5, program={"name": "whip",
                                                                                          "keyframes": frames})])
    still = motion_repair.neutralize_cue(cue, {"ENTRY"})
    for program in (still.params["program"], still.segments[0].program):
        assert program["name"] == motion_repair.REPAIRED_ENTRY and program["repaired_from"] == "whip"
        assert all((f["dx"], f["dy"], f["scale"]) == (0.0, 0.0, 1.0) for f in program["keyframes"])
        assert [f["progress"] for f in program["keyframes"]] == [0.0, 1.0]
    assert "reference_landing" not in still.params and "reference_slide" not in still.params
    assert still.params["entry_opacity"] == {"initial": 0.0}  # the reveal clock is kept


def test_family_followers_receive_the_leaders_repair() -> None:
    frames = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}, {"progress": 0.5, "dx": 0.01, "dy": 0.0,
                                                                       "scale": 1.0},
              {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]

    def cue(asset: str, **params) -> MotionCue:
        return MotionCue(beat_id="b", asset_id=asset, kind="program_v3", start=0.0, end=2.0, params=params,
                         segments=[MotionSegment(phase="INTERACT", start=0.5, end=1.0,
                                                 program={"name": "nudge", "keyframes": frames})])

    plan = RenderPlan(duration=2.0, story=[], composition=[], assets=[],
                      motion=[cue("lead"), cue("part", family_follow="lead"), cue("other")])
    repaired, rows = motion_repair.neutralize(plan, {("b", "lead"): {"INTERACT"}})
    names = {row.asset_id: row.segments[0].program["name"] for row in repaired.motion}
    assert names == {"lead": "reference_still_interact", "part": "reference_still_interact", "other": "nudge"}
    assert [row["follower_of"] for row in rows] == [None, "lead"]


def _qa_host(tmp_path: Path) -> SimpleNamespace:
    host = SimpleNamespace(encoded_motion_verifier=EncodedMotionVerifier())
    host._progress = lambda *args, **kwargs: None
    return host


def test_the_pipeline_repairs_every_target_records_it_and_renders_the_repaired_plan(tmp_path: Path) -> None:
    plan = _rejected_plan(tmp_path)
    workspace = tmp_path / "job"
    (workspace / "diagnostics").mkdir(parents=True)
    repairs: list[dict] = []
    plans = StoryEnginePipeline._require_pre_encode_motion_qa(
        _qa_host(tmp_path), {plan.target_id: plan}, {plan.target_id: workspace}, progress=None, at=0.5,
        repairs=repairs)
    repaired = plans[plan.target_id]
    assert EncodedMotionVerifier().preflight(repaired).violations == ()
    assert repairs == [{"stage": "pre_encode_motion_qa", "repair": "gesture_made_still", "repaired_cues": 1,
                        "rounds": 1, "remaining_codes": []}]
    written = RenderPlan.model_validate_json((workspace / "render-plan.json").read_text(encoding="utf-8"))
    assert written == repaired  # the renderer reads the repaired plan
    rows = json.loads((workspace / "diagnostics" / "pre-encode-motion-repairs.json").read_text(encoding="utf-8"))
    assert rows[0]["asset_id"] == RESULT and rows[0]["round"] == 1
    qa = json.loads((workspace / "diagnostics" / "pre-encode-motion-qa.json").read_text(encoding="utf-8"))
    assert qa["violations"] == []


def test_strict_mode_still_fails_closed_before_any_encode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(motion_repair, "PRE_ENCODE_REPAIR", False)
    plan = _rejected_plan(tmp_path)
    workspace = tmp_path / "job"
    (workspace / "diagnostics").mkdir(parents=True)
    with pytest.raises(StageFailedError) as error:
        StoryEnginePipeline._require_pre_encode_motion_qa(
            _qa_host(tmp_path), {plan.target_id: plan}, {plan.target_id: workspace}, progress=None, at=0.5)
    assert error.value.details["code"] == "PRE_ENCODE_MOTION_CONTRACT_FAILED"
    assert not (workspace / "diagnostics" / "pre-encode-motion-repairs.json").exists()


# -- safe-level ladder -----------------------------------------------------------------------
def test_safe_levels_switch_layers_off_and_always_restore_them() -> None:
    from app.boundary import release
    from app.composition import focus_staging
    from app.motion import resolution

    before = (focus_staging.FOCUS_STAGING, resolution.IDEA_CLIMAX_WASH, release.IDEA_BOARD, release.SCENE_WHIP)
    with safe_mode.safe_level(1):
        assert (focus_staging.FOCUS_STAGING, resolution.IDEA_CLIMAX_WASH, release.IDEA_BOARD) == (False,) * 3
        assert release.SCENE_WHIP == before[3]
    with pytest.raises(RuntimeError), safe_mode.safe_level(2):
        assert release.SCENE_WHIP is False
        raise RuntimeError("planning failed inside the level")
    assert (focus_staging.FOCUS_STAGING, resolution.IDEA_CLIMAX_WASH, release.IDEA_BOARD,
            release.SCENE_WHIP) == before


@pytest.mark.parametrize(("error", "expected"), [
    (StageFailedError("x", details={"code": "TEXT_LAYOUT_CONTRACT_FAILED"}), True),
    (StageFailedError("x", details={"code": "TARGET_SEMANTIC_DIVERGENCE"}), True),
    (StageFailedError("x", details={"code": "WORK_ROOT_INSUFFICIENT_SPACE"}), False),
    (StageFailedError("x", details={"code": "EXPORT_ROOT_UNAVAILABLE"}), False),
    (GenerationCancelledError("cancelled"), False),
    (DependencyUnavailableError("ffmpeg missing"), False),
    (ValueError("bug"), False),
])
def test_only_planning_failures_climb_the_ladder(error, expected) -> None:
    assert safe_mode.recoverable(error) is expected


def test_a_target_that_cannot_be_planned_is_planned_again_on_a_safer_level() -> None:
    from app.boundary import release

    host, shared, seen = SimpleNamespace(safe_level=0), SimpleNamespace(repairs=[]), []

    def plan():
        seen.append((host.safe_level, release.SCENE_WHIP))
        if host.safe_level < 2:
            raise StageFailedError("composition contract", details={"code": "COMPOSITION_CONTRACT_FAILED"})
        return "plans"

    assert StoryEnginePipeline._plan_with_safe_levels(host, shared, plan) == "plans"
    assert [level for level, _ in seen] == [0, 1, 2] and seen[2][1] is False
    assert [row["repair"] for row in shared.repairs] == ["safe_level_1", "safe_level_2"]
    assert host.safe_level == 0 and release.SCENE_WHIP is True


def test_the_ladder_stops_at_its_last_level_and_never_retries_input_failures() -> None:
    host, shared = SimpleNamespace(safe_level=0), SimpleNamespace(repairs=[])
    calls = []

    def always():
        calls.append(host.safe_level)
        raise StageFailedError("still broken", details={"code": "COMPOSITION_CONTRACT_FAILED"})

    with pytest.raises(StageFailedError):
        StoryEnginePipeline._plan_with_safe_levels(host, shared, always)
    assert calls == [0, 1, 2]

    calls.clear()

    def no_space():
        calls.append(host.safe_level)
        raise StageFailedError("disk", details={"code": "WORK_ROOT_INSUFFICIENT_SPACE"})

    with pytest.raises(StageFailedError):
        StoryEnginePipeline._plan_with_safe_levels(host, SimpleNamespace(repairs=[]), no_space)
    assert calls == [0]


# -- final media ---------------------------------------------------------------------------
class _Media:
    def __init__(self, *rounds: list[FinalMediaIssue]) -> None:
        self.rounds = list(rounds)
        self.required = 0

    def inspect(self, *_args, **_kwargs):
        return self.rounds.pop(0) if self.rounds else []

    def require(self, *_args, **_kwargs):
        self.required += 1


def _media_host(media: _Media) -> SimpleNamespace:
    muxed = []
    return SimpleNamespace(final_media=media, final=SimpleNamespace(mux=lambda *args: muxed.append(args)), muxed=muxed)


def _verify(host, tmp_path: Path):
    return StoryEnginePipeline._verify_final_media(host, tmp_path / "f.mp4", tmp_path / "v.mp4", tmp_path / "a.mp3",
                                                   tmp_path / "f.mp4", first_spoken_start=0.4)


def test_a_finding_that_a_remux_clears_leaves_no_warning(tmp_path: Path) -> None:
    host = _media_host(_Media([FinalMediaIssue("AUDIO_VIDEO_DRIFT", "drift")], []))
    assert _verify(host, tmp_path) == []
    assert len(host.muxed) == 1


def test_a_white_flash_or_drift_that_remains_is_recorded_not_a_stop(tmp_path: Path) -> None:
    issue = FinalMediaIssue("VISUAL_WHITE_FLASH", "flash", {"count": 3, "first_frames": [1, 2, 3]})
    host = _media_host(_Media([issue], [issue]))
    warnings = _verify(host, tmp_path)
    assert warnings == [{"stage": "final_media", "code": "VISUAL_WHITE_FLASH", "message": "flash",
                         "remuxed": True, "count": 3}]


def test_a_missing_audio_stream_after_the_remux_still_stops(tmp_path: Path) -> None:
    issue = FinalMediaIssue("FINAL_MISSING_AUDIO", "no audio")
    host = _media_host(_Media([issue], [issue]))
    with pytest.raises(StageFailedError) as error:
        _verify(host, tmp_path)
    assert error.value.details["code"] == "FINAL_MISSING_AUDIO"


def test_strict_final_media_requires_as_before(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(final_media_rules, "FINAL_MEDIA_REPAIR", False)
    media = _Media()
    assert _verify(_media_host(media), tmp_path) == [] and media.required == 1


# -- render segment retry ------------------------------------------------------------------
def _segment_job(tmp_path: Path):
    beat = SimpleNamespace(id="beat-2")
    previous = SimpleNamespace(id="beat-1")
    return (2, beat, previous, 1.0, 30, tmp_path / "0002-beat-2.mp4")


def _moving(beat: str, asset: str) -> MotionCue:
    frames = [{"progress": 0.0, "dx": 0.2, "dy": 0.0, "scale": 1.0}, {"progress": 1.0, "dx": 0.0, "dy": 0.0,
                                                                       "scale": 1.0}]
    return MotionCue(beat_id=beat, asset_id=asset, kind="program_v3", start=0.0, end=1.0,
                     params={"program": {"name": "slide", "keyframes": frames}, "motion_blur": {"owner": "MOTION"}})


@pytest.mark.parametrize(("failures", "repair"), [(1, "serial_retry"), (2, "beat_motion_still")])
def test_a_failed_segment_is_encoded_again_and_recorded(tmp_path: Path, monkeypatch, failures, repair) -> None:
    renderer = FFmpegRenderer("ffmpeg")
    calls = []

    def segment(plan, beat, previous, start, frames, target, assets, composition, motion):
        calls.append(motion)
        if len(calls) <= failures - 1:
            raise RuntimeError("ffmpeg exited 1")

    monkeypatch.setattr(renderer, "_render_beat_segment", segment)
    motion = {("beat-2", "a"): _moving("beat-2", "a"), ("beat-9", "z"): _moving("beat-9", "z")}
    renderer._retry_segment(None, _segment_job(tmp_path), RuntimeError("first encode failed"), {}, {}, motion)
    assert [row["repair"] for row in renderer.last_repairs] == [repair]
    used = calls[-1]
    if repair == "beat_motion_still":
        assert used[("beat-2", "a")].params["program"]["name"] == motion_repair.REPAIRED_ENTRY
        assert "motion_blur" not in used[("beat-2", "a")].params
        assert used[("beat-9", "z")] is motion[("beat-9", "z")]  # other beats untouched
    else:
        assert used is motion


def test_a_segment_that_never_encodes_stops_with_the_last_error(tmp_path: Path, monkeypatch) -> None:
    renderer = FFmpegRenderer("ffmpeg")

    def segment(*_args):
        raise RuntimeError("ffmpeg exited 1")

    monkeypatch.setattr(renderer, "_render_beat_segment", segment)
    with pytest.raises(StageFailedError):
        renderer._retry_segment(None, _segment_job(tmp_path), RuntimeError("x"), {}, {}, {})
    assert renderer.last_repairs == []


def test_a_missing_ffmpeg_is_never_retried(tmp_path: Path, monkeypatch) -> None:
    renderer = FFmpegRenderer("ffmpeg")
    calls = []

    def segment(*_args):
        calls.append(1)
        raise DependencyUnavailableError("ffmpeg is not available")

    monkeypatch.setattr(renderer, "_render_beat_segment", segment)
    with pytest.raises(DependencyUnavailableError):
        renderer._retry_segment(None, _segment_job(tmp_path), RuntimeError("x"), {}, {}, {})
    assert calls == [1]
