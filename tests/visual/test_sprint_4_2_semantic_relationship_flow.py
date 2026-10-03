"""Sprint 4.2 - semantic relationship flow (permanent regression gate).

Contracts, not pixels: Choreography turns each authored relation into the smallest visual
treatment (focus handoff, existing interaction, or abstention) from authored evidence only;
Motion executes a handoff at the target's Story reveal and settles on Composition. Only
the final test inspects encoded frames, to prove the progression is actually visible.
"""
from __future__ import annotations

import inspect
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from app.canonical import CanonicalRelation
from app.choreography import (
    ChoreographyDirector,
    InteractionIntent,
    RelationTreatment,
    SemanticEventFlow,
)
from app.choreography.relation_flow import plan_relation_flow
from app.composition import CompositionPlanner
from app.models import LayoutItem, MotionCue, MotionSegment, StoryBeat, Transcript, TranscriptSegment
from app.motion import MotionPlanner
from app.motion import relation_flow as motion_relation_flow
from app.motion.collision import box
from app.motion.reference import ReferenceMotionEnforcer
from app.motion.relation_flow import HANDOFF_LEAN_MAX_PX, apply_relation_focus_handoffs
from app.story import StoryPlanner
from tests.support.carrier_scene import Cutout, Event, SceneSpec, Unit, build_package, locator_for

PHRASE = tuple(f"w{index}" for index in range(10))
SLOW = 3.0

CHIP = (60, 560, 280, 240)
BAG = (640, 120, 260, 240)
HERO = (380, 300, 160, 380)
SERVER = (700, 620, 200, 180)
BLOCKER = (420, 360, 150, 150)


@dataclass
class Planned:
    built: object
    story: list
    choreography: object
    composition: list
    composition_before: list
    motion: list
    package: object
    transcript: Transcript
    assets: list

    def rid(self, key: str, scene: int = 0) -> str:
        return self.built.runtime_id(scene, key)

    def cue(self, key: str, scene: int = 0) -> MotionCue:
        asset = self.rid(key, scene)
        beat = self.story[scene]
        return next(c for c in self.motion if c.beat_id == beat.id and c.asset_id == asset)

    def flows(self, scene: int = 0):
        return self.choreography.directives[scene].relation_flows

    def handoffs(self, key: str, scene: int = 0) -> list[MotionSegment]:
        return [s for s in self.cue(key, scene).segments if s.semantic_action == "FOCUS_HANDOFF"]


def _slow(transcript: Transcript, factor: float) -> Transcript:
    words = [w.model_copy(update={"start": w.start * factor, "end": w.end * factor})
             for w in transcript.words]
    segments, offset = [], 0
    for segment in transcript.segments:
        count = len(segment.words)
        chunk = words[offset:offset + count]
        offset += count
        segments.append(TranscriptSegment(
            start=chunk[0].start, end=chunk[-1].end, text=segment.text,
            char_start=segment.char_start, char_end=segment.char_end, words=chunk,
        ))
    return Transcript(language=transcript.language, duration=transcript.duration * factor,
                      segments=segments, words=words, timing_source=transcript.timing_source)


def _unit(name, rect, words, role="supporting"):
    return Unit(name, words, role=role, locator=locator_for(rect)), Cutout(name, rect, role=role)


def flow_scene(
    *, source=("chip", CHIP, (2, 2), "supporting"), target=("bag", BAG, (7, 7), "RESULT"),
    extra=(), relations=(("chip", "ENABLES", "bag"),), target_is_result=True,
    source_in_target_event=False, events=None,
):
    """Two authored events: E1 led by the source, E2 led by the target (real-corpus shape)."""
    pieces = [_unit(*source), _unit(*target), *(_unit(*row) for row in extra)]
    units = tuple(u for u, _ in pieces)
    cutouts = tuple(c for _, c in pieces)
    if events is None:
        e1_participants = tuple(row[0] for row in extra if row[2][0] < 5)
        e2_participants = tuple(row[0] for row in extra if row[2][0] >= 5)
        if source_in_target_event:
            e2_participants = (source[0], *e2_participants)
        events = (
            Event("E1", leader=source[0], words=(1, 4), participants=e1_participants),
            Event("E2", leader=target[0], words=(6, 8), participants=e2_participants,
                  results=(target[0],) if target_is_result else (), depends_on=("E1",)),
        )
    return SceneSpec(PHRASE, units, cutouts, tuple(events)), tuple(relations)


