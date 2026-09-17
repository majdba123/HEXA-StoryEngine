from __future__ import annotations

from dataclasses import dataclass

from app.models import StoryBeat


@dataclass(frozen=True, slots=True)
class MotionStyle:
    """Visual styling decision independent of semantic layout."""

    hook: bool
    attention_reset: bool
    variant: int
    intensity: float
    pace_tier: str


class MotionStyleDirector:
    """Deterministic retention-oriented style policy for the motion layer.

    The opening receives an explicit hook profile. During longer videos, periodic
    attention resets and meaningful pace changes prevent the same entrance rhythm
    from repeating for a minute straight. The policy is generic: it depends only on
    timeline position and narration pace, never on scene IDs or package topic.
    """

    HOOK_WINDOW_SECONDS = 5.2
    HOOK_MAX_BEATS = 4
    ATTENTION_RESET_SECONDS = 6.2
    PACE_SHIFT_RESET_FLOOR = 3.2

    _PACE_VARIANT_OFFSET = {
        "snap": 2,
        "brisk": 3,
        "balanced": 0,
        "deliberate": 1,
    }

    def decide(
        self,
        *,
        beat: StoryBeat,
        beat_index: int,
        pace_tier: str,
        previous_pace_tier: str | None,
        last_attention_reset: float,
    ) -> MotionStyle:
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        hook = beat_index < self.HOOK_MAX_BEATS and audio_start < self.HOOK_WINDOW_SECONDS

        elapsed = max(0.0, audio_start - last_attention_reset)
        pace_shift = previous_pace_tier is not None and pace_tier != previous_pace_tier
        attention_reset = not hook and (
            elapsed >= self.ATTENTION_RESET_SECONDS
            or (pace_shift and elapsed >= self.PACE_SHIFT_RESET_FLOOR)
        )

        variant = (beat_index + self._PACE_VARIANT_OFFSET.get(pace_tier, 0)) % 4
        if attention_reset:
            variant = (variant + 2) % 4

        if hook:
            intensity = 1.55
        elif attention_reset:
            intensity = 1.28
        elif pace_tier == "snap":
            intensity = 1.16
        else:
            intensity = 1.0

        return MotionStyle(
            hook=hook,
            attention_reset=attention_reset,
            variant=variant,
            intensity=intensity,
            pace_tier=pace_tier,
        )
