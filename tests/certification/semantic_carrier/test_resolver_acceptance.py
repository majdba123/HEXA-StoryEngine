"""LAYER 2 - resolver semantic behaviour: roles, locator-less evidence, compounds, fuzz."""

from __future__ import annotations

import json
import time
import tracemalloc

import pytest

from app.canonical import CanonicalScriptSpan, CanonicalVisualProgression
from app.models import AssetActivation, StoryBeat
from app.shared.errors import StageFailedError
from app.story.carrier_resolver import (
    CarrierConfidence as Conf,
    CarrierKind as Kind,
    SemanticCarrierResolver,
)
from app.story.carriers import SemanticCarrierAuditor
from tests.support.carrier_scene import Cutout, Event, SceneSpec, Unit, build_package, locator_for

PHRASE = tuple(f"w{i}" for i in range(8))
LEAD_BOX, TARGET_BOX = (40, 100, 220, 300), (560, 120, 240, 320)
ROLES = ("LEADER", "PARTICIPANT", "RESULT", "TEXT_ANCHOR", "PROGRESSION_TARGET")
SITUATIONS = ("strong", "missing", "ambiguous", "hidden", "decorative_cutout", "compound")
PERFORMANCE_SIZES = (1, 5, 10, 25, 50, 75, 100, 150)
PERFORMANCE_BUDGET_MS = {1: 60, 5: 60, 10: 100, 25: 300, 50: 1200, 75: 3000, 100: 6000, 150: 18000}


def _scene_for_role(role: str, situation: str):
    """LEAD is always resolvable; TARGET holds exactly ``role`` in ``situation``."""
    fragments = [(560 + 85 * i, 120, 70, 320) for i in range(3)]
    near = [(500, 60, 360, 440), (518, 78, 360, 440)]
    target_locator = locator_for(*fragments) if situation == "compound" else locator_for(TARGET_BOX)
    cutouts = [Cutout("asset-01", LEAD_BOX, role="primary")]
    if situation in {"strong", "hidden"}:
        cutouts.append(Cutout("asset-02", TARGET_BOX))
    elif situation == "decorative_cutout":
        cutouts.append(Cutout("asset-02", TARGET_BOX, role="decorative"))
    elif situation == "compound":
        cutouts += [Cutout(f"asset-{i + 2:02d}", box) for i, box in enumerate(fragments)]
    elif situation == "ambiguous":
        cutouts += [Cutout("asset-02", near[0]), Cutout("asset-03", near[1])]

    lead = Unit("LEAD", (0, 1), role="primary", locator=locator_for(LEAD_BOX))
    target = Unit("TARGET", (2, 3), role="decorative" if situation == "decorative_cutout" else "supporting",
                  locator=target_locator)
    if role == "LEADER":
        events = (Event("E1", "LEAD", (0, 1)), Event("E2", "TARGET", (2, 3), depends_on=("E1",)))
    elif role == "PARTICIPANT":
        events = (Event("E1", "LEAD", (0, 3), participants=("TARGET",)),)
    elif role == "RESULT":
        events = (Event("E1", "LEAD", (0, 3), results=("TARGET",)),)
    else:
        events = (Event("E1", "LEAD", (0, 3)),)
    built = build_package([SceneSpec(PHRASE, (lead, target), tuple(cutouts), events,
                                     "SIMULTANEOUS_VISUAL_UNIT")])
    scene = built.package.scenes[0]
    target_id = built.semantic_id(0, "TARGET")
    if role == "TEXT_ANCHOR":
        scene = scene.model_copy(update={"semantic_events": tuple(
            event.model_copy(update={"text_anchor_asset_id": target_id})
            for event in scene.semantic_events
        )})
    elif role == "PROGRESSION_TARGET":
        scene = scene.model_copy(update={"visual_progression": (
            CanonicalVisualProgression(
                action="EXPLAIN", targets=(target_id,),
                trigger=CanonicalScriptSpan(text="w2", global_char_start=6, global_char_end=8),
            ),
        )})
    package = built.package.model_copy(update={"scenes": (scene,)})
    return built, package, scene, target_id


