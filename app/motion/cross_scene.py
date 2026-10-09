"""Cross-scene referent continuity (Roadmap V2 Sprint 7).

Authored identity (``CanonicalAsset.referent_id``) says two objects in ADJACENT scenes are the
same referent. This planner decides, per link, whether a visually safe handoff exists and
adapts only the incoming carrier's Motion cue. It runs after Text and Boundary are planned, so
Story, Choreography, Composition, Text, Text layout and Boundary decisions are untouched, and no
first-visible frame moves.

A handoff keeps the outgoing representation on screen, crisp and still, until the frame on
which the incoming representation first appears (its unchanged Story reveal), then swaps
ownership with no fade, no overlap and no gap. Depending on geometry and timing the incoming
carrier then:

* ``POSITION_AND_SCALE`` / ``POSITION_ONLY``: starts at the outgoing perceived pose and settles
  on its own Composition pose (a continuity ENTRY replacing the fresh-reveal ENTRY), or
* ``NO_GEOMETRY_INHERITANCE``: appears on its own pose (an in-place swap; only when the two
  footprints already read as one object in one place), or
* ``ABSTAIN``: the cue is not touched and the certified boundary runs unchanged.

Identity is never inferred: without ``referent_id`` nothing here runs. Non-adjacent recurrence
is identity only. The renderer receives only runtime asset ids (``handoff_from``), never a
referent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import hypot, isfinite, log, sqrt
from typing import Any

from app.assets import AssetManager
from app.layout.footprint import AlphaFootprintResolver
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    MotionSegment,
    SceneBoundaryRelease,
    StoryBeat,
    TextCompositionBeat,
    TextMotionCue,
    TextPlan,
    VisualAsset,
)
from app.motion.models import MotionKeyframe, MotionProgram
from app.motion.timing import (
    motion_comfort,
    projected_motion_activity_px,
    semantic_readability_floor_px,
)
from app.render.transition import SceneTransitionMode, VisualTransitionPolicy
from app.shared.frame_grid import beat_segments, first_visible_frame

Box = tuple[float, float, float, float]

POSITION_AND_SCALE = "POSITION_AND_SCALE"
POSITION_ONLY = "POSITION_ONLY"
NO_GEOMETRY_INHERITANCE = "NO_GEOMETRY_INHERITANCE"
ABSTAIN = "ABSTAIN"

HANDOFF_PARAM = "handoff_from"
CONTINUITY_PROGRAM = "referent_continuity_settle"
# Speed budget: the certified ENTRY comfort ceiling, with the same 5% planning margin the
# encoded QA tolerance (x1.08) is measured against.
_ENTRY_SPEED = motion_comfort("ENTRY").max_normalized_speed * 0.95
_ENTRY_MINIMUM_SECONDS = motion_comfort("ENTRY").minimum_seconds
# Uniform scale inheritance only between compatible artwork: aspect ratios within 25% and an
# area-equivalent factor within [0.75, 1.33] (the inverse pair), so the start pose is never a
# visibly different object size.
_MAX_ASPECT_CHANGE = log(1.25)
_SCALE_RANGE = (0.75, 1.0 / 0.75)
# An in-place swap must read as one object in one place: the footprints share at least half
# of the smaller one.
_IN_PLACE_OVERLAP = 0.5
_CANVAS_TOLERANCE = 0.005
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class ContinuityDecision:
    referent_id: str
    previous_scene_id: str
    current_scene_id: str
    previous_beat_id: str
    current_beat_id: str
    previous_asset_id: str | None
    current_asset_id: str | None
    decision: str
    reason: str
    identity_authority: str = "REFERENT_ID"
    previous_geometry: dict[str, float] | None = None
    current_geometry: dict[str, float] | None = None
    position_delta: tuple[float, float] | None = None
    scale_delta: float | None = None
    handoff_at: float | None = None
    settle_at: float | None = None
    outgoing_exit_action: str = "UNCHANGED"
    incoming_entry_action: str = "UNCHANGED"
    boundary_interaction: str | None = None
    final_geometry_preserved: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.decision != ABSTAIN

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class CrossSceneContinuityPlanner:
    def __init__(self) -> None:
        self.footprints = AlphaFootprintResolver()
        self.transitions = VisualTransitionPolicy()
        self.decisions: list[ContinuityDecision] = []
        self._baseline: dict[tuple[str, str], MotionCue] = {}

    # -- public ---------------------------------------------------------------------------
    def plan(
        self,
        *,
        package,
        story: list[StoryBeat],
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        assets: list[VisualAsset],
        duration: float,
        fps: int = 30,
        text: TextPlan | None = None,
        text_composition: list[TextCompositionBeat] | None = None,
        text_motion: list[TextMotionCue] | None = None,
        scene_boundaries: list[SceneBoundaryRelease] | None = None,
        frame_width: int,
        frame_height: int,
    ) -> list[MotionCue]:
        self.decisions = []
        self._baseline = {}
        carriers = self._authored_carriers(package)
        if not carriers:
            return motion  # no authored identity: Sprint 7 behaviour cannot exist
        from app.boundary.release import SceneBoundaryPlanner  # boundary owns text boxes

        scene_order = {scene.id: int(scene.order) for scene in package.scenes}
        layouts = {layout.beat_id: layout for layout in composition}
        cues = {(cue.beat_id, cue.asset_id): cue for cue in motion}
        asset_by_id = {asset.id: asset for asset in assets}
        text_boxes = SceneBoundaryPlanner._text_boxes(text, text_composition, text_motion)
        boundaries = {row.beat_id: row for row in scene_boundaries or []}
        replacements: dict[tuple[str, str], MotionCue] = {}

        for segment in beat_segments(story, duration=duration, fps=fps):
            previous, beat = segment.previous_beat, segment.beat
            if previous is None or previous.scene_id == beat.scene_id:
                continue
            if scene_order.get(beat.scene_id, -2) - scene_order.get(previous.scene_id, -9) != 1:
                continue  # non-adjacent recurrence stays identity metadata only
            before = carriers.get(previous.scene_id, {})
            after = carriers.get(beat.scene_id, {})
            decisions = [
                self._decide(
                    referent_id=referent_id, previous=previous, beat=beat, segment=segment,
                    previous_unit=before[referent_id], current_unit=after[referent_id],
                    layouts=layouts, cues=cues, assets=asset_by_id,
                    text_boxes=text_boxes.get(beat.id, []), boundary=boundaries.get(beat.id),
                    fps=fps, frame_width=frame_width, frame_height=frame_height,
                )
                for referent_id in sorted(set(before) & set(after))
            ]
            for decision in self._bound_boundary_energy(decisions):
                self.decisions.append(decision)
                if decision.accepted:
                    key = (decision.current_beat_id, decision.current_asset_id)
                    self._baseline.setdefault(key, cues[key])
                    replacements[key] = cues[key] = self._adapt_cue(cues[key], decision)
        return [replacements.get((cue.beat_id, cue.asset_id), cue) for cue in motion]

    def revoke(self, motion: list[MotionCue], beat_ids: set[str], reason: str) -> list[MotionCue]:
        """Return ``motion`` with every accepted link INTO ``beat_ids`` restored to baseline.

        Used by the pipeline transaction when re-authoring Text or Boundary against the
        candidate Motion would change them: those links abstain and keep the certified cue.
        """
        restored: set[tuple[str, str]] = set()
        decisions = []
        for decision in self.decisions:
            if decision.accepted and decision.current_beat_id in beat_ids:
                restored.add((decision.current_beat_id, decision.current_asset_id))
                decision = ContinuityDecision(**{
                    **asdict(decision), "decision": ABSTAIN, "reason": reason, "settle_at": None,
                    "outgoing_exit_action": "UNCHANGED", "incoming_entry_action": "UNCHANGED",
                    "evidence": {**decision.evidence, "revoked_decision": decision.decision,
                                 "revoked_reason": decision.reason},
                })
            decisions.append(decision)
        self.decisions = decisions
        return [self._baseline[(cue.beat_id, cue.asset_id)] if (cue.beat_id, cue.asset_id) in restored else cue
                for cue in motion]

    # -- identity -------------------------------------------------------------------------
    @staticmethod
    def _authored_carriers(package) -> dict[str, dict[str, str]]:
        """scene_id -> referent_id -> package asset_id of the root carrier (authored only)."""
        output: dict[str, dict[str, str]] = {}
        for scene in package.scenes:
            by_referent: dict[str, list] = {}
            for unit in scene.units:
                if unit.referent_id is not None:
                    by_referent.setdefault(unit.referent_id, []).append(unit)
            for referent_id, units in sorted(by_referent.items()):
                ids = {unit.asset_id for unit in units}
                roots = sorted(unit.asset_id for unit in units if unit.parent_asset_id not in ids)
                if len(roots) == 1:  # the loader guarantees this; never guess otherwise
                    output.setdefault(scene.id, {})[referent_id] = roots[0]
        return output

    @staticmethod
    def _runtime_carrier(beat: StoryBeat, package_asset_id: str) -> list[str]:
        return sorted({
            row.asset_id for row in beat.asset_activations
            if row.semantic_unit_id == package_asset_id
            and str(row.policy or "").upper() != "SAFE_ABSTENTION"
        })

    # -- decision -------------------------------------------------------------------------
    def _decide(
        self, *, referent_id: str, previous: StoryBeat, beat: StoryBeat, segment,
        previous_unit: str, current_unit: str, layouts: dict[str, CompositionBeat],
        cues: dict[tuple[str, str], MotionCue], assets: dict[str, VisualAsset],
        text_boxes: list[tuple[float, float, Box]], boundary: SceneBoundaryRelease | None,
        fps: int, frame_width: int, frame_height: int,
    ) -> ContinuityDecision:
        prev_ids = self._runtime_carrier(previous, previous_unit)
        cur_ids = self._runtime_carrier(beat, current_unit)
        base = dict(referent_id=referent_id, previous_scene_id=previous.scene_id,
                    current_scene_id=beat.scene_id, previous_beat_id=previous.id,
                    current_beat_id=beat.id,
                    previous_asset_id=prev_ids[0] if len(prev_ids) == 1 else None,
                    current_asset_id=cur_ids[0] if len(cur_ids) == 1 else None,
                    boundary_interaction=boundary.mode if boundary is not None else None)

        def abstain(reason: str, **evidence) -> ContinuityDecision:
            return ContinuityDecision(decision=ABSTAIN, reason=reason, evidence=evidence, **base)

        if len(prev_ids) != 1 or len(cur_ids) != 1:
            return abstain("unsafe_geometry:runtime_carrier_not_single",
                           previous_runtime=prev_ids, current_runtime=cur_ids)
        prev_id, cur_id = prev_ids[0], cur_ids[0]
        prev_layout, layout = layouts.get(previous.id), layouts.get(beat.id)
        prev_item = self._item(prev_layout, prev_id, previous)
        cur_item = self._item(layout, cur_id, beat)
        if prev_item is None or cur_item is None:
            return abstain("unsafe_geometry:carrier_not_on_screen")
        if self._family_size(prev_layout, prev_id, assets) > 1 or self._family_size(layout, cur_id, assets) > 1:
            return abstain("unsafe_geometry:multi_layer_family_carrier")

        legacy = self.transitions.decide(previous, prev_layout, layout, current_beat=beat)
        if legacy.mode != SceneTransitionMode.MOTION_HANDOFF or legacy.persistent_asset_ids:
            return abstain(f"timing:boundary_owned_by_{legacy.reason}")

        prev_cue, cue = cues.get((previous.id, prev_id)), cues.get((beat.id, cur_id))
        if cue is None:
            return abstain("timing:incoming_cue_missing")
        segment_start = segment.start_frame / fps
        outgoing_end = segment_start  # the previous segment's last frame ends here
        if prev_cue is not None:
            if any(row.phase == "EXIT" for row in prev_cue.segments):
                return abstain("timing:outgoing_has_terminal_exit")
            if self._motion_end(prev_cue) > outgoing_end - 1.0 / fps + _EPS:
                return abstain("timing:outgoing_not_settled_before_boundary")
        if any(row.phase == "EXIT" for row in cue.segments):
            return abstain("timing:incoming_has_exit")
        handoff = self._visible_start(beat, cue)
        handoff_frame = first_visible_frame(handoff - segment_start, fps)
        if handoff_frame >= segment.frame_count:
            return abstain("timing:incoming_not_visible_in_segment")
        handoff_at = (segment.start_frame + handoff_frame) / fps

        old = self.footprints.resolve(prev_item, assets.get(prev_id)).box
        new = self.footprints.resolve(cur_item, assets.get(cur_id)).box
        geometry = dict(previous_geometry=self._geometry(prev_item, old),
                        current_geometry=self._geometry(cur_item, new))

        # The outgoing representation lingers (still, opaque) until the handoff frame. It
        # must not sit on any incoming artwork or text that appears before that frame.
        others = [item for item in self._active(beat, layout) if item.asset_id != cur_id]
        for item in others:
            appear = first_visible_frame(self._visible_start(beat, cues.get((beat.id, item.asset_id))) - segment_start, fps)
            if appear < handoff_frame and self._intersects(old, self.footprints.resolve(item, assets.get(item.asset_id)).box):
                return abstain("visual_quality:lingering_carrier_covers_incoming_artwork",
                               blocker=item.asset_id, **geometry)
        for start, _end, box in text_boxes:
            if first_visible_frame(start - segment_start, fps) < handoff_frame and self._intersects(old, box):
                return abstain("visual_quality:lingering_carrier_covers_incoming_text", **geometry)

        old_area, new_area = self._area(old), self._area(new)
        overlap = self._intersection(old, new) / max(_EPS, min(old_area, new_area))
        scale = sqrt(old_area / new_area) if new_area > _EPS else 1.0
        aspect_change = abs(log(max(_EPS, self._aspect(old)) / max(_EPS, self._aspect(new))))
        inherit_scale = (_SCALE_RANGE[0] <= scale <= _SCALE_RANGE[1] and aspect_change <= _MAX_ASPECT_CHANGE
                         and abs(scale - 1.0) > 0.02)
        start_scale = scale if inherit_scale else 1.0
        # The renderer scales the Composition box about its centre, so solve the box offset
        # that puts the scaled incoming footprint centre on the outgoing footprint centre.
        old_c, new_c = self._centre(old), self._centre(new)
        box_c = (float(cur_item.x), float(cur_item.y))
        dx = old_c[0] - box_c[0] - start_scale * (new_c[0] - box_c[0])
        dy = old_c[1] - box_c[1] - start_scale * (new_c[1] - box_c[1])
        evidence = dict(footprint_overlap=round(overlap, 4), area_scale=round(scale, 4),
                        aspect_change=round(aspect_change, 4), handoff_frame=handoff_frame, **geometry)
        common = dict(handoff_at=handoff_at, position_delta=(dx, dy), **geometry, **base)

        activity_px = projected_motion_activity_px(
            dx=dx, dy=dy, scale=start_scale, item_width=cur_item.width, item_height=cur_item.height,
            frame_width=frame_width, frame_height=frame_height,
        )
        in_place = overlap >= _IN_PLACE_OVERLAP

        # Travel window: from the handoff frame until the cue's first semantic accent (or
        # the end of the segment). A continuing referent may not spend its scene travelling.
        # An accent already running at the handoff frame owns the pose from that frame on
        # (the renderer gives non-ENTRY segments priority inside their window): no travel.
        accents = [max(float(row.start), handoff_at) for row in cue.segments
                   if row.phase not in {"ENTRY", "EXIT"} and float(row.end) > handoff_at + _EPS]
        deadline = min([*accents, (segment.start_frame + segment.frame_count) / fps])
        travel = max(hypot(dx, dy), abs(start_scale - 1.0) * min(cur_item.width, cur_item.height))
        needed = max(_ENTRY_MINIMUM_SECONDS, travel / _ENTRY_SPEED)
        floor_px = semantic_readability_floor_px(
            "ENTRY", item_width=cur_item.width, item_height=cur_item.height, duration=needed,
            frame_width=frame_width, frame_height=frame_height)
        position_reason = None
        if activity_px + _EPS < floor_px:
            position_reason = "geometry:already_continuous_below_perceptual_floor"
        elif handoff_at + needed > deadline + _EPS:
            position_reason = "timing:no_settle_window_before_semantic_accent"
        elif not self._inside_canvas(self._moved(new, box_c, dx, dy, start_scale)):
            position_reason = "unsafe_geometry:inherited_pose_outside_canvas"
        else:
            settle = handoff_at + needed
            path_conflict = self._path_conflict(new, box_c, dx, dy, start_scale, others, beat, cues, assets,
                                                text_boxes, handoff_at, settle)
            if path_conflict is not None:
                position_reason = f"visual_quality:{path_conflict}"
            else:
                return ContinuityDecision(
                    decision=POSITION_AND_SCALE if inherit_scale else POSITION_ONLY,
                    reason="inherited_pose_settles_before_semantic_accent",
                    scale_delta=start_scale - 1.0, settle_at=settle,
                    outgoing_exit_action="HOLD_UNTIL_HANDOFF_FRAME",
                    incoming_entry_action="CONTINUITY_SETTLE_FROM_INHERITED_POSE",
                    evidence={**evidence, "travel": round(travel, 5), "travel_seconds": round(needed, 4),
                              "deadline": deadline, "activity_px": round(activity_px, 2), "floor_px": round(floor_px, 2)},
                    **common,
                )
        if in_place:
            return ContinuityDecision(
                decision=NO_GEOMETRY_INHERITANCE,
                reason=f"in_place_swap ({position_reason})",
                scale_delta=0.0, outgoing_exit_action="HOLD_UNTIL_HANDOFF_FRAME",
                incoming_entry_action="OPAQUE_SWAP_ON_AUTHORED_POSE",
                evidence={**evidence, "position_rejected": position_reason}, **common,
            )
        prefix = position_reason.split(":", 1)[0] if position_reason else "unsafe_geometry"
        reason = position_reason if prefix != "geometry" else "unsafe_geometry:not_in_place"
        return ContinuityDecision(decision=ABSTAIN, reason=f"{reason};footprints_not_in_place",
                                  evidence=evidence, **{k: v for k, v in common.items() if k not in {"handoff_at", "position_delta"}})

    @staticmethod
    def _bound_boundary_energy(decisions: list[ContinuityDecision]) -> list[ContinuityDecision]:
        """At most one travelling continuity per boundary: the largest carrier keeps it."""
        moving = [d for d in decisions if d.decision in {POSITION_AND_SCALE, POSITION_ONLY}]
        if len(moving) <= 1:
            return decisions
        keep = max(moving, key=lambda d: (CrossSceneContinuityPlanner._geometry_area(d), d.referent_id))
        output = []
        for decision in decisions:
            if decision in moving and decision is not keep:
                if decision.evidence.get("footprint_overlap", 0.0) >= _IN_PLACE_OVERLAP:
                    decision = ContinuityDecision(**{**asdict(decision), "decision": NO_GEOMETRY_INHERITANCE,
                                                     "reason": "in_place_swap (boundary_motion_budget)",
                                                     "scale_delta": 0.0, "settle_at": None,
                                                     "incoming_entry_action": "OPAQUE_SWAP_ON_AUTHORED_POSE"})
                else:
                    decision = ContinuityDecision(**{**asdict(decision), "decision": ABSTAIN,
                                                     "reason": "visual_quality:boundary_motion_budget",
                                                     "outgoing_exit_action": "UNCHANGED",
                                                     "incoming_entry_action": "UNCHANGED", "settle_at": None})
            output.append(decision)
        return output

    @staticmethod
    def _geometry_area(decision: ContinuityDecision) -> float:
        geometry = decision.current_geometry or {}
        return float(geometry.get("footprint_width", 0.0)) * float(geometry.get("footprint_height", 0.0))

    # -- cue adaptation -------------------------------------------------------------------
    @staticmethod
    def _adapt_cue(cue: MotionCue, decision: ContinuityDecision) -> MotionCue:
        params = {key: value for key, value in cue.params.items() if key != "entry_opacity"}
        params[HANDOFF_PARAM] = {"beat_id": decision.previous_beat_id, "asset_id": decision.previous_asset_id}
        segments = list(cue.segments)
        end = float(cue.end)
        if decision.decision in {POSITION_AND_SCALE, POSITION_ONLY}:
            dx, dy = decision.position_delta
            program = MotionProgram(
                name=CONTINUITY_PROGRAM,
                keyframes=(
                    MotionKeyframe(progress=0.0, dx=dx, dy=dy, scale=1.0 + float(decision.scale_delta or 0.0),
                                   easing="ease_in_out_cubic"),
                    MotionKeyframe(progress=1.0),
                ),
            ).to_payload()
            program["continuity"] = "REFERENT_HANDOFF"
            entry = MotionSegment(phase="ENTRY", start=float(decision.handoff_at), end=float(decision.settle_at),
                                  program=program, semantic_action="CONTINUE")
            segments = [entry, *(row for row in segments if row.phase != "ENTRY")]
            end = max(end, float(decision.settle_at))
        return cue.model_copy(update={"params": params, "segments": segments, "end": end})

    # -- geometry helpers -----------------------------------------------------------------
    @staticmethod
    def _item(layout: CompositionBeat | None, asset_id: str, beat: StoryBeat) -> LayoutItem | None:
        if layout is None:
            return None
        if beat.active_visual_semantic_state is not None and asset_id not in beat.active_visual_semantic_state:
            return None
        return next((item for item in layout.items if item.asset_id == asset_id), None)

    @staticmethod
    def _active(beat: StoryBeat, layout: CompositionBeat | None) -> list[LayoutItem]:
        if layout is None:
            return []
        items = sorted(layout.items, key=lambda item: (item.z, item.asset_id))
        if beat.active_visual_semantic_state is not None:
            items = [item for item in items if item.asset_id in beat.active_visual_semantic_state]
        return items

    @staticmethod
    def _family_size(layout: CompositionBeat | None, asset_id: str, assets: dict[str, VisualAsset]) -> int:
        if layout is None or asset_id not in assets:
            return 0
        family = AssetManager.family_id(assets[asset_id])
        return sum(1 for item in layout.items
                   if item.asset_id in assets and AssetManager.family_id(assets[item.asset_id]) == family)

    @staticmethod
    def _visible_start(beat: StoryBeat, cue: MotionCue | None) -> float:
        if cue is None:
            return float(beat.start)
        return min([float(cue.start), *(float(row.start) for row in cue.segments if row.phase != "EXIT")])

    @staticmethod
    def _motion_end(cue: MotionCue) -> float:
        return max([float(cue.end), *(float(row.end) for row in cue.segments)])

    @staticmethod
    def _centre(box: Box) -> tuple[float, float]:
        return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0

    @staticmethod
    def _area(box: Box) -> float:
        return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])

    @staticmethod
    def _aspect(box: Box) -> float:
        return max(_EPS, box[2] - box[0]) / max(_EPS, box[3] - box[1])

    @staticmethod
    def _intersection(left: Box, right: Box) -> float:
        width = min(left[2], right[2]) - max(left[0], right[0])
        height = min(left[3], right[3]) - max(left[1], right[1])
        return max(0.0, width) * max(0.0, height)

    @classmethod
    def _intersects(cls, left: Box, right: Box) -> bool:
        return cls._intersection(left, right) > _EPS

    @staticmethod
    def _moved(box: Box, pivot: tuple[float, float], dx: float, dy: float, scale: float) -> Box:
        """Footprint when the Composition box (centre ``pivot``) is offset and scaled."""
        px, py = pivot
        return (px + dx + scale * (box[0] - px), py + dy + scale * (box[1] - py),
                px + dx + scale * (box[2] - px), py + dy + scale * (box[3] - py))

    @staticmethod
    def _inside_canvas(box: Box) -> bool:
        return (box[0] >= -_CANVAS_TOLERANCE and box[1] >= -_CANVAS_TOLERANCE
                and box[2] <= 1.0 + _CANVAS_TOLERANCE and box[3] <= 1.0 + _CANVAS_TOLERANCE)

    def _path_conflict(self, new: Box, pivot: tuple[float, float], dx: float, dy: float, scale: float,
                       others: list[LayoutItem],
                       beat: StoryBeat, cues, assets, text_boxes, start: float, settle: float) -> str | None:
        """The travelling carrier may only cross what its final pose already overlaps."""
        samples = (0.0, 0.25, 0.5, 0.75)
        for item in others:
            appear = self._visible_start(beat, cues.get((beat.id, item.asset_id)))
            box = self.footprints.resolve(item, assets.get(item.asset_id)).box
            if self._intersects(new, box):
                continue  # authored by Composition at the final pose
            for p in samples:
                t = start + (settle - start) * p
                remain = 1.0 - p  # linear bound of the eased path
                if appear <= t + _EPS and self._intersects(self._moved(new, pivot, dx * remain, dy * remain,
                                                                       1.0 + (scale - 1.0) * remain), box):
                    return "travel_crosses_incoming_artwork"
        for text_start, text_end, box in text_boxes:
            if self._intersects(new, box):
                continue
            for p in samples:
                t = start + (settle - start) * p
                remain = 1.0 - p
                if text_start <= t + _EPS and text_end >= t - _EPS and self._intersects(
                        self._moved(new, pivot, dx * remain, dy * remain, 1.0 + (scale - 1.0) * remain), box):
                    return "travel_crosses_text"
        return None

    @staticmethod
    def _geometry(item: LayoutItem, footprint: Box) -> dict[str, float]:
        values = {
            "x": item.x, "y": item.y, "width": item.width, "height": item.height,
            "footprint_x0": footprint[0], "footprint_y0": footprint[1],
            "footprint_x1": footprint[2], "footprint_y1": footprint[3],
            "footprint_width": footprint[2] - footprint[0], "footprint_height": footprint[3] - footprint[1],
        }
        if not all(isfinite(float(value)) for value in values.values()):
            raise ValueError("non-finite continuity geometry")
        return {key: round(float(value), 6) for key, value in values.items()}
