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
from PIL import Image, ImageDraw

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
from app.motion.landing import ReferenceLandingPolicy
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
                activations.append(AssetActivation(asset_id=runtime, semantic_unit_id=package_id,
                                                   continuity=row.get("continuity")))
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
    frame_width = kwargs.pop("frame_width", 1920)
    frame_height = kwargs.pop("frame_height", 1080)
    out = planner.plan(package=package, story=story, composition=composition, motion=motion, assets=assets,
                       duration=SCENE * len(story), scene_boundaries=list(rows),
                       frame_width=frame_width, frame_height=frame_height, **kwargs)
    return out, planner.decisions


def adapted(out, beat_id):
    return next(cue for cue in out if cue.beat_id == beat_id and HANDOFF_PARAM in cue.params)


def test_v2_authored_calendar_replaces_in_place_without_referent() -> None:
    target = "SCENE_002_calendar_new"
    data = build([obj("calendar_old", 0.3, 0.5,
                      continuity={"mode": "TRANSFORM_TO", "target_asset_id": target})],
                 [obj("calendar_new", 0.3, 0.5)])
    baseline, _ = run(*data)
    assert baseline is data[3]
    changed, [decision] = run(*data, enable_visual_continuity_v2=True)
    assert decision.decision == NO_GEOMETRY_INHERITANCE
    assert decision.identity_authority == "AUTHORED_CONTINUITY"
    assert decision.evidence["handoff_frame"] == 15
    cue = adapted(changed, "beat-002")
    assert "entry_opacity" not in cue.params
    assert cue.segments[0].program["name"] == CONTINUITY_PROGRAM
    landed = ReferenceLandingPolicy().apply(story=data[1], composition=data[2],
                                            motion=changed, assets=data[4])
    assert next(row for row in landed if row.beat_id == "beat-002").segments[0].program == cue.segments[0].program


def test_v2_segmentless_base_arrival_is_replaced_with_stillness() -> None:
    data = build([obj("calendar_old", 0.3, 0.5, continuity={"mode": "TRANSFORM_TO",
                      "target_asset_id": "SCENE_002_calendar_new"})],
                 [obj("calendar_new", 0.3, 0.5)])
    cue = data[3][1]
    slide = {"name": "reference_slide_arrival", "keyframes": [
        {"progress": 0.0, "dx": 0.2, "dy": 0.0, "scale": 0.8},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    ]}
    data[3][1] = cue.model_copy(update={"segments": [], "params": {
        **cue.params, "program": slide, "reference_slide": {"direction": "right"}}})
    changed, [decision] = run(*data, enable_visual_continuity_v2=True)
    assert decision.decision == NO_GEOMETRY_INHERITANCE
    updated = adapted(changed, "beat-002")
    assert updated.segments == []
    assert updated.params["program"]["name"] == CONTINUITY_PROGRAM
    assert "reference_slide" not in updated.params
    assert all((row["dx"], row["dy"], row["scale"]) == (0.0, 0.0, 1.0)
               for row in updated.params["program"]["keyframes"])


def test_v2_two_authored_pose_changes_match_independently() -> None:
    data = build([
        obj("person_a_old", 0.25, 0.5, continuity={"mode": "TRANSFORM_TO",
            "target_asset_id": "SCENE_002_person_a_new"}),
        obj("person_b_old", 0.75, 0.5, continuity={"mode": "TRANSFORM_TO",
            "target_asset_id": "SCENE_002_person_b_new"}),
    ], [obj("person_a_new", 0.25, 0.5), obj("person_b_new", 0.75, 0.5)])
    changed, decisions = run(*data, enable_visual_continuity_v2=True)
    assert len(decisions) == 2
    assert all(row.decision == NO_GEOMETRY_INHERITANCE for row in decisions)
    assert {cue.params[HANDOFF_PARAM]["asset_id"] for cue in changed
            if HANDOFF_PARAM in cue.params} == {"SCENE_001:asset-01", "SCENE_001:asset-02"}


def test_v2_unrelated_similar_artwork_still_abstains() -> None:
    data = build([obj("hacker_a", 0.3, 0.5, semantic_name="hacker")],
                 [obj("hacker_b", 0.3, 0.5, semantic_name="hacker")])
    changed, decisions = run(*data, enable_visual_continuity_v2=True)
    assert changed == data[3]
    assert decisions == []


def test_v2_visual_slot_requires_unique_graphic_correspondence(tmp_path: Path) -> None:
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    for path, changed in ((first, False), (second, True)):
        image = Image.new("RGB", (200, 100), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 80, 80), fill="navy")
        if changed:
            draw.rectangle((40, 45, 52, 52), fill="gold")
        image.save(path)
    locator = SimpleNamespace(cx=0.25, cy=0.5, width=0.3, height=0.6)

    def unit(name, role="OBJECT"):
        return SimpleNamespace(asset_id=name, visual_locator=locator, referent_id=None,
                               needs_review=False, semantic_role=role)
    old = SimpleNamespace(image_path=first, units=(unit("old"),))
    new = SimpleNamespace(image_path=second, units=(unit("new"),),
                          relation_to_previous="CONTINUES_NARRATIVE")
    planner = CrossSceneContinuityPlanner()
    assert len(planner._visual_slot_pairs(old, new)) == 1
    new.relation_to_previous = "NEW_IDEA"
    assert planner._visual_slot_pairs(old, new) == []
    new.relation_to_previous = "CONTINUES_NARRATIVE"
    new.units = (unit("new", role="CHARACTER"),)
    assert planner._visual_slot_pairs(old, new) == []
    new.units = (unit("new"), unit("duplicate"))
    assert planner._visual_slot_pairs(old, new) == []


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


