"""Sprint 4.3 - conservative semantic composition (permanent regression gate).

Contracts, not pixels: authored geometry is candidate zero and wins by default. A scene
changes only when an active Choreography relation is unreadable for a geometric reason
(crowded participants, or a third element crossing the relation) and one rigid, bounded
translation of a single free family fixes it with margin. Only the encoded test inspects
frames, to prove the final rest is the staged Composition geometry.
"""
from __future__ import annotations

import inspect
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

import app.composition.semantic_staging as staging_module
from app.choreography import (
    ChoreographyDirective,
    ChoreographyPlan,
    RelationFlowDecision,
    RelationTreatment,
    SequencePhase,
)
from app.composition import CompositionPlanner
from app.composition.geometry import AuthoredGeometryMapper
from app.composition.semantic_staging import (
    _CLEARANCE_PX,
    _MATERIAL_LENGTH_PX,
    _MATERIAL_MARGIN_PX,
    MAX_SHIFT,
    STAGED_PLACEMENT_SOURCE,
    SemanticStagingPlanner,
    StagingResult,
)
from app.layout import ConstraintLayoutSolver
from app.models import CompositionBeat, LayoutItem, StoryBeat, VisualAsset
from app.motion.collision import authored_overlap_ratio, box, overlap_ratio
from app.reference.profile import HexaVisualProfile
from app.render.connection import _endpoints
from tests.visual.test_sprint_4_2_semantic_relationship_flow import (
    CHIP,
    BLOCKER,
    Planned,
    flow_scene,
    plan,
)

W, H = 1920, 1080
CROWDED_BAG = (428, 560, 200, 200)   # 88 units right of CHIP: arrow just under readable
TIGHT_BAG = (380, 560, 200, 200)     # 40 units: only a minimum-size arrow fits the ceiling
CLIPPER = (470, 300, 100, 100)       # clips the chip->bag line by a small corner
PROFILE = HexaVisualProfile.production()


@dataclass
class Pair:
    staged: Planned
    baseline: Planned


def _plan_pair(spec, tmp_path: Path, *, shuffle: bool = False) -> Pair:
    staged = plan([spec], tmp_path=tmp_path / "staged", shuffle=shuffle)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SemanticStagingPlanner, "stage",
                      lambda self, items, assets, directives: StagingResult(items, "off"))
        baseline = plan([spec], tmp_path=tmp_path / "baseline", shuffle=shuffle)
    return Pair(staged, baseline)


def _items(planned: Planned, scene: int = 0) -> dict[str, LayoutItem]:
    return {i.asset_id.split(":", 1)[1]: i for i in planned.composition[scene].items}


def _staging(planned: Planned, scene: int = 0) -> str:
    (row,) = [e for e in planned.composition[scene].state_evidence
              if e.startswith("semantic_staging:")]
    return row


def _px(item: LayoutItem):
    return ((item.x - item.width / 2) * W, (item.y - item.height / 2) * H,
            (item.x + item.width / 2) * W, (item.y + item.height / 2) * H)


def _gap(a, b) -> float:
    return max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])


def _connector(items: dict[str, LayoutItem], source: str, target: str, margin: float = 0.0):
    others = [tuple(v + d for v, d in zip(_px(item), (-margin, -margin, margin, margin)))
              for key, item in sorted(items.items()) if key not in {source, target}]
    return _endpoints(_px(items[source]), _px(items[target]), others)


def _length(points) -> float:
    if points is None:
        return 0.0
    (x0, y0), (x1, y1) = points
    return float(np.hypot(x1 - x0, y1 - y0))


def _moved(pair: Pair) -> dict[str, tuple[float, float]]:
    before, after = _items(pair.baseline), _items(pair.staged)
    return {k: (after[k].x - before[k].x, after[k].y - before[k].y)
            for k in after if (after[k].x, after[k].y) != (before[k].x, before[k].y)}


