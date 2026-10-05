from __future__ import annotations

from app.assets import AssetManager
from app.composition.text_director import TextPlacementDirector
from app.layout.footprint import AlphaFootprintResolver
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    SceneBoundaryRelease,
    StoryBeat,
    TextCompositionBeat,
    TextMotionCue,
    TextPlan,
    VisualAsset,
)
from app.render.transition import SceneTransitionMode, VisualTransitionPolicy
from app.shared.frame_grid import BeatSegment, beat_segments, first_visible_frame

# Sprint 4.5: reference-derived scene release. Measured reference boundaries fade the
# outgoing scene over 5-7 frames (median 6); where old and new share the screen they do so
# for a median of 4 frames. Nothing shorter than 5 frames is a release: it is a cut.
RELEASE_FRAMES = 6
MIN_RELEASE_FRAMES = 5
OVERLAP_FRAMES = 4
_EPS = 1e-6
# Segment phases that carry certified semantic motion (Sprint 4.1 / 4.2); an overlap must
# never run underneath them.
_PROTECTED_PHASES = frozenset({"INTERACT", "REACT", "PAYOFF"})

Box = tuple[float, float, float, float]


class SceneBoundaryPlanner:
    """Plan how each outgoing scene leaves the screen, above the renderer.

    Eligibility is the existing boundary classification only: an unrelated cross-scene
    change with no authored continuity and nothing persistent. Every other boundary
    abstains and keeps its certified behaviour. For eligible boundaries the requested
    mode is the reference one (a short overlap) and safety checks on final geometry,
    text and timing may only downgrade it: OVERLAP -> EXACT_END -> HARD_CUT. A collision
    is a safety fact, never evidence that two scenes are related.
    """

    def __init__(self) -> None:
        self.classifier = VisualTransitionPolicy()
        self.footprints = AlphaFootprintResolver()

    def plan(
        self,
        *,
        story: list[StoryBeat],
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        assets: list[VisualAsset],
        duration: float,
        fps: int = 30,
        text: TextPlan | None = None,
        text_composition: list[TextCompositionBeat] | None = None,
        text_motion: list[TextMotionCue] | None = None,
    ) -> list[SceneBoundaryRelease]:
        layouts = {layout.beat_id: layout for layout in composition}
        cues = {(cue.beat_id, cue.asset_id): cue for cue in motion}
        assets_by_id = {asset.id: asset for asset in assets}
        text_boxes = self._text_boxes(text, text_composition, text_motion)
        output: list[SceneBoundaryRelease] = []
        for segment in beat_segments(story, duration=duration, fps=fps):
            if segment.previous_beat is None:
                continue
            output.append(self._plan_one(
                segment, layouts=layouts, cues=cues, assets=assets_by_id,
                text_boxes=text_boxes.get(segment.beat.id, []), fps=fps,
            ))
        return output

    def _plan_one(
        self,
        segment: BeatSegment,
        *,
        layouts: dict[str, CompositionBeat],
        cues: dict[tuple[str, str], MotionCue],
        assets: dict[str, VisualAsset],
        text_boxes: list[tuple[float, float, Box]],
        fps: int,
    ) -> SceneBoundaryRelease:
        beat, previous = segment.beat, segment.previous_beat
        assert previous is not None

        def result(mode: str, reason: str, downgrade: str | None = None, **audit) -> SceneBoundaryRelease:
            return SceneBoundaryRelease(
                beat_id=beat.id, from_beat_id=previous.id, mode=mode, reason=reason,
                downgrade_reason=downgrade,
                opener_at=audit.pop("opener_at", None),
                release_start=audit.pop("release_start", None),
                release_end=audit.pop("release_end", None),
                audit=audit,
            )

        layout, previous_layout = layouts.get(beat.id), layouts.get(previous.id)
        incoming = self._active_items(beat, layout)
        if previous_layout is None or not incoming:
            return result("HARD_CUT", "abstain:no_boundary_artwork")
        legacy = self.classifier.decide(previous, previous_layout, layout, current_beat=beat)
        if legacy.mode != SceneTransitionMode.MOTION_HANDOFF or legacy.persistent_asset_ids:
            # Same scene, authored continuity, persistent artwork or an authored blur:
            # that boundary already has an owner and this release must not touch it.
            return result("HARD_CUT", f"abstain:legacy_boundary:{legacy.reason}")
        outgoing = [item for item in previous_layout.items
                    if item.asset_id in legacy.carry_outgoing_asset_ids]
        if not outgoing:
            return result("HARD_CUT", "abstain:no_outgoing_artwork")

        start_time = segment.start_frame / fps
        first = {
            item.asset_id: first_visible_frame(
                self._visible_start(beat, cues.get((beat.id, item.asset_id))) - start_time, fps)
            for item in incoming
        }
        frames = sorted(set(first.values()))
        k_open = frames[0]
        k_next = frames[1] if len(frames) > 1 else None
        audit = {"opener_frame": k_open, "next_reveal_frame": k_next,
                 "outgoing_assets": len(outgoing),
                 "outgoing_pass2_families": self._multi_layer_families(outgoing, assets)}

        def at(frame: int) -> float:
            return (segment.start_frame + frame) / fps

        if k_open >= segment.frame_count:
            return result("HARD_CUT", "abstain:no_incoming_reveal_in_segment", **audit)
        if self._split_families(previous, previous_layout, outgoing, assets):
            return result("HARD_CUT", "pass2_family_cannot_share_one_clock",
                          "pass2_family_cannot_share_one_clock", **audit)
        cohort = [item for item in incoming if first[item.asset_id] == k_open]
        if all(self._has_entry_opacity(cues.get((beat.id, item.asset_id))) for item in cohort):
            # Without a solid opener a completed release would leave a near-white frame.
            return result("HARD_CUT", "opener_not_solid", "opener_not_solid", **audit)
        outgoing_done = max(
            (self._motion_end(cues.get((previous.id, item.asset_id))) for item in outgoing),
            default=0.0,
        )

        # Requested mode: the reference overlap. Safety may only downgrade it.
        overlap_start = k_open - (RELEASE_FRAMES - OVERLAP_FRAMES)
        overlap_zero = k_open + OVERLAP_FRAMES
        if k_next is not None:
            overlap_zero = min(overlap_zero, k_next - 1)  # opacity 0 before any later reveal
        overlap_zero = min(overlap_zero, segment.frame_count)
        blocker = None
        if overlap_start < 0 or overlap_zero - overlap_start < MIN_RELEASE_FRAMES:
            blocker = "overlap_window_insufficient"
        elif outgoing_done > at(overlap_start) + _EPS:
            blocker = "outgoing_action_incomplete"
        elif self._protected_motion_before(beat, incoming, cues, at(overlap_zero)):
            blocker = "protected_motion_conflict"
        else:
            old_boxes = [self.footprints.resolve(item, assets.get(item.asset_id)).box for item in outgoing]
            new_boxes = [self.footprints.resolve(item, assets.get(item.asset_id)).box
                         for item in incoming if first[item.asset_id] < overlap_zero]
            art = sum(1 for old in old_boxes for new in new_boxes if self._intersects(old, new))
            words = sum(
                1 for start, end, box in text_boxes
                if start < at(overlap_zero) - _EPS and end > at(overlap_start) + _EPS
                for old in old_boxes if self._intersects(old, box)
            )
            audit.update(artwork_collisions=art, text_collisions=words)
            if art:
                blocker = "opener_collides_with_outgoing_artwork"
            elif words:
                blocker = "incoming_text_over_outgoing_artwork"
        if blocker is None:
            return result(
                "OVERLAP", "collision_free_overlap",
                opener_at=at(k_open), release_start=at(overlap_start), release_end=at(overlap_zero),
                release_frames=overlap_zero - overlap_start, overlap_frames=overlap_zero - k_open, **audit,
            )

        # Default: the release completes on the opener frame.
        release_frames = min(RELEASE_FRAMES, k_open)
        if release_frames >= MIN_RELEASE_FRAMES and outgoing_done > at(k_open - release_frames) + _EPS:
            release_frames = MIN_RELEASE_FRAMES
        if release_frames < MIN_RELEASE_FRAMES:
            return result("HARD_CUT", "release_window_too_short", blocker, **audit)
        if outgoing_done > at(k_open - release_frames) + _EPS:
            return result("HARD_CUT", "outgoing_action_incomplete", blocker, **audit)
        return result(
            "EXACT_END", "exact_end_release", blocker,
            opener_at=at(k_open), release_start=at(k_open - release_frames), release_end=at(k_open),
            release_frames=release_frames, overlap_frames=0, **audit,
        )

    @staticmethod
    def _active_items(beat: StoryBeat, layout: CompositionBeat | None) -> list[LayoutItem]:
        if layout is None:
            return []
        items = list(layout.items)
        if beat.active_visual_semantic_state is not None:
            active = set(beat.active_visual_semantic_state)
            items = [item for item in items if item.asset_id in active]
        return items

    @staticmethod
    def _visible_start(beat: StoryBeat, cue: MotionCue | None) -> float:
        """First moment Motion shows the asset (proxy segments may precede the cue)."""
        if cue is None:
            return float(beat.start)
        starts = [float(segment.start) for segment in cue.segments if segment.phase != "EXIT"]
        return min([float(cue.start), *starts])

    @staticmethod
    def _motion_end(cue: MotionCue | None) -> float:
        if cue is None:
            return 0.0
        return max([float(cue.end), *(float(segment.end) for segment in cue.segments)])

    @staticmethod
    def _has_entry_opacity(cue: MotionCue | None) -> bool:
        return cue is not None and isinstance(cue.params, dict) and isinstance(
            cue.params.get("entry_opacity"), dict)

    @staticmethod
    def _protected_motion_before(
        beat: StoryBeat,
        incoming: list[LayoutItem],
        cues: dict[tuple[str, str], MotionCue],
        limit: float,
    ) -> bool:
        for item in incoming:
            cue = cues.get((beat.id, item.asset_id))
            for segment in (cue.segments if cue is not None else []):
                protected = (
                    segment.phase in _PROTECTED_PHASES or segment.connection
                    or segment.semantic_action is not None
                )
                if protected and float(segment.start) < limit - _EPS:
                    return True
        return False

    @staticmethod
    def _multi_layer_families(items: list[LayoutItem], assets: dict[str, VisualAsset]) -> int:
        sizes: dict[str, int] = {}
        for item in items:
            asset = assets.get(item.asset_id)
            family = AssetManager.family_id(asset) if asset is not None else item.asset_id
            sizes[family] = sizes.get(family, 0) + 1
        return sum(1 for size in sizes.values() if size > 1)

    @staticmethod
    def _split_families(
        previous: StoryBeat,
        previous_layout: CompositionBeat,
        outgoing: list[LayoutItem],
        assets: dict[str, VisualAsset],
    ) -> bool:
        """True when a visible Pass2 family would not leave as one unit."""
        def family(asset_id: str) -> str:
            asset = assets.get(asset_id)
            return AssetManager.family_id(asset) if asset is not None else asset_id

        visible = {item.asset_id for item in SceneBoundaryPlanner._active_items(previous, previous_layout)}
        leaving = {item.asset_id for item in outgoing}
        leaving_families = {family(asset_id) for asset_id in leaving}
        return any(family(asset_id) in leaving_families for asset_id in visible - leaving)

    @staticmethod
    def _intersects(left: Box, right: Box) -> bool:
        return min(left[2], right[2]) - max(left[0], right[0]) > _EPS and (
            min(left[3], right[3]) - max(left[1], right[1]) > _EPS)

    @staticmethod
    def _text_boxes(
        text: TextPlan | None,
        text_composition: list[TextCompositionBeat] | None,
        text_motion: list[TextMotionCue] | None,
    ) -> dict[str, list[tuple[float, float, Box]]]:
        cues = {cue.id: cue for cue in (text.cues if text is not None else [])}
        ends = {
            row.text_cue_id: float(row.params.get("visible_end", row.end))
            for row in (text_motion or []) if isinstance(row.params, dict)
        }
        output: dict[str, list[tuple[float, float, Box]]] = {}
        for beat in text_composition or []:
            for item in beat.items:
                cue = cues.get(item.text_cue_id)
                if cue is None:
                    continue
                width, height = TextPlacementDirector.estimated_box(cue, scale=item.font_scale)
                box = TextPlacementDirector._box(item.x, item.y, width, height)
                end = max(float(cue.spoken_end), ends.get(cue.id, float(cue.spoken_end)))
                output.setdefault(beat.beat_id, []).append((float(cue.spoken_start), end, box))
        return output
