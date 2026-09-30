"""SemanticCarrierResolver: the single authority for semantic asset -> runtime cutouts."""

from __future__ import annotations

import dataclasses
import json
import random

import pytest

from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.story.carrier_resolver import (
    CarrierConfidence as Conf,
    CarrierKind as Kind,
    SemanticCarrierResolver,
)
from app.story.identity import VisualIdentityBinder
from tests.support.carrier_matrix import POSITIVE_FAMILIES, family_case
from tests.support.carrier_scene import Cutout, Event, SceneSpec, Unit, build_package, locator_for

PHRASE = tuple(f"w{i}" for i in range(8))
A, B, C, D = (40, 100, 200, 300), (300, 100, 200, 300), (560, 100, 200, 300), (780, 500, 180, 300)


def _resolve(spec: SceneSpec, hints: dict[str, str] | None = None):
    built = build_package([spec])
    sid = built.scene_ids[0]
    resolution = SemanticCarrierResolver().resolve(
        scene=built.package.scenes[0], assets=built.assets,
        order_hints={f"{sid}_{k}": f"{sid}:{v}" for k, v in (hints or {}).items()},
    )
    return built, resolution, lambda name: resolution.assignments[f"{sid}_{name}"]


def _ids(assignment) -> list[str]:
    return [member.cutout_id.split(":", 1)[1] for member in assignment.members]


def _spec(units, cutouts, events=None, **kwargs) -> SceneSpec:
    events = events if events is not None else (Event("E1", units[0].name, (0, 1)),)
    return SceneSpec(phrase=PHRASE, units=tuple(units), cutouts=tuple(cutouts),
                     events=tuple(events), **kwargs)


# ---------------------------------------------------------------- scoring signals

def test_scoring_rewards_overlap_centre_size_and_shape() -> None:
    score = VisualIdentityBinder._geometry_score
    locator = (0.2, 0.2, 0.4, 0.6)
    exact = score(locator, locator)
    shifted = score(locator, (0.25, 0.2, 0.45, 0.6))
    outside = score(locator, (0.7, 0.2, 0.9, 0.6))
    tiny = score(locator, (0.29, 0.39, 0.31, 0.41))
    wide = score(locator, (0.2, 0.35, 0.4, 0.45))
    assert exact == pytest.approx(1.0)
    assert exact > shifted > outside
    assert outside < 0.2
    assert tiny < 0.60 and wide < exact
    assert score(locator, (0.0, 0.0, 1.0, 1.0)) < 0.60  # a huge cutout is not the target


def test_claimed_parent_family_bonus_and_penalty() -> None:
    bonus = VisualIdentityBinder._family_bonus
    built = build_package([_spec([Unit("P", (0, 0), locator=locator_for(A))],
                                 [Cutout("asset-01", A), Cutout("asset-02", B)])])
    parent, other = built.assets
    member = other.model_copy(update={"parent_asset_id": parent.id})
    stranger = other.model_copy(update={"parent_asset_id": "someone-else"})
    assert bonus(member, parent) > 0 > bonus(stranger, parent)
    assert bonus(other, None) == 0.0


# ---------------------------------------------------------------- locator evidence

def test_precise_locator_is_a_proven_exclusive_carrier() -> None:
    _, resolution, of = _resolve(_spec(
        [Unit("X", (0, 1), role="primary", locator=locator_for(A))],
        [Cutout("asset-01", A), Cutout("asset-02", C)],
    ))
    row = of("X")
    assert (row.kind, row.confidence, _ids(row)) == (Kind.EXCLUSIVE, Conf.PROVEN, ["asset-01"])
    assert row.members[0].score >= 0.85 and row.members[0].margin >= 0.25
    assert resolution.owners == {resolution.assignments[row.semantic_asset_id].members[0].cutout_id:
                                 (row.semantic_asset_id,)}