def plan(scene_specs, *, tmp_path: Path, shuffle: bool = False, slow: float = SLOW) -> Planned:
    built = build_package([s for s, _ in scene_specs], namespace="S42",
                          image_root=tmp_path / "images", write_images=True)
    scenes = []
    for index, (_spec, relations) in enumerate(scene_specs):
        scene = built.package.scenes[index]
        rows = tuple(
            # Real Unified 2.0 relations carry no script span; the events own timing.
            CanonicalRelation(relation_id=f"{scene.id}_R{n}", subject_asset_id=f"{scene.id}_{s}",
                              relation_type=kind, object_asset_id=f"{scene.id}_{t}")
            for n, (s, kind, t) in enumerate(relations)
        )
        scenes.append(scene.model_copy(update={"relations": rows}))
    package = built.package.model_copy(update={"scenes": tuple(scenes)})
    assets = list(reversed(built.assets)) if shuffle else list(built.assets)
    transcript = _slow(built.transcript, slow)
    story = StoryPlanner().plan(package, transcript, assets)
    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)
    before = json.loads(json.dumps([c.model_dump(mode="json") for c in composition]))
    motion = ReferenceMotionEnforcer().enforce(
        MotionPlanner().plan(story, composition, choreography, assets))
    return Planned(built, story, choreography, composition, before, motion,
                   package, transcript, assets)


@pytest.fixture(scope="module")
def handoff(tmp_path_factory) -> Planned:
    return plan([flow_scene()], tmp_path=tmp_path_factory.mktemp("handoff"))


@pytest.fixture(scope="module")
def plain(tmp_path_factory) -> Planned:
    return plan([flow_scene(relations=())], tmp_path=tmp_path_factory.mktemp("plain"))


def _story_window(planned: Planned, key: str, scene: int = 0):
    beat = planned.story[scene]
    asset = planned.rid(key, scene)
    return next(a for a in beat.asset_activations if a.asset_id == asset)


def _program_at(segment: MotionSegment, progress: float) -> tuple[float, float, float]:
    frames = segment.program["keyframes"]
    for left, right in zip(frames, frames[1:]):
        if left["progress"] <= progress <= right["progress"]:
            span = max(1e-9, right["progress"] - left["progress"])
            t = (progress - left["progress"]) / span
            return tuple(left[k] + (right[k] - left[k]) * t for k in ("dx", "dy", "scale"))
    last = frames[-1]
    return last["dx"], last["dy"], last["scale"]


# 1 + 2. Authored source -> target relation compiles an ordered progression ---------------------
def test_source_to_target_relation_creates_ordered_interaction(handoff) -> None:
    (decision,) = handoff.flows()
    assert decision.treatment == RelationTreatment.FOCUS_HANDOFF
    assert decision.source_asset_id == handoff.rid("chip")
    assert decision.target_asset_id == handoff.rid("bag")
    interact = [s for s in handoff.cue("chip").segments if s.phase == "INTERACT"]
    (segment,) = handoff.handoffs("chip")
    assert interact and interact[0].start < segment.start


def test_progression_follows_authored_event_order(handoff) -> None:
    (decision,) = handoff.flows()
    events = [f.event_id for f in handoff.choreography.directives[0].event_flows]
    assert events.index(decision.source_event_id) < events.index(decision.target_event_id)
    assert handoff.cue("chip").start < handoff.cue("bag").start


