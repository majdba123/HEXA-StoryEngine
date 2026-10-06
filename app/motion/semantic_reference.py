from __future__ import annotations

from dataclasses import dataclass, field

from app.models import CompositionBeat, LayoutItem, MotionCue


@dataclass(frozen=True, slots=True)
class MotionSemanticReference:
    """The reference-format Motion decisions every other output format must reproduce.

    Motion makes a few semantic decisions behind geometric gates: the internal reveal
    order of a multi-cutout intent (a spatial tie-break), whether a focused character can
    grow or its supports recede instead, and whether a relation focus handoff executes.
    Those answers are part of the edit, not of the frame shape, so a non-reference target
    takes them from the reference plan and only solves *how far* things move on its own
    geometry. On the reference target this object is absent and planning is unchanged.
    """

    composition: tuple[CompositionBeat, ...]
    motion: tuple[MotionCue, ...]
    # Text cues the reference format kept (text selection is shared; placement is not).
    text_cue_ids: frozenset[str] | None = None
    _layouts: dict[str, CompositionBeat] = field(init=False, repr=False, compare=False)
    _cues: dict[tuple[str, str], MotionCue] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_layouts", {row.beat_id: row for row in self.composition})
        object.__setattr__(self, "_cues", {(c.beat_id, c.asset_id): c for c in self.motion})

    @classmethod
    def of(
        cls,
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        text_cue_ids: set[str] | frozenset[str] | None = None,
    ) -> "MotionSemanticReference":
        return cls(
            composition=tuple(composition),
            motion=tuple(motion),
            text_cue_ids=frozenset(text_cue_ids) if text_cue_ids is not None else None,
        )

    @classmethod
    def from_plan(cls, plan) -> "MotionSemanticReference":
        """Reference decisions from a reference-format RenderPlan."""
        return cls.of(plan.composition, plan.motion, {cue.id for cue in plan.text.cues})

    def order_items(self, beat_id: str, items: list[LayoutItem]) -> list[LayoutItem] | None:
        """Reference geometry for the same items (used only to break order ties)."""
        layout = self._layouts.get(beat_id)
        if layout is None:
            return None
        by_id = {item.asset_id: item for item in layout.items}
        if {item.asset_id for item in items} != set(by_id):
            return None
        return [by_id[item.asset_id] for item in items]

    def cue(self, beat_id: str, asset_id: str) -> MotionCue | None:
        return self._cues.get((beat_id, asset_id))

    def emphasis(self, beat_id: str, asset_id: str) -> dict | None:
        cue = self.cue(beat_id, asset_id)
        audit = cue.params.get("character_emphasis") if cue is not None else None
        return dict(audit) if isinstance(audit, dict) else None

    def dipped_supports(self, beat_id: str, focus_asset_id: str) -> set[str] | None:
        cue = self.cue(beat_id, focus_asset_id)
        audit = cue.params.get("supporting_deemphasis") if cue is not None else None
        if not isinstance(audit, dict):
            return None
        return set(audit.get("assets") or []) if audit.get("applied") else set()

    def handoff_applied(self, beat_id: str, source_id: str, target_id: str) -> bool | None:
        cue = self.cue(beat_id, source_id)
        if cue is None:
            return None
        if any(
            row.semantic_action == "FOCUS_HANDOFF" and row.target_asset_id == target_id
            for row in cue.segments
        ):
            return True
        return False