def test_weaker_locator_is_accepted_but_not_called_proven() -> None:
    loose = locator_for((60, 120, 250, 340))
    _, _, of = _resolve(_spec([Unit("X", (0, 1), locator=loose)], [Cutout("asset-01", A)]))
    row = of("X")
    member = row.members[0]
    assert row.kind is Kind.EXCLUSIVE and 0.60 <= member.score < 0.85
    assert row.confidence is Conf.HIGH_CONFIDENCE


def test_wrong_locator_does_not_bind_to_an_unrelated_cutout() -> None:
    _, _, of = _resolve(_spec(
        [Unit("X", (0, 1), locator=(0.85, 0.85, 0.2, 0.2))],
        [Cutout("asset-01", A), Cutout("asset-02", B)],
    ))
    row = of("X")
    assert (row.kind, row.confidence, row.members, row.shared) == (
        Kind.NONE, Conf.UNRESOLVED, (), None,
    )


def test_too_broad_locator_takes_only_what_no_precise_locator_owns() -> None:
    _, resolution, of = _resolve(_spec(
        [Unit("BROAD", (0, 1), role="primary", locator=locator_for(A, B, C)),
         Unit("PRECISE", (2, 2), locator=locator_for(B))],
        [Cutout("asset-01", A), Cutout("asset-02", B), Cutout("asset-03", C)],
        events=(Event("E1", "BROAD", (0, 1), participants=("PRECISE",)),),
    ))
    assert _ids(of("PRECISE")) == ["asset-02"]
    assert sorted(_ids(of("BROAD"))) == ["asset-01", "asset-03"]
    assert of("BROAD").kind is Kind.GROUP
    assert all(len(owners) == 1 for owners in resolution.owners.values())


def test_overlapping_locators_resolve_to_their_own_cutouts() -> None:
    left, right = (100, 100, 300, 300), (330, 100, 300, 300)
    _, _, of = _resolve(_spec(
        [Unit("L", (0, 0), locator=locator_for((100, 100, 340, 300))),
         Unit("R", (1, 1), locator=locator_for((290, 100, 340, 300)))],
        [Cutout("asset-01", left), Cutout("asset-02", right)],
        events=(Event("E1", "L", (0, 1), participants=("R",)),),
    ))
    assert _ids(of("L")) == ["asset-01"] and _ids(of("R")) == ["asset-02"]


def test_locator_at_the_image_boundary_is_valid() -> None:
    corner = (0, 0, 180, 220)
    _, _, of = _resolve(_spec([Unit("X", (0, 1), locator=locator_for(corner))],
                              [Cutout("asset-01", corner), Cutout("asset-02", C)]))
    assert _ids(of("X")) == ["asset-01"] and of("X").confidence is Conf.PROVEN


def test_tiny_and_nested_targets_keep_their_own_identity() -> None:
    big, inner, tiny = (100, 100, 500, 600), (250, 300, 120, 120), (800, 800, 22, 22)
    _, _, of = _resolve(_spec(
        [Unit("BIG", (0, 0), role="primary", locator=locator_for(big)),
         Unit("INNER", (1, 1), locator=locator_for(inner)),
         Unit("TINY", (2, 2), locator=locator_for(tiny))],
        [Cutout("asset-01", big), Cutout("asset-02", inner), Cutout("asset-03", tiny)],
        events=(Event("E1", "BIG", (0, 2), participants=("INNER", "TINY")),),
    ))
    assert (_ids(of("BIG")), _ids(of("INNER")), _ids(of("TINY"))) == (
        ["asset-01"], ["asset-02"], ["asset-03"],
    )


def test_repeated_similar_icons_each_keep_their_locator_cutout() -> None:
    boxes = [(40 + 240 * i, 400, 180, 180) for i in range(4)]
    units = [Unit(f"I{i}", (i, i), locator=locator_for(box)) for i, box in enumerate(boxes)]
    _, _, of = _resolve(_spec(
        units, [Cutout(f"asset-0{i + 1}", box) for i, box in enumerate(boxes)],
        events=(Event("E1", "I0", (0, 3), participants=("I1", "I2", "I3")),),
    ))
    assert [_ids(of(f"I{i}")) for i in range(4)] == [[f"asset-0{i + 1}"] for i in range(4)]


