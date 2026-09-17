from pathlib import Path

from app.choreography import ChoreographyDirector, HookKind, SequencePhase
from app.models import PackageModel, SceneSource, StoryBeat, VisualAsset


def _scene(scene_id: str, semantic_name: str, concept: str = "") -> SceneSource:
    return SceneSource(
        id=scene_id,
        image_path=Path(f"/{scene_id}.png"),
        order=int(scene_id.split("-")[-1]),
        visual_concept=concept,
        relation_to_previous="CONTINUES_CANONICAL_EXPLANATION",
        units=[
            {
                "unit_id": "UNIT_001",
                "semantic_name": semantic_name,
                "narrative_function": f"EXPLAIN_{semantic_name.upper()}",
                "semantic_intent": "EXPLAIN",
            }
        ],
    )


def _beat(index: int, narration: str) -> StoryBeat:
    start = (index - 1) * 2.4
    return StoryBeat(
        id=f"beat-{index:03d}",
        scene_id=f"scene-{index}",
        start=start,
        end=start + 2.4,
        audio_start=start + 0.2,
        audio_end=start + 2.1,
        narration=narration,
        primary_asset_ids=[f"asset-{index}"],
        support_asset_ids=[f"support-{index}"],
        action="REVEAL_DETAIL",
    )


def test_choreography_groups_story_and_schedules_multiple_hooks_without_scene_ids() -> None:
    semantics = [
        "wallet_model",
        "total_balance",
        "reserved_funds",
        "online_spending_cap",
        "payment_request",
        "subsequent_decline",
        "website_decline",
        "payment_route",
        "privacy_shield",
        "ten_retries",
        "actual_available_amount",
        "load_exceeds_gate_limit",
    ]
    scenes = [_scene(f"scene-{i}", semantic) for i, semantic in enumerate(semantics, start=1)]
    package = PackageModel(root=Path("/tmp"), package_id="p", scenes=scenes, script="x")
    beats = [_beat(i, semantic.replace("_", " ")) for i, semantic in enumerate(semantics, start=1)]

    plan = ChoreographyDirector().plan(package, beats, [])

    assert len(plan.directives) == len(beats)
    assert plan.directives[0].hook == HookKind.OPEN
    assert len(plan.hook_beats()) >= 3
    assert all(2 <= len(sequence.beat_ids) <= 4 for sequence in plan.sequences)
    assert any(row.action == "REJECT" for row in plan.directives)
    assert any(row.action == "BLOCK" for row in plan.directives)
    assert any(row.action == "LOOP" for row in plan.directives)
    assert any(row.phase == SequencePhase.CONSEQUENCE for row in plan.directives)


def test_choreography_uses_semantic_metadata_instead_of_specific_scene_number() -> None:
    package = PackageModel(
        root=Path("/tmp"),
        package_id="p",
        scenes=[_scene("scene-77", "subsequent_decline")],
        script="x",
    )
    beat = StoryBeat(
        id="arbitrary-beat",
        scene_id="scene-77",
        start=0.0,
        end=2.0,
        audio_start=0.1,
        audio_end=1.8,
        narration="neutral narration",
        primary_asset_ids=["a"],
        support_asset_ids=["b"],
        action="REVEAL_DETAIL",
    )
    plan = ChoreographyDirector().plan(package, [beat], [])
    assert plan.directives[0].action == "REJECT"
    assert plan.directives[0].tension >= 0.9


def test_hook_mechanisms_vary_across_long_story() -> None:
    semantics = [
        "wallet_model", "reserved_funds", "online_spending_cap", "payment_request",
        "subsequent_decline", "ten_retries", "physical_store_compare", "privacy_shield",
        "actual_available_amount", "load_exceeds_gate_limit", "subsequent_decline", "solution_raise_limit",
    ]
    scenes = [_scene(f"scene-{i}", semantic) for i, semantic in enumerate(semantics, start=1)]
    package = PackageModel(root=Path("/tmp"), package_id="p", scenes=scenes, script="x")
    beats = [_beat(i, semantic.replace("_", " ")) for i, semantic in enumerate(semantics, start=1)]

    plan = ChoreographyDirector().plan(package, beats, [])
    hooked = [sequence for sequence in plan.sequences if sequence.hook != HookKind.NONE]

    assert len(hooked) >= 3
    mechanisms = [sequence.hook_mechanism.value for sequence in hooked]
    assert len(set(mechanisms)) >= 2
    assert mechanisms[0] in {"CURIOSITY", "CONTRADICTION"}


