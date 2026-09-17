from __future__ import annotations

from dataclasses import dataclass

from app.models import StoryBeat


@dataclass(frozen=True, slots=True)
class MotionWindow:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class MotionTimingPolicy:
    """Narration-aware, distance-aware timing for visual object motion.

    Primary artwork must already be settled when its narrated idea arrives. Richness
    therefore comes from the trajectory inside the authored visual lead-in, never by
    allowing the primary object to chase narration after the semantic anchor. Support
    objects may stagger through the spoken window when readability permits it.
    """

    _MIN_DURATION = 0.12
    _MIN_EXECUTABLE_DURATION = 0.05
    _PRIMARY_SETTLE_GRACE = 0.04
    _MAX_PRIMARY_DURATION = 0.72
    _MAX_SUPPORT_DURATION = 0.52

    def window(
        self,
        *,
        beat: StoryBeat,
        distance: float,
        index: int,
        count: int,
        primary: bool,
    ) -> MotionWindow:
        visual_duration = max(0.08, beat.end - beat.start)
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        spoken_duration = max(0.12, audio_end - audio_start)
        words = max(1, len(beat.narration.split()))
        words_per_second = words / spoken_duration

        pace_factor = self._clamp(2.8 / max(1.4, words_per_second), 0.72, 1.14)
        distance_factor = self._clamp(0.85 + distance * 4.4, 0.82, 1.28)
        semantic_factor = {
            "RESULT": 0.88,
            "EMPHASIZE": 0.92,
            "COMPARE": 1.02,
            "HANDOFF": 1.08,
            "INTRODUCE": 1.04,
            "REVEAL_DETAIL": 0.96,
        }.get(beat.action, 1.0)

        base = 0.38 if primary else 0.30
        cap = self._MAX_PRIMARY_DURATION if primary else self._MAX_SUPPORT_DURATION
        preferred_duration = self._clamp(
            base * pace_factor * distance_factor * semantic_factor,
            self._MIN_DURATION,
            min(cap, max(self._MIN_DURATION, visual_duration - 0.04)),
        )

        if primary:
            return self._primary_window(
                beat=beat,
                audio_start=audio_start,
                pace_factor=pace_factor,
                preferred_duration=preferred_duration,
            )
        return self._support_window(
            beat=beat,
            audio_start=audio_start,
            spoken_duration=spoken_duration,
            preferred_duration=preferred_duration,
            index=index,
            count=count,
        )

    def _primary_window(
        self,
        *,
        beat: StoryBeat,
        audio_start: float,
        pace_factor: float,
        preferred_duration: float,
    ) -> MotionWindow:
        start = beat.start
        settle_deadline = min(beat.end, audio_start + self._PRIMARY_SETTLE_GRACE)
        lead_budget = max(0.0, settle_deadline - start)

        if lead_budget <= self._MIN_EXECUTABLE_DURATION:
            end = min(beat.end, start + max(0.0, lead_budget))
            if end <= start:
                end = min(beat.end, start + self._MIN_EXECUTABLE_DURATION)
            return MotionWindow(start=start, end=end)

        # Faster narration compresses the gesture *inside* the lead-in instead of
        # moving the semantic settle point later. Slow speech can use the full budget.
        pace_budget = lead_budget * min(1.0, pace_factor)
        duration = min(preferred_duration, max(self._MIN_EXECUTABLE_DURATION, pace_budget))
        end = min(settle_deadline, start + duration)
        end = max(start + self._MIN_EXECUTABLE_DURATION, end)
        end = min(settle_deadline, end)
        return MotionWindow(start=start, end=end)

    def _support_window(
        self,
        *,
        beat: StoryBeat,
        audio_start: float,
        spoken_duration: float,
        preferred_duration: float,
        index: int,
        count: int,
    ) -> MotionWindow:
        duration = preferred_duration
        support_count = max(1, count - 1)
        support_index = max(0, index - 1)
        readable_span = max(0.0, min(spoken_duration * 0.58, beat.end - audio_start - 0.06))
        stagger = readable_span / support_count
        start = max(beat.start, audio_start + 0.04 + support_index * stagger)
        latest_start = max(beat.start, beat.end - duration - 0.04)
        start = min(start, latest_start)
        end = min(beat.end - 0.03, start + duration)

        minimum = min(self._MIN_DURATION, max(0.0, beat.end - start))
        end = max(start + minimum, end)
        end = min(beat.end, end)
        if end <= start:
            end = min(beat.end, start + self._MIN_EXECUTABLE_DURATION)
        return MotionWindow(start=start, end=end)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        if high < low:
            return low
        return max(low, min(high, value))
