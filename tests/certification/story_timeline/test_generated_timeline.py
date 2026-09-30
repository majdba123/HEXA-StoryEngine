"""Generated boundary certification: canonical spans are half-open [start, end).

1012 deterministic cases through Story and Choreography (+ handoff gates):
  300 Arabic / 200 English / 200 mixed-language random layouts (separators, punctuation,
  contiguous or gapped spans, authored or default progression, silence between scenes)
  192 explicit contiguous-boundary cases (8 separators x 2 progression modes x 2
  punctuation x 3 languages, A.end == B.start)
  120 multi-event scenes (2-5 authored events, adjacent / separated / punctuation-ended)
plus scene-count (1-100) and token-count (10-5000) size matrices.

Oracle: a word belongs to a span iff ``word.char_end > start and word.char_start < end``;
it is computed here, independently of the planners.
"""

from __future__ import annotations

import pytest

from .builder import SEPARATORS, CaseSpec
from .cases import make_spec
from .run import check_timeline, run

ARABIC = [("ar", seed) for seed in range(300)]
ENGLISH = [("en", 1000 + seed) for seed in range(200)]
MIXED = [("mixed", 2000 + seed) for seed in range(200)]
MULTI_EVENT = [("ar" if s % 2 else "mixed", 3000 + s) for s in range(120)]
BOUNDARY = [
    (language, separator, authored, punctuation)
    for language in ("ar", "en", "mixed")
    for separator in SEPARATORS
    for authored in (True, False)
    for punctuation in (False, True)
]


def _assert_contract(spec: CaseSpec) -> None:
    outcome = run(spec)
    assert check_timeline(outcome) == []
    # Adjacent scenes never share a word: scene N's last owned word precedes N+1's first.
    built = outcome.built
    if spec.contiguous_scenes:
        for (_, end_a), (start_b, _) in zip(built.scene_spans, built.scene_spans[1:], strict=False):
            assert end_a == start_b  # the case really is boundary-adjacent


@pytest.mark.parametrize(("language", "seed"), ARABIC + ENGLISH + MIXED)
def test_random_layouts_keep_every_word_with_its_own_span(language: str, seed: int) -> None:
    _assert_contract(make_spec(seed, language))


@pytest.mark.parametrize(("language", "seed"), MULTI_EVENT)
def test_multi_event_scenes_never_leak_the_next_events_first_word(language: str, seed: int) -> None:
    spec = make_spec(seed, language, multi_event=True, authored=True)
    assert all(len(events) >= 2 for events in spec.scenes)
    _assert_contract(spec)


@pytest.mark.parametrize(("language", "separator", "authored", "punctuation"), BOUNDARY)
def test_adjacent_scenes_end_equals_start_for_every_separator(
    language: str, separator: str, authored: bool, punctuation: bool,
) -> None:
    layout = ((3, 2), (4,), (2, 2)) if authored else ((5,), (4,), (4,))
    for contiguous_events in (True, False):
        spec = CaseSpec(
            language=language, scenes=layout, separator=separator, event_separator=separator,
            punctuation=punctuation, contiguous_scenes=True, contiguous_events=contiguous_events,
            authored=authored, seed=len(separator) + int(punctuation),
        )
        outcome = run(spec)
        assert check_timeline(outcome) == []
        # Word B0 starts exactly at A.end: it is owned by B and outside A's window.
        (_, end_a), (start_b, _) = outcome.built.scene_spans[:2]
        assert end_a == start_b
        first_b = next(w for w in outcome.built.words if w.char_start >= start_b)
        beat_a = [b for b in outcome.story if b.scene_id == outcome.built.package.scenes[0].id][-1]
        assert beat_a.audio_end <= first_b.start + 1e-9


@pytest.mark.parametrize("scenes", [1, 2, 5, 20, 50, 100])
@pytest.mark.parametrize("language", ["ar", "en", "mixed"])
def test_scene_count_matrix(scenes: int, language: str) -> None:
    _assert_contract(make_spec(scenes * 13, language, scenes=scenes, events=1))


@pytest.mark.parametrize("tokens", [10, 100, 326, 1000, 5000])
@pytest.mark.parametrize("scenes", [1, 5])
def test_token_count_matrix(tokens: int, scenes: int) -> None:
    per_scene = max(1, tokens // scenes)
    spec = CaseSpec(
        language="ar", scenes=tuple(((per_scene,),) * scenes), separator="double_newline",
        contiguous_scenes=True, authored=False, seed=tokens + scenes,
    )
    outcome = run(spec)
    assert check_timeline(outcome) == []
    assert len(outcome.built.words) == per_scene * scenes