# ---------------------------------------------------------------- ownership conflicts

def test_two_intents_on_one_cutout_share_it_instead_of_one_vanishing() -> None:
    _, resolution, of = _resolve(_spec(
        [Unit("ONE", (0, 0), role="primary", locator=locator_for(A)),
         Unit("TWO", (1, 1), locator=locator_for(A))],
        [Cutout("asset-01", A), Cutout("asset-02", C)],
        events=(Event("E1", "ONE", (0, 0)), Event("E2", "TWO", (1, 1), depends_on=("E1",))),
    ))
    rows = [of("ONE"), of("TWO")]
    assert all(row.kind is Kind.SHARED and not row.members for row in rows)
    assert {row.shared.cutout_id.split(":")[1] for row in rows} == {"asset-01"}
    assert len(resolution.owners[rows[0].shared.cutout_id]) == 2


def test_required_intent_with_two_equal_candidates_is_ambiguous_not_guessed() -> None:
    left, right = (240, 390, 160, 160), (600, 390, 160, 160)
    _, _, of = _resolve(_spec(
        [Unit("X", (0, 1), locator=(0.5, 0.47, 0.40, 0.40))],
        [Cutout("asset-01", left), Cutout("asset-02", right)],
    ))
    row = of("X")
    assert (row.kind, row.members, row.shared) == (Kind.NONE, (), None)
    assert row.confidence in {Conf.AMBIGUOUS, Conf.UNRESOLVED}
    assert {cutout.split(":")[1] for cutout, _ in row.candidates} == {"asset-01", "asset-02"}


def test_near_tied_one_to_one_candidates_are_classified_ambiguous() -> None:
    # Both candidates are larger than the locator (not contained members) and near-tied.
    near_a, near_b = (55, 50, 420, 420), (75, 70, 420, 420)
    _, _, of = _resolve(_spec(
        [Unit("X", (0, 1), locator=locator_for((115, 110, 300, 300)))],
        [Cutout("asset-01", near_a), Cutout("asset-02", near_b)],
    ))
    row = of("X")
    assert row.confidence is Conf.AMBIGUOUS and row.rival is not None and not row.members


def test_ambiguous_required_participant_fails_closed_with_typed_code() -> None:
    near_a, near_b = (455, 50, 420, 420), (475, 70, 420, 420)
    built = build_package([_spec(
        [Unit("LEAD", (0, 1), role="primary", locator=locator_for(A)),
         Unit("PART", (2, 3), locator=locator_for((515, 110, 300, 300)))],
        [Cutout("asset-01", A, role="primary"), Cutout("asset-02", near_a),
         Cutout("asset-03", near_b)],
        events=(Event("E1", "LEAD", (0, 3), participants=("PART",)),),
        group_policy="SIMULTANEOUS_VISUAL_UNIT",
    )])
    with pytest.raises(StageFailedError) as caught:
        StoryPlanner().plan(built.package, built.transcript, built.assets)
    assert caught.value.effective_code == "SEMANTIC_CARRIER_AMBIGUOUS"
    violation = caught.value.details["violations"][0]
    assert violation["semantic_asset_id"] == built.semantic_id(0, "PART")
    assert violation["resolution"]["confidence"] == "AMBIGUOUS"
    top, second = violation["resolution"]["candidates"][:2]
    assert top["score"] - second["score"] < 0.065 and second["score"] >= 0.60
    assert violation["resolution"]["ownership_conflict"]


