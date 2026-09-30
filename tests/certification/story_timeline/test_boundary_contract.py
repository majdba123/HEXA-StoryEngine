"""Explicit half-open boundary contract, mutations and malformed inputs.

Canonical script spans are ``[start, end)`` everywhere: a word that begins at ``end``
belongs to the NEXT span and never to this one.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.canonical import CanonicalScene
from app.final_package.loader import FinalPackageLoader
from app.final_package.models import ScriptSpanPayload
from app.models import StoryTrigger, Transcript, TranscriptWord
from app.shared.errors import InvalidPackageError
from app.story import StoryPlanner
from app.story.activation import SemanticActivationPlanner
from app.story.semantic import StorySemanticContext  # noqa: F401  (contract import check)

from .builder import SEPARATORS, CaseSpec, build, words_in
from .cases import make_spec
from .run import check_timeline, run


def _transcript(script: str) -> Transcript:
    import re

    words = [
        TranscriptWord(text=m.group(), start=i * 0.5, end=i * 0.5 + 0.4,
                       char_start=m.start(), char_end=m.end())
        for i, m in enumerate(re.finditer(r"\S+", script))
    ]
    return Transcript(language="en", duration=len(words) * 0.5 + 0.5, segments=[], words=words)


# ------------------------------------------------ the exact bug: A.end == B.start


@pytest.mark.parametrize("separator", list(SEPARATORS.values()) + ["", " \n\n "])
def test_helper_never_gives_scene_a_the_first_word_of_scene_b(separator: str) -> None:
    """Old helper (+1) included the word starting at A.end in A's timing."""
    script = f"hello{separator}world"
    transcript = _transcript(script)
    a_end = len("hello") + len(separator)  # A = [0, a_end): contiguous with B
    b_start = a_end
    if separator:
        start, end, narration = StoryPlanner._timing_for_span(transcript, script, 0, b_start, None)
        assert (start, end) == (transcript.words[0].start, transcript.words[0].end)
        assert narration == script[0:b_start].strip()
        b = StoryPlanner._timing_for_span(transcript, script, b_start, len(script), None)
        assert (b[0], b[1]) == (transcript.words[1].start, transcript.words[1].end)
    else:
        # No whitespace at all: a single token straddles nothing and belongs to both spans
        # only when a span genuinely overlaps it (documented crossing-word contract).
        assert len(transcript.words) == 1


def test_adjacent_fixture_fails_with_the_legacy_inclusive_conversion() -> None:
    script = "alpha\nbeta"
    transcript = _transcript(script)
    legacy_end = 6 + 1  # A=[0,6) treated as inclusive by a +1 helper
    leaked = [w for w in transcript.words if w.char_end > 0 and w.char_start < legacy_end]
    assert [w.text for w in leaked] == ["alpha", "beta"]  # the defect being guarded
    correct = StoryPlanner._timing_for_span(transcript, script, 0, 6, None)
    assert correct[1] == transcript.words[0].end  # the fix: only "alpha"


@pytest.mark.parametrize(("separator", "a", "b"), [
    (" ", (0, 5), (6, 11)), ("\n", (0, 5), (6, 11)), ("\n\n", (0, 5), (7, 12)),
    ("\r\n", (0, 5), (7, 12)), ("\t", (0, 5), (6, 11)),
])
def test_hello_world_spans_with_gap_and_contiguous_variants(separator, a, b) -> None:
    script = f"hello{separator}world"
    transcript = _transcript(script)
    for a_end in (a[1], b[0]):  # A.end < B.start, then A.end == B.start
        ta = StoryPlanner._timing_for_span(transcript, script, a[0], a_end, None)
        tb = StoryPlanner._timing_for_span(transcript, script, b[0], b[1], None)
        assert (ta[0], ta[1]) == (transcript.words[0].start, transcript.words[0].end)
        assert (tb[0], tb[1]) == (transcript.words[1].start, transcript.words[1].end)


@pytest.mark.parametrize(("span", "expected"), [
    ((0, 5), ["w0"]),            # touches start exactly, ends exactly at the word end
    ((3, 5), ["w0"]),            # starts inside the word
    ((5, 6), []),                # the separator only
    ((6, 11), ["w1"]),           # starts exactly where the word starts
    ((0, 6), ["w0"]),            # end == next word start: excluded
    ((0, 7), ["w0", "w1"]),      # end one char into the next word: overlap, included
    ((11, 11), []),              # empty span
])
def test_word_overlap_rule_at_every_contact_point(span, expected) -> None:
    script = "abcde fghij"
    transcript = _transcript(script)
    words = [w for w in transcript.words if w.char_end > span[0] and w.char_start < span[1]]
    assert [f"w{transcript.words.index(w)}" for w in words] == expected
    got = StoryPlanner._timing_for_span(transcript, script, span[0], span[1], None)
    if expected:
        assert got[0] == transcript.words[int(expected[0][1])].start
        assert got[1] == transcript.words[int(expected[-1][1])].end