# 3 + 4 + 22. Story timing is absolute ----------------------------------------------------------
def test_future_target_never_appears_before_its_story_reveal(handoff, plain) -> None:
    (segment,) = handoff.handoffs("chip")
    target = handoff.cue("bag")
    assert segment.start >= target.start - 1e-9
    assert target.start == plain.cue("bag").start


def test_result_never_appears_early(handoff) -> None:
    activation = _story_window(handoff, "bag")
    assert handoff.cue("bag").start >= float(activation.spoken_start) - 1.0  # Story visual lead only
    assert handoff.cue("bag").start == pytest.approx(
        next(c for c in handoff.motion if c.asset_id == handoff.rid("bag")).start)
    for cue in handoff.motion:
        for segment in cue.segments:
            if segment.phase == "PAYOFF":
                assert segment.start >= handoff.cue("bag").start - 1e-9


def test_story_timing_is_unchanged_by_relationship_flow(handoff, plain) -> None:
    def timing(planned):
        return [(b.start, b.end, b.audio_start, b.audio_end,
                 [(a.asset_id, a.spoken_start, a.spoken_end) for a in b.asset_activations])
                for b in planned.story]
    assert timing(handoff) == timing(plain)


# 5 + 6. Leader shifts source -> target; previous leader stays as support -----------------------
def test_leader_shifts_from_source_to_target_when_authored(handoff) -> None:
    (segment,) = handoff.handoffs("chip")
    assert segment.target_asset_id == handoff.rid("bag")
    assert segment.involvement == "SUPPORT"
    path = handoff.choreography.directives[0].event_focus_path_asset_ids
    assert path.index(handoff.rid("chip")) < path.index(handoff.rid("bag"))


def test_previous_leader_becomes_support_without_disappearing(handoff) -> None:
    (segment,) = handoff.handoffs("chip")
    _dx, _dy, peak = _program_at(segment, 0.45)
    assert 0.85 <= peak < 1.0  # recedes, never vanishes
    assert not [s for s in handoff.cue("chip").segments if s.phase == "EXIT"]
    beat = handoff.story[0]
    assert handoff.rid("chip") in (beat.active_visual_semantic_state or {})


# 7 + 8 + 9. Characters: works without one, composes with Sprint 4.1 ---------------------------
def test_interaction_works_without_a_character(handoff) -> None:
    assert not handoff.choreography.directives[0].emphasis_asset_ids
    assert handoff.handoffs("chip")


def test_character_relation_remains_compatible_with_sprint_4_1(tmp_path, monkeypatch) -> None:
    scene = flow_scene(source=("hero", HERO, (2, 2), "CHARACTER"),
                       relations=(("hero", "ENABLES", "bag"),))
    planned = plan([scene], tmp_path=tmp_path / "with")
    monkeypatch.setattr("app.motion.planner.apply_relation_focus_handoffs",
                        lambda cues, **_kwargs: cues)
    baseline = plan([scene], tmp_path=tmp_path / "without")
    assert planned.rid("hero") in planned.choreography.directives[0].emphasis_asset_ids

    def sprint_4_1(planned_):
        return sorted(
            (c.asset_id, json.dumps(c.params.get("character_emphasis"), sort_keys=True),
             json.dumps(c.params.get("supporting_deemphasis"), sort_keys=True),
             json.dumps([s.model_dump(mode="json") for s in c.segments
                         if s.semantic_action in {"EMPHASIZE", "DEEMPHASIZE"}], sort_keys=True))
            for c in planned_.motion
        )
    assert sprint_4_1(planned) == sprint_4_1(baseline)
    hero = planned.cue("hero")
    for first in hero.segments:
        if first.semantic_action != "EMPHASIZE":
            continue
        for second in planned.handoffs("hero"):
            assert first.end <= second.start + 1e-9 or second.end <= first.start + 1e-9


def test_active_participant_is_not_receded(tmp_path) -> None:
    planned = plan([flow_scene(source_in_target_event=True)], tmp_path=tmp_path)
    (decision,) = planned.flows()
    assert decision.treatment == RelationTreatment.INTERACTION
    assert decision.reason == "source_active_in_target_event"
    assert not planned.handoffs("chip")