@pytest.mark.parametrize("situation", SITUATIONS)
@pytest.mark.parametrize("role", ROLES)
def test_required_role_matrix(role: str, situation: str) -> None:
    built, package, scene, target_id = _scene_for_role(role, situation)
    assert role in scene.semantic_carrier_roles[target_id]
    resolution = SemanticCarrierResolver().resolve(scene=scene, assets=built.assets)
    row = resolution.assignments[target_id]
    assert row.required
    carried = [member.cutout_id.split(":", 1)[1] for member in row.members]

    if situation in {"strong", "hidden", "decorative_cutout"}:
        assert carried == ["asset-02"] and row.confidence is Conf.PROVEN
    elif situation == "compound":
        assert sorted(carried) == ["asset-02", "asset-03", "asset-04"] and row.kind is Kind.GROUP
    elif situation == "missing":
        assert not carried and row.confidence is Conf.UNRESOLVED
    else:
        assert not carried and row.confidence is Conf.AMBIGUOUS and row.rival

    # The Story gate turns every non-carried required role into a typed failure.
    lead_runtime = built.runtime_id(0, "asset-01")
    activations = [AssetActivation(asset_id=lead_runtime, semantic_unit_id=built.semantic_id(0, "LEAD"),
                                   policy="SEMANTIC", source="unified_final_package")]
    visible = {lead_runtime: built.semantic_id(0, "LEAD")}
    for member in row.members:
        activations.append(AssetActivation(asset_id=member.cutout_id, semantic_unit_id=target_id,
                                           policy="SEMANTIC", source="unified_final_package"))
        if situation != "hidden":
            visible[member.cutout_id] = target_id
    beat = StoryBeat(id="beat-001", scene_id=scene.id, start=0.0, end=3.0, audio_start=0.0,
                     audio_end=3.0, narration="x", primary_asset_ids=[lead_runtime],
                     action="INTRODUCE", asset_activations=activations,
                     active_visual_semantic_state=visible)
    auditor = SemanticCarrierAuditor()
    records = auditor.audit(package=package, assets=built.assets, beats=[beat],
                            resolutions={"beat-001": resolution})
    status = next(r["status"] for r in records if r["semantic_asset_id"] == target_id)
    expected = {"strong": "CARRIED", "decorative_cutout": "CARRIED", "compound": "CARRIED",
                "missing": "UNRESOLVED", "ambiguous": "AMBIGUOUS",
                # A hidden carrier lying inside its own required locator is reported by
                # the stronger "hidden cutout inside required locator" rule.
                "hidden": "UNRESOLVED"}[situation]
    assert status == expected
    if expected == "CARRIED":
        auditor.require(records)
    else:
        with pytest.raises(StageFailedError) as caught:
            auditor.require(records)
        assert caught.value.effective_code == f"SEMANTIC_CARRIER_{expected}"


# ---------------------------------------------------------------- locator-less matrix

def _resolve(units, cutouts, events=None, hints=None):
    events = events if events is not None else (Event("E1", units[0].name, (0, 1)),)
    built = build_package([SceneSpec(PHRASE, tuple(units), tuple(cutouts), tuple(events))])
    sid = built.scene_ids[0]
    resolution = SemanticCarrierResolver().resolve(
        scene=built.package.scenes[0], assets=built.assets,
        order_hints={f"{sid}_{k}": (v if ":" in v else f"{sid}:{v}") for k, v in (hints or {}).items()},
    )
    return built, resolution, lambda name: resolution.assignments[f"{sid}_{name}"]


def test_locator_less_a_explicit_runtime_id_is_proven() -> None:
    built = build_package([SceneSpec(PHRASE, (Unit("X", (0, 1)),), (Cutout("asset-01", LEAD_BOX),),
                                     (Event("E1", "X", (0, 1)),))])
    semantic_id = built.semantic_id(0, "X")
    row = SemanticCarrierResolver().resolve(
        scene=built.package.scenes[0],
        assets=[built.assets[0].model_copy(update={"id": semantic_id})],
    ).assignments[semantic_id]
    assert (row.kind, row.confidence) == (Kind.EXPLICIT, Conf.PROVEN)
    assert row.members[0].score is None


