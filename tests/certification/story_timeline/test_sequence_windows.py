"""Choreography outer window is Story-owned visual time, never widened by spoken time.

StoryBeat.start/end   = Story-owned visual interval (may lead the spoken start)
StoryBeat.audio_*     = authoritative spoken interval (forced alignment)
ChoreographySequence  = visual unit: start >= first.start, end <= last.end.
"""

from __future__ import annotations

import random

import pytest

from app.choreography import ChoreographyDirector
from app.choreography.sequence import SequenceGrouper
from app.models import StoryBeat
from app.shared.errors import StageFailedError
from app.shared.handoff import LayerHandoffValidator
from app.story import StoryPlanner

from .builder import CaseSpec, build
from .cases import make_spec
from .run import EPS, run

DIVERGENCES = ("audio_end_past_visual_end", "visual_lead", "visual_ends_early", "both", "equal")


def _diverge(beats: list[StoryBeat], mode: str, rng: random.Random) -> list[StoryBeat]:
    """Re-time the VISUAL interval only; the spoken interval is left untouched."""
    out = []
    for index, beat in enumerate(beats):
        start, end = beat.start, beat.end
        if mode in {"visual_lead", "both"}:
            start = max(0.0, beat.audio_start - rng.uniform(0.2, 0.9))
            start = max(start, out[-1].end if out else 0.0) if index else start
        if mode in {"audio_end_past_visual_end", "visual_ends_early", "both"}:
            end = max(start + 0.2, beat.audio_end - rng.uniform(0.05, 0.6))
        out.append(beat.model_copy(update={"start": start, "end": max(end, start + 0.2)}))
    # keep the visual timeline gap-free and ordered like Story's own output
    for index in range(len(out) - 1):
        out[index] = out[index].model_copy(update={"end": max(out[index].start + 0.2, out[index + 1].start)})
    return out


@pytest.mark.parametrize("seed", range(120))
def test_sequence_window_stays_inside_story_when_audio_and_visual_diverge(seed: int) -> None:
    mode = DIVERGENCES[seed % len(DIVERGENCES)]
    rng = random.Random(seed)
    spec = make_spec(9000 + seed, ("ar", "en", "mixed")[seed % 3], authored=seed % 2 == 0, multi_event=True)
    outcome = run(spec)
    story = _diverge(outcome.story, mode, rng)
    if mode != "equal":
        assert any(b.audio_end > b.end + 1e-9 or b.start < b.audio_start - 1e-9 for b in story)
    plan = ChoreographyDirector().plan(outcome.built.package, story, outcome.built.assets)
    LayerHandoffValidator.require_choreography_for_composition(
        story=story, assets=outcome.built.assets, choreography=plan,
    )
    by_id = {b.id: b for b in story}
    for sequence in plan.sequences:
        first, last = by_id[sequence.beat_ids[0]], by_id[sequence.beat_ids[-1]]
        assert sequence.start >= first.start - EPS and sequence.end <= last.end + EPS
    # Spoken authority is untouched: every beat still carries its own audio interval.
    for before, after in zip(outcome.story, story, strict=True):
        assert (before.audio_start, before.audio_end) == (after.audio_start, after.audio_end)


def test_sequence_window_uses_visual_start_not_spoken_start() -> None:
    outcome = run(CaseSpec(language="ar", scenes=((3,), (3,), (3,)), separator="newline", seed=11))
    first = outcome.story[0]
    lead = first.audio_start - first.start
    assert lead > 0, "Story must lead the first beat visually for this contract test"
    sequence = outcome.plan.sequences[0]
    assert sequence.start == pytest.approx(first.start)  # visual start, not audio_start
    assert sequence.start < first.audio_start
    # The spoken anchor survives untouched for pacing/hook scheduling.
    assert first.audio_start == pytest.approx(outcome.built.words[0].start)