@pytest.fixture(scope="module")
def readable(tmp_path_factory) -> Pair:
    return _plan_pair(flow_scene(), tmp_path_factory.mktemp("readable"))


@pytest.fixture(scope="module")
def plain(tmp_path_factory) -> Pair:
    return _plan_pair(flow_scene(relations=()), tmp_path_factory.mktemp("plain"))


@pytest.fixture(scope="module")
def crowded(tmp_path_factory) -> Pair:
    spec = flow_scene(target=("bag", CROWDED_BAG, (7, 7), "RESULT"))
    return _plan_pair(spec, tmp_path_factory.mktemp("crowded"))


@pytest.fixture(scope="module")
def crossing(tmp_path_factory) -> Pair:
    spec = flow_scene(extra=(("blocker", CLIPPER, (3, 3), "supporting"),))
    return _plan_pair(spec, tmp_path_factory.mktemp("crossing"))


@pytest.fixture(scope="module")
def blocked(tmp_path_factory) -> Pair:
    spec = flow_scene(extra=(("blocker", BLOCKER, (3, 3), "supporting"),))
    return _plan_pair(spec, tmp_path_factory.mktemp("blocked"))


@pytest.fixture(scope="module")
def adjusted(crowded, crossing) -> list[Pair]:
    return [crowded, crossing]


# -- unit-level scaffolding -------------------------------------------------------------
def _asset(asset_id: str, *, family: str | None = None) -> VisualAsset:
    return VisualAsset(id=asset_id, scene_id="s", role="supporting",
                       image_path=Path("missing") / f"{asset_id}.png",
                       asset_family_id=family, extraction_method="test")


def _item(asset_id: str, x: float, y: float, w: float = 0.10, h: float = 0.16) -> LayoutItem:
    return LayoutItem(asset_id=asset_id, x=x, y=y, width=w, height=h,
                      placement_source="authored_scene_geometry")


def _directive(*pairs, beat_id="b", treatment=RelationTreatment.INTERACTION, leader=None):
    return ChoreographyDirective(
        beat_id=beat_id, sequence_id="q", phase=SequencePhase.SETUP, action="REVEAL",
        primary_asset_id=leader,
        relation_flows=tuple(
            RelationFlowDecision(relationship="ENABLES", source_asset_id=s,
                                 target_asset_id=t, treatment=treatment, reason="test")
            for s, t in pairs
        ),
    )


def _stage(items, assets, directives) -> StagingResult:
    return SemanticStagingPlanner().stage(items, assets, directives)


# 1. No semantic evidence keeps baseline geometry ---------------------------------------------
def test_no_semantic_evidence_keeps_baseline_geometry(plain) -> None:
    assert _staging(plain.staged) == "semantic_staging:baseline:no_relation_evidence"
    assert _items(plain.staged) == _items(plain.baseline)


# 2. Already-good relation layout is unchanged -----------------------------------------------
def test_already_readable_relation_layout_is_unchanged(readable) -> None:
    assert _staging(readable.staged) == "semantic_staging:baseline:readable"
    assert _items(readable.staged) == _items(readable.baseline)


# 3 + 15. Source-target crowding triggers conservative staging and spacing improves ------------
def test_crowded_source_target_is_staged_and_spacing_improves(crowded) -> None:
    assert _staging(crowded.staged).startswith(
        "semantic_staging:adjusted:participant_crowding:")
    before, after = _items(crowded.baseline), _items(crowded.staged)
    assert _connector(before, "chip", "bag") is None
    assert _length(_connector(after, "chip", "bag", margin=_MATERIAL_MARGIN_PX)) >= _MATERIAL_LENGTH_PX
    assert _gap(_px(after["chip"]), _px(after["bag"])) > _gap(_px(before["chip"]), _px(before["bag"]))
    assert set(_moved(crowded)) == {"bag"}