def test_empty_span_never_borrows_a_neighbouring_word() -> None:
    """start == end owns no word: Story falls back to the proportional position, never
    to an adjacent word's timestamps (documented legacy fallback, unchanged)."""
    script = "abcde fghij"
    transcript = _transcript(script)
    start, end, _ = StoryPlanner._timing_for_span(transcript, script, 5, 5, None)
    assert start == pytest.approx(transcript.duration * 5 / len(script))
    assert end >= start + 0.12
    assert not any(abs(start - w.start) < 1e-9 for w in transcript.words)


def test_last_scene_at_script_end_does_not_read_past_the_text() -> None:
    script = "one two\n"
    transcript = _transcript(script)
    got = StoryPlanner._timing_for_span(transcript, script, 0, len(script), None)
    assert got[1] == transcript.words[-1].end and got[2] == "one two"
    assert StoryPlanner._timing_for_span(transcript, script, 4, len(script) + 50, None)[1] >= got[0]


def test_leading_whitespace_and_scene_starting_after_it() -> None:
    script = "\n\n  one two"
    transcript = _transcript(script)
    a = StoryPlanner._timing_for_span(transcript, script, 0, 4, None)  # whitespace only
    assert a[2] == ""  # no fabricated narration
    b = StoryPlanner._timing_for_span(transcript, script, 4, len(script), None)
    assert b[0] == transcript.words[0].start


# ---------------------------------------- the other span readers share the contract


@pytest.mark.parametrize("separator", list(SEPARATORS.values()))
def test_trigger_readers_are_half_open(separator: str) -> None:
    script = f"alpha{separator}beta{separator}gamma"
    transcript = _transcript(script)
    second = script.index("beta")
    trigger = StoryTrigger(global_char_start=second, global_char_end=second + 4)
    scene = CanonicalScene(id="S", image_path="s.png", order=0,
                           script_char_start=0, script_char_end=len(script))
    rows = SemanticActivationPlanner._words_for_trigger(trigger, transcript.words, script, scene)
    assert [w.text for w in rows] == ["beta"]  # gamma starts after the end; alpha before
    adjacent = StoryTrigger(global_char_start=0, global_char_end=second)
    rows = SemanticActivationPlanner._words_for_trigger(adjacent, transcript.words, script, scene)
    assert [w.text for w in rows] == ["alpha"]  # beta starts exactly at end: excluded


@pytest.mark.parametrize("separator", list(SEPARATORS.values()))
def test_scene_phrase_fallback_window_excludes_the_next_scene(separator: str) -> None:
    script = f"same{separator}same"
    scene = CanonicalScene(id="S", image_path="s.png", order=0,
                           script_char_start=0, script_char_end=4 + len(separator))
    span = SemanticActivationPlanner._binding_phrase_span(script, scene, "same")
    assert span == (0, 4)  # the second "same" sits outside [0, end)


def test_authored_event_span_with_edge_whitespace_is_tightened_not_rejected() -> None:
    script = "\nfirst phrase\n\nsecond"
    authored = type("S", (), {"global_char_start": 0, "global_char_end": 14})()
    scene = CanonicalScene(id="S", image_path="s.png", order=0,
                           script_char_start=0, script_char_end=len(script))
    got = SemanticActivationPlanner._binding_authored_span(script, scene, "first phrase", authored)
    assert got == (1, 13) and script[got[0]:got[1]] == "first phrase"


# --------------------------------------------------- relation / event boundaries


def test_event_n_does_not_take_the_first_word_of_event_n_plus_1() -> None:
    for authored in (True,):
        outcome = run(CaseSpec(language="ar", scenes=((3, 3, 3),), separator="space",
                               event_separator="newline", contiguous_events=True,
                               authored=authored, seed=77))
        assert check_timeline(outcome) == []
        (events,) = outcome.built.event_spans
        for beat, (start, end) in zip(outcome.story, events, strict=True):
            owned = words_in(outcome.built, start, end)
            assert beat.audio_end == pytest.approx(owned[-1].end)
            following = [w for w in outcome.built.words if w.char_start >= end]
            assert all(w.start >= beat.audio_end - 1e-9 for w in following)


def test_relation_spoken_timing_uses_the_same_half_open_span() -> None:
    script = "alpha\nbeta gamma"
    transcript = _transcript(script)

    class Relation:
        trigger_char_start, trigger_char_end, trigger_text = 0, 6, "alpha\n"

        def model_copy(self, update):
            return update

    class Context:
        relations = [Relation()]

        def model_copy(self, update):
            return update

    out = StoryPlanner._resolve_relation_timing(
        Context(), transcript=transcript, script=script, beat_start=0.0, beat_end=3.0,
    )
    (resolved,) = out["relations"]
    assert resolved["spoken_end"] == pytest.approx(transcript.words[0].end)  # not "beta"


# --------------------------------------------------------------- mutations