def test_sequence_end_is_story_end_even_when_speech_runs_past_the_visual_handoff() -> None:
    outcome = run(CaseSpec(language="ar", scenes=((3,), (3,)), separator="space", seed=5))
    story = list(outcome.story)
    story[0] = story[0].model_copy(update={"end": story[0].audio_end - 0.3})
    story[1] = story[1].model_copy(update={"start": story[0].end})
    plan = ChoreographyDirector().plan(outcome.built.package, story, outcome.built.assets)
    sequence = plan.sequences[0]
    assert sequence.end <= story[-1].end + EPS
    assert story[0].audio_end > story[0].end  # the divergence is real and preserved


def test_handoff_gate_stays_strict() -> None:
    """Producer fix only: a sequence reaching past Story is still rejected by the gate."""
    outcome = run(CaseSpec(language="en", scenes=((2,), (2,)), separator="space", seed=2))
    plan = outcome.plan
    widened = type(plan.sequences[0])(
        id=plan.sequences[0].id, beat_ids=plan.sequences[0].beat_ids,
        start=plan.sequences[0].start, end=outcome.story[-1].end + 0.5,
    )
    from app.choreography import ChoreographyPlan
    bad = ChoreographyPlan(sequences=(widened,), directives=plan.directives)
    with pytest.raises(StageFailedError) as info:
        LayerHandoffValidator.require_choreography_for_composition(
            story=outcome.story, assets=outcome.built.assets, choreography=bad,
        )
    assert "sequence_window_outside_story" in str(info.value.details)


# ------------------------------------------------------------------ grouping


def _beats(count: int, *, length: float = 1.0, gap: float = 0.0) -> list[StoryBeat]:
    beats, at = [], 0.0
    for index in range(count):
        beats.append(StoryBeat(
            id=f"b{index}", scene_id=f"s{index}", start=at, end=at + length + gap,
            audio_start=at + gap / 2, audio_end=at + gap / 2 + length * 0.9,
            narration="x", action="EXPLAIN",
        ))
        at += length + gap
    return beats


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 8, 9])
def test_grouped_sequences_bound_their_window_by_first_and_last_beat(count: int) -> None:
    beats = _beats(count)
    groups = SequenceGrouper().group(beats)
    assert [b.id for g in groups for b in g] == [b.id for b in beats]
    assert all(len(group) <= SequenceGrouper.MAX_BEATS for group in groups)
    for group in groups:
        assert group[0].start <= group[-1].end


def test_split_by_max_beats_seconds_and_hard_gap() -> None:
    assert len(SequenceGrouper().group(_beats(9))) >= 3  # MAX_BEATS
    assert len(SequenceGrouper().group(_beats(4, length=3.0))) >= 2  # MAX_SECONDS
    assert len(SequenceGrouper().group(_beats(4, length=0.5, gap=1.6))) == 3  # hard gap; a trailing singleton merges back


@pytest.mark.parametrize("scenes", [1, 2, 3, 4, 6, 9])
def test_real_planner_sequences_cover_each_beat_exactly_once(scenes: int) -> None:
    outcome = run(make_spec(400 + scenes, "ar", scenes=scenes, events=1, authored=False))
    covered = [beat_id for sequence in outcome.plan.sequences for beat_id in sequence.beat_ids]
    assert covered == [beat.id for beat in outcome.story]


def test_default_and_authored_progression_share_half_open_semantics() -> None:
    """Regression for the scene-level path (default event) and the authored path."""
    for authored in (False, True):
        built = build(CaseSpec(
            language="ar", scenes=((3, 3), (2, 2)) if authored else ((6,), (4,)),
            separator="double_newline", event_separator="newline",
            contiguous_scenes=True, contiguous_events=True, authored=authored, seed=31,
        ))
        story = StoryPlanner().plan(built.package, built.transcript, built.assets)
        scene_a_words = [w for w in built.words if w.char_start < built.scene_spans[0][1]]
        last_a = [b for b in story if b.scene_id == built.package.scenes[0].id][-1]
        assert last_a.audio_end == pytest.approx(scene_a_words[-1].end)
        assert all(b.audio_end <= built.words[len(scene_a_words)].start + 1e-9
                   for b in story if b.scene_id == built.package.scenes[0].id)
