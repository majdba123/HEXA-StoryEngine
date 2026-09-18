from __future__ import annotations

from app.models import MotionCue
from app.reference import HexaVisualProfile


class ReferenceMotionEnforcer:
    """Keep short beats readable by removing directional travel that cannot meet the reference minimum."""

    def __init__(self, profile: HexaVisualProfile | None = None, *, fps: int = 30) -> None:
        self.profile = profile or HexaVisualProfile.production()
        self.fps = fps

    def enforce(self, cues: list[MotionCue]) -> list[MotionCue]:
        minimum = self.profile.minimum_directional_frames / self.fps
        output: list[MotionCue] = []
        for cue in cues:
            if cue.end - cue.start + 1e-9 >= minimum:
                output.append(cue)
                continue
            params = dict(cue.params)
            program = dict(params.get("program") or {})
            frames = [dict(frame) for frame in program.get("keyframes") or []]
            directional = any(abs(float(f.get("dx", 0))) > 1e-5 or abs(float(f.get("dy", 0))) > 1e-5 for f in frames)
            if not directional:
                output.append(cue)
                continue
            for frame in frames:
                frame["dx"] = 0.0
                frame["dy"] = 0.0
            program["keyframes"] = frames
            program["name"] = f"reference_safe_{program.get('name') or 'hold'}"
            params["program"] = program
            params["reference_motion_adjusted"] = True
            output.append(cue.model_copy(update={"params": params}))
        return output
