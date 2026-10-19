"""Black Hat scene-36 PAYOFF through the production downstream Motion chain.

The user's real export (job f96ba7e0, commit 65f44df) failed ~2.5 minutes into the
YouTube encode with ``MOTION_BELOW_PERCEPTUAL_FLOOR`` for SCENE_036:asset-04: expected
0.01188 vs floor 0.01340. MotionPlanner had authored a valid PAYOFF (activity 0.01340);
PayoffResolutionDirector._pop() then replaced the complete program with a fixed 1.07
icon hit: 0.07 x 0.16977 (item width) = 0.01188, and its 2-frame return also exceeded
the PAYOFF comfort ceiling. The earlier regression only called the Planner directly, so
it could not see a later pass replace a valid program.

The fixture is the real beat-036 state entering HeroTravelPlanner.plan, captured from the
real package + narration (minimized to this beat; image pixels are not read by Motion).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.models import CompositionBeat, MotionCue, RenderPlan, StoryBeat, VisualAsset
from app.motion.arrivals import SecondaryArrivalPlanner
from app.motion.contract import accent_readability_floor, segment_contract_violations
from app.motion.emphasis_leader import EmphasisLeaderPolicy
from app.motion.family import bind_families
from app.motion.hero_travel import HeroTravelPlanner
from app.motion.motion_blur import MotionBlurPolicy
from app.motion.resolution import ICON_HIT_MAX_PEAK_SCALE, PayoffResolutionDirector
from app.render.verification import EncodedMotionVerifier
from app.shared.errors import StageFailedError
from app.targets import REELS_9_16 as REELS_TARGET
from app.targets import REFERENCE_TARGET
from app.targets.projection import ReferencePlanProjector

FIXTURE = Path(__file__).with_name("fixtures") / "black_hat_beat036_pre_hero_travel.json"
RESULT = "SCENE_036:asset-04"


def _fixture(tmp_path: Path):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    story = [StoryBeat.model_validate(data["story_beat"])]
    composition = [CompositionBeat.model_validate(data["composition_beat"])]
    assets = []
    for row in data["assets"]:
        path = tmp_path / row["image_path"]
        cv2.imwrite(str(path), np.zeros((4, 4, 4), np.uint8))
        assets.append(VisualAsset.model_validate({**row, "image_path": str(path)}))
    motion = [MotionCue.model_validate(row) for row in data["motion_entering_hero_travel"]]
    return data, story, composition, motion, assets


def _production_chain(data, story, composition, motion, assets):
    """StoryEnginePipeline._plan_target's Motion order after EntryArrival, for one beat.

    HeroTravelPlanner reads only ``primary_asset_id`` from Choreography. The S01
    focus-only cross-scene pass needs a neighbouring scene and is a no-op here.
    """
    primary = data["choreography_primary_asset_id"]
    choreography = SimpleNamespace(for_beat=lambda _beat_id: SimpleNamespace(primary_asset_id=primary))
    boxes = {story[0].id: [(t0, t1, tuple(box)) for t0, t1, box in data["text_boxes"]]}
    entry_motion = motion
    hero = HeroTravelPlanner(horizontal_padding=data["horizontal_padding"])
    motion = hero.plan(story=story, composition=composition, choreography=choreography, motion=motion,
                       assets=assets, referent_carriers={tuple(row) for row in data["referent_carriers"]})
    resolution = PayoffResolutionDirector(icon_focus_mode=True)
    motion = resolution.plan(story=story, composition=composition, motion=motion, assets=assets,
                             emphasize=hero.secondary_emphasis)
    arrivals = SecondaryArrivalPlanner()
    motion = arrivals.plan(story=story, composition=composition, motion=motion, assets=assets,
                           travel_sweeps=hero.sweeps)
    motion = hero.hold_emphasis(story=story, composition=composition, motion=motion, assets=assets)
    leaders = EmphasisLeaderPolicy()
    motion = leaders.plan(story=story, composition=composition, motion=motion, assets=assets)
    motion = hero.revoke_through_text(motion, entry_motion, boxes)
    motion = arrivals.pop_withdrawn(motion, hero.withdrawn, composition=composition, assets=assets)
    motion = hero.fit_emphasis_to_text(motion, boxes)
    motion = arrivals.settle_against_text(motion, boxes)
    motion = leaders.enforce(motion, assets=assets)
    motion = bind_families(motion, {row.beat_id: {item.asset_id: item for item in row.items} for row in composition},
                           {asset.id: asset for asset in assets})
    motion = MotionBlurPolicy().plan(motion, composition, width=1920, height=1080, fps=30, assets=assets)
    return motion, resolution


def _plans(tmp_path: Path):
    data, story, composition, motion, assets = _fixture(tmp_path)
    final_motion, resolution = _production_chain(data, story, composition, motion, assets)
    youtube = RenderPlan(target_id=REFERENCE_TARGET.target_id, duration=data["duration"], story=story,
                         composition=composition, motion=final_motion, assets=assets)
    reels = ReferencePlanProjector().project(youtube, REELS_TARGET, tmp_path / "reels")
    return data, motion, youtube, reels, resolution


def _payoff(plan: RenderPlan):
    cue = next(row for row in plan.motion if row.asset_id == RESULT)
    item = next(row for beat in plan.composition for row in beat.items if row.asset_id == RESULT)
    return cue, next(row for row in cue.segments if row.phase == "PAYOFF"), item


def test_fixture_is_the_real_planner_payoff_that_was_valid_before_resolution(tmp_path: Path) -> None:
    data, _story, composition, motion, _assets = _fixture(tmp_path)
    cue = next(row for row in motion if row.asset_id == RESULT)
    payoff = next(row for row in cue.segments if row.phase == "PAYOFF")
    item = next(row for row in composition[0].items if row.asset_id == RESULT)
    assert payoff.program["name"] == "reference_result_enter"
    assert item.width == pytest.approx(0.16977, abs=1e-5) and item.height == pytest.approx(0.18385, abs=1e-5)
    floor = accent_readability_floor("PAYOFF", segment_duration=payoff.end - payoff.start,
                                     active_duration=payoff.program.get("semantic_active_duration"),
                                     item_width=item.width, item_height=item.height)
    assert floor == pytest.approx(0.01340, abs=5e-6)
    # MotionPlanner's _enforce_event_readability ran and met the floor (upward lift + scale).
    assert segment_contract_violations(phase="PAYOFF", program=payoff.program, params=cue.params,
                                       segment_duration=payoff.end - payoff.start,
                                       item_width=item.width, item_height=item.height) == []
    # The real production final plan carried the replaced, invalid icon hit.
    final = next(MotionCue.model_validate(row) for row in data["production_final_motion"] if row["asset_id"] == RESULT)
    hit = next(row for row in final.segments if row.phase == "PAYOFF")
    assert hit.program["name"] == "reference_icon_hit_payoff"
    assert [row["scale"] for row in hit.program["keyframes"]] == [1.0, 1.07, 1.07, 1.0, 1.0]
    codes = [row.code for row in segment_contract_violations(
        phase="PAYOFF", program=hit.program, params=final.params, segment_duration=hit.end - hit.start,
        item_width=item.width, item_height=item.height)]
    assert codes == ["MOTION_BELOW_PERCEPTUAL_FLOOR", "MOTION_TOO_FAST"]


@pytest.mark.parametrize("target", ["youtube", "reels"])
def test_real_scene_36_final_plan_passes_pre_encode_motion_qa_on_both_targets(tmp_path: Path, target: str) -> None:
    _data, _motion, youtube, reels, _resolution = _plans(tmp_path)
    plan = youtube if target == "youtube" else reels
    report = EncodedMotionVerifier().preflight(plan)
    assert [(row.code, row.asset_id, row.detail) for row in report.violations] == []
    assert report.checked_segments > 0


def test_real_scene_36_keeps_one_icon_specific_held_payoff_and_semantic_timing(tmp_path: Path) -> None:
    _data, entering, youtube, _reels, resolution = _plans(tmp_path)
    cue, payoff, item = _payoff(youtube)
    before = next(row for row in next(c for c in entering if c.asset_id == RESULT).segments if row.phase == "PAYOFF")
    # Story-owned timing and authored geometry never move.
    assert (payoff.start, payoff.end) == (before.start, before.end)
    assert (cue.start, cue.end) == (82.637, 82.9954)
    assert (item.x, item.y, item.width, item.height) == pytest.approx((0.51614, 0.24283, 0.16977, 0.18385), abs=1e-5)
    frames = payoff.program["keyframes"]
    scales = [row["scale"] for row in frames]
    # One scale accent owned by the result icon: rest -> held peak -> rest, no lateral shake.
    assert payoff.program["name"] == "reference_icon_hit_payoff"
    assert all(row["dx"] == 0.0 and row["dy"] == 0.0 for row in frames)
    assert scales[0] == 1.0 and scales[-1] == 1.0
    peak = max(scales)
    assert 1.07 <= peak <= ICON_HIT_MAX_PEAK_SCALE
    held = [row for row in frames if row["scale"] == peak]
    assert len(held) == 2 and held[1]["progress"] > held[0]["progress"], "a held peak, not a spike"
    assert sum(1 for left, right in zip(scales, scales[1:]) if right < left) == 1, "exactly one return"
    assert cue.params["payoff_icon_hit"]["peak_scale"] == pytest.approx(peak)
    decision = next(row for row in resolution.decisions if row.beat_id == "beat-036")
    assert decision.arrival == "reference_pop" and decision.wash == "none"


def test_final_plans_survive_serialization_and_rounding(tmp_path: Path) -> None:
    """The renderer consumes render-plan.json: QA must hold after the JSON round trip."""
    _data, _motion, youtube, reels, _resolution = _plans(tmp_path)
    for plan in (youtube, reels):
        reloaded = RenderPlan.model_validate_json(plan.model_dump_json())
        assert EncodedMotionVerifier().preflight(reloaded).violations == ()


def test_encoded_qa_still_rejects_the_original_invalid_program(tmp_path: Path) -> None:
    """Pre-encode and encoded QA share one contract: the old program fails both, identically."""
    data, story, composition, _motion, assets = _fixture(tmp_path)
    final = [MotionCue.model_validate(row) for row in data["production_final_motion"]]
    plan = RenderPlan(target_id=REFERENCE_TARGET.target_id, duration=data["duration"], story=story,
                      composition=composition, motion=[row for row in final if row.asset_id == RESULT],
                      assets=assets)
    pre = EncodedMotionVerifier().preflight(plan)
    video = tmp_path / "encoded.mp4"
    video.write_bytes(b"\x00")
    encoded = EncodedMotionVerifier().inspect(video=video, plan=plan)
    assert [(row.code, row.detail) for row in pre.violations] == [
        ("MOTION_BELOW_PERCEPTUAL_FLOOR", "expected normalized motion 0.01188 is below shared readability floor 0.01340")]
    assert encoded.violations == pre.violations
    with pytest.raises(StageFailedError) as error:
        EncodedMotionVerifier.require_preflight({plan.target_id: (plan, pre)})
    details = error.value.details
    assert details["code"] == "PRE_ENCODE_MOTION_CONTRACT_FAILED"
    assert details["violation_codes"] == ["MOTION_BELOW_PERCEPTUAL_FLOOR"]
    assert details["failed_targets"] == [REFERENCE_TARGET.target_id]
    evidence = details["violations"][0]
    assert evidence["asset_id"] == RESULT and evidence["phase"] == "PAYOFF"
    assert evidence["program_name"] == "reference_icon_hit_payoff"
    assert "payoff_resolution" in evidence["authoring_marks"]
