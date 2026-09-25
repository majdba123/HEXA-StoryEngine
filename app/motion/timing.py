from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from app.models import AssetActivation, StoryBeat

GOLDEN_MAJOR = 0.6180339887498949
GOLDEN_MINOR = 1.0 - GOLDEN_MAJOR


@dataclass(frozen=True, slots=True)
class MotionComfortProfile:
    target_seconds: float
    minimum_seconds: float
    max_normalized_speed: float


_MOTION_COMFORT: dict[str, MotionComfortProfile] = {
    "ENTRY": MotionComfortProfile(0.42, 0.26, 0.14),
    "INTERACT": MotionComfortProfile(0.40, 0.28, 0.13),
    "REACT": MotionComfortProfile(0.36, 0.26, 0.12),
    "PAYOFF": MotionComfortProfile(0.42, 0.30, 0.11),
    "EXIT": MotionComfortProfile(0.40, 0.32, 0.14),
}


def motion_comfort(phase: str) -> MotionComfortProfile:
    return _MOTION_COMFORT.get(
        str(phase).upper(),
        MotionComfortProfile(0.36, 0.24, 0.13),
    )


def comfort_gain(phase: str, duration: float) -> float:
    """Scale amplitude down when Story cannot provide a comfortable motion window."""
    profile = motion_comfort(phase)
    duration = max(0.0, float(duration))
    return max(0.0, min(1.0, duration / max(profile.minimum_seconds, 1e-6)))


def max_comfort_displacement(phase: str, duration: float) -> float:
    profile = motion_comfort(phase)
    return max(0.0, float(duration)) * profile.max_normalized_speed


if TYPE_CHECKING:
    from app.story.windows import StoryAssetActivation


def story_activation_window(
    activation: AssetActivation | None, beat: StoryBeat,
) -> tuple[bool, StoryAssetActivation | None]:
    """Distinguish absent V2 (legacy) from V2 abstention/invalid data.

    Read the versioned evidence too: base-typed serialized Story containers omit
    subclass fields. Invalid V2 must never silently become a spoken_start anchor.
    """
    if activation is None:
        return False, None
    has_v2 = hasattr(activation, "activation_policy") or any(
        row.startswith("story_activation_v2:") for row in activation.evidence
    )
    if not has_v2:
        return False, None
    from app.story.windows import StoryAssetActivation

    try:
        window = (
            StoryAssetActivation.model_validate(activation.model_dump())
            if hasattr(activation, "activation_policy")
            else StoryAssetActivation.from_legacy(activation)
        )
        if window.activation_policy not in {"OWN_WINDOW", "INHERITED_WINDOW"}:
            return True, None
        if not (isfinite(beat.start) and isfinite(beat.end)
                and beat.start <= window.reveal_start < window.settle_at <= beat.end):
            return True, None
    except (ValueError, TypeError, OverflowError):
        return True, None
    return True, window


