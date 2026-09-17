from __future__ import annotations

from app.models import CompositionBeat, MotionCue, StoryBeat

from app.motion.compiler import MotionCompiler
from app.motion.primitives import MotionPrimitiveLibrary
from app.motion.timing import MotionTimingPolicy


class MotionPlanner:
    """Plan general-purpose object motion without owning layout.

    Composition owns semantic resting positions. Motion owns the path and pacing used
    to reach those positions. Every Motion V3 program is resolution-independent,
    narration-aware, deterministic, and guaranteed to settle back on its Composition
    target. This makes the same engine reusable across future Final Packages instead of
    encoding scene-specific movement rules.
    """

    def __init__(self) -> None:
        self.primitives = MotionPrimitiveLibrary()
        self.timing = MotionTimingPolicy()
        self.compiler = MotionCompiler()

    def plan(
        self,
        beats: list[StoryBeat],
        composition: list[CompositionBeat],
    ) -> list[MotionCue]:
        by_beat = {item.beat_id: item for item in composition}
        cues: list[MotionCue] = []

        for beat in beats:
            layout = by_beat.get(beat.id)
            if layout is None or not layout.items:
                continue

            visual_duration = max(0.08, beat.end - beat.start)
            count = len(layout.items)
            for index, item in enumerate(layout.items):
                program = self.primitives.build(
                    action=beat.action,
                    item=item,
                    index=index,
                    count=count,
                    visual_duration=visual_duration,
                )
                window = self.timing.window(
                    beat=beat,
                    distance=program.travel_distance,
                    index=index,
                    count=count,
                    primary=index == 0,
                )
                cues.append(
                    self.compiler.compile(
                        beat=beat,
                        asset_id=item.asset_id,
                        program=program,
                        window=window,
                        index=index,
                        count=count,
                    )
                )

        return cues