# 10 + 11 + 12. Treatment only when semantically justified ------------------------------------
def test_directional_connector_only_when_semantically_justified(handoff, tmp_path) -> None:
    connected = [s for c in handoff.motion for s in c.segments if s.connection]
    assert len(connected) == 1 and connected[0].relationship == "ENABLES"
    descriptive = plan([flow_scene(relations=(("chip", "SPECIFIES", "bag"),))], tmp_path=tmp_path)
    assert not [s for c in descriptive.motion for s in c.segments if s.connection]


def test_descriptive_relation_forces_no_movement(tmp_path) -> None:
    for kind in ("REVEALS_IDENTITY", "CONTAINS_RISK", "COMPARES_WITH"):
        planned = plan([flow_scene(relations=(("chip", kind, "bag"),))], tmp_path=tmp_path / kind)
        (decision,) = planned.flows()
        assert decision.treatment == RelationTreatment.ABSTAIN
        assert not planned.handoffs("chip")


def test_unsupported_relation_safely_abstains(tmp_path) -> None:
    planned = plan([flow_scene(relations=(("chip", "INVENTED_VERB", "bag"),))], tmp_path=tmp_path)
    (decision,) = planned.flows()
    assert decision.treatment == RelationTreatment.ABSTAIN
    assert decision.reason == "non_directional_relation"
    assert not planned.handoffs("chip")


# 13. Short window simplifies -----------------------------------------------------------------
def test_short_timing_window_abstains() -> None:
    from app.choreography import RelationFlowDecision

    source = MotionCue(beat_id="b", asset_id="src", kind="program_v3", start=0.0, end=0.3)
    target = MotionCue(beat_id="b", asset_id="dst", kind="program_v3", start=1.0, end=1.3)
    beat = StoryBeat(id="b", scene_id="s", start=0.0, end=3.0, narration="x", action="REVEAL")
    items = [LayoutItem(asset_id="src", x=0.25, y=0.7, width=0.3, height=0.4),
             LayoutItem(asset_id="dst", x=0.7, y=0.3, width=0.3, height=0.4)]
    decision = RelationFlowDecision("ENABLES", "src", "dst", RelationTreatment.FOCUS_HANDOFF, "x")

    def run(next_reveal: float):
        return apply_relation_focus_handoffs(
            [source, target], beat=beat, decisions=(decision,), layout_items=items,
            next_reveal=lambda _c: next_reveal, carry_entry=lambda *_a, **_k: None,
        )[0]
    short = run(1.2)  # the next Story reveal leaves 0.2s: no room for a readable yield
    assert short.params["relation_flow"][0]["reason"] == "short_window"
    assert short.segments == source.segments


# 14 + 15. Density ------------------------------------------------------------------------------
def test_dense_scene_avoids_connector_clutter(tmp_path) -> None:
    planned = plan([flow_scene(
        extra=(("hero", HERO, (3, 3), "CHARACTER"), ("server", SERVER, (7, 7), "supporting")),
        relations=(("chip", "ENABLES", "bag"), ("chip", "LEADS_TO", "server")),
    )], tmp_path=tmp_path)
    connected = [s for c in planned.motion for s in c.segments if s.connection]
    assert len(connected) <= 2
    # One source never yields twice at once.
    handoffs = planned.handoffs("chip")
    for first, second in zip(handoffs, handoffs[1:]):
        assert first.end <= second.start + 1e-9


def test_sparse_scene_remains_restrained(tmp_path) -> None:
    unit, cutout = _unit("chip", CHIP, (2, 2))
    spec = SceneSpec(PHRASE, (unit,), (cutout,), (Event("E1", leader="chip", words=(1, 4)),))
    planned = plan([(spec, ())], tmp_path=tmp_path)
    assert planned.flows() == ()
    assert not planned.handoffs("chip")


