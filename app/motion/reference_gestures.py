from __future__ import annotations

from math import hypot

from app.models import LayoutItem
from app.motion.models import MotionKeyframe, MotionProgram
from app.reference.motion_language import ReferenceGestureKind, ReferenceMotionLanguage


class ReferenceGestureLibrary:
    """Reference-only motion vocabulary used by production MotionPlanner.

    Every generated program has one readable gesture, reaches Composition once, then
    holds. It intentionally does not reuse legacy bounce/wobble primitives.
    """

    def __init__(self, language: ReferenceMotionLanguage | None = None) -> None:
        self.language = language or ReferenceMotionLanguage.production()

    @staticmethod
    def _edge_direction(item: LayoutItem) -> float:
        return -1.0 if item.x < 0.5 else 1.0

    @staticmethod
    def _clamp_vector(vector: tuple[float, float], limit: float) -> tuple[float, float]:
        x, y = vector
        length = hypot(x, y)
        if length <= 1e-9 or length <= limit:
            return x, y
        gain = limit / length
        return x * gain, y * gain

    @staticmethod
    def _one_shot(
        *,
        name: str,
        dx: float = 0.0,
        dy: float = 0.0,
        scale: float = 1.0,
        settle: float = 0.78,
        easing: str = "ease_in_out_cubic",
    ) -> MotionProgram:
        settle = max(0.55, min(0.92, settle))
        checkpoint = settle * 0.618
        return MotionProgram(
            name=name,
            settle_progress=settle,
            keyframes=(
                MotionKeyframe(0.0, dx, dy, scale, easing),
                MotionKeyframe(
                    checkpoint,
                    dx * 0.382,
                    dy * 0.382,
                    1.0 + (scale - 1.0) * 0.382,
                    "ease_in_out_cubic",
                ),
                MotionKeyframe(settle, 0.0, 0.0, 1.0, "smoothstep"),
                MotionKeyframe(1.0, 0.0, 0.0, 1.0, "smoothstep"),
            ),
        )

    def build_family_secondary(self) -> MotionProgram:
        return MotionProgram(
            name="family_secondary_footprint_locked_reveal",
            settle_progress=1.0,
            keyframes=(MotionKeyframe(0.0), MotionKeyframe(1.0)),
        )

    def build_legacy(
        self,
        *,
        action: str,
        item: LayoutItem,
        index: int,
        count: int,
        visual_duration: float,
    ) -> MotionProgram:
        del count
        action = str(action or "").upper()
        if action == "RESULT":
            return self._one_shot(
                name="reference_result_enter",
                dy=0.022,
                scale=self.language.result_scale_start,
                settle=self.language.entry_settle_progress,
            )
        if action == "COMPARE":
            return self._one_shot(
                name="reference_compare_shift",
                dx=self._edge_direction(item) * 0.028,
                scale=0.985,
                settle=self.language.entry_settle_progress,
            )
        if action in {"HANDOFF", "TRAVEL", "CONNECT"}:
            return self._one_shot(
                name="reference_directional_handoff",
                dx=self._edge_direction(item) * 0.040,
                dy=0.008,
                scale=0.985,
                settle=self.language.entry_settle_progress,
            )
        return self.build(
            action="FOCUS",
            item=item,
            index=index,
            count=1,
            visual_duration=visual_duration,
            is_primary=index == 0,
        )

    def build(
        self,
        *,
        action: str,
        item: LayoutItem,
        index: int,
        count: int,
        visual_duration: float,
        interaction_vector: tuple[float, float] = (0.0, 0.0),
        phase: str = "ACTION",
        hook_kind: str = "NONE",
        hook_mechanism: str = "NONE",
        energy: float = 0.6,
        tension: float = 0.0,
        variant: int = 0,
        is_primary: bool | None = None,
        participant_role: str = "SUPPORT",
    ) -> MotionProgram:
        del action, count, interaction_vector, phase, hook_mechanism, tension, variant
        primary = index == 0 if is_primary is None else bool(is_primary)
        if visual_duration < 0.10:
            return MotionProgram(
                name="reference_hold",
                settle_progress=1.0,
                keyframes=(MotionKeyframe(0.0), MotionKeyframe(1.0)),
            )

        hook = hook_kind != "NONE"
        energy = max(0.35, min(1.0, float(energy)))
        role = str(participant_role or "SUPPORT").upper()
        direction = self._edge_direction(item)

        if role == "RESULT":
            amplitude = (0.030 if hook else 0.018) * energy
            return self._one_shot(
                name="reference_result_enter",
                dx=direction * amplitude,
                dy=0.018 * energy,
                scale=self.language.result_scale_start,
                settle=self.language.entry_settle_progress,
            )

        if primary:
            amplitude = (0.060 if hook else 0.040) * (0.80 + 0.20 * energy)
            amplitude = min(amplitude, self.language.max_entry_offset)
            return self._one_shot(
                name="reference_slide_settle",
                dx=direction * amplitude,
                dy=0.012 * energy,
                scale=0.975 if hook else 0.985,
                settle=self.language.entry_settle_progress,
            )

        return self._one_shot(
            name="reference_pop_reveal",
            dy=0.016 * energy,
            scale=self.language.support_scale_start,
            settle=self.language.entry_settle_progress,
        )

    def build_continuity(
        self,
        *,
        action: str,
        item: LayoutItem,
        index: int,
        count: int,
        visual_duration: float,
        previous_offset: tuple[float, float],
        previous_scale: float,
        interaction_vector: tuple[float, float] = (0.0, 0.0),
        phase: str = "ACTION",
        hook_kind: str = "NONE",
        hook_mechanism: str = "NONE",
        energy: float = 0.6,
        tension: float = 0.0,
        variant: int = 0,
        same_asset: bool = True,
        is_primary: bool | None = None,
        participant_role: str = "SUPPORT",
    ) -> MotionProgram:
        del (
            action,
            index,
            count,
            visual_duration,
            interaction_vector,
            phase,
            hook_kind,
            hook_mechanism,
            energy,
            tension,
            variant,
            is_primary,
            participant_role,
        )
        limit = 0.075 if same_asset else 0.060
        px, py = self._clamp_vector(previous_offset, limit)
        previous_scale = max(0.94, min(1.06, float(previous_scale)))
        return self._one_shot(
            name="reference_focus_handoff" if same_asset else "reference_slide_settle",
            dx=px,
            dy=py,
            scale=previous_scale,
            settle=0.72,
        )

    @classmethod
    def event_accent(
        cls,
        *,
        stage: str,
        semantic_action: str,
        involvement: str,
        vector: tuple[float, float],
        focus_strength: float,
    ) -> tuple[ReferenceGestureKind, float, float, float]:
        language = ReferenceMotionLanguage.production()
        vx, vy = cls._clamp_vector(vector, language.max_semantic_offset)
        stage = str(stage or "").upper()
        action = str(semantic_action or "").upper()
        involvement = str(involvement or "").upper()
        focus = max(0.0, min(1.0, float(focus_strength)))

        if stage == "ESTABLISH":
            return ReferenceGestureKind.FOCUS_HANDOFF, 0.0, -0.004, 1.020 + 0.012 * focus
        if stage == "ADD":
            return ReferenceGestureKind.SEQUENTIAL_ADD, vx * 0.20, vy * 0.20 - 0.003, 1.018 + 0.010 * focus
        if stage == "INTERACT":
            if action == "COMPARE":
                return ReferenceGestureKind.COMPARE_SHIFT, -vx * 0.65, -vy * 0.65, 1.015
            if action == "LOOP":
                return ReferenceGestureKind.DIRECTIONAL_HANDOFF, -vy * 0.65, vx * 0.65, 1.012
            if action in {"TRAVEL", "CONNECT"}:
                factor = 0.90 if involvement == "SOURCE" else 0.32
                return ReferenceGestureKind.DIRECTIONAL_HANDOFF, vx * factor, vy * factor, 1.015
            if action in {"BLOCK", "REJECT"}:
                if involvement == "TARGET":
                    return ReferenceGestureKind.SHORT_IMPACT, -vx * 0.40, -vy * 0.40, language.max_impact_scale
                return ReferenceGestureKind.DIRECTIONAL_HANDOFF, vx * 0.72, vy * 0.72, 1.015
            if action == "LOCK":
                return ReferenceGestureKind.STATE_CHANGE, vx * 0.20, vy * 0.20, 0.985
            if action in {"PROTECT", "RESOLVE", "REVEAL"}:
                return ReferenceGestureKind.FOCUS_HANDOFF, vx * 0.24, vy * 0.24 - 0.003, 1.025
            if involvement == "SOURCE":
                return ReferenceGestureKind.DIRECTIONAL_HANDOFF, vx * 0.65, vy * 0.65, 1.015
            return ReferenceGestureKind.FOCUS_HANDOFF, 0.0, -0.003, 1.022
        if stage == "REACT":
            if action in {"BLOCK", "REJECT"}:
                return ReferenceGestureKind.SHORT_IMPACT, -vx * 0.45, -vy * 0.45, language.max_impact_scale
            if action == "LOCK":
                return ReferenceGestureKind.STATE_CHANGE, vx * 0.18, vy * 0.18, 0.982
            if action in {"TRAVEL", "CONNECT"}:
                return ReferenceGestureKind.FOCUS_HANDOFF, vx * 0.22, vy * 0.22 - 0.003, 1.025
            if action in {"REVEAL", "PROTECT", "RESOLVE"}:
                return ReferenceGestureKind.STATE_CHANGE, 0.0, -0.005, 1.030
            if action == "LOOP":
                return ReferenceGestureKind.SHORT_IMPACT, -vy * 0.35, vx * 0.35, 1.025
            return ReferenceGestureKind.SHORT_IMPACT, -vx * 0.30, -vy * 0.30 - 0.003, 1.028
        if stage == "PAYOFF":
            if action in {"LOCK", "RESOLVE"}:
                return ReferenceGestureKind.STATE_CHANGE, 0.0, -0.004, 1.032
            if action == "COMPARE":
                return ReferenceGestureKind.FOCUS_HANDOFF, 0.0, -0.004, 1.030
            return ReferenceGestureKind.RESULT_ENTER, vx * 0.16, vy * 0.16 - 0.006, language.max_result_scale
        return ReferenceGestureKind.HOLD, 0.0, 0.0, 1.0

    @classmethod
    def fallback_action_accent(
        cls,
        *,
        action: str,
        interaction_vector: tuple[float, float],
        focus_strength: float,
    ) -> tuple[ReferenceGestureKind, float, float, float] | None:
        action = str(action or "").upper()
        vx, vy = cls._clamp_vector(interaction_vector, 0.05)
        focus = max(0.0, min(1.0, float(focus_strength)))
        if action in {"REJECT", "BLOCK"}:
            return ReferenceGestureKind.SHORT_IMPACT, -vx * 0.40, -vy * 0.40 - 0.003, 1.025
        if action in {"TRAVEL", "CONNECT"}:
            return ReferenceGestureKind.DIRECTIONAL_HANDOFF, vx * 0.75, vy * 0.75, 1.012
        if action == "COMPARE":
            return ReferenceGestureKind.COMPARE_SHIFT, -vx * 0.60, -vy * 0.60, 1.015
        if action == "LOCK":
            return ReferenceGestureKind.STATE_CHANGE, 0.0, 0.0, 0.985
        if action in {"REVEAL", "RESOLVE", "PROTECT"}:
            return ReferenceGestureKind.FOCUS_HANDOFF, 0.0, -0.004, 1.020 + 0.012 * focus
        if action == "LOOP":
            return ReferenceGestureKind.DIRECTIONAL_HANDOFF, -vy * 0.55, vx * 0.55, 1.012
        if action in {"RESULT", "PAYOFF"}:
            return ReferenceGestureKind.RESULT_ENTER, 0.0, -0.006, 1.040
        return None

    @classmethod
    def pattern_accent(
        cls,
        *,
        pattern: str,
        participant_role: str,
        primary: bool,
        momentary_focus: bool,
        focus_role: str,
        focus_strength: float,
        state_target: bool,
        interaction_vector: tuple[float, float],
    ) -> tuple[ReferenceGestureKind, float, float, float] | None:
        pattern = str(pattern or "STANDARD").upper()
        role = str(participant_role or "SUPPORT").upper()
        focus_role = str(focus_role or role).upper()
        focus = max(0.0, min(1.0, float(focus_strength)))
        vx, vy = cls._clamp_vector(interaction_vector, 0.05)
        if pattern == "STANDARD":
            if not momentary_focus:
                return None
            return ReferenceGestureKind.FOCUS_HANDOFF, 0.0, -0.004, 1.018 + 0.012 * focus
        if pattern == "PROGRESSIVE_BUILD":
            if not (momentary_focus or primary):
                return None
            return ReferenceGestureKind.SEQUENTIAL_ADD, 0.0, -0.004, 1.020 + 0.012 * focus
        if pattern == "FOCUS_TRANSFER":
            if not (momentary_focus or primary):
                return None
            return ReferenceGestureKind.FOCUS_HANDOFF, 0.0, -0.005, 1.020 + 0.015 * focus
        if pattern == "STATE_TRANSFORM":
            if not (state_target or momentary_focus or primary):
                return None
            return ReferenceGestureKind.STATE_CHANGE, 0.0, -0.005, 1.025 + 0.010 * focus
        if pattern == "CAUSE_EFFECT_CHAIN":
            if role == "SUBJECT":
                return ReferenceGestureKind.DIRECTIONAL_HANDOFF, vx * 0.75, vy * 0.75, 1.012
            if role == "OBJECT":
                return ReferenceGestureKind.SHORT_IMPACT, -vx * 0.30, -vy * 0.30, 1.025
            if role == "RESULT" or focus_role == "RESULT":
                return ReferenceGestureKind.RESULT_ENTER, 0.0, -0.006, 1.040
            if momentary_focus or primary:
                return ReferenceGestureKind.FOCUS_HANDOFF, 0.0, -0.004, 1.022
        return None