def test_minimum_size_connector_is_marginal_and_keeps_baseline(tmp_path) -> None:
    pair = _plan_pair(flow_scene(target=("bag", TIGHT_BAG, (7, 7), "RESULT")), tmp_path)
    assert _staging(pair.staged).startswith("semantic_staging:baseline:marginal_improvement:")
    assert _items(pair.staged) == _items(pair.baseline)


# 4. The chosen adjustment is the smallest effective one ---------------------------------------
def test_adjustment_is_smallest_effective_displacement(crowded) -> None:
    ((dx, dy),) = _moved(crowded).values()
    assert dy == 0.0 and 0.0 < abs(dx) <= MAX_SHIFT + 1e-9
    before = _items(crowded.baseline)
    smaller = dict(before)
    step = MAX_SHIFT / 8
    smaller["bag"] = before["bag"].model_copy(update={"x": before["bag"].x + dx - np.sign(dx) * step})
    assert _length(_connector(smaller, "chip", "bag", margin=_MATERIAL_MARGIN_PX)) < _MATERIAL_LENGTH_PX
    larger = dict(before)
    larger["bag"] = before["bag"].model_copy(update={"x": before["bag"].x + np.sign(dx) * MAX_SHIFT})
    assert _length(_connector(larger, "chip", "bag", margin=_MATERIAL_MARGIN_PX)) >= _MATERIAL_LENGTH_PX


# 5. Safe frame ------------------------------------------------------------------------------
def test_final_layout_preserves_safe_frame(adjusted) -> None:
    for pair in adjusted:
        after = _items(pair.staged)
        for key in _moved(pair):
            left, top, right, bottom = box(after[key], (0.0, 0.0, 1.0))
            assert left >= PROFILE.safe_left and right <= PROFILE.safe_right
            assert top >= PROFILE.safe_top and bottom <= PROFILE.safe_bottom
        assert ConstraintLayoutSolver().inspect(
            pair.staged.composition[0].items, {a.id: a for a in pair.staged.assets}) == []


# 6 + 7. No overlap, no important touching ----------------------------------------------------
def test_staged_family_never_overlaps_or_touches_another(adjusted) -> None:
    for pair in adjusted:
        after = _items(pair.staged)
        for key in _moved(pair):
            for other, item in after.items():
                if other != key:
                    assert _gap(_px(after[key]), _px(item)) >= _CLEARANCE_PX


# 8 - 11. Size, aspect and asset identity are untouched ---------------------------------------
def test_sizes_aspect_and_asset_set_are_unchanged(adjusted) -> None:
    for pair in adjusted:
        before, after = _items(pair.baseline), _items(pair.staged)
        assert list(after) == list(before)  # same count, none invented, none removed
        for key in before:
            assert (after[key].width, after[key].height, after[key].z) == (
                before[key].width, before[key].height, before[key].z)
        assert {a.id for a in pair.staged.assets} == {a.id for a in pair.baseline.assets}


# 12. Story timing is not modified ------------------------------------------------------------
def test_story_timing_is_unchanged(adjusted) -> None:
    for pair in adjusted:
        assert [b.model_dump(mode="json") for b in pair.staged.story] == [
            b.model_dump(mode="json") for b in pair.baseline.story]
        timing = lambda p: sorted((c.asset_id, c.start, c.end) for c in p.motion)  # noqa: E731
        assert timing(pair.staged) == timing(pair.baseline)


# 13 + 14. Leader readable; support subordinate without being hidden --------------------------
def test_leader_readable_and_support_kept_visible(crossing) -> None:
    after = _items(crossing.staged)
    directive = crossing.staged.choreography.directives[0]
    leader = directive.primary_asset_id.split(":", 1)[1]
    assert leader not in _moved(crossing)
    assert _connector(after, "chip", "bag") is not None
    assert set(_moved(crossing)) == {"blocker"}
    blocker = crossing.staged.rid("blocker")
    assert any(c.asset_id == blocker for c in crossing.staged.motion)
    assert any(a.asset_id == blocker for a in crossing.staged.story[0].asset_activations)