# 16 + 17 + 18. Multiple relations ----------------------------------------------------------
def test_multiple_relations_preserve_event_order(tmp_path) -> None:
    planned = plan([flow_scene(
        extra=(("server", SERVER, (7, 7), "supporting"),),
        relations=(("chip", "LEADS_TO", "bag"), ("chip", "ENABLES", "server")),
    )], tmp_path=tmp_path)
    events = [f.event_id for f in planned.choreography.directives[0].event_flows]
    for decision in planned.flows():
        if decision.treatment == RelationTreatment.FOCUS_HANDOFF:
            assert events.index(decision.source_event_id) < events.index(decision.target_event_id)


def test_one_source_to_multiple_targets_is_deterministic(tmp_path) -> None:
    scene = flow_scene(
        extra=(("server", SERVER, (7, 7), "supporting"),),
        relations=(("chip", "ENABLES", "bag"), ("chip", "LEADS_TO", "server")),
    )
    first = plan([scene], tmp_path=tmp_path / "a")
    second = plan([scene], tmp_path=tmp_path / "b")
    assert [(d.source_asset_id, d.target_asset_id, d.treatment, d.reason) for d in first.flows()] \
        == [(d.source_asset_id, d.target_asset_id, d.treatment, d.reason) for d in second.flows()]
    assert [s.model_dump() for s in first.handoffs("chip")] == \
        [s.model_dump() for s in second.handoffs("chip")]


def test_multiple_sources_to_one_target_are_deterministic(tmp_path) -> None:
    scene = flow_scene(
        extra=(("server", SERVER, (3, 3), "supporting"),),
        relations=(("chip", "ENABLES", "bag"), ("server", "LEADS_TO", "bag")),
    )
    first = plan([scene], tmp_path=tmp_path / "a")
    second = plan([scene], tmp_path=tmp_path / "b", shuffle=True)
    key = [(d.source_asset_id, d.target_asset_id, d.treatment) for d in first.flows()]
    assert key == sorted(key)
    assert key == [(d.source_asset_id, d.target_asset_id, d.treatment) for d in second.flows()]


# 19. Connector never crosses an unrelated element ---------------------------------------------
def test_connector_does_not_cross_an_unrelated_element() -> None:
    from app.render.connection import _endpoints

    source, target = (100.0, 600.0, 300.0, 760.0), (650.0, 150.0, 870.0, 350.0)
    assert _endpoints(source, target, []) is not None
    assert _endpoints(source, target, [(420.0, 360.0, 570.0, 510.0)]) is None


# 20 + 21. Composition owns final geometry ------------------------------------------------------
def test_final_geometry_exactly_matches_composition(handoff) -> None:
    after = [c.model_dump(mode="json") for c in handoff.composition]
    assert after == handoff.composition_before


def test_no_geometry_drift_after_interaction(handoff) -> None:
    (segment,) = handoff.handoffs("chip")
    first, last = segment.program["keyframes"][0], segment.program["keyframes"][-1]
    for frame in (first, last):
        assert (frame["dx"], frame["dy"], frame["scale"]) == (0.0, 0.0, 1.0)
    assert segment.end <= float(handoff.story[0].end) + 1e-9
    _dx, _dy, scale = _program_at(segment, 1.0)
    assert scale == 1.0


def test_handoff_lean_points_at_target_and_stays_bounded(handoff) -> None:
    (segment,) = handoff.handoffs("chip")
    dx, dy, _scale = _program_at(segment, 0.45)
    items = {i.asset_id: i for i in handoff.composition[0].items}
    chip, bag = items[handoff.rid("chip")], items[handoff.rid("bag")]
    assert dx * (bag.x - chip.x) >= 0 and dy * (bag.y - chip.y) >= 0
    assert (dx * 1920) ** 2 + (dy * 1080) ** 2 <= (HANDOFF_LEAN_MAX_PX + 1e-6) ** 2


