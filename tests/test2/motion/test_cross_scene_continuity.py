"""Roadmap V2 Sprint 7 - cross-scene referent continuity decisions (Motion owner).

Identity comes only from the authored ``referent_id``; every other shared attribute
(semantic_name, source_asset_id, unit_id, artwork) must leave Motion untouched.
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    MotionCue,
    MotionSegment,
    SceneBoundaryRelease,
    StoryBeat,
    TextCompositionBeat,
    TextCue,
    TextLayoutItem,
    TextPlan,
    VisualAsset,
)
from app.motion.cross_scene import (
    ABSTAIN,
    CONTINUITY_PROGRAM,
    HANDOFF_PARAM,
    NO_GEOMETRY_INHERITANCE,
    POSITION_AND_SCALE,
    POSITION_ONLY,
    CrossSceneContinuityPlanner,
)
from app.motion.timing import motion_comfort

ROOT = Path(__file__).resolve().parents[3]
SCENE = 3.0  # seconds per scene; reveals sit 0.5 s after each cut


def obj(asset: str, x: float, y: float, w: float = 0.2, h: float = 0.4, **extra) -> dict:
    return {"asset": asset, "x": x, "y": y, "w": w, "h": h, **extra}


def build(*scenes: list[dict], boundaries: dict[int, str] | None = None):
    """Scenes of objects -> (package, story, composition, motion, assets)."""
    units, story, composition, motion, assets = [], [], [], [], []
    for index, objects in enumerate(scenes):
        scene_id, beat_id, start = f"SCENE_{index + 1:03d}", f"beat-{index + 1:03d}", index * SCENE
        scene_units, activations, items = [], [], []
        for order, row in enumerate(objects):
            package_id = f"{scene_id}_{row['asset']}"
            runtime = f"{scene_id}:asset-{order + 1:02d}"
            scene_units.append(SimpleNamespace(
                asset_id=package_id, referent_id=row.get("referent"), parent_asset_id=row.get("parent"),
                semantic_name=row.get("semantic_name"), source_asset_id=row.get("source"),
                unit_id=row.get("unit", package_id)))
            if row.get("runtime", True):
                activations.append(AssetActivation(asset_id=runtime, semantic_unit_id=package_id))
                items.append(LayoutItem(asset_id=runtime, x=row["x"], y=row["y"], width=row["w"],
                                        height=row["h"], z=10 + order))
                assets.append(VisualAsset(id=runtime, scene_id=scene_id, role="primary",
                                          image_path=Path("missing.png"), extraction_method="test"))
                reveal = start + row.get("reveal", 0.5)
                segments = [MotionSegment(phase="ENTRY", start=reveal, end=reveal + 0.25,
                                          program={"name": "reference_pop_reveal_readable", "keyframes": []})]
                for phase, offset in row.get("accents", []):
                    segments.append(MotionSegment(phase=phase, start=reveal + offset, end=reveal + offset + 0.4))
                if row.get("exit"):
                    segments.append(MotionSegment(phase="EXIT", start=start + 2.5, end=start + 2.9,
                                                  program={"terminal_behavior": "LEAVE"}))
                motion.append(MotionCue(beat_id=beat_id, asset_id=runtime, kind="program_v3", start=reveal,
                                        end=reveal + 0.25,
                                        params={"engine_version": 3,
                                                "entry_opacity": {"initial": 0.3, "start": reveal, "settle": reveal + 0.25}},
                                        segments=segments))
        units.append(SimpleNamespace(id=scene_id, order=index, units=tuple(scene_units)))
        story.append(StoryBeat(id=beat_id, scene_id=scene_id, start=start, end=start + SCENE, narration="n",
                               action="REVEAL", asset_activations=activations))
        composition.append(CompositionBeat(beat_id=beat_id, items=items))
    package = SimpleNamespace(scenes=tuple(units))
    rows = [SceneBoundaryRelease(beat_id=f"beat-{i + 1:03d}", from_beat_id=f"beat-{i:03d}", mode=mode, reason="t")
            for i, mode in (boundaries or {}).items()]
    return package, story, composition, motion, assets, rows


def run(package, story, composition, motion, assets, rows=(), **kwargs):
    planner = CrossSceneContinuityPlanner()
    out = planner.plan(package=package, story=story, composition=composition, motion=motion, assets=assets,
                       duration=SCENE * len(story), scene_boundaries=list(rows),
                       frame_width=1920, frame_height=1080, **kwargs)
    return out, planner.decisions


def adapted(out, beat_id):
    return next(cue for cue in out if cue.beat_id == beat_id and HANDOFF_PARAM in cue.params)


# 1, 2, 14 --------------------------------------------------------------------------------
def test_same_authored_referent_adjacent_inherits_position_with_different_asset_ids() -> None:
    data = build([obj("A01_worker", 0.30, 0.5, referent="REF_P")],
                 [obj("B07_clerk", 0.33, 0.5, referent="REF_P")])
    out, decisions = run(*data)
    [decision] = decisions
    assert decision.decision in {POSITION_ONLY, POSITION_AND_SCALE}
    assert decision.identity_authority == "REFERENT_ID"
    assert (decision.previous_asset_id, decision.current_asset_id) == ("SCENE_001:asset-01", "SCENE_002:asset-01")
    cue = adapted(out, "beat-002")
    entry = next(row for row in cue.segments if row.phase == "ENTRY")
    first, last = entry.program["keyframes"][0], entry.program["keyframes"][-1]
    assert entry.program["name"] == CONTINUITY_PROGRAM
    assert first["dx"] == pytest.approx(-0.03) and first["dy"] == pytest.approx(0.0)
    assert (last["dx"], last["dy"], last["scale"]) == (0.0, 0.0, 1.0)
    assert cue.params[HANDOFF_PARAM] == {"beat_id": "beat-001", "asset_id": "SCENE_001:asset-01"}


# 3-8 negative controls -------------------------------------------------------------------
@pytest.mark.parametrize("left, right", [
    ({}, {}),
    ({"referent": "REF_A"}, {"referent": "REF_B"}),
    ({"semantic_name": "hacker"}, {"semantic_name": "hacker"}),
    ({"source": "security_researcher"}, {"source": "security_researcher"}),
    ({"unit": "UNIT_001"}, {"unit": "UNIT_001"}),
], ids=["no_referent", "different_referents", "same_semantic_name", "same_source_asset_id", "same_unit_id"])
def test_nothing_but_a_shared_referent_id_creates_continuity(left, right) -> None:
    data = build([obj("A01", 0.30, 0.5, **left)], [obj("B01", 0.31, 0.5, **right)])
    out, decisions = run(*data)
    assert decisions == [] and out == data[3]
    if not left.get("referent"):
        assert out is data[3]  # no authored identity: Motion list returned untouched


def test_non_adjacent_recurrence_is_identity_only() -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P")], [obj("B01", 0.7, 0.2)],
                 [obj("C01", 0.30, 0.5, referent="REF_P")])
    out, decisions = run(*data)
    assert decisions == [] and out == data[3]


# 9 ---------------------------------------------------------------------------------------
def test_three_scene_chain_uses_one_carrier_per_boundary() -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P")], [obj("B01", 0.32, 0.5, referent="REF_P")],
                 [obj("C01", 0.34, 0.5, referent="REF_P")])
    out, decisions = run(*data)
    assert [(d.previous_asset_id, d.current_asset_id) for d in decisions] == [
        ("SCENE_001:asset-01", "SCENE_002:asset-01"), ("SCENE_002:asset-01", "SCENE_003:asset-01")]
    assert {d.referent_id for d in decisions} == {"REF_P"} and all(d.accepted for d in decisions)
    assert adapted(out, "beat-003").params[HANDOFF_PARAM]["asset_id"] == "SCENE_002:asset-01"


# 10 --------------------------------------------------------------------------------------
def test_multiple_referents_at_one_boundary_allow_one_travelling_carrier() -> None:
    data = build([obj("A01", 0.25, 0.5, referent="REF_P"), obj("A02", 0.75, 0.5, w=0.1, h=0.2, referent="REF_D")],
                 [obj("B01", 0.28, 0.5, referent="REF_P"), obj("B02", 0.77, 0.5, w=0.1, h=0.2, referent="REF_D")])
    _, decisions = run(*data)
    travelling = [d for d in decisions if d.decision in {POSITION_ONLY, POSITION_AND_SCALE}]
    assert [d.referent_id for d in decisions] == ["REF_D", "REF_P"]
    assert [d.referent_id for d in travelling] == ["REF_P"]  # larger carrier keeps the motion
    assert next(d for d in decisions if d.referent_id == "REF_D").decision == NO_GEOMETRY_INHERITANCE


# 11 --------------------------------------------------------------------------------------
def test_compound_root_is_the_only_carrier() -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P"),
                  obj("A02", 0.30, 0.4, w=0.05, h=0.05, referent="REF_P", parent="SCENE_001_A01")],
                 [obj("B01", 0.32, 0.5, referent="REF_P")])
    _, [decision] = run(*data)
    assert decision.previous_asset_id == "SCENE_001:asset-01" and decision.accepted


# 12, 13 ----------------------------------------------------------------------------------
def test_previous_terminal_leave_abstains() -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P", exit=True)], [obj("B01", 0.31, 0.5, referent="REF_P")])
    out, [decision] = run(*data)
    assert decision.decision == ABSTAIN and decision.reason == "timing:outgoing_has_terminal_exit"
    assert out == data[3]


def test_incoming_fresh_entry_is_replaced_by_an_opaque_continuity_entry() -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P")],
                 [obj("B01", 0.33, 0.5, referent="REF_P", accents=[("INTERACT", 0.9)])])
    out, _ = run(*data)
    cue = adapted(out, "beat-002")
    assert "entry_opacity" not in cue.params
    assert [row.phase for row in cue.segments] == ["ENTRY", "INTERACT"]  # semantic accent kept
    assert cue.segments[0].start == pytest.approx(3.5)  # first visible frame unchanged
    original = next(c for c in data[3] if c.beat_id == "beat-002")
    assert cue.segments[1] == original.segments[1]


# 15, 16 ----------------------------------------------------------------------------------
def test_compatible_artwork_inherits_scale() -> None:
    data = build([obj("A01", 0.30, 0.5, w=0.2, h=0.4, referent="REF_P")],
                 [obj("B01", 0.32, 0.5, w=0.24, h=0.48, referent="REF_P")])
    out, [decision] = run(*data)
    assert decision.decision == POSITION_AND_SCALE
    first = adapted(out, "beat-002").segments[0].program["keyframes"][0]
    assert first["scale"] == pytest.approx(0.2 / 0.24)


def test_incompatible_artwork_rejects_scale_but_keeps_position() -> None:
    data = build([obj("A01", 0.30, 0.5, w=0.2, h=0.4, referent="REF_P")],
                 [obj("B01", 0.32, 0.5, w=0.4, h=0.2, referent="REF_P")])  # portrait -> landscape
    out, [decision] = run(*data)
    assert decision.decision == POSITION_ONLY
    assert adapted(out, "beat-002").segments[0].program["keyframes"][0]["scale"] == 1.0


# 17, 18, 19 ------------------------------------------------------------------------------
def test_inherited_pose_outside_canvas_is_rejected() -> None:
    data = build([obj("A01", 0.95, 0.5, w=0.1, h=0.4, referent="REF_P")],
                 [obj("B01", 0.83, 0.5, w=0.3, h=0.4, referent="REF_P")])
    _, [decision] = run(*data)
    assert decision.decision in {ABSTAIN, NO_GEOMETRY_INHERITANCE}
    assert "inherited_pose_outside_canvas" in decision.reason


def test_excessive_travel_abstains_rather_than_flying_across_the_screen() -> None:
    data = build([obj("A01", 0.15, 0.5, referent="REF_P")], [obj("B01", 0.85, 0.5, referent="REF_P")])
    out, [decision] = run(*data)
    assert decision.decision == ABSTAIN and out == data[3]
    assert decision.reason.startswith("timing:no_settle_window")


def test_insufficient_settle_time_falls_back_to_in_place_swap_or_abstains() -> None:
    near = build([obj("A01", 0.30, 0.5, referent="REF_P")],
                 [obj("B01", 0.33, 0.5, referent="REF_P", accents=[("INTERACT", 0.0)])])
    _, [decision] = run(*near)
    assert decision.decision == NO_GEOMETRY_INHERITANCE
    assert decision.evidence["position_rejected"] == "timing:no_settle_window_before_semantic_accent"
    far = build([obj("A01", 0.20, 0.5, referent="REF_P")],
                [obj("B01", 0.60, 0.5, referent="REF_P", accents=[("INTERACT", 0.0)])])
    _, [decision] = run(*far)
    assert decision.decision == ABSTAIN


def test_accent_running_at_the_handoff_frame_blocks_travel() -> None:
    # The accent starts a hair before the frame-quantized handoff and is still running:
    # the renderer would give it the pose, so a travel would be silently overridden.
    data = build([obj("A01", 0.30, 0.5, referent="REF_P")],
                 [obj("B01", 0.33, 0.5, referent="REF_P", reveal=0.4995, accents=[("PAYOFF", 0.0)])])
    _, [decision] = run(*data)
    assert decision.decision == NO_GEOMETRY_INHERITANCE
    assert decision.evidence["position_rejected"] == "timing:no_settle_window_before_semantic_accent"


def test_travel_respects_the_certified_entry_comfort_speed() -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P")], [obj("B01", 0.36, 0.5, referent="REF_P")])
    out, [decision] = run(*data)
    entry = adapted(out, "beat-002").segments[0]
    speed = 0.06 / (entry.end - entry.start)
    assert speed <= motion_comfort("ENTRY").max_normalized_speed + 1e-9


# 20 --------------------------------------------------------------------------------------
def test_lingering_carrier_never_covers_incoming_text() -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P")], [obj("B01", 0.33, 0.5, referent="REF_P", reveal=1.5)])
    cue = TextCue(id="t1", beat_id="beat-002", text="word", semantic_type="KEYWORD", source_char_start=0,
                  source_char_end=4, spoken_start=3.2, spoken_end=3.9, emphasis_time=3.3, style_id="s")
    layout = [TextCompositionBeat(beat_id="beat-002", items=[TextLayoutItem(text_cue_id="t1", x=0.30, y=0.5, max_width=0.3)])]
    out, [decision] = run(*data, text=TextPlan(cues=[cue]), text_composition=layout, text_motion=[])
    assert decision.decision == ABSTAIN and decision.reason == "visual_quality:lingering_carrier_covers_incoming_text"
    assert out == data[3]


# 21 --------------------------------------------------------------------------------------
def test_composition_is_never_modified_and_every_program_ends_on_it() -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P")], [obj("B01", 0.34, 0.45, referent="REF_P")])
    before = [layout.model_copy(deep=True) for layout in data[2]]
    out, _ = run(*data)
    assert data[2] == before
    for cue in out:
        for row in cue.segments:
            frames = row.program.get("keyframes") or []
            if frames:
                assert (frames[-1]["dx"], frames[-1]["dy"], frames[-1]["scale"]) == (0.0, 0.0, 1.0)


# 22-25 -----------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["HOLD_TO_OPENER", "EXACT_END", "OVERLAP", "HARD_CUT"])
def test_boundary_mode_is_respected_and_never_rewritten(mode) -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P")], [obj("B01", 0.33, 0.5, referent="REF_P")],
                 boundaries={1: mode})
    rows = [row.model_copy(deep=True) for row in data[5]]
    out, [decision] = run(*data)
    assert data[5] == rows  # Boundary decisions are inputs, never outputs
    assert decision.boundary_interaction == mode and decision.accepted
    # The handoff is the incoming carrier's own first visible frame (the opener): never earlier.
    assert decision.handoff_at == pytest.approx(3.5)


# 28 --------------------------------------------------------------------------------------
def test_decisions_are_deterministic_and_independent_of_input_order() -> None:
    data = build([obj("A01", 0.25, 0.5, referent="REF_P"), obj("A02", 0.75, 0.5, w=0.1, h=0.2, referent="REF_D")],
                 [obj("B01", 0.28, 0.5, referent="REF_P"), obj("B02", 0.77, 0.5, w=0.1, h=0.2, referent="REF_D")])
    first_out, first = run(*data)
    shuffled = list(data[3])
    random.Random(7).shuffle(shuffled)
    second_out, second = run(data[0], data[1], data[2], shuffled, data[4], data[5])
    assert [d.to_payload() for d in first] == [d.to_payload() for d in second]
    assert sorted(first_out, key=lambda c: (c.beat_id, c.asset_id)) == sorted(second_out, key=lambda c: (c.beat_id, c.asset_id))


# 29 --------------------------------------------------------------------------------------
def test_renderer_has_no_referent_semantics() -> None:
    hits = subprocess.run(["git", "grep", "-n", "referent", "--", "app/render", "app/targets"],
                          cwd=ROOT, capture_output=True, text=True).stdout
    assert hits == ""
