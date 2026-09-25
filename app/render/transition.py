from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models import CompositionBeat, StoryBeat


class SceneTransitionMode(StrEnum):
    NONE = "NONE"
    CLEAN_HANDOFF = "CLEAN_HANDOFF"
    OBJECT_HANDOFF = "OBJECT_HANDOFF"
    MOTION_HANDOFF = "MOTION_HANDOFF"
    BLUR_BRIDGE = "BLUR_BRIDGE"


@dataclass(frozen=True, slots=True)
class VisualTransitionDecision:
    persistent_asset_ids: frozenset[str]
    carry_outgoing_asset_ids: frozenset[str]
    mode: SceneTransitionMode = SceneTransitionMode.NONE
    bridge_duration: float = 0.0
    blur_sigma: float = 0.0
    reason: str = "none"


class VisualTransitionPolicy:
    """Choose scene-boundary continuity without leaking future semantic artwork.

    Cross-scene boundaries always receive a controlled outgoing handoff. Blur is
    reserved for explicit authored handoffs/continuations; ordinary scene changes use
    motion only. The renderer never alpha-crossfades unrelated cutouts, avoiding the
    pale ghost silhouettes that motivated the original no-carry policy.
    """

    _EXPLICIT_BLUR_TOKENS = ("BLUR", "SOFT", "DEFOCUS", "DEPTH_BRIDGE")

    @classmethod
    def _has_explicit_blur_intent(cls, beat: StoryBeat) -> bool:
        """Blur is an authored render style, never a synonym for continuity."""
        context = beat.semantic_context
        if context is None:
            return False

        candidates = [str(context.continuity_relation or "")]
        for metadata in (context.scene_metadata, context.event_metadata):
            for key in ("transition", "transition_style", "handoff_style", "bridge_style"):
                value = metadata.get(key)
                if value is not None:
                    candidates.append(str(value))
        return any(
            token in candidate.strip().upper()
            for candidate in candidates
            for token in cls._EXPLICIT_BLUR_TOKENS
        )

    @staticmethod
    def _has_object_continuity(beat: StoryBeat) -> bool:
        context = beat.semantic_context
        if context is None:
            return False
        return any(
            isinstance(spec, dict)
            and str(spec.get("mode") or "").strip().upper() in {"PERSIST", "TRANSFORM_TO"}
            for spec in context.continuity_by_unit.values()
        )

    def decide(
        self,
        previous_beat: StoryBeat | None,
        previous_layout: CompositionBeat | None,
        current_layout: CompositionBeat | None,
        *,
        current_beat: StoryBeat | None = None,
    ) -> VisualTransitionDecision:
        previous_ids = {
            item.asset_id for item in previous_layout.items
        } if previous_layout is not None else set()
        current_ids = {
            item.asset_id for item in current_layout.items
        } if current_layout is not None else set()
        persistent = frozenset(previous_ids & current_ids)

        if (
            previous_beat is None
            or current_beat is None
            or previous_layout is None
            or current_layout is None
        ):
            return VisualTransitionDecision(
                persistent_asset_ids=persistent,
                carry_outgoing_asset_ids=frozenset(),
            )

        if previous_beat.scene_id == current_beat.scene_id:
            return VisualTransitionDecision(
                persistent_asset_ids=persistent,
                carry_outgoing_asset_ids=frozenset(),
                mode=SceneTransitionMode.CLEAN_HANDOFF,
                reason="same_scene",
            )

        outgoing = frozenset(previous_ids - persistent)
        if not outgoing:
            return VisualTransitionDecision(
                persistent_asset_ids=persistent,
                carry_outgoing_asset_ids=frozenset(),
                mode=SceneTransitionMode.CLEAN_HANDOFF,
                reason="no_distinct_outgoing_assets",
            )

        beat_duration = max(0.0, float(current_beat.end) - float(current_beat.start))
        if self._has_object_continuity(current_beat):
            bridge_duration = min(0.42, max(0.26, beat_duration * 0.18))
            return VisualTransitionDecision(
                persistent_asset_ids=persistent,
                carry_outgoing_asset_ids=outgoing,
                mode=SceneTransitionMode.OBJECT_HANDOFF,
                bridge_duration=bridge_duration,
                reason="authored_object_continuity",
            )

        if self._has_explicit_blur_intent(current_beat):
            bridge_duration = min(0.48, max(0.30, beat_duration * 0.22))
            return VisualTransitionDecision(
                persistent_asset_ids=persistent,
                carry_outgoing_asset_ids=outgoing,
                mode=SceneTransitionMode.BLUR_BRIDGE,
                bridge_duration=bridge_duration,
                blur_sigma=5.5,
                reason="explicit_blur_intent",
            )

        bridge_duration = min(0.40, max(0.24, beat_duration * 0.16))
        return VisualTransitionDecision(
            persistent_asset_ids=persistent,
            carry_outgoing_asset_ids=outgoing,
            mode=SceneTransitionMode.MOTION_HANDOFF,
            bridge_duration=bridge_duration,
            reason="cross_scene_motion_handoff",
        )