def test_locator_less_b_one_intent_one_unclaimed_cutout_is_eliminated() -> None:
    _, _, of = _resolve(
        [Unit("LOC", (0, 0), role="primary", locator=locator_for(LEAD_BOX)), Unit("FREE", (1, 2))],
        [Cutout("asset-01", LEAD_BOX), Cutout("asset-02", TARGET_BOX)],
        events=(Event("E1", "LOC", (0, 2), participants=("FREE",)),),
    )
    row = of("FREE")
    assert (row.kind, row.confidence) == (Kind.ELIMINATION, Conf.HIGH_CONFIDENCE)
    assert row.members[0].cutout_id.endswith("asset-02") and row.members[0].score is None


def test_locator_less_c_one_intent_two_plausible_cutouts_is_not_guessed() -> None:
    _, _, of = _resolve(
        [Unit("LOC", (0, 0), role="primary", locator=locator_for(LEAD_BOX)), Unit("FREE", (1, 2))],
        [Cutout("asset-01", LEAD_BOX), Cutout("asset-02", TARGET_BOX),
         Cutout("asset-03", (300, 600, 200, 300))],
        events=(Event("E1", "LOC", (0, 2), participants=("FREE",)),),
    )
    assert not of("FREE").members and of("FREE").confidence is Conf.UNRESOLVED


def test_locator_less_d_two_intents_one_cutout_is_not_arbitrary() -> None:
    _, resolution, of = _resolve(
        [Unit("LOC", (0, 0), role="primary", locator=locator_for(LEAD_BOX)),
         Unit("F1", (1, 1)), Unit("F2", (2, 2))],
        [Cutout("asset-01", LEAD_BOX), Cutout("asset-02", TARGET_BOX)],
        events=(Event("E1", "LOC", (0, 2), participants=("F1", "F2")),),
    )
    assert not of("F1").members and not of("F2").members
    assert all(len(owners) == 1 for owners in resolution.owners.values())


def test_locator_less_e_order_hint_cannot_displace_a_locator_proven_owner() -> None:
    _, _, of = _resolve(
        [Unit("LOC", (0, 0), role="primary", locator=locator_for(LEAD_BOX)), Unit("FREE", (1, 2))],
        [Cutout("asset-01", LEAD_BOX), Cutout("asset-02", TARGET_BOX),
         Cutout("asset-03", (300, 600, 200, 300))],
        events=(Event("E1", "LOC", (0, 2), participants=("FREE",)),),
        hints={"FREE": "asset-01"},
    )
    assert [m.cutout_id.split(":")[1] for m in of("LOC").members] == ["asset-01"]
    assert of("LOC").confidence is Conf.PROVEN
    assert not of("FREE").members, "two free cutouts remain: the displaced intent is not guessed"


def test_locator_less_f_hint_to_unknown_runtime_id_invents_nothing() -> None:
    _, resolution, of = _resolve(
        [Unit("X", (0, 1))], [Cutout("asset-01", LEAD_BOX), Cutout("asset-02", TARGET_BOX)],
        hints={"X": "CERT:asset-404", "GHOST": "asset-01"},
    )
    assert not of("X").members and len(resolution.assignments) == 1


def test_unclaimed_order_hint_is_labelled_inferred_without_geometry_evidence() -> None:
    _, _, of = _resolve(
        [Unit("X", (0, 1))], [Cutout("asset-01", LEAD_BOX), Cutout("asset-02", TARGET_BOX)],
        hints={"X": "asset-02"},
    )
    row = of("X")
    assert (row.kind, row.confidence) == (Kind.ORDER_HINT, Conf.INFERRED)
    assert row.members[0].score is None and row.members[0].margin is None


def test_unrelated_decorative_speck_does_not_block_a_provable_elimination() -> None:
    """Regression: a decorative fragment is another unit's label, not an open candidate."""
    units = [Unit("LOC", (0, 0), role="primary", locator=locator_for(LEAD_BOX)), Unit("FREE", (1, 2))]
    events = (Event("E1", "LOC", (0, 2), participants=("FREE",)),)
    base = [Cutout("asset-01", LEAD_BOX), Cutout("asset-02", TARGET_BOX)]
    _, _, of = _resolve(units, [*base, Cutout("asset-03", (985, 985, 9, 9), role="decorative")], events)
    assert of("FREE").kind is Kind.ELIMINATION
    assert of("FREE").members[0].cutout_id.endswith("asset-02")