# 16 + 17. Crossing improves with one bounded move, not a redesign ----------------------------
def test_connector_crossing_improves_with_a_single_bounded_move(crossing) -> None:
    assert _staging(crossing.staged).startswith("semantic_staging:adjusted:relation_crossing:")
    assert _connector(_items(crossing.baseline), "chip", "bag") is None
    assert _connector(_items(crossing.staged), "chip", "bag", margin=_MATERIAL_MARGIN_PX)
    ((dx, dy),) = _moved(crossing).values()
    assert (dx == 0.0) != (dy == 0.0) and max(abs(dx), abs(dy)) <= MAX_SHIFT + 1e-9


# 18. An unsafe connector still abstains -------------------------------------------------------
def test_unfixable_connector_keeps_baseline_and_still_abstains(blocked) -> None:
    assert _staging(blocked.staged).startswith("semantic_staging:baseline:no_safe_improvement:")
    assert _items(blocked.staged) == _items(blocked.baseline)
    assert _connector(_items(blocked.staged), "chip", "bag") is None


# 19. Dense scene keeps baseline when no family is free ----------------------------------------
def test_dense_scene_preserves_baseline_when_improvement_is_unsafe() -> None:
    items = [_item("a", 0.40, 0.50), _item("b", 0.51, 0.50),
             _item("c", 0.40, 0.67), _item("d", 0.51, 0.67), _item("e", 0.40, 0.33),
             _item("f", 0.51, 0.33), _item("g", 0.62, 0.50), _item("h", 0.29, 0.50)]
    assets = [_asset(i.asset_id) for i in items]
    result = _stage(items, assets, [_directive(("a", "b"))])
    assert result.items == items
    assert result.evidence.startswith("semantic_staging:baseline:")
    assert ":readable" not in result.evidence


# 20. Sparse scene is not spread out -----------------------------------------------------------
def test_sparse_scene_is_not_spread(readable, crowded) -> None:
    assert not _moved(readable)

    def span(planned):
        boxes = [_px(i) for i in _items(planned).values()]
        return max(b[2] for b in boxes) - min(b[0] for b in boxes)
    assert span(crowded.staged) - span(crowded.baseline) <= MAX_SHIFT * W + 1e-6


# 21. Unsupported / descriptive relations cause no reflow --------------------------------------
@pytest.mark.parametrize("kind", ["SPECIFIES", "REVEALS_IDENTITY", "INVENTED_VERB"])
def test_descriptive_or_unsupported_relation_triggers_no_reflow(kind, tmp_path) -> None:
    spec = flow_scene(target=("bag", CROWDED_BAG, (7, 7), "RESULT"),
                      relations=(("chip", kind, "bag"),))
    pair = _plan_pair(spec, tmp_path)
    assert _staging(pair.staged) == "semantic_staging:baseline:no_relation_evidence"
    assert _items(pair.staged) == _items(pair.baseline)


# 22 + 32. Multiple relations and repeated planning are deterministic --------------------------
def test_multiple_relations_and_repeated_planning_are_deterministic(tmp_path) -> None:
    spec = flow_scene(target=("bag", CROWDED_BAG, (7, 7), "RESULT"),
                      extra=(("server", (700, 120, 200, 180), (3, 3), "supporting"),),
                      relations=(("chip", "ENABLES", "bag"), ("chip", "SENDS_TO", "server")))
    first = plan([spec], tmp_path=tmp_path / "a")
    second = plan([spec], tmp_path=tmp_path / "b")
    dump = lambda p: [c.model_dump(mode="json") for c in p.composition]  # noqa: E731
    assert dump(first) == dump(second)
    items = [_item("a", 0.30, 0.5), _item("b", 0.42, 0.5)]
    assets = [_asset("a"), _asset("b")]
    runs = {_stage(items, assets, [_directive(("a", "b"))]).evidence for _ in range(3)}
    assert len(runs) == 1


