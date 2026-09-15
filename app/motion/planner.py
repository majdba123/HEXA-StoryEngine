from __future__ import annotations

from app.models import CompositionBeat, MotionCue, StoryBeat


class MotionPlanner:
    """Narration-locked entrance and handoff planner.

    Objects enter in a controlled sequence inside the spoken beat. The first visual may
    anticipate narration very slightly so its visual peak lands on the phrase; support
    objects are staggered rather than dumped simultaneously.
    """

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
            entrance_duration = min(0.38, max(0.14, beat_duration * 0.18))
            anticipation = min(0.10, max(0.0, beat.start - previous_end) * 0.4)
            first_start = max(previous_end, beat.start - anticipation)

            # Reserve the first ~55% of a spoken beat for sequential entrances and
            # leave the rest readable. This scales automatically with short/long beats.
            entrance_window = max(0.0, beat_duration * 0.55 - entrance_duration)
            step = entrance_window / max(1, len(layout.items) - 1) if len(layout.items) > 1 else 0.0
            step = min(0.34, max(0.10 if len(layout.items) > 1 else 0.0, step))

            for index, item in enumerate(layout.items):
                cue_start = first_start + index * step
                latest_start = max(first_start, beat.end - entrance_duration - 0.06)
                cue_start = min(cue_start, latest_start)
                cue_end = min(beat.end - 0.02, cue_start + entrance_duration)
                cue_end = max(cue_end, cue_start + 0.06)

                if index == 0 and beat.action == "HANDOFF":
                    kind = "handoff_in"
                elif index == 0 and beat.action in {"EMPHASIZE", "RESULT"}:
                    kind = "emphasis_in"
                else:
                    kind = "reveal_in"
                cues.append(MotionCue(
                    beat_id=beat.id,
                    asset_id=item.asset_id,
                    kind=kind,
                    start=cue_start,
                    end=cue_end,
                    params={
                        "overshoot": 0.04 if index == 0 else 0.022,
                        "sequence_index": index,
                        "sequence_count": len(layout.items),
                    },
                ))
            previous_end = max(previous_end, beat.end)
        return cues