def test_ambiguous_optional_intent_abstains_without_failing() -> None:
    near_a, near_b = (500, 100, 40, 40), (506, 104, 40, 40)
    built = build_package([_spec(
        [Unit("LEAD", (0, 1), role="primary", locator=locator_for(A)),
         Unit("OPTIONAL", (2, 3), locator=locator_for((503, 102, 40, 40)))],
        [Cutout("asset-01", A, role="primary"), Cutout("asset-02", near_a),
         Cutout("asset-03", near_b)],
        group_policy="SIMULTANEOUS_VISUAL_UNIT",
    )])
    planner = StoryPlanner()
    beats = planner.plan(built.package, built.transcript, built.assets)
    optional = planner.activation.carrier_resolutions[beats[0].id].assignments[
        built.semantic_id(0, "OPTIONAL")
    ]
    assert not optional.required and not optional.members
    assert optional.confidence in {Conf.AMBIGUOUS, Conf.UNRESOLVED}


# ---------------------------------------------------------------- presentation roles

def test_decorative_cutout_binds_only_when_the_intent_is_required() -> None:
    def case(required: bool):
        events = (Event("E1", "ORN" if required else "MAIN", (0, 1)),)
        return _resolve(_spec(
            [Unit("MAIN", (0, 1), role="primary", locator=locator_for(A)),
             Unit("ORN", (2, 2), role="decorative", locator=locator_for(C))],
            [Cutout("asset-01", A, role="primary"), Cutout("asset-02", C, role="decorative")],
            events=events,
        ))[2]("ORN")

    assert _ids(case(required=True)) == ["asset-02"]
    optional = case(required=False)
    assert not optional.members and not optional.required


def test_all_decorative_optional_scene_resolves_nothing_and_raises_nothing() -> None:
    _, resolution, of = _resolve(_spec(
        [Unit("ORN", (0, 0), role="decorative", locator=locator_for(A))],
        [Cutout("asset-01", A, role="decorative")], events=(),
    ))
    assert not of("ORN").members and resolution.owners == {}


# ---------------------------------------------------------------- compound carriers

def test_over_segmented_intent_is_one_group_not_many_identities() -> None:
    fragments = [(100 + 60 * i, 700 + 25 * (i % 2), 45, 30) for i in range(7)]
    _, resolution, of = _resolve(_spec(
        [Unit("HOUSE", (0, 0), role="primary", locator=locator_for(A)),
         Unit("PRINTS", (1, 2), locator=locator_for(*fragments))],
        [Cutout("asset-01", A, role="primary"),
         *(Cutout(f"asset-{i + 2:02d}", box) for i, box in enumerate(fragments))],
        events=(Event("E1", "HOUSE", (0, 0)), Event("E2", "PRINTS", (1, 2), depends_on=("E1",))),
    ))
    prints = of("PRINTS")
    assert prints.kind is Kind.GROUP and len(prints.members) == 7
    assert {owners for owners in resolution.owners.values()} == {
        (of("HOUSE").semantic_asset_id,), (prints.semantic_asset_id,),
    }
    assert set(resolution.assignments) == {of("HOUSE").semantic_asset_id, prints.semantic_asset_id}


def test_scattered_fragments_outside_the_locator_are_not_grouped() -> None:
    inside, far = (120, 700, 45, 30), (800, 100, 45, 30)
    _, _, of = _resolve(_spec(
        [Unit("PRINTS", (0, 1), locator=locator_for((100, 690, 200, 60)))],
        [Cutout("asset-01", inside), Cutout("asset-02", (190, 705, 45, 30)),
         Cutout("asset-03", far)],
    ))
    assert "asset-03" not in _ids(of("PRINTS"))