# 23 + 24. No hidden content, no invented asset -------------------------------------------------
def test_no_hidden_authored_content(handoff) -> None:
    beat = handoff.story[0]
    for activation in beat.asset_activations:
        assert any(c.asset_id == activation.asset_id for c in handoff.motion)


def test_no_invented_asset(handoff, plain) -> None:
    assert {c.asset_id for c in handoff.motion} == {c.asset_id for c in plain.motion}
    for decision in handoff.flows():
        assert decision.source_asset_id in {a.id for a in handoff.assets}
        assert decision.target_asset_id in {a.id for a in handoff.assets}


# 25. No package-specific behavior --------------------------------------------------------------
def test_no_package_specific_behavior() -> None:
    import app.choreography.relation_flow as choreography_relation_flow

    for module in (choreography_relation_flow, motion_relation_flow):
        source = inspect.getsource(module).upper()
        for token in ("SCENE_0", "BLACK_HAT", "INSIDER", "HACKTIVIST", "WHITE_HAT", "HEXA_"):
            assert token not in source


# 26 + 27. Determinism and input-order independence -------------------------------------------
def test_repeated_planning_is_deterministic_and_input_order_independent(tmp_path) -> None:
    first = plan([flow_scene()], tmp_path=tmp_path / "a")
    second = plan([flow_scene()], tmp_path=tmp_path / "b", shuffle=True)

    def fingerprint(planned):
        return sorted((c.asset_id, json.dumps(c.model_dump(mode="json")["segments"], sort_keys=True))
                      for c in planned.motion)
    assert fingerprint(first) == fingerprint(second)


# 28. No relation evidence == Sprint 4.1 behavior ---------------------------------------------
def test_no_relation_evidence_preserves_existing_behavior(plain) -> None:
    assert plain.flows() == ()
    for cue in plain.motion:
        assert "relation_flow" not in cue.params
        assert not [s for s in cue.segments if s.semantic_action == "FOCUS_HANDOFF"]


def test_planner_without_decisions_returns_cues_unchanged() -> None:
    cue = MotionCue(beat_id="b", asset_id="a", kind="program_v3", start=0.0, end=0.4)
    beat = StoryBeat(id="b", scene_id="s", start=0.0, end=2.0, narration="x", action="REVEAL")
    assert apply_relation_focus_handoffs(
        [cue], beat=beat, decisions=(), layout_items=[], next_reveal=lambda _c: 2.0,
        carry_entry=lambda *_a, **_k: None,
    ) == [cue]


def test_ambiguous_direction_and_missing_carrier_abstain() -> None:
    beat = StoryBeat(id="b", scene_id="s", start=0.0, end=2.0, narration="x", action="REVEAL",
                     primary_asset_ids=["a"], support_asset_ids=["b"])
    rows = (
        InteractionIntent("CONNECT", "ENABLES", "a", "a", authority="FINAL_PACKAGE_ASSET_RELATION",
                          executable=True),
        InteractionIntent("CONNECT", "ENABLES", "a", "ghost",
                          authority="FINAL_PACKAGE_ASSET_RELATION", executable=True),
        InteractionIntent("CONNECT", "DECLARED_PROGRESSION", "a", "b",
                          authority="FINAL_PACKAGE_VISUAL_PROGRESSION", executable=False),
    )
    flows = (SemanticEventFlow("E1", leader_asset_ids=("a",)),
             SemanticEventFlow("E2", leader_asset_ids=("b",)))
    decisions = plan_relation_flow(beat, rows, flows)
    assert [(d.target_asset_id, d.reason) for d in decisions] == [
        ("a", "ambiguous_direction"), ("ghost", "missing_carrier"),
    ]


