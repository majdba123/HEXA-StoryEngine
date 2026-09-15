from __future__ import annotations

from app.models import CompositionBeat, MotionCue, StoryBeat


class MotionPlanner:
    def plan(self, beats: list[StoryBeat], composition: list[CompositionBeat]) -> list[MotionCue]:
        by_beat = {item.beat_id: item for item in composition}
        cues: list[MotionCue] = []
        for beat in beats:
            layout = by_beat.get(beat.id)
            if not layout:
                continue
            duration = max(0.15, min(0.45, (beat.end - beat.start) * 0.22))
            for index, item in enumerate(layout.items):
                cue_start = min(beat.end - 0.05, beat.start + index * min(0.22, duration * 0.6))
                cue_end = min(beat.end, cue_start + duration)
                kind = "handoff_in" if beat.action == "HANDOFF" and index == 0 else "reveal_in"
                cues.append(MotionCue(
                    beat_id=beat.id,
                    asset_id=item.asset_id,
                    kind=kind,
                    start=cue_start,
                    end=max(cue_end, cue_start + 0.05),
                    params={"overshoot": 0.035 if index == 0 else 0.02},
                ))
        return cues
