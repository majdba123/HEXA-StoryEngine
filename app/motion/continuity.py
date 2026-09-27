from __future__ import annotations

from dataclasses import dataclass

from app.models import AssetActivation, CompositionBeat, MotionCue, StoryBeat


@dataclass(frozen=True, slots=True)
class AssetLifecycleBoundary:
    """Motion-owned lifecycle decision for one adjacent beat boundary."""

    shared_asset_ids: frozenset[str]
    persistent_asset_ids: frozenset[str]
    terminal_exit_asset_ids: frozenset[str]

    @property
    def invalid_terminal_persistence(self) -> frozenset[str]:
        return self.shared_asset_ids & self.terminal_exit_asset_ids


class ContinuityContract:
    """Single source of truth for cross-beat asset lifecycle.

    Motion owns terminal-exit and visual-lifetime rules. QA and Render may inspect the
    same contract, but they do not define it. Behavior and thresholds are preserved
    exactly from the former generic app.contracts location.
    """

    TERMINAL_BEHAVIOR = "LEAVE"

    @staticmethod
    def _semantic_identity(activation: AssetActivation) -> tuple[str, str] | None:
        if getattr(activation, "activation_policy", None) == "SAFE_ABSTENTION":
            return None
        return (
            activation.asset_id,
            str(activation.semantic_unit_id or activation.asset_id),
        )

    @classmethod
    def persistent_asset_ids(
        cls,
        previous_beat: StoryBeat | None,
        current_beat: StoryBeat | None,
        previous_layout: CompositionBeat | None,
        current_layout: CompositionBeat | None,
    ) -> frozenset[str]:
        """Return exact runtime carriers with continuous semantic participation.

        Composition deliberately contains every independently animatable scene asset,
        so layout overlap alone is not semantic continuity.  When Story provides
        activations, the same runtime asset must represent the same semantic unit on
        both sides of the adjacent boundary.  Activation-free legacy callers retain
        the historical layout-based behavior.
        """
        previous_ids = {
            item.asset_id for item in previous_layout.items
        } if previous_layout is not None else set()
        current_ids = {
            item.asset_id for item in current_layout.items
        } if current_layout is not None else set()
        shared_layout_ids = previous_ids & current_ids
        if previous_beat is None or current_beat is None:
            return frozenset(shared_layout_ids)
        if not previous_beat.asset_activations or not current_beat.asset_activations:
            return frozenset(shared_layout_ids)

        previous_semantics = {
            identity
            for row in previous_beat.asset_activations
            if (identity := cls._semantic_identity(row)) is not None
        }
        current_semantics = {
            identity
            for row in current_beat.asset_activations
            if (identity := cls._semantic_identity(row)) is not None
        }
        return frozenset(
            asset_id
            for asset_id, _unit_id in previous_semantics & current_semantics
            if asset_id in shared_layout_ids
        )

    @staticmethod
    def continues_into_layout(asset_id: str, next_layout: CompositionBeat | None) -> bool:
        if next_layout is None:
            return False
        return any(item.asset_id == asset_id for item in next_layout.items)

    @classmethod
    def continues_between_beats(
        cls,
        asset_id: str,
        current_beat: StoryBeat,
        next_beat: StoryBeat | None,
        current_layout: CompositionBeat,
        next_layout: CompositionBeat | None,
    ) -> bool:
        return asset_id in cls.persistent_asset_ids(
            current_beat,
            next_beat,
            current_layout,
            next_layout,
        )

    @classmethod
    def has_terminal_exit(cls, cue: MotionCue | None) -> bool:
        if cue is None:
            return False
        for segment in cue.segments:
            if str(segment.phase).upper() != "EXIT":
                continue
            terminal = str(segment.program.get("terminal_behavior") or "").upper()
            if terminal == cls.TERMINAL_BEHAVIOR:
                return True
        return False

    @classmethod
    def classify_boundary(
        cls,
        *,
        previous_layout: CompositionBeat | None,
        current_layout: CompositionBeat | None,
        previous_motion_by_asset: dict[str, MotionCue],
        previous_beat: StoryBeat | None = None,
        current_beat: StoryBeat | None = None,
    ) -> AssetLifecycleBoundary:
        shared = cls.persistent_asset_ids(
            previous_beat,
            current_beat,
            previous_layout,
            current_layout,
        )
        terminal = frozenset(
            asset_id
            for asset_id in shared
            if cls.has_terminal_exit(previous_motion_by_asset.get(asset_id))
        )
        return AssetLifecycleBoundary(
            shared_asset_ids=shared,
            persistent_asset_ids=frozenset(shared - terminal),
            terminal_exit_asset_ids=terminal,
        )