def test_under_segmented_cutout_is_shared_by_both_located_intents() -> None:
    merged = (500, 300, 340, 380)
    _, resolution, of = _resolve(_spec(
        [Unit("SIGNED", (0, 0), role="primary", locator=locator_for(A)),
         Unit("HAT", (1, 1), locator=locator_for((502, 436, 183, 242))),
         Unit("DOC", (2, 2), locator=locator_for((688, 303, 150, 376)))],
        [Cutout("asset-01", A, role="primary"), Cutout("asset-02", merged)],
        events=(Event("E1", "SIGNED", (0, 0)), Event("E2", "HAT", (1, 1), depends_on=("E1",)),
                Event("E3", "DOC", (2, 2), depends_on=("E2",))),
    ))
    hat, doc = of("HAT"), of("DOC")
    assert hat.kind is doc.kind is Kind.SHARED
    assert hat.shared.cutout_id == doc.shared.cutout_id
    assert resolution.owners[hat.shared.cutout_id] == (
        doc.semantic_asset_id, hat.semantic_asset_id,
    )


def test_region_near_tie_is_not_a_shared_carrier() -> None:
    _, _, of = _resolve(_spec(
        [Unit("X", (0, 1), locator=(0.5, 0.47, 0.40, 0.40))],
        [Cutout("asset-01", (240, 390, 160, 160)), Cutout("asset-02", (600, 390, 160, 160))],
    ))
    assert of("X").shared is None


# ---------------------------------------------------------------- locator-less intents

def test_explicit_runtime_id_is_proven_identity() -> None:
    built = build_package([_spec([Unit("X", (0, 1))], [Cutout("asset-01", A)])])
    semantic_id = built.semantic_id(0, "X")
    assets = [built.assets[0].model_copy(update={"id": semantic_id})]
    row = SemanticCarrierResolver().resolve(
        scene=built.package.scenes[0], assets=assets,
    ).assignments[semantic_id]
    assert (row.kind, row.confidence) == (Kind.EXPLICIT, Conf.PROVEN)


def test_unclaimed_order_hint_is_inferred_not_proof() -> None:
    _, _, of = _resolve(
        _spec([Unit("X", (0, 1))], [Cutout("asset-01", A), Cutout("asset-02", C)]),
        hints={"X": "asset-02"},
    )
    assert (of("X").kind, of("X").confidence, _ids(of("X"))) == (
        Kind.ORDER_HINT, Conf.INFERRED, ["asset-02"],
    )


def test_locator_less_intent_takes_the_single_unclaimed_cutout_by_elimination() -> None:
    _, _, of = _resolve(
        _spec([Unit("LOC", (0, 0), role="primary", locator=locator_for(A)),
               Unit("FREE", (1, 2))],
              [Cutout("asset-01", A), Cutout("asset-02", C)],
              events=(Event("E1", "LOC", (0, 2), participants=("FREE",)),)),
        hints={"FREE": "asset-01"},  # legacy hint collides with the locator owner
    )
    assert (of("FREE").kind, of("FREE").confidence, _ids(of("FREE"))) == (
        Kind.ELIMINATION, Conf.HIGH_CONFIDENCE, ["asset-02"],
    )


def test_locator_less_intents_with_several_free_cutouts_are_not_guessed() -> None:
    _, _, of = _resolve(_spec(
        [Unit("LOC", (0, 0), role="primary", locator=locator_for(A)),
         Unit("F1", (1, 1)), Unit("F2", (2, 2))],
        [Cutout("asset-01", A), Cutout("asset-02", B), Cutout("asset-03", C)],
        events=(Event("E1", "LOC", (0, 2), participants=("F1", "F2")),),
    ))
    assert all(of(name).confidence is Conf.UNRESOLVED and not of(name).members for name in ("F1", "F2"))


def test_required_intent_with_no_candidate_is_unresolved() -> None:
    for role_event in (
        Event("E1", "X", (0, 1)),
        Event("E1", "LEAD", (0, 1), participants=("X",)),
        Event("E1", "LEAD", (0, 1), results=("X",)),
    ):
        _, _, of = _resolve(_spec(
            [Unit("LEAD", (0, 0), role="primary", locator=locator_for(A)), Unit("X", (1, 1))],
            [Cutout("asset-01", A)], events=(role_event,),
        ))
        assert of("X").required and of("X").confidence is Conf.UNRESOLVED and not of("X").members


