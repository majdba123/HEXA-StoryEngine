"""Required authored semantics must never silently lose their visible carrier.

Each test reproduces one production failure shape with generalized fixtures (no
real scene/asset ids): a decorative-labelled event leader, a proxy-proven carrier
hidden by the scene lifecycle, a locator-less intent displaced by a locator claim,
a group proxy on the wrong cutout, and an authored unit split into many cutouts.
"""

from __future__ import annotations

import pytest

from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.story.identity import VisualIdentityBinder
from tests.support.carrier_scene import Cutout, Event, SceneSpec, Unit, build_package, locator_for

PHRASE = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")

LEFT = (40, 200, 280, 600)
MIDDLE = (380, 300, 240, 400)
RIGHT = (680, 220, 280, 560)


def _plan(built):
    planner = StoryPlanner()
    beats = planner.plan(built.package, built.transcript, built.assets)
    return planner, beats


def _visible(beats, scene_id: str) -> set[str]:
    return {
        asset_id
        for beat in beats if beat.scene_id == scene_id
        for asset_id in (beat.active_visual_semantic_state or {})
    }


def _records(planner, semantic_id: str) -> dict:
    return next(r for r in planner.semantic_carrier_audit if r["semantic_asset_id"] == semantic_id)


def test_semantic_carrier_roles_cover_required_participation_only() -> None:
    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(
            Unit("LEAD", (0, 1)), Unit("PART", (2, 2)), Unit("RES", (3, 3)),
            Unit("CTX", (4, 4)), Unit("FREE", (5, 5)),
        ),
        cutouts=(Cutout("asset-01", LEFT),),
        events=(Event("E1", "LEAD", (0, 3), participants=("PART",), results=("RES",),
                      context=("CTX",)),),
    )])
    scene = built.package.scenes[0]
    roles = scene.semantic_carrier_roles
    sid = built.scene_ids[0]
    assert roles[f"{sid}_LEAD"] == ("LEADER", "TEXT_ANCHOR")
    assert roles[f"{sid}_PART"] == ("PARTICIPANT",)
    assert roles[f"{sid}_RES"] == ("RESULT",)
    assert f"{sid}_CTX" not in roles and f"{sid}_FREE" not in roles


@pytest.mark.parametrize("leader_position", [0, 1, 2])
def test_decorative_labelled_event_leader_keeps_its_cutout(leader_position: int) -> None:
    """Regression: a package-``decorative`` event leader must not become NOT_VISIBLE."""
    boxes = [LEFT, MIDDLE, RIGHT]
    names = ["U1", "U2", "U3"]
    leader = names[leader_position]
    units = tuple(
        Unit(
            name, (index, index + 1),
            role="decorative" if name == leader else ("primary" if index == 0 else "supporting"),
            locator=locator_for(box),
        )
        for index, (name, box) in enumerate(zip(names, boxes))
    )
    cutouts = tuple(
        Cutout(f"asset-0{index + 1}", box, role=unit.role)
        for index, (unit, box) in enumerate(zip(units, boxes))
    )
    built = build_package([SceneSpec(
        phrase=PHRASE, units=units, cutouts=cutouts,
        events=(Event("E1", leader, (0, 3),
                      participants=tuple(n for n in names if n != leader)),),
    )])

    planner, beats = _plan(built)

    sid = built.scene_ids[0]
    leader_runtime = built.runtime_id(0, f"asset-0{leader_position + 1}")
    state = beats[0].active_visual_semantic_state
    assert state[leader_runtime] == f"{sid}_{leader}"
    assert _visible(beats, sid) == {asset.id for asset in built.assets}
    assert _records(planner, f"{sid}_{leader}")["status"] == "CARRIED"


def test_optional_decorative_unit_is_not_forced_into_identity() -> None:
    """Only required participation lifts the decorative exclusion."""
    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(Unit("MAIN", (0, 1), role="primary", locator=locator_for(LEFT)),
               Unit("ORNAMENT", (2, 2), role="decorative", locator=locator_for(RIGHT))),
        cutouts=(Cutout("asset-01", LEFT, role="primary"),
                 Cutout("asset-02", RIGHT, role="decorative")),
        events=(Event("E1", "MAIN", (0, 1)),),
    )])
    scene = built.package.scenes[0]
    binding = VisualIdentityBinder().bind(
        scene=scene, semantic_assets=list(scene.units), assets=built.assets,
    )
    assert built.semantic_id(0, "MAIN") in binding.matches
    assert built.semantic_id(0, "ORNAMENT") in binding.unresolved_locator_ids


