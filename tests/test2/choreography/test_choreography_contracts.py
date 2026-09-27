from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical import CanonicalPackage, CanonicalScene, CanonicalSemanticEvent
from app.choreography import (
    ChoreographyDirective,
    ChoreographyPlan,
    ChoreographySequence,
    HookKind,
    SequencePhase,
    VisualGrammarStage,
)
from app.choreography.director import ChoreographyDirector
from app.models import StoryBeat, StoryRelation, StorySemanticContext
from app.shared.errors import StageFailedError


def _package(*event_ids: str) -> CanonicalPackage:
    scene = CanonicalScene(
        id="SCENE_001",
        image_path=Path("scene.png"),
        order=0,
        semantic_events=tuple(
            CanonicalSemanticEvent(
                semantic_event_id=event_id,
                scene_id="SCENE_001",
                sequence_order=index,
            )
            for index, event_id in enumerate(event_ids, start=1)
        ),
    )
    return CanonicalPackage(root=Path("."), package_id="test2-choreo", scenes=(scene,))


def _beat(*, relation: bool = False) -> StoryBeat:
    context = StorySemanticContext(
        relations=(
            [
                StoryRelation(
                    source_unit_id="A",
                    target_unit_id="B",
                    kind="ENABLES",
                    authority="FINAL_PACKAGE_ASSET_RELATION",
                )
            ]
            if relation else []
        )
    )
    return StoryBeat(
        id="beat-001",
        scene_id="SCENE_001",
        start=0.0,
        end=1.0,
        narration="alpha",
        primary_asset_ids=["a"],
        support_asset_ids=["b"],
        action="INTRODUCE",
        semantic_context=context,
    )


def _sequence(stages: tuple[VisualGrammarStage, ...]) -> ChoreographySequence:
    return ChoreographySequence(
        id="sequence-001",
        beat_ids=("beat-001",),
        start=0.0,
        end=1.0,
        hook=HookKind.OPEN,
        grammar_stages=stages,
    )


def test_choreography_contract_rejects_missing_semantic_event_flow() -> None:
    package = _package("E1")
    beat = _beat()
    plan = ChoreographyPlan(
        sequences=(_sequence((
            VisualGrammarStage.ENTER,
            VisualGrammarStage.READ,
            VisualGrammarStage.RELEASE,
        )),),
        directives=(ChoreographyDirective(
            beat_id=beat.id,
            sequence_id="sequence-001",
            phase=SequencePhase.SETUP,
            action="INTRODUCE",
            hook=HookKind.OPEN,
            primary_asset_id="a",
            event_flows=(),
        ),),
    )

    with pytest.raises(StageFailedError) as exc:
        ChoreographyDirector._require_quality_contract(
            package=package,
            beats=[beat],
            plan=plan,
        )

    assert exc.value.effective_code == "FINAL_PACKAGE_SEMANTIC_EVENT_COVERAGE"


def test_choreography_contract_rejects_missing_authored_relation() -> None:
    package = _package()
    beat = _beat(relation=True)
    plan = ChoreographyPlan(
        sequences=(_sequence((
            VisualGrammarStage.ENTER,
            VisualGrammarStage.READ,
            VisualGrammarStage.RELEASE,
        )),),
        directives=(ChoreographyDirective(
            beat_id=beat.id,
            sequence_id="sequence-001",
            phase=SequencePhase.SETUP,
            action="INTRODUCE",
            hook=HookKind.OPEN,
            primary_asset_id="a",
            interactions=(),
        ),),
    )

    with pytest.raises(StageFailedError) as exc:
        ChoreographyDirector._require_quality_contract(
            package=package,
            beats=[beat],
            plan=plan,
        )

    assert exc.value.effective_code == "FINAL_PACKAGE_RELATIONSHIP_COVERAGE"


def test_choreography_contract_rejects_incomplete_visual_grammar() -> None:
    package = _package()
    beat = _beat()
    plan = ChoreographyPlan(
        sequences=(_sequence((VisualGrammarStage.READ,)),),
        directives=(ChoreographyDirective(
            beat_id=beat.id,
            sequence_id="sequence-001",
            phase=SequencePhase.SETUP,
            action="INTRODUCE",
            hook=HookKind.OPEN,
            primary_asset_id="a",
        ),),
    )

    with pytest.raises(StageFailedError) as exc:
        ChoreographyDirector._require_quality_contract(
            package=package,
            beats=[beat],
            plan=plan,
        )

    assert exc.value.effective_code == "REFERENCE_VISUAL_GRAMMAR"
