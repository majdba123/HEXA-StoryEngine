from __future__ import annotations

from app.models import MotionCue, StoryBeat

from app.motion.models import MotionProgram
from app.motion.timing import MotionWindow


class MotionCompiler:
    """Compile backend-neutral programs into the stable public MotionCue contract."""

    ENGINE_VERSION = 3

    def compile(
        self,
        *,
        beat: StoryBeat,
        asset_id: str,
        program: MotionProgram,
        window: MotionWindow,
        index: int,
        count: int,
    ) -> MotionCue:
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        return MotionCue(
            beat_id=beat.id,
            asset_id=asset_id,
            kind="program_v3",
            start=window.start,
            end=window.end,
            params={
                "engine_version": self.ENGINE_VERSION,
                "semantic_action": beat.action,
                "audio_anchor": audio_start,
                "spoken_duration": max(0.0, audio_end - audio_start),
                "sequence_index": index,
                "sequence_count": count,
                "program": program.to_payload(),
            },
        )