MUTATIONS = {
    "scene_end_plus_1": dict(scene_end_delta=1),
    "scene_end_minus_1": dict(scene_end_delta=-1),
    "next_start_plus_1": dict(next_start_delta=1),
    "next_start_minus_1": dict(next_start_delta=-1),
    "add_newline": dict(separator="newline", event_separator="newline"),
    "remove_newline": dict(separator="space", event_separator="space"),
    "trailing_whitespace": dict(trailing="   \n"),
    "space_to_crlf": dict(separator="crlf", event_separator="crlf"),
    "split_event": "split", "merge_event": "merge",
    "remove_progression": dict(authored=False), "add_progression": dict(authored=True),
}


def _mutated(seed: int, name: str) -> CaseSpec:
    base = make_spec(5000 + seed, ("ar", "en", "mixed")[seed % 3], scenes=3, events=2, authored=True)
    change = MUTATIONS[name]
    if change == "split":
        last = base.scenes[-1][-1]
        scenes = (*base.scenes[:-1], (*base.scenes[-1][:-1], max(1, last - 1), 1))
        return dataclasses.replace(base, scenes=scenes)
    if change == "merge":
        scenes = tuple((sum(row),) for row in base.scenes)
        return dataclasses.replace(base, scenes=scenes)
    if change.get("authored") is False:
        return dataclasses.replace(base, scenes=tuple((sum(row),) for row in base.scenes), authored=False)
    return dataclasses.replace(base, **change)


@pytest.mark.parametrize("name", list(MUTATIONS))
@pytest.mark.parametrize("seed", range(12))
def test_single_mutation_yields_correct_timing_or_a_typed_rejection(name: str, seed: int) -> None:
    spec = _mutated(seed, name)
    try:
        outcome = run(spec)
    except Exception as exc:  # any rejection must be typed, never a crash
        assert getattr(exc, "effective_code", None), (name, seed, repr(exc))
        return
    assert check_timeline(outcome) == [], (name, seed)


# ------------------------------------------------------------ malformed input


@pytest.mark.parametrize(("start", "end", "text"), [
    (5, 3, None),            # reversed
    (-1, 3, None),           # negative start
    (0, 99, None),           # end beyond the script
    (3, None, "abc"),        # incomplete
    (None, 3, "abc"),        # incomplete
    (0, 3, "xyz"),           # text does not match [start, end)
    (0, 4, "abc"),           # end is exclusive: 4 chars do not equal "abc"
    (1, 3, "abc"),           # shifted window
    (0, 3, "abc "),          # trailing space not in the span
])
def test_loader_rejects_invalid_or_misaligned_spans(start, end, text) -> None:
    script = "abcdef"
    span = ScriptSpanPayload(text=text, global_char_start=start, global_char_end=end)
    with pytest.raises(InvalidPackageError):
        FinalPackageLoader._validate_span(script, span, "ctx")


@pytest.mark.parametrize(("start", "end"), [(0, 3), (2, 6), (0, 6), (3, 3)])
def test_loader_accepts_half_open_spans_including_the_script_end(start, end) -> None:
    script = "abcdef"
    span = ScriptSpanPayload(text=script[start:end], global_char_start=start, global_char_end=end)
    FinalPackageLoader._validate_span(script, span, "ctx", allow_empty=True)


def test_overlapping_scene_spans_are_permitted_by_the_loader_and_handled_per_scene() -> None:
    """Unified 2.0 validates each span on its own; no exclusivity is assumed, so a word in
    an overlap is owned by both scenes and planning stays independent of list order."""
    built = build(CaseSpec(language="en", scenes=((4,), (4,)), separator="space",
                           contiguous_scenes=True, authored=False, seed=9, scene_end_delta=6))
    first_end = built.scene_spans[0][1]
    assert first_end > built.scene_spans[1][0]  # genuine overlap
    story = StoryPlanner().plan(built.package, built.transcript, built.assets)
    reversed_package = built.package.model_copy(update={"scenes": tuple(reversed(built.package.scenes))})
    again = StoryPlanner().plan(reversed_package, built.transcript, built.assets)
    by_scene = {b.scene_id: (b.audio_start, b.audio_end) for b in story}
    assert by_scene == {b.scene_id: (b.audio_start, b.audio_end) for b in again}


def test_timing_does_not_depend_on_scene_list_order() -> None:
    built = build(make_spec(123, "ar", scenes=4, events=2, authored=True))
    plain = {b.id: (b.audio_start, b.audio_end)
             for b in StoryPlanner().plan(built.package, built.transcript, built.assets)}
    flipped = built.package.model_copy(update={"scenes": tuple(reversed(built.package.scenes))})
    mixed = StoryPlanner().plan(flipped, built.transcript, built.assets)
    assert {(b.scene_id, round(b.audio_start, 6), round(b.audio_end, 6)) for b in mixed} == {
        (b.scene_id, round(b.audio_start, 6), round(b.audio_end, 6))
        for b in StoryPlanner().plan(built.package, built.transcript, built.assets)
    }
    assert plain  # timings exist