# ---------------------------------------------------------------- compound carriers

@pytest.mark.parametrize("fragments", [2, 3, 5, 10, 20])
@pytest.mark.parametrize("shape", ["footprints", "grid", "row_of_cards"])
def test_over_segmented_intent_stays_one_semantic_identity(fragments: int, shape: str) -> None:
    if shape == "footprints":
        boxes = [(30 + 46 * i, 820 + (16 if i % 2 else 0), 36, 26) for i in range(fragments)]
    elif shape == "row_of_cards":
        boxes = [(30 + 47 * i, 520, 40, 120) for i in range(fragments)]
    else:
        columns = 5
        boxes = [(40 + (i % columns) * 90, 430 + (i // columns) * 90, 70, 70) for i in range(fragments)]
    _, resolution, of = _resolve(
        [Unit("ANCHOR", (0, 0), role="primary", locator=locator_for((560, 60, 380, 320))),
         Unit("GROUPED", (1, 2), locator=locator_for(*boxes))],
        [Cutout("asset-01", (560, 60, 380, 320), role="primary"),
         *(Cutout(f"asset-{i + 2:02d}", box) for i, box in enumerate(boxes))],
        events=(Event("E1", "ANCHOR", (0, 0)), Event("E2", "GROUPED", (1, 2), depends_on=("E1",))),
    )
    grouped = of("GROUPED")
    assert len(grouped.members) == fragments and len(resolution.assignments) == 2
    assert grouped.kind in {Kind.GROUP, Kind.EXCLUSIVE} and grouped.confidence is not Conf.AMBIGUOUS
    assert {owners for owners in resolution.owners.values()} == {
        (of("ANCHOR").semantic_asset_id,), (grouped.semantic_asset_id,),
    }


@pytest.mark.parametrize("intents", [2, 3])
def test_under_segmented_cutout_keeps_every_intent_as_a_shared_carrier(intents: int) -> None:
    merged = (300, 250, 200 * intents + 20, 400)
    halves = [(310 + 200 * i, 250, 190, 400) for i in range(intents)]
    names = [f"PART{i}" for i in range(intents)]
    _, resolution, of = _resolve(
        [Unit("ANCHOR", (0, 0), role="primary", locator=locator_for(LEAD_BOX)),
         *(Unit(name, (i + 1, i + 1), locator=locator_for(halves[i])) for i, name in enumerate(names))],
        [Cutout("asset-01", LEAD_BOX, role="primary"), Cutout("asset-02", merged)],
        events=(Event("E1", "ANCHOR", (0, 0)),
                *(Event(f"E{i + 2}", name, (i + 1, i + 1), depends_on=(f"E{i + 1}",))
                  for i, name in enumerate(names))),
    )
    rows = [of(name) for name in names]
    merged_id = next(key for key in resolution.cutout_ids if key.endswith("asset-02"))
    for row in rows:
        carriers = [m.cutout_id for m in row.members] + ([row.shared.cutout_id] if row.shared else [])
        assert carriers == [merged_id] and row.reason, "no intent is dropped by under-segmentation"
    assert sum(bool(row.members) for row in rows) <= 1, "at most one exclusive owner"
    assert len(resolution.owners[merged_id]) == intents


def test_nested_intents_inside_one_compound_cutout_are_shared_not_dropped() -> None:
    compound = (200, 200, 600, 600)
    _, _, of = _resolve(
        [Unit("WHOLE", (0, 0), role="primary", locator=locator_for(compound)),
         Unit("INNER", (1, 1), locator=locator_for((420, 430, 150, 140)))],
        [Cutout("asset-01", compound, role="primary")],
        events=(Event("E1", "WHOLE", (0, 0)), Event("E2", "INNER", (1, 1), depends_on=("E1",))),
    )
    assert of("WHOLE").members[0].cutout_id.endswith("asset-01")
    inner = of("INNER")
    assert not inner.members and inner.shared and inner.shared.cutout_id.endswith("asset-01")


def test_mixed_two_intents_five_overlapping_fragments_and_an_unrelated_cutout() -> None:
    left = [(60 + 70 * i, 300 + 20 * (i % 2), 80, 120) for i in range(3)]
    right = [(560 + 90 * i, 320, 100, 140) for i in range(2)]
    _, resolution, of = _resolve(
        [Unit("LEFT", (0, 1), role="primary", locator=locator_for(*left)),
         Unit("RIGHT", (2, 3), locator=locator_for(*right))],
        [*(Cutout(f"asset-{i + 1:02d}", box) for i, box in enumerate(left + right)),
         Cutout("asset-06", (420, 880, 60, 60))],
        events=(Event("E1", "LEFT", (0, 1)), Event("E2", "RIGHT", (2, 3), depends_on=("E1",))),
    )
    assert sorted(m.cutout_id.split(":")[1] for m in of("LEFT").members) == [
        "asset-01", "asset-02", "asset-03",
    ]
    assert sorted(m.cutout_id.split(":")[1] for m in of("RIGHT").members) == ["asset-04", "asset-05"]
    payload = resolution.to_payload()
    assert [key.split(":")[1] for key in payload["unowned_cutouts"]] == ["asset-06"]
    assert all(len(owners) == 1 for owners in payload["cutout_owners"].values())


def test_parent_child_family_prefers_the_parents_own_child_cutout() -> None:
    parent_box, child_a, child_b = (100, 100, 300, 500), (430, 300, 120, 120), (450, 320, 120, 120)
    built = build_package([SceneSpec(
        PHRASE,
        (Unit("PARENT", (0, 0), role="primary", locator=locator_for(parent_box)),
         Unit("CHILD", (1, 1), locator=locator_for((440, 310, 120, 120)))),
        (Cutout("asset-01", parent_box, role="primary"), Cutout("asset-02", child_a),
         Cutout("asset-03", child_b)),
        (Event("E1", "PARENT", (0, 0)), Event("E2", "CHILD", (1, 1), depends_on=("E1",))),
    )])
    scene = built.package.scenes[0]
    parent_id, child_id = built.semantic_id(0, "PARENT"), built.semantic_id(0, "CHILD")
    scene = scene.model_copy(update={"units": tuple(
        unit.model_copy(update={"parent_asset_id": parent_id}) if unit.asset_id == child_id else unit
        for unit in scene.units
    )})
    parent_runtime = built.runtime_id(0, "asset-01")
    assets = [
        asset.model_copy(update={"parent_asset_id": parent_runtime}) if asset.id.endswith("asset-02")
        else asset.model_copy(update={"parent_asset_id": "some-other-parent"})
        if asset.id.endswith("asset-03") else asset
        for asset in built.assets
    ]
    without_family = SemanticCarrierResolver().resolve(scene=scene, assets=built.assets)
    assert without_family.assignments[child_id].confidence is Conf.AMBIGUOUS
    with_family = SemanticCarrierResolver().resolve(scene=scene, assets=assets)
    assert [m.cutout_id for m in with_family.assignments[child_id].members] == [
        built.runtime_id(0, "asset-02"),
    ]


# ---------------------------------------------------------------- locator geometry fuzz

FUZZ_BOXES = [
    (0, 0, 60, 60), (940, 0, 60, 60), (0, 940, 60, 60), (940, 940, 60, 60),   # corners
    (0, 470, 40, 60), (960, 470, 40, 60), (470, 0, 60, 40), (470, 960, 60, 40),  # borders
    (500, 500, 8, 8), (500, 500, 8, 300), (500, 500, 300, 8),                 # tiny / thin
    (5, 5, 990, 990),                                                         # near full frame
]


@pytest.mark.parametrize("box", FUZZ_BOXES)
@pytest.mark.parametrize("locator_scale", [1.0, 0.97, 1.03])
def test_locator_geometry_at_the_limits_resolves_to_the_true_cutout(box, locator_scale) -> None:
    x, y, w, h = box
    lw, lh = min(1000 - x, w * locator_scale), min(1000 - y, h * locator_scale)
    locator = ((x + lw / 2) / 1000, (y + lh / 2) / 1000, lw / 1000, lh / 1000)
    other = (400, 400, 90, 90) if (x, y) != (500, 500) and w < 900 else (100, 100, 60, 60)
    cutouts = [Cutout("asset-01", box)] + ([] if w >= 900 else [Cutout("asset-02", other)])
    _, _, of = _resolve([Unit("X", (0, 1), locator=locator)], cutouts)
    assert [m.cutout_id.split(":")[1] for m in of("X").members] == ["asset-01"]


@pytest.mark.parametrize("gap", [0, 1, 40, 300])
def test_border_contact_or_no_overlap_never_binds(gap: int) -> None:
    """Exact border contact and near-zero overlap are not evidence of ownership."""
    box = (600 + gap, 300, 200, 200)
    _, _, of = _resolve([Unit("X", (0, 1), locator=locator_for((400, 300, 200, 200)))],
                        [Cutout("asset-01", box)])
    row = of("X")
    assert not row.members and row.shared is None and row.confidence is Conf.UNRESOLVED


# ---------------------------------------------------------------- invalid candidate sets

def test_corrupt_candidate_sets_fail_typed_and_report_the_ids() -> None:
    built = build_package([SceneSpec(PHRASE, (Unit("X", (0, 1), locator=locator_for(LEAD_BOX)),),
                                     (Cutout("asset-01", LEAD_BOX),), (Event("E1", "X", (0, 1)),))])
    scene = built.package.scenes[0]
    duplicate = built.assets * 2
    foreign = [built.assets[0].model_copy(update={"scene_id": "OTHER_SCENE"})]
    for broken, key in ((duplicate, "duplicate_runtime_ids"), (foreign, "foreign_scene_runtime_ids")):
        with pytest.raises(StageFailedError) as caught:
            SemanticCarrierResolver().resolve(scene=scene, assets=broken)
        assert caught.value.effective_code == "SEMANTIC_CARRIER_INPUT_INVALID"
        assert caught.value.details[key] == [built.assets[0].id]


# ---------------------------------------------------------------- performance

PERFORMANCE_SAMPLES: dict[int, dict[str, float]] = {}


@pytest.mark.parametrize("count", PERFORMANCE_SIZES)
def test_resolver_scaling_is_bounded(count: int) -> None:
    columns = max(1, int(count ** 0.5 + 0.999))
    cell = 1000 // columns
    boxes = [((i % columns) * cell + 5, (i // columns) * cell + 5, cell - 10, cell - 10)
             for i in range(count)]
    built = build_package([SceneSpec(
        PHRASE, tuple(Unit(f"U{i:03d}", (0, 0), locator=locator_for(b)) for i, b in enumerate(boxes)),
        tuple(Cutout(f"asset-{i + 1:03d}", b) for i, b in enumerate(boxes)), (),
    )])
    scene = built.package.scenes[0]
    SemanticCarrierResolver().resolve(scene=scene, assets=built.assets)  # warm-up
    started = time.perf_counter()
    resolution = SemanticCarrierResolver().resolve(scene=scene, assets=built.assets)
    elapsed_ms = (time.perf_counter() - started) * 1000
    tracemalloc.start()
    SemanticCarrierResolver().resolve(scene=scene, assets=built.assets)
    peak_kb = tracemalloc.get_traced_memory()[1] / 1024
    tracemalloc.stop()
    PERFORMANCE_SAMPLES[count] = {
        "wall_ms": round(elapsed_ms, 2), "matrix_cells": count * count, "peak_kb": round(peak_kb, 1),
    }
    assert sum(len(row.members) for row in resolution.assignments.values()) == count
    assert all(row.confidence is Conf.PROVEN or row.confidence is Conf.HIGH_CONFIDENCE
               for row in resolution.assignments.values())
    assert elapsed_ms < PERFORMANCE_BUDGET_MS[count], f"{count} intents: {elapsed_ms:.0f} ms"
    json.dumps(resolution.to_payload())