def test_in_place_swap_removes_fresh_entry_motion_without_moving_reveal() -> None:
    data = build([obj("A01", 0.30, 0.5, referent="REF_P")],
                 [obj("B01", 0.30, 0.5, referent="REF_P", accents=[("INTERACT", 0.9)])])
    original = next(cue for cue in data[3] if cue.beat_id == "beat-002")
    pop = original.segments[0].model_copy(update={"program": {"name": "fresh_pop", "keyframes": [
        {"progress": 0.0, "dx": -0.06, "dy": 0.0, "scale": 0.7},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    ]}})
    data[3][1] = original.model_copy(update={"segments": [pop, original.segments[1]]})

    out, [decision] = run(*data)
    assert decision.decision == NO_GEOMETRY_INHERITANCE
    cue = adapted(out, "beat-002")
    entry = cue.segments[0]
    assert (entry.start, entry.end) == (pop.start, pop.end)
    assert entry.program["name"] == CONTINUITY_PROGRAM
    assert all((frame["dx"], frame["dy"], frame["scale"]) == (0.0, 0.0, 1.0)
               for frame in entry.program["keyframes"])
    assert "entry_opacity" not in cue.params
    assert cue.segments[1] == original.segments[1]


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920)])
def test_missing_identity_uses_directional_focus_without_claiming_referent(size) -> None:
    data = build([obj("old", 0.25, 0.5)], [obj("new", 0.55, 0.5)])
    data[1][0].primary_asset_ids = ["SCENE_001:asset-01"]
    data[1][1].primary_asset_ids = ["SCENE_002:asset-01"]
    out, [decision] = run(*data, enable_focus_continuity=True,
                          frame_width=size[0], frame_height=size[1])
    assert decision.decision == "NARRATIVE_FOCUS"
    assert decision.identity_authority == "NONE"
    assert decision.evidence["confidence"] == 0.7
    cue = next(row for row in out if row.beat_id == "beat-002")
    assert HANDOFF_PARAM not in cue.params
    assert cue.segments[0].program["keyframes"][0]["dx"] < 0
    assert cue.segments[0].program["keyframes"][-1]["dx"] == 0
    assert cue.segments[0].start == data[3][1].segments[0].start


def test_pre_text_focus_only_moves_unrelated_primary_without_claiming_identity() -> None:
    data = build([obj("old", 0.25, 0.5)], [obj("new", 0.55, 0.5)])
    data[1][0].primary_asset_ids = ["SCENE_001:asset-01"]
    data[1][1].primary_asset_ids = ["SCENE_002:asset-01"]
    planner = CrossSceneContinuityPlanner()
    out = planner.plan(
        package=data[0], story=data[1], composition=data[2], motion=data[3],
        assets=data[4], duration=SCENE * len(data[1]), frame_width=1920,
        frame_height=1080, enable_focus_continuity=True, focus_only=True,
    )
    assert planner.boundary_decisions[0].decision == "NARRATIVE_FOCUS"
    assert out != data[3]
    assert all(HANDOFF_PARAM not in cue.params for cue in out)


def test_pre_text_focus_only_reserves_authored_identity_for_late_handoff() -> None:
    data = build([obj("old", 0.25, 0.5, referent="REF_P")],
                 [obj("new", 0.55, 0.5, referent="REF_P")])
    data[1][0].primary_asset_ids = ["SCENE_001:asset-01"]
    data[1][1].primary_asset_ids = ["SCENE_002:asset-01"]
    planner = CrossSceneContinuityPlanner()
    out = planner.plan(
        package=data[0], story=data[1], composition=data[2], motion=data[3],
        assets=data[4], duration=SCENE * len(data[1]), frame_width=1920,
        frame_height=1080, enable_focus_continuity=True, focus_only=True,
    )
    assert out == data[3]
    assert planner.decisions == []
    assert planner.boundary_decisions[0].reason == "safe_cinematic_cut:authored_identity_reserved"


def test_missing_focus_chooses_explicit_safe_cut() -> None:
    data = build([obj("old", 0.25, 0.5)], [obj("new", 0.55, 0.5)])
    planner = CrossSceneContinuityPlanner()
    out = planner.plan(package=data[0], story=data[1], composition=data[2], motion=data[3],
                       assets=data[4], duration=SCENE * len(data[1]), frame_width=1920,
                       frame_height=1080, enable_focus_continuity=True)
    [decision] = planner.boundary_decisions
    assert decision.decision == ABSTAIN
    assert decision.reason == "safe_cinematic_cut:focus_not_unique"
    assert planner.decisions == []
    assert out == data[3]


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