def test_staging_never_trades_one_crowding_for_another() -> None:
    # Opening a->b by pushing b right would leave unrelated c tighter than before: keep baseline.
    items = [_item("a", 0.092, 0.5), _item("b", 0.2415, 0.5), _item("c", 0.391, 0.5)]
    assets = [_asset(i.asset_id) for i in items]
    assert _stage(items[:2], assets[:2], [_directive(("a", "b"))]).evidence.startswith(
        "semantic_staging:adjusted:")
    result = _stage(items, assets, [_directive(("a", "b"))])
    assert result.items == items
    assert result.evidence.startswith("semantic_staging:baseline:")


# 23. Competing relations fail conservatively --------------------------------------------------
def test_competing_relations_keep_baseline() -> None:
    # b sits tight between a and c: any single move fixing a->b crowds b->c and vice versa.
    items = [_item("a", 0.30, 0.5), _item("b", 0.4495, 0.5), _item("c", 0.599, 0.5)]
    assets = [_asset(i.asset_id) for i in items]
    alone = _stage(items, assets, [_directive(("a", "b"))])
    assert alone.evidence.startswith("semantic_staging:adjusted:")
    both = _stage(items, assets, [_directive(("a", "b"), ("b", "c"))])
    assert both.items == items
    assert both.evidence.startswith("semantic_staging:baseline:conflicting_relations:")


# 24 + 25. Sprint 4.1 character emphasis stays safe and restores ------------------------------
def test_sprint_4_1_emphasis_remains_safe_on_staged_geometry(tmp_path) -> None:
    spec = flow_scene(source=("hero", (60, 300, 280, 420), (2, 2), "CHARACTER"),
                      target=("bag", (428, 400, 200, 200), (7, 7), "RESULT"),
                      relations=(("hero", "ATTACKS", "bag"),))
    pair = _plan_pair(spec, tmp_path)
    assert _moved(pair), _staging(pair.staged)
    staged = pair.staged
    assert (staged.choreography.directives[0].emphasis_asset_ids
            == pair.baseline.choreography.directives[0].emphasis_asset_ids)
    items = staged.composition[0].items
    for cue in staged.motion:
        emphasis = cue.params.get("character_emphasis") or {}
        if not emphasis.get("peak_scale"):
            continue
        item = next(i for i in items if i.asset_id == cue.asset_id)
        grown = box(item, (0.0, 0.0, emphasis["peak_scale"]))
        assert grown[0] >= PROFILE.safe_left and grown[2] <= PROFILE.safe_right
        assert grown[1] >= PROFILE.safe_top and grown[3] <= PROFILE.safe_bottom
        for other in items:
            if other.asset_id != item.asset_id:
                assert overlap_ratio(grown, box(other, (0.0, 0.0, 1.0))) <= (
                    authored_overlap_ratio(item, other) + 0.005 + 1e-9)
    _assert_every_program_settles(staged)


def _assert_every_program_settles(planned: Planned) -> None:
    for cue in planned.motion:
        for program in [cue.params.get("program") or {}, *(s.program for s in cue.segments)]:
            frames = program.get("keyframes") or []
            if frames:
                last = frames[-1]
                assert (last["dx"], last["dy"], last["scale"]) == (0.0, 0.0, 1.0)


