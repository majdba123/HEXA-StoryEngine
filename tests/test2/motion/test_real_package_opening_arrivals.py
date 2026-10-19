"""Black Hat opening (beat-001): entrances must be real travel, not fades in place.

User review of export v4 (2026-10-19): the lock, shield and central character "fade in near
their final positions". Decoded v4 frames confirm it: tracked travel was 0 px (lock), 3 px
(shield) and 2 px (character). Their Story windows (reveal -> settle) are only 0.25-0.30 s.

The fixture is the real beat-001 state entering HeroTravelPlanner.plan, captured from the
real package + narration; the downstream Motion chain below is the production order. An
empty following beat reproduces the production multi-beat path (scene-flow directions).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import MotionCue, RenderPlan, StoryBeat
from app.motion.arrivals import ARRIVAL_OPACITY_SECONDS, SLIDE_START_SCALE
from app.render.verification import EncodedMotionVerifier
from app.targets import REELS_9_16, REFERENCE_TARGET
from app.targets.projection import ReferencePlanProjector
from tests.test2.motion.test_real_package_payoff_final_plan import _fixture, _production_chain

FIXTURE = Path(__file__).with_name("fixtures") / "black_hat_beat001_pre_hero_travel.json"
LOCK, SHIELD, CHARACTER = "SCENE_001:asset-03", "SCENE_001:asset-02", "SCENE_001:asset-01"


def _opening(tmp_path: Path):
    import tests.test2.motion.test_real_package_payoff_final_plan as chain

    original = chain.FIXTURE
    chain.FIXTURE = FIXTURE
    try:
        data, story, composition, motion, assets = _fixture(tmp_path)
    finally:
        chain.FIXTURE = original
    beat = story[0]
    following = StoryBeat(id="beat-next", scene_id="SCENE_NEXT", start=beat.end, end=beat.end + 2.0,
                          narration="x", action="REVEAL")
    final, _resolution = _production_chain(data, [beat, following], composition, motion, assets)
    plan = RenderPlan(target_id=REFERENCE_TARGET.target_id, duration=data["duration"], story=[beat],
                      composition=composition, motion=final, assets=assets)
    return {cue.asset_id: cue for cue in final}, plan, motion


def _entry_program(cue: MotionCue) -> dict:
    row = next((s for s in cue.segments if abs(s.start - cue.start) < 1e-6), None)
    return row.program if row is not None else cue.params["program"]


def test_opening_lock_and_shield_travel_laterally_and_the_character_rises(tmp_path: Path) -> None:
    cues, _plan, entering = _opening(tmp_path)
    before = {cue.asset_id: (cue.start, cue.end, [(s.phase, s.start, s.end) for s in cue.segments])
              for cue in entering}
    lock, shield, character = (_entry_program(cues[key])["keyframes"][0] for key in (LOCK, SHIELD, CHARACTER))
    # The lock approaches its authored target (the character) from the LEFT; the shield
    # enters from the RIGHT edge; the centred character (no lateral path clear of both)
    # rises from the BOTTOM. Every one grows 0.93 -> 1.00 while it travels.
    assert lock["dx"] < -0.02 and shield["dx"] > 0.04 and character["dy"] > 0.04
    assert lock["scale"] == shield["scale"] == character["scale"] == SLIDE_START_SCALE
    assert cues[LOCK].params["relation_approach"]["target_asset_id"] == CHARACTER
    for key in (LOCK, SHIELD, CHARACTER):
        program = _entry_program(cues[key])
        assert program["keyframes"][-1] | {"easing": None} == {"progress": 1.0, "dx": 0.0, "dy": 0.0,
                                                               "scale": 1.0, "easing": None}
        cue = cues[key]
        assert (cue.start, cue.end, [(s.phase, s.start, s.end) for s in cue.segments]) == before[key], \
            "Story reveal/settle and every segment window are unchanged"
        opacity = cue.params.get("entry_opacity")
        if opacity:
            assert opacity["settle"] <= cue.start + ARRIVAL_OPACITY_SECONDS + 1e-6, "seen moving, not fading"


@pytest.mark.parametrize("target", ["youtube", "reels"])
def test_opening_plan_passes_pre_encode_motion_qa(tmp_path: Path, target: str) -> None:
    _cues, plan, _entering = _opening(tmp_path)
    if target == "reels":
        plan = ReferencePlanProjector().project(plan, REELS_9_16, tmp_path / "reels")
    report = EncodedMotionVerifier().preflight(plan)
    assert [(row.code, row.asset_id, row.detail) for row in report.violations] == []
    assert json.loads(plan.model_dump_json())["target_id"] == plan.target_id