def test_split_semantic_carrier_abstains() -> None:
    from app.choreography import RelationFlowDecision
    from app.models import AssetActivation

    def item(asset_id, x, y):
        return LayoutItem(asset_id=asset_id, x=x, y=y, width=0.2, height=0.2)

    source = MotionCue(beat_id="b", asset_id="src", kind="program_v3", start=0.0, end=0.3)
    piece = MotionCue(beat_id="b", asset_id="src:secondary-01", kind="program_v3", start=0.0, end=0.3)
    target = MotionCue(beat_id="b", asset_id="dst", kind="program_v3", start=1.0, end=1.3)
    beat = StoryBeat(id="b", scene_id="s", start=0.0, end=3.0, narration="x", action="REVEAL",
                     asset_activations=[AssetActivation(asset_id="src", semantic_unit_id="u"),
                                        AssetActivation(asset_id="src:secondary-01", semantic_unit_id="u"),
                                        AssetActivation(asset_id="dst", semantic_unit_id="v")])
    decision = RelationFlowDecision("ENABLES", "src", "dst", RelationTreatment.FOCUS_HANDOFF, "x")
    output = apply_relation_focus_handoffs(
        [source, piece, target], beat=beat, decisions=(decision,),
        layout_items=[item("src", 0.2, 0.7), item("src:secondary-01", 0.3, 0.7), item("dst", 0.7, 0.3)],
        next_reveal=lambda _c: 3.0, carry_entry=lambda *_a, **_k: None,
    )
    assert output[0].params["relation_flow"][0] == {
        "relationship": "ENABLES", "target_asset_id": "dst", "applied": False,
        "reason": "split_semantic_carrier",
    }
    assert output[0].segments == source.segments


# 29. Scene boundary never creates cross-scene identity ----------------------------------------
def test_scene_boundary_creates_no_cross_scene_identity(tmp_path) -> None:
    planned = plan([flow_scene(), flow_scene()], tmp_path=tmp_path)
    for scene in (0, 1):
        beat_assets = set(planned.story[scene].primary_asset_ids) | set(
            planned.story[scene].support_asset_ids)
        for decision in planned.flows(scene):
            assert {decision.source_asset_id, decision.target_asset_id} <= beat_assets
    second = planned.handoffs("chip", scene=1)
    assert all(s.target_asset_id == planned.rid("bag", 1) for s in second)
    assert planned.story[1].active_visual_semantic_state is not None
    assert planned.rid("chip", 0) not in planned.story[1].active_visual_semantic_state


# 30. Encoded frames: the relationship visibly progresses ------------------------------------
def _frame(video: Path, at: float) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", "scale=960:540,format=gray", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(540, 960)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_relationship_visibly_progresses_in_encoded_frames(handoff, tmp_path) -> None:
    from app.render import RenderPlanner
    from app.render.renderer import FFmpegRenderer
    from app.text import TextPlanner

    text = TextPlanner().plan(transcript=handoff.transcript, story=handoff.story,
                              assets=handoff.assets, package=handoff.package,
                              choreography=handoff.choreography)
    workspace = tmp_path / "render"
    workspace.mkdir()
    plan_, _ = RenderPlanner().compile(handoff.transcript, handoff.assets, handoff.story,
                                       handoff.composition, handoff.motion, workspace, text=text)
    video = FFmpegRenderer("ffmpeg").render(plan_, tmp_path / "video.mp4")

    (segment,) = handoff.handoffs("chip")
    chip = next(i for i in handoff.composition[0].items if i.asset_id == handoff.rid("chip"))
    left, top, right, bottom = box(chip, (0.0, 0.0, 1.0))
    region = (slice(int(top * 540) + 2, int(bottom * 540) - 2),
              slice(int(left * 960) + 2, int(right * 960) - 2))

    def ink(at: float) -> int:
        return int((_frame(video, at)[region] < 235).sum())

    rest_before = ink(segment.start - 0.05)
    peak = ink(segment.start + (segment.end - segment.start) * 0.45)
    rest_after = ink(min(float(plan_.duration) - 0.05, segment.end + 0.2))
    # The previous leader visibly yields while the target arrives, then rests exactly.
    assert peak < rest_before * 0.95
    assert abs(rest_after - rest_before) <= max(4, rest_before * 0.01)