# ---------------------------------------------------------------- input validation

def test_duplicate_or_foreign_runtime_cutouts_are_rejected() -> None:
    built = build_package([_spec([Unit("X", (0, 1), locator=locator_for(A))], [Cutout("asset-01", A)])])
    scene = built.package.scenes[0]
    for broken in (
        built.assets * 2,
        [built.assets[0].model_copy(update={"scene_id": "ANOTHER_SCENE"})],
    ):
        with pytest.raises(StageFailedError) as caught:
            SemanticCarrierResolver().resolve(scene=scene, assets=broken)
        assert caught.value.effective_code == "SEMANTIC_CARRIER_INPUT_INVALID"


def test_empty_scene_and_scene_without_cutouts_resolve_cleanly() -> None:
    _, empty, _ = _resolve(_spec([], [Cutout("asset-01", A)], events=()))
    assert empty.assignments == {} and empty.owners == {}
    _, bare, of = _resolve(_spec([Unit("X", (0, 1), locator=locator_for(A))], []))
    assert of("X").confidence is Conf.UNRESOLVED and bare.cutout_ids == ()


# ---------------------------------------------------------------- invariants

def _payload(resolution) -> str:
    return json.dumps(resolution.to_payload(), sort_keys=True)


@pytest.mark.parametrize("seed", range(48))
def test_resolution_is_independent_of_unit_and_cutout_order(seed: int) -> None:
    family = POSITIVE_FAMILIES[seed % len(POSITIVE_FAMILIES)]
    spec = family_case(family, 3000 + seed).scenes[0]
    reference = SemanticCarrierResolver().resolve(
        scene=build_package([spec]).package.scenes[0], assets=build_package([spec]).assets,
    )
    rng = random.Random(seed)
    for _ in range(3):
        built = build_package([spec])
        scene = built.package.scenes[0]
        units = list(scene.units)
        assets = list(built.assets)
        rng.shuffle(units)
        rng.shuffle(assets)
        shuffled = scene.model_copy(update={"units": tuple(units)})
        assert _payload(SemanticCarrierResolver().resolve(scene=shuffled, assets=assets)) == (
            _payload(reference)
        )


@pytest.mark.parametrize("seed", range(48))
def test_resolution_references_only_real_same_scene_cutouts_and_authored_ids(seed: int) -> None:
    family = POSITIVE_FAMILIES[seed % len(POSITIVE_FAMILIES)]
    built = build_package([family_case(family, 4000 + seed).scenes[0]])
    scene = built.package.scenes[0]
    resolution = SemanticCarrierResolver().resolve(scene=scene, assets=built.assets)
    real = {asset.id for asset in built.assets if asset.scene_id == scene.id}
    assert set(resolution.assignments) == {unit.asset_id for unit in scene.assets}
    for row in resolution.assignments.values():
        used = [m.cutout_id for m in row.members] + ([row.shared.cutout_id] if row.shared else [])
        assert set(used) <= real
        assert bool(row.members) == (row.kind not in {Kind.NONE, Kind.SHARED})
    exclusive = [m.cutout_id for row in resolution.assignments.values() for m in row.members]
    assert len(exclusive) == len(set(exclusive)), "an owned cutout has exactly one owner"


@pytest.mark.parametrize("seed", range(36))
def test_unrelated_far_decorative_cutout_does_not_change_any_mapping(seed: int) -> None:
    family = ("few", "many", "decorative_leader", "overlap")[seed % 4]
    spec = family_case(family, 5000 + seed).scenes[0]
    base = SemanticCarrierResolver().resolve(
        scene=build_package([spec]).package.scenes[0], assets=build_package([spec]).assets,
    )
    extra = dataclasses.replace(
        spec, cutouts=(*spec.cutouts, Cutout("asset-99", (985, 985, 12, 12), role="decorative")),
    )
    grown = SemanticCarrierResolver().resolve(
        scene=build_package([extra]).package.scenes[0], assets=build_package([extra]).assets,
    )
    assert {k: [m.cutout_id for m in v.members] for k, v in grown.assignments.items()} == {
        k: [m.cutout_id for m in v.members] for k, v in base.assignments.items()
    }