def test_sprint_4_1_deemphasis_restores_on_staged_geometry(crowded) -> None:
    from app.models import MotionCue, MotionSegment
    from app.motion.emphasis import deemphasize_supporting

    items = crowded.staged.composition[0].items
    staged = next(i for i in items if i.placement_source == STAGED_PLACEMENT_SOURCE)
    hero = LayoutItem(asset_id="hero", x=0.12, y=0.5, width=0.12, height=0.9)
    focus = MotionCue(beat_id="b", asset_id="hero", kind="program_v3", start=1.8, end=2.0,
                      params={"program": {"keyframes": [
                          {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "opacity": 1.0},
                          {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "opacity": 1.0}]},
                          "character_emphasis": {"applied": False, "reason": "no_safe_headroom",
                                                 "window": [2.0, 2.6]}})
    support = focus.model_copy(update={"asset_id": staged.asset_id, "start": 0.5, "end": 0.7,
                                       "params": {"program": focus.params["program"]}})
    carry = lambda cue, *, item: MotionSegment(  # noqa: E731
        phase="ENTRY", start=float(cue.start), end=float(cue.end), program=dict(cue.params["program"]))
    out = {c.asset_id: c for c in deemphasize_supporting(
        [focus, support], focus_asset_id="hero", layout_items=[hero, staged],
        protected_asset_ids={"hero"}, semantic_event_id="E", carry_entry=carry)}
    dip = next(s for s in out[staged.asset_id].segments if s.semantic_action == "DEEMPHASIZE")
    first, last = dip.program["keyframes"][0], dip.program["keyframes"][-1]
    assert (first["scale"], last["scale"], last["dx"], last["dy"]) == (1.0, 1.0, 0.0, 0.0)
    assert min(f["scale"] for f in dip.program["keyframes"]) < 1.0


# 26 + 27 + 28. Sprint 4.2 handoff lands on staged geometry, flow stays ordered ----------------
def test_sprint_4_2_handoff_lands_on_staged_composition(crowded) -> None:
    staged, baseline = crowded.staged, crowded.baseline
    assert staged.flows() == baseline.flows()
    (decision,) = staged.flows()
    assert decision.treatment == RelationTreatment.FOCUS_HANDOFF
    (segment,) = staged.handoffs("chip")
    (before,) = baseline.handoffs("chip")
    assert (segment.start, segment.end) == (before.start, before.end)
    bag = next(a for a in staged.story[0].asset_activations if a.asset_id == staged.rid("bag"))
    assert segment.start >= float(bag.reveal_start) - 1e-6
    frames = segment.program["keyframes"]
    assert (frames[-1]["dx"], frames[-1]["dy"], frames[-1]["scale"]) == (0.0, 0.0, 1.0)
    assert [c.model_dump(mode="json") for c in staged.composition] == staged.composition_before
    _assert_every_program_settles(staged)


# 29 + 30. Topology preserved; no universal left-to-right rule ---------------------------------
def test_topology_is_preserved(adjusted) -> None:
    for pair in adjusted:
        before, after = _items(pair.baseline), _items(pair.staged)
        for a in before:
            for b in before:
                for axis in ("x", "y"):
                    was = getattr(before[a], axis) - getattr(before[b], axis)
                    now = getattr(after[a], axis) - getattr(after[b], axis)
                    assert abs(was) < 1e-9 or was * now > 0


def test_no_universal_left_to_right_rule(tmp_path) -> None:
    mirrored = flow_scene(source=("chip", (660, 560, 280, 240), (2, 2), "supporting"),
                          target=("bag", (372, 560, 200, 200), (7, 7), "RESULT"))
    pair = _plan_pair(mirrored, tmp_path / "mirrored")
    ((dx, _dy),) = _moved(pair).values()
    assert dx < 0  # the target keeps its authored side; staging just opens the gap
    right_to_left = flow_scene(source=("chip", (640, 560, 280, 240), (2, 2), "supporting"),
                               target=("bag", (60, 120, 260, 240), (7, 7), "RESULT"))
    kept = _plan_pair(right_to_left, tmp_path / "kept")
    assert not _moved(kept)


# 31. Input-order independence -----------------------------------------------------------------
def test_input_order_independence(tmp_path) -> None:
    spec = flow_scene(target=("bag", CROWDED_BAG, (7, 7), "RESULT"))
    ordered = plan([spec], tmp_path=tmp_path / "a")
    shuffled = plan([spec], tmp_path=tmp_path / "b", shuffle=True)
    geometry = lambda p: {k: (i.x, i.y, i.width, i.height) for k, i in _items(p).items()}  # noqa: E731
    assert geometry(ordered) == geometry(shuffled)
    assert _staging(ordered) == _staging(shuffled)