def test_choreography_marks_cross_asset_focus_as_semantic_handoff() -> None:
    from app.choreography import ContinuityMode

    package = PackageModel(
        root=Path("/tmp"), package_id="p",
        scenes=[_scene("scene-1", "wallet_model"), _scene("scene-2", "payment_request")],
        script="x",
    )
    first = _beat(1, "wallet")
    second = _beat(2, "request")
    plan = ChoreographyDirector().plan(package, [first, second], [])

    assert plan.directives[1].continuity_from == first.primary_asset_ids[0]
    assert plan.directives[1].continuity_mode == ContinuityMode.SEMANTIC_HANDOFF


def test_choreography_binds_concept_cutout_instead_of_tall_character() -> None:
    scene = SceneSource(
        id="scene-1",
        image_path=Path("/scene.png"),
        order=1,
        units=[
            {
                "unit_id": "UNIT_001",
                "semantic_name": "wallet_model",
                "type": "GROUP",
                "role": "PRIMARY",
            },
            {
                "unit_id": "UNIT_002",
                "semantic_name": "adult_secondary_customer",
                "type": "SECONDARY_CHARACTER",
                "role": "SUPPORTING",
            },
        ],
    )
    package = PackageModel(root=Path("/tmp"), package_id="p", scenes=[scene], script="x")
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-1",
        start=0.0,
        end=2.0,
        audio_start=0.2,
        audio_end=1.8,
        narration="wallet",
        primary_asset_ids=["character"],
        support_asset_ids=["wallet"],
        action="REVEAL_DETAIL",
    )
    assets = [
        VisualAsset(
            id="character", scene_id="scene-1", role="primary_visual",
            image_path=Path("/character.png"), extraction_method="test",
            source_bbox=(20, 20, 280, 760), source_canvas_width=1000, source_canvas_height=1000,
            source_area_ratio=0.21,
        ),
        VisualAsset(
            id="wallet", scene_id="scene-1", role="support_visual_1",
            image_path=Path("/wallet.png"), extraction_method="test",
            source_bbox=(420, 250, 460, 360), source_canvas_width=1000, source_canvas_height=1000,
            source_area_ratio=0.17,
        ),
    ]

    directive = ChoreographyDirector().plan(package, [beat], assets).directives[0]

    assert directive.primary_asset_id == "wallet"
    assert directive.actor_asset_ids == ("character",)
    assert directive.interaction_asset_id == "character"


def test_story_primary_keeps_narration_locked_timing_when_choreography_focus_is_support() -> None:
    """Semantic focus may change without letting authored primary artwork arrive late."""
    from app.choreography import ChoreographyDirective, ChoreographyPlan, HookKind, SequencePhase
    from app.models import CompositionBeat, LayoutItem
    from app.motion import MotionPlanner

    beat = StoryBeat(
        id="beat-001",
        scene_id="SCENE_GENERIC",
        start=0.0,
        end=1.8,
        audio_start=0.30,
        audio_end=1.50,
        narration="payment rejected",
        primary_asset_ids=["authored-primary"],
        support_asset_ids=["semantic-focus"],
        action="REVEAL_DETAIL",
    )
    plan = ChoreographyPlan(directives=(ChoreographyDirective(
        beat_id=beat.id,
        sequence_id="sequence-001",
        phase=SequencePhase.ACTION,
        action="REJECT",
        hook=HookKind.OPEN,
        primary_asset_id="semantic-focus",
        support_asset_ids=("authored-primary",),
        energy=0.9,
        tension=0.9,
    ),))
    composition = [CompositionBeat(beat_id=beat.id, items=[
        LayoutItem(asset_id="authored-primary", x=0.30, y=0.5, width=0.38, height=0.50),
        LayoutItem(asset_id="semantic-focus", x=0.70, y=0.5, width=0.26, height=0.28),
    ])]

    cues = MotionPlanner().plan([beat], composition, plan)
    by_asset = {cue.asset_id: cue for cue in cues}
    authored = by_asset["authored-primary"]
    semantic = by_asset["semantic-focus"]

    assert authored.params["semantic_settle_time"] <= beat.audio_start + 0.12
    assert semantic.params["semantic_settle_time"] <= beat.audio_start + 0.12
    assert semantic.params["program"]["name"] != authored.params["program"]["name"]