@pytest.mark.parametrize("seed", range(36))
def test_optional_context_intent_does_not_break_required_mappings(seed: int) -> None:
    family = ("few", "many", "decorative_leader", "result_tail")[seed % 4]
    spec = family_case(family, 6000 + seed).scenes[0]
    base = SemanticCarrierResolver().resolve(
        scene=build_package([spec]).package.scenes[0], assets=build_package([spec]).assets,
    )
    grown_spec = dataclasses.replace(
        spec, units=(*spec.units, Unit("ZCONTEXT", (0, 0), locator=(0.97, 0.97, 0.04, 0.04))),
    )
    grown = SemanticCarrierResolver().resolve(
        scene=build_package([grown_spec]).package.scenes[0],
        assets=build_package([grown_spec]).assets,
    )
    for semantic_id, row in base.assignments.items():
        assert [m.cutout_id for m in grown.assignments[semantic_id].members] == [
            m.cutout_id for m in row.members
        ]


def test_resolution_report_is_inspectable_per_scene() -> None:
    built = build_package([_spec(
        [Unit("X", (0, 1), role="primary", locator=locator_for(A)), Unit("Y", (2, 2))],
        [Cutout("asset-01", A, role="primary"), Cutout("asset-02", C)],
        events=(Event("E1", "X", (0, 2), participants=("Y",)),),
    )])
    planner = StoryPlanner()
    planner.plan(built.package, built.transcript, built.assets)
    report = planner.carrier_resolution_report
    assert [row["scene_id"] for row in report] == built.scene_ids
    scene = report[0]
    assert set(scene) >= {"beat_id", "runtime_cutouts", "assignments", "cutout_owners", "unowned_cutouts"}
    row = scene["assignments"][0]
    assert set(row) >= {
        "semantic_asset_id", "roles", "required", "locator_present", "kind", "confidence",
        "selected", "shared_carrier", "candidates", "rejected", "ownership_conflict", "reason",
    }
    json.dumps(report)


def test_hint_to_a_missing_runtime_cutout_is_ignored_not_trusted() -> None:
    built = build_package([_spec([Unit("X", (0, 1))], [Cutout("asset-01", A), Cutout("asset-02", C)])])
    semantic_id = built.semantic_id(0, "X")
    row = SemanticCarrierResolver().resolve(
        scene=built.package.scenes[0], assets=built.assets,
        order_hints={semantic_id: "CARRIER_SCENE_001:asset-404", "GHOST_UNIT": built.assets[0].id},
    )
    assert set(row.assignments) == {semantic_id}
    assert row.assignments[semantic_id].confidence is Conf.UNRESOLVED
    assert not row.assignments[semantic_id].members

def test_decorative_speck_is_not_an_elimination_candidate() -> None:
    """Regression: an unrelated decorative fragment must not block a provable elimination."""
    units = [Unit("LOC", (0, 0), role="primary", locator=locator_for(A)), Unit("FREE", (1, 2))]
    events = (Event("E1", "LOC", (0, 2), participants=("FREE",)),)
    for extra in ((), (Cutout("asset-03", (985, 985, 9, 9), role="decorative"),)):
        _, _, of = _resolve(_spec(units, [Cutout("asset-01", A), Cutout("asset-02", C), *extra], events))
        assert (of("FREE").kind, _ids(of("FREE"))) == (Kind.ELIMINATION, ["asset-02"])
    # A second *non-decorative* free cutout is a real rival: still never guessed.
    _, _, of = _resolve(_spec(units, [Cutout("asset-01", A), Cutout("asset-02", C),
                                      Cutout("asset-03", D)], events))
    assert not of("FREE").members