def test_proxy_proven_leader_is_visible_in_scene_lifecycle() -> None:
    """Approximate locators prove a region carrier; that carrier must render."""
    approximate = (0.20, 0.40, 0.18, 0.22)  # well inside LEFT, far too small for 1:1
    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(Unit("LEAD", (0, 1), role="primary", locator=approximate),),
        cutouts=(Cutout("asset-01", LEFT, role="primary"),),
        events=(Event("E1", "LEAD", (0, 1)),),
    )])

    planner, beats = _plan(built)

    runtime = built.runtime_id(0, "asset-01")
    assert beats[0].semantic_event_proxies, "expected a region-carrier proxy"
    assert runtime in beats[0].active_visual_semantic_state
    assert _records(planner, built.semantic_id(0, "LEAD"))["status"] == "CARRIED"


def test_locator_less_required_intent_binds_by_elimination() -> None:
    """A locator claim must not strand a locator-less leader on anonymous context."""
    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(
            Unit("GATE", (0, 0), role="primary", binding="EXPLICIT"),
            Unit("ACTOR", (1, 1), locator=locator_for(LEFT)),
            Unit("RESULT", (2, 3)),
        ),
        cutouts=(
            Cutout("asset-01", MIDDLE, role="primary"),
            Cutout("asset-02", RIGHT, role="supporting"),
            Cutout("asset-03", LEFT, role="supporting"),
        ),
        events=(Event("E1", "RESULT", (0, 3), participants=("GATE", "ACTOR"),
                      results=("RESULT",)),),
    )])

    planner, beats = _plan(built)

    required = [built.semantic_id(0, name) for name in ("GATE", "ACTOR", "RESULT")]
    assert all(_records(planner, name)["status"] == "CARRIED" for name in required)
    owners = {
        row.asset_id: row.semantic_unit_id
        for row in beats[0].asset_activations
        if row.semantic_unit_id in required
    }
    assert sorted(owners.values()) == sorted(required), "one distinct cutout per intent"
    assert any(
        "visual_identity_by_elimination" in row.evidence
        for row in beats[0].asset_activations
    )


def test_group_proxy_never_carries_a_located_member_outside_its_locator() -> None:
    """A member whose locator failed must not be proxied onto a sibling's cutout."""
    hat_and_doc = (500, 300, 340, 380)  # segmentation merged two authored objects
    cross = (845, 400, 140, 270)
    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(
            Unit("SIGNED", (0, 3), role="primary", locator=locator_for((20, 290, 350, 400))),
            Unit("KEY", (0, 3), locator=locator_for((372, 350, 100, 330))),
            Unit("OTHER", (1, 1), locator=locator_for((502, 436, 183, 242))),
            Unit("MISSING", (0, 3), locator=locator_for((688, 303, 300, 376))),
        ),
        cutouts=(
            Cutout("asset-01", (20, 290, 350, 400), role="primary"),
            Cutout("asset-02", hat_and_doc),
            Cutout("asset-03", cross),
            Cutout("asset-04", (372, 350, 100, 330)),
        ),
        events=(
            Event("E1", "SIGNED", (0, 3), participants=("MISSING",)),
            Event("E2", "KEY", (0, 3), depends_on=("E1",)),
            Event("E3", "OTHER", (1, 1), depends_on=("E2",)),
        ),
    )])

    planner, beats = _plan(built)

    other = built.semantic_id(0, "OTHER")
    record = _records(planner, other)
    assert record["status"] == "CARRIED"
    assert record["carrier_asset_ids"] == [built.runtime_id(0, "asset-02")]
    assert built.runtime_id(0, "asset-03") in _visible(beats, built.scene_ids[0])


def test_authored_unit_split_into_many_cutouts_keeps_every_piece() -> None:
    """Over-segmentation of one located unit (a person with loose keys)."""
    person = (300, 180, 180, 780)
    keys = [(20 + 70 * (i % 4), 120 + 160 * (i // 4), 60, 90) for i in range(7)]
    doors = (560, 60, 420, 520)
    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(
            Unit("TRYING", (0, 1), role="primary", locator=locator_for(person, *keys)),
            Unit("DOORS", (2, 3), locator=locator_for(doors)),
        ),
        cutouts=(
            Cutout("asset-01", doors, role="supporting"),
            Cutout("asset-02", person, role="primary"),
            *(Cutout(f"asset-{i + 3:02d}", box) for i, box in enumerate(keys)),
        ),
        events=(Event("E1", "TRYING", (0, 1)), Event("E2", "DOORS", (2, 3), depends_on=("E1",))),
    )])

    planner, beats = _plan(built)

    assert _visible(beats, built.scene_ids[0]) == {asset.id for asset in built.assets}
    assert planner.hidden_content_audit == []