# 33 + 34. No package-specific behavior, no Final Package dependency ---------------------------
def test_no_package_specific_behavior_or_final_package_dependency() -> None:
    source = inspect.getsource(staging_module)
    for token in ("SCENE_0", "BLACK_HAT", "INSIDER", "HACKTIVIST", "WHITE_HAT", "HEXA_", "PROMO"):
        assert token not in source.upper()
    for module in ("app.final", "app.final_package", "app.canonical", "app.vision", "app.cutout"):
        assert f"from {module}" not in source and f"import {module}" not in source


# Rigid families, per-scene resolution and the authored lock ----------------------------------
def test_family_layers_move_rigidly_with_one_delta() -> None:
    # "a" hugs the safe edge, so the crowded relation can only open by moving family "b".
    items = [_item("a", 0.092, 0.5), _item("b", 0.2415, 0.5), _item("b:secondary-1", 0.2415, 0.5)]
    assets = [_asset("a"), _asset("b", family="b"), _asset("b:secondary-1", family="b")]
    result = _stage(items, assets, [_directive(("a", "b"))])
    assert result.evidence.startswith("semantic_staging:adjusted:participant_crowding:b:")
    moved = {i.asset_id: (i.x - o.x, i.y - o.y) for i, o in zip(result.items, items) if i != o}
    assert set(moved) == {"b", "b:secondary-1"}
    assert moved["b"] == moved["b:secondary-1"]


def test_staging_is_resolved_once_per_scene_for_every_beat(tmp_path) -> None:
    mapper = AuthoredGeometryMapper()
    assets = [
        VisualAsset(id=key, scene_id="s", role="supporting", image_path=tmp_path / f"{key}.png",
                    extraction_method="test", source_bbox=bbox, source_canvas_width=1000,
                    source_canvas_height=1000)
        for key, bbox in (("a", (60, 560, 280, 240)), ("b", CROWDED_BAG))
    ]
    beats = [StoryBeat(id=f"b{n}", scene_id="s", start=n * 2.0, end=n * 2.0 + 2.0,
                       narration="x", action="REVEAL") for n in range(3)]
    plan_ = ChoreographyPlan(directives=(_directive(("a", "b"), beat_id="b1"),))
    layouts = CompositionPlanner().plan(beats, assets, plan_)
    geometry = [[(i.asset_id, i.x, i.y) for i in layout.items] for layout in layouts]
    assert geometry[0] == geometry[1] == geometry[2]
    assert geometry[0] != [(a.id, mapper.item(a).x, mapper.item(a).y) for a in assets]


def test_staged_placement_stays_inside_the_authored_lock() -> None:
    staged = _item("a", 0.5, 0.5).model_copy(update={"placement_source": STAGED_PLACEMENT_SOURCE})
    beat = CompositionBeat(beat_id="b", items=[staged])
    solved = ConstraintLayoutSolver().solve(beat, [_asset("a")])
    assert solved.items == [staged]
    assert "layout:authored_geometry_locked" in solved.state_evidence


# 38. Malformed or impossible evidence falls back to baseline ---------------------------------
def test_malformed_semantic_evidence_falls_back_to_baseline() -> None:
    items = [_item("a", 0.30, 0.5), _item("b", 0.42, 0.5)]
    assets = [_asset("a"), _asset("b")]
    for directive in (
        _directive(("a", "ghost")), _directive(("a", "a")), _directive((None, "b")),
        _directive(("a", "b"), treatment=RelationTreatment.ABSTAIN),
    ):
        result = _stage(items, assets, [directive])
        assert result.items == items and "baseline" in result.evidence
    assert _stage([], [], [_directive(("a", "b"))]).items == []
    fallback = [items[0], items[1].model_copy(update={"placement_source": "fallback_missing"})]
    assert _stage(fallback, assets, [_directive(("a", "b"))]).items == fallback
    touching = [_item("a", 0.30, 0.5), _item("b", 0.39, 0.5)]  # authored contact: never pulled apart
    assert _stage(touching, assets, [_directive(("a", "b"))]).items == touching


