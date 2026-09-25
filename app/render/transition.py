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
    object_handoff_pairs: tuple[tuple[str, str], ...] = ()
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

    _EXPLICIT_BLUR_TOKENS = ("BLUR", "DEFOCUS", "DEPTH_BRIDGE")
    _STYLE_BLUR_TOKENS = (*_EXPLICIT_BLUR_TOKENS, "SOFT")

    @classmethod
    def _has_explicit_blur_intent(cls, beat: StoryBeat) -> bool:
        """Blur is an authored render style, never a synonym for continuity."""
        context = beat.semantic_context
        if context is None:
            return False

        continuity = str(context.continuity_relation or "").strip().upper()
        if any(token in continuity for token in cls._EXPLICIT_BLUR_TOKENS):
            return True

        style_candidates: list[str] = []
        for metadata in (context.scene_metadata, context.event_metadata):
            for key in ("transition", "transition_style", "handoff_style", "bridge_style"):
                value = metadata.get(key)
                if value is not None:
                    style_candidates.append(str(value).strip().upper())
        return any(
            token in candidate
            for candidate in style_candidates
            for token in cls._STYLE_BLUR_TOKENS
        )

    @staticmethod
    def _object_handoff_pairs(
        previous_beat: StoryBeat,
        current_beat: StoryBeat,
    ) -> tuple[tuple[str, str], ...]:
        """Resolve authored continuity to real runtime cutout ids.

        Final Package continuity names semantic assets; Story activation binds those
        semantic ids to actual Pass1/Pass2 cutouts. Only an unambiguous runtime pair is
        allowed to drive object-level handoff motion.
        """
        current_by_key: dict[str, list[str]] = {}
        for activation in current_beat.asset_activations:
            for key in (activation.asset_id, activation.semantic_unit_id):
                if not key:
                    continue
                current_by_key.setdefault(str(key), []).append(activation.asset_id)

        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for activation in previous_beat.asset_activations:
            spec = activation.continuity
            if not isinstance(spec, dict) and previous_beat.semantic_context is not None:
                if activation.semantic_unit_id:
                    candidate = previous_beat.semantic_context.continuity_by_unit.get(
                        activation.semantic_unit_id
                    )
                    spec = candidate if isinstance(candidate, dict) else None
            if not isinstance(spec, dict):
                continue

            mode = str(spec.get("mode") or "").strip().upper()
            if mode not in {"PERSIST", "TRANSFORM_TO"}:
                continue
            target_key = (
                spec.get("target_asset_id")
                or spec.get("target_semantic_unit_id")
                or (activation.semantic_unit_id if mode == "PERSIST" else None)
            )
            if target_key is None:
                continue
            targets = tuple(dict.fromkeys(current_by_key.get(str(target_key), ())))
            if len(targets) != 1:
                continue
            pair = (activation.asset_id, targets[0])
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)
        return tuple(pairs)

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

        object_pairs = self._object_handoff_pairs(previous_beat, current_beat)
        if object_pairs:
            paired_outgoing = frozenset(
                old_id for old_id, _new_id in object_pairs if old_id in outgoing
            )
            bridge_duration = min(0.42, max(0.26, beat_duration * 0.18))
            return VisualTransitionDecision(
                persistent_asset_ids=persistent,
                # Keep every outgoing visual alive for the short handoff so the rest
                # of the old scene exits instead of hard-cutting. Only paired assets
                # receive target-seeking object motion; unpaired assets recede normally.
                carry_outgoing_asset_ids=outgoing,
                object_handoff_pairs=object_pairs,
                mode=SceneTransitionMode.OBJECT_HANDOFF,
                bridge_duration=bridge_duration,
                reason="authored_object_continuity",
            )

        bridge_duration = min(0.40, max(0.24, beat_duration * 0.16))
        return VisualTransitionDecision(
            persistent_asset_ids=persistent,
            carry_outgoing_asset_ids=outgoing,
            mode=SceneTransitionMode.MOTION_HANDOFF,
            bridge_duration=bridge_duration,
            reason="cross_scene_motion_handoff",
        )
