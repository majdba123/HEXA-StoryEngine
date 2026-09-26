from __future__ import annotations

from dataclasses import dataclass

from app.models import CompositionBeat, MotionCue


@dataclass(frozen=True, slots=True)
class AssetLifecycleBoundary:
    """Shared lifecycle decision for one adjacent beat boundary."""

    shared_asset_ids: frozenset[str]
    persistent_asset_ids: frozenset[str]
    terminal_exit_asset_ids: frozenset[str]

    @property
    def invalid_terminal_persistence(self) -> frozenset[str]:
        return self.shared_asset_ids & self.terminal_exit_asset_ids


class ContinuityContract:
    """Single source of truth for cross-beat asset lifecycle.

    The same runtime asset may persist across adjacent beats, but an authored terminal
    EXIT/LEAVE explicitly ends that visual lifetime. A planner must therefore avoid
    authoring a terminal exit when the exact same asset continues in the next layout.
    QA consumes the same rule and rejects externally supplied or legacy plans that
    violate it before FFmpeg rendering.
    """

    TERMINAL_BEHAVIOR = "LEAVE"

    @staticmethod
    def continues_into_layout(asset_id: str, next_layout: CompositionBeat | None) -> bool:
        if next_layout is None:
            return False
        return any(item.asset_id == asset_id for item in next_layout.items)

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
    ) -> AssetLifecycleBoundary:
        previous_ids = (
            {item.asset_id for item in previous_layout.items}
            if previous_layout is not None
            else set()
        )
        current_ids = (
            {item.asset_id for item in current_layout.items}
            if current_layout is not None
            else set()
        )
        shared = frozenset(previous_ids & current_ids)
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