# 36. Representative character -> file -> server relationship ---------------------------------
def test_representative_relationship_case_is_staged_more_clearly(tmp_path) -> None:
    spec = flow_scene(
        source=("hero", (60, 300, 260, 420), (2, 2), "CHARACTER"),
        target=("server", (760, 300, 200, 300), (7, 7), "RESULT"),
        extra=(("file", (408, 380, 150, 150), (4, 4), "supporting"),),
        relations=(("hero", "SENDS_TO", "file"), ("file", "TRANSFERS_TO", "server")),
    )
    pair = _plan_pair(spec, tmp_path)
    before, after = _items(pair.baseline), _items(pair.staged)
    readable = lambda items: sum(  # noqa: E731
        _connector(items, s, t) is not None for s, t in (("hero", "file"), ("file", "server")))
    assert _staging(pair.staged).startswith("semantic_staging:adjusted:participant_crowding:")
    assert readable(after) == 2 > readable(before)
    assert set(_moved(pair)) == {"file"}  # character and server keep their authored place


# 35 + 37. Encoded frames rest on staged geometry; unchanged scenes render the 4.2 contract ----
def _frame(video: Path, at: float) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", "scale=960:540,format=gray", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(540, 960)


def _compile(planned: Planned, workspace: Path):
    from app.render import RenderPlanner
    from app.text import TextPlanner

    text = TextPlanner().plan(transcript=planned.transcript, story=planned.story,
                              assets=planned.assets, package=planned.package,
                              choreography=planned.choreography)
    workspace.mkdir(parents=True)
    plan_, _ = RenderPlanner().compile(planned.transcript, planned.assets, planned.story,
                                       planned.composition, planned.motion, workspace, text=text)
    return plan_


def test_unadjusted_scene_compiles_to_the_sprint_4_2_render_contract(readable, tmp_path) -> None:
    staged = _compile(readable.staged, tmp_path / "staged")
    baseline = _compile(readable.baseline, tmp_path / "baseline")
    assert [c.items for c in staged.composition] == [c.items for c in baseline.composition]
    assert [m.model_dump(mode="json") for m in staged.motion] == [
        m.model_dump(mode="json") for m in baseline.motion]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_final_rest_equals_staged_composition(crowded, tmp_path) -> None:
    from app.render.renderer import FFmpegRenderer

    plan_ = _compile(crowded.staged, tmp_path / "render")
    assert [c.items for c in plan_.composition] == [c.items for c in crowded.staged.composition]
    video = FFmpegRenderer("ffmpeg").render(plan_, tmp_path / "video.mp4")
    frame = _frame(video, float(plan_.duration) - 0.10)
    before, after = _items(crowded.baseline)["bag"], _items(crowded.staged)["bag"]
    top, bottom = int((after.y - after.height / 4) * 540), int((after.y + after.height / 4) * 540)
    old_left = int((before.x - before.width / 2) * 960)
    new_left = int((after.x - after.width / 2) * 960)
    new_right = int((after.x + after.width / 2) * 960)
    old_right = int((before.x + before.width / 2) * 960)
    vacated = frame[top:bottom, old_left + 2:new_left - 2]
    gained = frame[top:bottom, old_right + 2:new_right - 2]
    assert (gained < 235).mean() > 0.8   # the bag rests at its staged position
    assert (vacated < 235).mean() < 0.35  # and no longer at its baseline position


def test_chip_stays_in_place_while_the_crowded_target_moves(crowded) -> None:
    assert _items(crowded.staged)["chip"] == _items(crowded.baseline)["chip"]
    assert CHIP[0] < CROWDED_BAG[0]