def test_unresolved_required_carrier_fails_before_render_with_diagnostics() -> None:
    """Ambiguous locator-less participant + hidden candidates -> typed failure."""
    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(
            Unit("SIGNED", (0, 3), role="primary", locator=locator_for(LEFT)),
            Unit("AAA", (4, 4), binding="AMBIGUOUS"),
            Unit("BBB", (5, 5), binding="AMBIGUOUS"),
            Unit("ZMISSING", (0, 3)),
        ),
        cutouts=(
            Cutout("asset-01", LEFT, role="primary"),
            Cutout("asset-02", MIDDLE),
            Cutout("asset-03", RIGHT),
        ),
        events=(Event("E1", "SIGNED", (0, 3), participants=("ZMISSING",)),),
        group_policy="SIMULTANEOUS_VISUAL_UNIT",
    )])

    with pytest.raises(StageFailedError) as caught:
        StoryPlanner().plan(built.package, built.transcript, built.assets)

    error = caught.value
    assert error.effective_code == "SEMANTIC_CARRIER_UNRESOLVED"
    violation = next(
        row for row in error.details["violations"]
        if row["semantic_asset_id"] == built.semantic_id(0, "ZMISSING")
    )
    assert violation["scene_id"] == built.scene_ids[0]
    assert violation["semantic_event_ids"] == [f"{built.scene_ids[0]}_E1"]
    assert violation["roles"] == ["PARTICIPANT"]
    assert violation["locator_present"] is False
    assert violation["reason"] == "no_locator_and_scene_hides_cutouts"
    assert set(violation["candidate_hidden_asset_ids"]) == {
        built.runtime_id(0, "asset-02"), built.runtime_id(0, "asset-03"),
    }
    assert set(violation["runtime_mapping"]) == set(violation["candidate_hidden_asset_ids"])
    assert all(row["visible"] is False for row in violation["runtime_mapping"].values())
    assert violation["segmentation_ambiguity"] is True
    assert built.scene_ids[0] in str(error)


def test_dependency_proxy_outside_authored_locator_fails_closed() -> None:
    """A carrier that contradicts the authored locator is a wrong binding."""
    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(
            Unit("FIRST", (0, 1), role="primary", locator=locator_for(LEFT)),
            Unit("NOWHERE", (2, 3), locator=(0.80, 0.15, 0.20, 0.12)),
        ),
        cutouts=(Cutout("asset-01", LEFT, role="primary"),),
        events=(Event("E1", "FIRST", (0, 1)),
                Event("E2", "NOWHERE", (2, 3), depends_on=("E1",))),
    )])

    with pytest.raises(StageFailedError) as caught:
        StoryPlanner().plan(built.package, built.transcript, built.assets)

    violation = caught.value.details["violations"][0]
    assert caught.value.effective_code == "SEMANTIC_CARRIER_UNRESOLVED"
    assert violation["semantic_asset_id"] == built.semantic_id(0, "NOWHERE")
    assert violation["reason"] == "carrier_outside_authored_locator"


def _hidden_content_case(extra: Cutout, *, extra_unit: Unit | None = None):
    units = [Unit("MAIN", (0, 1), role="primary", locator=locator_for(LEFT))]
    if extra_unit is not None:
        units.append(extra_unit)
    return build_package([SceneSpec(
        phrase=PHRASE,
        units=tuple(units),
        cutouts=(Cutout("asset-01", LEFT, role="primary"), extra),
        events=(Event("E1", "MAIN", (0, 1)),),
        # A single sequential group schedules leftovers as context; simultaneous
        # groups keep the production lifecycle that hides unclaimed cutouts.
        group_policy="SIMULTANEOUS_VISUAL_UNIT",
    )])


