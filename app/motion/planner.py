from __future__ import annotations

import math

from app.models import CompositionBeat, MotionCue, StoryBeat


class MotionPlanner:
    """Narration-locked, readability-first entrance and handoff planner.

    The previous baseline compressed every object into the first half of a beat, which
    looked energetic but rushed. This planner protects a readable hold after the last
    strong entrance. If a spoken phrase is too short for every object to receive a full
    motion, extra objects arrive as quiet context instead of forcing faster animation.
    """

    MIN_STRONG_DURATION = 0.38
    MAX_STRONG_DURATION = 0.68
    MIN_STRONG_STEP = 0.28
    MAX_STRONG_STEP = 0.46

    def plan(self, beats: list[StoryBeat], composition: list[CompositionBeat]) -> list[MotionCue]:
        by_beat = {item.beat_id: item for item in composition}
        cues: list[MotionCue] = []
        previous_end = 0.0
        for beat in beats:
            layout = by_beat.get(beat.id)
            if not layout or not layout.items:
                previous_end = max(previous_end, beat.end)
                continue

            beat_duration = max(0.12, beat.end - beat.start)
            anticipation = min(0.08, max(0.0, beat.start - previous_end) * 0.35)
            first_start = max(previous_end, beat.start - anticipation)

            strong_duration = self._strong_duration(beat_duration)
            readable_hold = self._readable_hold(beat_duration)
            motion_budget = max(strong_duration, beat.end - first_start - readable_hold)
            strong_count = self._strong_count(
                item_count=len(layout.items),
                motion_budget=motion_budget,
                strong_duration=strong_duration,
            )
            step = self._strong_step(
                strong_count=strong_count,
                motion_budget=motion_budget,
                strong_duration=strong_duration,
            )

            for index, item in enumerate(layout.items):
                if index < strong_count:
                    cue_start = first_start + index * step
                    latest_start = max(first_start, beat.end - readable_hold - strong_duration)
                    cue_start = min(cue_start, latest_start)
                    cue_end = min(beat.end - readable_hold, cue_start + strong_duration)
                    cue_end = max(cue_end, cue_start + min(0.24, strong_duration))
                    if index == 0 and beat.action == "HANDOFF":
                        kind = "handoff_in"
                    elif index == 0 and beat.action in {"EMPHASIZE", "RESULT"}:
                        kind = "emphasis_in"
                    else:
                        kind = "reveal_in"
                    overshoot = 0.028 if index == 0 else 0.014
                else:
                    # Context objects are still independent layers, but short narration
                    # must not force six rapid translations. A slow opacity arrival keeps
                    # the authored scene readable while reserving attention for the main
                    # storytelling motion.
                    quiet_offset = min(0.18, 0.055 * (index - strong_count))
                    cue_start = max(beat.start, first_start + quiet_offset)
                    context_duration = min(0.48, max(0.30, beat_duration * 0.28))
                    cue_end = min(beat.end - min(0.14, readable_hold * 0.5), cue_start + context_duration)
                    cue_end = max(cue_end, cue_start + 0.18)
                    kind = "context_in"
                    overshoot = 0.0

                cues.append(MotionCue(
                    beat_id=beat.id,
                    asset_id=item.asset_id,
                    kind=kind,
                    start=cue_start,
                    end=cue_end,
                    params={
                        "overshoot": overshoot,
                        "sequence_index": index,
                        "sequence_count": len(layout.items),
                        "strong_sequence_count": strong_count,
                        "protected_hold": readable_hold,
                    },
                ))
            previous_end = max(previous_end, beat.end)
        return cues

    @classmethod
    def _strong_duration(cls, beat_duration: float) -> float:
        if beat_duration < 0.75:
            return max(0.24, beat_duration * 0.48)
        return min(cls.MAX_STRONG_DURATION, max(cls.MIN_STRONG_DURATION, beat_duration * 0.24))

    @staticmethod
    def _readable_hold(beat_duration: float) -> float:
        if beat_duration < 0.75:
            return max(0.10, beat_duration * 0.18)
        return min(0.82, max(0.34, beat_duration * 0.30))

    @classmethod
    def _strong_count(cls, *, item_count: int, motion_budget: float, strong_duration: float) -> int:
        if item_count <= 1:
            return item_count
        usable = max(0.0, motion_budget - strong_duration)
        slots = 1 + int(math.floor(usable / cls.MIN_STRONG_STEP))
        return max(1, min(item_count, slots, 5))

    @classmethod
    def _strong_step(cls, *, strong_count: int, motion_budget: float, strong_duration: float) -> float:
        if strong_count <= 1:
            return 0.0
        available = max(0.0, motion_budget - strong_duration)
        ideal = available / max(1, strong_count - 1)
        return min(cls.MAX_STRONG_STEP, max(cls.MIN_STRONG_STEP, ideal))