@dataclass(frozen=True, slots=True)
class MotionWindow:
    start: float
    end: float
    semantic_settle: float
    pace_tier: str
    semantic_peak: float | None = None
    story_v2: bool = False
    sequence_staggered: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class MotionTimingPolicy:
    """Narration-aware, distance-aware timing for visual object motion.

    Motion V3.1 separates *appearance settle* from *follow-through*. The primary
    artwork reaches the Composition target at ``semantic_settle`` near the spoken
    anchor, while a restrained semantic reaction may continue afterward. This is
    what lets fast narration feel snappy and slow narration breathe without making
    the viewer wait for the object to arrive.
    """

    _MIN_DURATION = 0.12
    _MIN_EXECUTABLE_DURATION = 0.05
    _PRIMARY_SETTLE_GRACE = 0.04
    _HOOK_SETTLE_GRACE = 0.09
    _MAX_PRIMARY_DURATION = 0.96
    _MAX_SUPPORT_DURATION = 0.68

    def window(
        self,
        *,
        beat: StoryBeat,
        distance: float,
        index: int,
        count: int,
        primary: bool,
        settle_progress: float = 0.58,
        hook: bool = False,
        pace_tier: str | None = None,
        activation: AssetActivation | None = None,
        visual_unit_index: int = 0,
        visual_unit_count: int = 1,
    ) -> MotionWindow:
        visual_duration = max(0.08, beat.end - beat.start)
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        spoken_duration = max(0.12, audio_end - audio_start)
        words = max(1, len(beat.narration.split()))
        words_per_second = words / spoken_duration
        pace_tier = pace_tier or self._pace_tier(words_per_second)

        distance_factor = self._clamp(0.84 + distance * 3.8, 0.82, 1.30)
        semantic_factor = {
            "RESULT": 0.86,
            "EMPHASIZE": 0.90,
            "COMPARE": 1.08,
            "HANDOFF": 1.00,
            "INTRODUCE": 1.02,
            "REVEAL_DETAIL": 0.96,
        }.get(beat.action, 1.0)

        if primary:
            base_duration = {
                # Reference videos sustain meaningful entry motion for roughly
                # 0.4-0.8s instead of snapping into place in 0.15-0.30s.
                # These are preferred window lengths; short beats and semantic
                # anchors still clamp them safely to executable capacity.
                "snap": 0.42,
                "brisk": 0.54,
                "balanced": 0.70,
                "deliberate": 0.86,
            }[pace_tier]
            if hook:
                base_duration = max(base_duration, 0.56)
            preferred = self._clamp(
                base_duration * distance_factor * semantic_factor,
                self._MIN_DURATION,
                min(self._MAX_PRIMARY_DURATION, max(self._MIN_DURATION, visual_duration)),
            )
            anchored = self._activation_window(
                beat=beat,
                activation=activation,
                preferred_duration=preferred,
                settle_progress=settle_progress,
                pace_tier=pace_tier,
                visual_unit_index=visual_unit_index,
                visual_unit_count=visual_unit_count,
            )
            if anchored is not None:
                return anchored
            return self._primary_window(
                beat=beat,
                audio_start=audio_start,
                preferred_duration=preferred,
                settle_progress=settle_progress,
                pace_tier=pace_tier,
                hook=hook,
            )

        base_duration = {
            "snap": 0.34,
            "brisk": 0.44,
            "balanced": 0.56,
            "deliberate": 0.68,
        }[pace_tier]
        if hook:
            base_duration = min(base_duration, 0.32)
        preferred = self._clamp(
            base_duration * distance_factor,
            self._MIN_DURATION,
            min(self._MAX_SUPPORT_DURATION, max(self._MIN_DURATION, visual_duration)),
        )
        anchored = self._activation_window(
            beat=beat,
            activation=activation,
            preferred_duration=preferred,
            settle_progress=settle_progress,
            pace_tier=pace_tier,
            visual_unit_index=visual_unit_index,
            visual_unit_count=visual_unit_count,
        )
        if anchored is not None:
            return anchored
        return self._support_window(
            beat=beat,
            audio_start=audio_start,
            spoken_duration=spoken_duration,
            preferred_duration=preferred,
            index=index,
            count=count,
            settle_progress=settle_progress,
            pace_tier=pace_tier,
            hook=hook,
        )

    def legacy_window(
        self,
        *,
        beat: StoryBeat,
        distance: float,
        index: int,
        count: int,
        primary: bool,
        activation: AssetActivation | None = None,
        settle_progress: float = 0.58,
        visual_unit_index: int = 0,
        visual_unit_count: int = 1,
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
            "RESULT": 0.88, "EMPHASIZE": 0.92, "COMPARE": 1.02,
            "HANDOFF": 1.08, "INTRODUCE": 1.04, "REVEAL_DETAIL": 0.96,
        }.get(beat.action, 1.0)
        base = 0.38 if primary else 0.30
        cap = 0.72 if primary else 0.52
        preferred = self._clamp(
            base * pace_factor * distance_factor * semantic_factor,
            0.12,
            min(cap, max(0.12, visual_duration - 0.04)),
        )
        anchored = self._activation_window(
            beat=beat,
            activation=activation,
            preferred_duration=preferred,
            settle_progress=settle_progress,
            pace_tier=self._pace_tier(words_per_second),
            visual_unit_index=visual_unit_index,
            visual_unit_count=visual_unit_count,
        )
        if anchored is not None:
            return anchored

        if primary:
            start = beat.start
            settle_deadline = min(beat.end, audio_start + 0.04)
            lead_budget = max(0.0, settle_deadline - start)
            if lead_budget <= 0.05:
                end = min(beat.end, start + max(0.0, lead_budget))
                if end <= start:
                    end = min(beat.end, start + 0.05)
            else:
                pace_budget = lead_budget * min(1.0, pace_factor)
                duration = min(preferred, max(0.05, pace_budget))
                end = min(settle_deadline, start + duration)
                end = max(start + 0.05, end)
                end = min(settle_deadline, end)
            tier = self._pace_tier(words_per_second)
            return MotionWindow(start=start, end=end, semantic_settle=end, pace_tier=tier)

        support_count = max(1, count - 1)
        support_index = max(0, index - 1)
        readable_span = max(0.0, min(spoken_duration * 0.58, beat.end - audio_start - 0.06))
        stagger = readable_span / support_count
        start = max(beat.start, audio_start + 0.04 + support_index * stagger)
        latest_start = max(beat.start, beat.end - preferred - 0.04)
        start = min(start, latest_start)
        end = min(beat.end - 0.03, start + preferred)
        minimum = min(0.12, max(0.0, beat.end - start))
        end = max(start + minimum, end)
        end = min(beat.end, end)
        if end <= start:
            end = min(beat.end, start + 0.05)
        tier = self._pace_tier(words_per_second)
        return MotionWindow(start=start, end=end, semantic_settle=end, pace_tier=tier)

    def _primary_window(
        self,
        *,
        beat: StoryBeat,
        audio_start: float,
        preferred_duration: float,
        settle_progress: float,
        pace_tier: str,
        hook: bool,
    ) -> MotionWindow:
        grace = self._HOOK_SETTLE_GRACE if hook else self._PRIMARY_SETTLE_GRACE
        settle_target = min(beat.end, audio_start + grace)
        settle_progress = self._clamp(settle_progress, 0.05, 1.0)

        desired_start = settle_target - preferred_duration * settle_progress
        start = max(beat.start, desired_start)
        lead = max(0.0, settle_target - start)

        if lead <= self._MIN_EXECUTABLE_DURATION:
            duration = min(
                preferred_duration,
                max(self._MIN_EXECUTABLE_DURATION, beat.end - start),
            )
        else:
            duration = lead / settle_progress
            duration = min(preferred_duration, duration)

        duration = min(duration, max(self._MIN_EXECUTABLE_DURATION, beat.end - start))
        end = min(beat.end, start + max(self._MIN_EXECUTABLE_DURATION, duration))
        actual_duration = max(self._MIN_EXECUTABLE_DURATION, end - start)
        semantic_settle = start + settle_progress * actual_duration
        semantic_settle = min(end, semantic_settle)

        return MotionWindow(
            start=start,
            end=end,
            semantic_settle=semantic_settle,
            pace_tier=pace_tier,
        )

    def _support_window(
        self,
        *,
        beat: StoryBeat,
        audio_start: float,
        spoken_duration: float,
        preferred_duration: float,
        index: int,
        count: int,
        settle_progress: float,
        pace_tier: str,
        hook: bool,
    ) -> MotionWindow:
        support_count = max(1, count - 1)
        support_index = max(0, index - 1)

        if hook:
            stagger = 0.085 + min(support_index, 3) * 0.015
            start = max(beat.start, audio_start + support_index * stagger)
        else:
            readable_fraction = {
                "snap": 0.36,
                "brisk": 0.46,
                "balanced": 0.58,
                "deliberate": 0.68,
            }[pace_tier]
            readable_span = max(
                0.0,
                min(spoken_duration * readable_fraction, beat.end - audio_start - 0.04),
            )
            stagger = readable_span / support_count
            start = max(beat.start, audio_start + 0.03 + support_index * stagger)

        # Preserve stagger even when a beat is shorter than the preferred support
        # gesture. In tight beats we shorten the tail gesture instead of pulling all
        # supports back to the same start time (which creates a multi-element pop).
        latest_start = max(beat.start, beat.end - self._MIN_EXECUTABLE_DURATION)
        start = min(start, latest_start)
        end = min(beat.end, start + preferred_duration)
        if end <= start:
            end = min(beat.end, start + self._MIN_EXECUTABLE_DURATION)

        settle_progress = self._clamp(settle_progress, 0.05, 1.0)
        semantic_settle = start + (end - start) * settle_progress
        return MotionWindow(
            start=start,
            end=end,
            semantic_settle=min(end, semantic_settle),
            pace_tier=pace_tier,
        )

    def _activation_window(
        self,
        *,
        beat: StoryBeat,
        activation: AssetActivation | None,
        preferred_duration: float,
        settle_progress: float,
        pace_tier: str,
        visual_unit_index: int = 0,
        visual_unit_count: int = 1,
    ) -> MotionWindow | None:
        has_v2, story_window = story_activation_window(activation, beat)
        if has_v2:
            if story_window is None:
                return None
            base = MotionWindow(
                start=story_window.reveal_start,
                end=story_window.settle_at,
                semantic_settle=story_window.settle_at,
                pace_tier=pace_tier,
                semantic_peak=story_window.semantic_peak,
                story_v2=True,
            )
            return self._stagger_visual_unit_window(
                base,
                index=visual_unit_index,
                count=visual_unit_count,
            )
        if (
            activation is None
            or activation.spoken_start is None
            or activation.policy not in {"SEMANTIC", "EXPLICIT", "GROUP"}
        ):
            return None

        anchor = float(activation.spoken_start)
        if anchor < beat.start + 0.015 or anchor > beat.end - 0.015:
            return None

        settle_progress = self._clamp(settle_progress, 0.05, 1.0)
        before_capacity = max(0.0, anchor - beat.start)
        max_by_before = before_capacity / settle_progress
        if settle_progress >= 1.0 - 1e-9:
            max_by_after = float("inf")
        else:
            after_capacity = max(0.0, beat.end - anchor)
            max_by_after = after_capacity / (1.0 - settle_progress)

        duration = min(preferred_duration, max_by_before, max_by_after)
        if duration < 0.025:
            return None

        start = anchor - settle_progress * duration
        end = start + duration
        base = MotionWindow(
            start=max(beat.start, start),
            end=min(beat.end, end),
            semantic_settle=anchor,
            pace_tier=pace_tier,
        )
        return self._stagger_visual_unit_window(
            base,
            index=visual_unit_index,
            count=visual_unit_count,
        )

    @classmethod
    def _stagger_visual_unit_window(
        cls,
        window: MotionWindow,
        *,
        index: int,
        count: int,
    ) -> MotionWindow:
        """Subdivide one Story-owned window for locator-backed multi-cutout units.

        Final Package/Story still own the outer semantic window. Motion only determines
        the ordered reveal choreography inside that window. The first member starts at
        the Story reveal boundary and the final member completes at Story settle.
        """
        if count <= 1:
            return window
        index = max(0, min(count - 1, int(index)))
        span = max(0.0, window.end - window.start)
        if span <= cls._MIN_EXECUTABLE_DURATION + 1e-9:
            return window

        preferred_motion = min(0.48, max(0.08, span * 0.56))
        preferred_gap = 0.04
        maximum_motion_for_gap = span - preferred_gap * (count - 1)
        if maximum_motion_for_gap >= cls._MIN_EXECUTABLE_DURATION:
            motion_duration = min(preferred_motion, maximum_motion_for_gap)
        else:
            motion_duration = max(cls._MIN_EXECUTABLE_DURATION, span * 0.45)
            motion_duration = min(motion_duration, span)

        if motion_duration >= span - 1e-9:
            return window
        step = (span - motion_duration) / (count - 1)
        if step <= 1e-6:
            return window

        start = window.start + step * index
        end = min(window.end, start + motion_duration)
        if index == count - 1:
            end = window.end
        if end <= start:
            return window
        return MotionWindow(
            start=start,
            end=end,
            semantic_settle=end,
            pace_tier=window.pace_tier,
            semantic_peak=(
                start
                + (end - start)
                * (
                    (window.semantic_peak - window.start)
                    / max(cls._MIN_EXECUTABLE_DURATION, window.end - window.start)
                )
                if window.semantic_peak is not None
                else None
            ),
            story_v2=window.story_v2,
            sequence_staggered=True,
        )

    def pace_tier_for_beat(
        self,
        beat: StoryBeat,
        *,
        choreography_action: str | None = None,
        pacing_bias: float = 1.0,
    ) -> str:
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        spoken_duration = max(0.12, audio_end - audio_start)
        words = max(1, len(beat.narration.split()))
        words_per_second = words / spoken_duration
        action = (choreography_action or "").upper()
        if action in {"REJECT", "BLOCK", "LOOP"}:
            words_per_second = max(words_per_second, 3.15)
        elif action in {"TRAVEL", "SCAN", "COMPARE"}:
            words_per_second = max(words_per_second, 2.55)
        elif action in {"PROTECT", "REVEAL"}:
            words_per_second = min(words_per_second, 2.35)
        words_per_second /= max(0.72, min(1.28, pacing_bias))
        return self._pace_tier(words_per_second)

    @staticmethod
    def _pace_tier(words_per_second: float) -> str:
        if words_per_second >= 3.0:
            return "snap"
        if words_per_second >= 2.5:
            return "brisk"
        if words_per_second >= 2.0:
            return "balanced"
        return "deliberate"

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        if high < low:
            return low
        return max(low, min(high, value))
