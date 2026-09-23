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
        hook: bool,
        handoff: bool,
        attention_reset: bool,
        variant: int,
        intensity: float,
        choreography: dict | None = None,
        semantic_focus: dict | None = None,
        motion_order: dict | None = None,
        render_constraints: dict | None = None,
    ) -> MotionCue:
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        params = {
            "engine_version": self.ENGINE_VERSION,
            "semantic_action": (choreography or {}).get("action") or beat.action,
            "semantic_settle_time": window.semantic_settle,
            "audio_anchor": audio_start,
            "spoken_duration": max(0.0, audio_end - audio_start),
            "pace_tier": window.pace_tier,
            "hook": hook,
            "handoff": handoff,
            "attention_reset": attention_reset,
            "variant": variant,
            "intensity": intensity,
            "sequence_index": index,
            "sequence_count": count,
            "choreography": choreography or {},
            "program": program.to_payload(),
        }
        if semantic_focus:
            params["semantic_focus"] = semantic_focus
        if motion_order:
            params["motion_order"] = {
                **motion_order,
                "stagger_applied": window.sequence_staggered,
            }
        if render_constraints:
            params["render_constraints"] = render_constraints
        if window.story_v2:
            # The renderer maps normalized progress through max(0.05, duration).
            # Retiming the existing entry (not its easing/transforms) is necessary:
            # otherwise its original 78% settle frame arrives before Story's time.
            payload = params["program"]
            settle_progress = (window.semantic_settle - window.start) / max(0.05, window.duration)
            frames = []
            for frame in payload["keyframes"]:
                if frame["progress"] <= program.settle_progress:
                    frames.append({**frame, "progress": (
                        frame["progress"] / program.settle_progress * settle_progress
                    )})
            if settle_progress < 1.0:
                frames.append({**payload["keyframes"][-1], "progress": 1.0})
            payload["keyframes"] = frames
            payload["settle_progress"] = settle_progress
        return MotionCue(
            beat_id=beat.id,
            asset_id=asset_id,
            kind="program_v3",
            start=window.start,
            end=window.end,
            params=params,
        )
