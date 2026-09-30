"""Run a generated case through Story and Choreography and check the timeline contract."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.choreography import ChoreographyDirector, ChoreographyPlan
from app.models import StoryBeat
from app.shared.handoff import LayerHandoffValidator
from app.story import StoryPlanner

from .builder import Built, build, words_in

EPS = 1e-6
TOLERANCE = 0.06  # Story nudges a repeated spoken start by +0.05 s to keep order strict


@dataclass
class Outcome:
    built: Built
    story: list[StoryBeat]
    plan: ChoreographyPlan


def run(spec) -> Outcome:
    built = build(spec)
    story = StoryPlanner().plan(built.package, built.transcript, built.assets)
    LayerHandoffValidator.require_story_for_choreography(
        package=built.package, transcript=built.transcript, assets=built.assets, story=story,
    )
    plan = ChoreographyDirector().plan(built.package, story, built.assets)
    LayerHandoffValidator.require_choreography_for_composition(
        story=story, assets=built.assets, choreography=plan,
    )
    return Outcome(built, story, plan)


def expected_windows(built: Built) -> list[tuple[int, int, int]]:
    """(scene index, char_start, char_end) for every Story beat, in Story order."""
    rows = []
    for scene_index, scene in enumerate(built.package.scenes):
        if scene.visual_progression:
            for event in scene.visual_progression:
                rows.append((scene_index, event.trigger.global_char_start, event.trigger.global_char_end))
        else:
            rows.append((scene_index, scene.script_char_start, scene.script_char_end))
    return rows


def check_timeline(outcome: Outcome) -> list[str]:
    """Every violation of the boundary contract, as readable strings (empty = correct)."""
    built, story = outcome.built, outcome.story
    problems: list[str] = []
    windows = expected_windows(built)
    if len(windows) != len(story):
        return [f"beat count {len(story)} != expected {len(windows)}"]
    previous_start = -1.0
    for index, (beat, (scene_index, start, end)) in enumerate(zip(story, windows, strict=True)):
        label = f"{beat.id}@{start}:{end}"
        owned = words_in(built, start, end)
        if beat.scene_id != built.package.scenes[scene_index].id:
            problems.append(f"{label}: wrong scene {beat.scene_id}")
        if not owned:
            continue
        # The spoken interval is exactly the words the half-open span owns.
        if abs(beat.audio_start - owned[0].start) > TOLERANCE:
            problems.append(f"{label}: audio_start {beat.audio_start} != {owned[0].start}")
        expected_end = max(owned[-1].end, beat.audio_start + 0.12)
        if abs(beat.audio_end - expected_end) > EPS:
            problems.append(f"{label}: audio_end {beat.audio_end} != {expected_end}")
        foreign = [w for w in built.words if w.char_start >= end and w.start < beat.audio_end - EPS]
        foreign = [w for w in foreign if w.start < beat.audio_end - EPS and w.char_start >= end]
        # a later word (starting at/after the exclusive end) must never be inside the beat
        if any(w.start + EPS < beat.audio_end and w.char_start >= end for w in foreign):
            problems.append(f"{label}: later word leaked into audio window")
        if start is not None and end is not None and built.script[start:end].strip():
            if beat.narration != built.script[start:end].strip():
                problems.append(f"{label}: narration text differs from script[start:end]")
        for value in (beat.start, beat.end, beat.audio_start, beat.audio_end):
            if not isfinite(value) or value < 0:
                problems.append(f"{label}: non-finite/negative timestamp")
        if not beat.start < beat.end:
            problems.append(f"{label}: start >= end")
        if beat.audio_start > beat.audio_end:
            problems.append(f"{label}: audio_start > audio_end")
        if beat.start < previous_start - EPS:
            problems.append(f"{label}: visual start not monotonic")
        previous_start = beat.start
    by_id = {beat.id: beat for beat in story}
    for sequence in outcome.plan.sequences:
        first, last = by_id[sequence.beat_ids[0]], by_id[sequence.beat_ids[-1]]
        if sequence.start < first.start - EPS or sequence.end > last.end + EPS:
            problems.append(
                f"{sequence.id}: window {sequence.start}-{sequence.end} outside "
                f"story {first.start}-{last.end}"
            )
    return problems
