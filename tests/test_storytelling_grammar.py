from app.choreography import ChoreographySequence, HookKind, VisualGrammarStage
from app.diagnostics.storytelling import StorytellingValidator


def _sequence(*stages: VisualGrammarStage, beat_count: int) -> ChoreographySequence:
    return ChoreographySequence(
        id="sequence-test",
        beat_ids=tuple(f"beat-{index}" for index in range(beat_count)),
        start=0.0,
        end=1.0,
        hook=HookKind.NONE,
        grammar_stages=stages,
    )


def test_single_beat_sequence_is_complete_without_fabricated_add_stage() -> None:
    sequence = _sequence(
        VisualGrammarStage.ENTER,
        VisualGrammarStage.READ,
        VisualGrammarStage.RELEASE,
        beat_count=1,
    )

    assert StorytellingValidator._grammar_sequence_is_compliant(sequence)


def test_multi_beat_sequence_still_requires_meaning_progression() -> None:
    incomplete = _sequence(
        VisualGrammarStage.ENTER,
        VisualGrammarStage.READ,
        VisualGrammarStage.RELEASE,
        beat_count=2,
    )
    complete = _sequence(
        VisualGrammarStage.ENTER,
        VisualGrammarStage.READ,
        VisualGrammarStage.ADD,
        VisualGrammarStage.RELEASE,
        beat_count=2,
    )

    assert not StorytellingValidator._grammar_sequence_is_compliant(incomplete)
    assert StorytellingValidator._grammar_sequence_is_compliant(complete)