@pytest.mark.parametrize(
    "extra,extra_unit,reason",
    [
        (Cutout("asset-02", RIGHT), None, "visually_significant_hidden_cutout"),
        (Cutout("asset-02", (700, 700, 40, 40), role="primary"), None,
         "hidden_cutout_with_authored_primary_role"),
        (Cutout("asset-02", (700, 700, 60, 60), role="decorative"),
         Unit("ORNAMENT", (4, 4), role="decorative", locator=(0.73, 0.73, 0.10, 0.10)),
         "hidden_cutout_inside_authored_locator"),
    ],
    ids=["significant-area", "authored-primary-role", "inside-authored-locator"],
)
def test_materially_hidden_authored_content_fails_before_render(extra, extra_unit, reason) -> None:
    built = _hidden_content_case(extra, extra_unit=extra_unit)
    with pytest.raises(StageFailedError) as caught:
        StoryPlanner().plan(built.package, built.transcript, built.assets)
    assert caught.value.effective_code == "AUTHORED_CONTENT_HIDDEN"
    violation = caught.value.details["violations"][0]
    assert violation["runtime_asset_id"] == built.runtime_id(0, "asset-02")
    assert violation["reason"] == reason


@pytest.mark.parametrize("count", [1, 4, 9])
def test_tiny_unlocated_segmentation_fragments_may_stay_hidden(count: int) -> None:
    """Dotted-line pieces and specks below the significance floor are not artwork."""
    dots = tuple(
        Cutout(f"asset-{i + 2:02d}", (620 + 30 * i, 900, 12, 12)) for i in range(count)
    )
    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(Unit("MAIN", (0, 1), role="primary", locator=locator_for(LEFT)),),
        cutouts=(Cutout("asset-01", LEFT, role="primary"), *dots),
        events=(Event("E1", "MAIN", (0, 1)),),
        group_policy="SIMULTANEOUS_VISUAL_UNIT",
    )])
    planner, beats = _plan(built)
    assert planner.hidden_content_audit == []
    assert not {dot.key for dot in dots} & {
        asset_id.split(":", 1)[1] for asset_id in _visible(beats, built.scene_ids[0])
    }, "fragments must actually be hidden for this test to prove anything"
    assert built.runtime_id(0, "asset-01") in _visible(beats, built.scene_ids[0])


def test_proxy_on_another_units_cutout_is_not_proof_while_candidates_hide() -> None:
    """A locator-less leader borrowing a sibling's cutout cannot hide its own pixels."""
    from app.models import AssetActivation, SemanticEventProxy, StoryBeat
    from app.story.carriers import SemanticCarrierAuditor

    built = build_package([SceneSpec(
        phrase=PHRASE,
        units=(Unit("HOUSE", (0, 3), role="primary", locator=locator_for(LEFT)),
               Unit("FOOT", (0, 3))),
        cutouts=(Cutout("asset-01", LEFT, role="primary"),
                 *(Cutout(f"asset-0{i + 2}", (60 + 40 * i, 900, 30, 20)) for i in range(3))),
        events=(Event("E1", "HOUSE", (0, 3)), Event("E2", "FOOT", (0, 3), depends_on=("E1",))),
    )])
    sid = built.scene_ids[0]
    house, foot = built.semantic_id(0, "HOUSE"), built.semantic_id(0, "FOOT")
    carrier = built.runtime_id(0, "asset-01")
    beat = StoryBeat(
        id="beat-001", scene_id=sid, start=0.0, end=3.0, audio_start=0.0, audio_end=3.0,
        narration="alpha", primary_asset_ids=[carrier], action="INTRODUCE",
        asset_activations=[AssetActivation(
            asset_id=carrier, semantic_unit_id=house, semantic_event_id=f"{sid}_E1",
            policy="SEMANTIC", source="unified_final_package",
        )],
        semantic_event_proxies=[SemanticEventProxy(
            asset_id=carrier, semantic_unit_id=foot, semantic_event_id=f"{sid}_E2",
            trigger_text="alpha", trigger_char_start=0, trigger_char_end=5,
            spoken_start=0.3, spoken_end=0.6, reveal_start=0.3, semantic_peak=0.45,
            settle_at=0.6, authority="FINAL_PACKAGE_GROUP_PROXY",
        )],
        active_visual_semantic_state={carrier: house},
    )
    records = SemanticCarrierAuditor().audit(
        package=built.package, assets=built.assets, beats=[beat],
    )
    row = next(r for r in records if r["semantic_asset_id"] == foot)
    assert row["status"] == "UNRESOLVED"
    assert row["reason"] == "proxy_carrier_while_scene_hides_candidates"
    assert len(row["candidate_hidden_asset_ids"]) == 3