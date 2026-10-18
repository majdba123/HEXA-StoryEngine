from __future__ import annotations

from math import ceil, isfinite

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
from app.motion.hero_travel import HERO_TRAVEL, SMOOTHSTEP_PEAK
from app.motion.motion_blur import MAX_LENGTH, MIN_LENGTH, MOTION_BLUR_SHUTTER
from app.render.transition import SceneTransitionMode, VisualTransitionPolicy
from app.shared.frame_grid import BeatSegment, beat_segments, first_visible_frame

# Sprint 4.5: reference-derived scene release. Measured reference boundaries fade the
# outgoing scene over 5-7 frames (median 6); where old and new share the screen they do so
# for a median of 4 frames. Nothing shorter than 5 frames is a release: it is a cut.
RELEASE_FRAMES = 6
MIN_RELEASE_FRAMES = 5
OVERLAP_FRAMES = 4
_OFFSCREEN_MARGIN = 0.01
# An opener cohort covers the frame on its own (no near-white frame after a clean cut) only
# when one of its cutouts is drawn at full opacity from its first frame and its footprint
# covers at least this share of the frame.
_SOLID_OPENER_AREA = 0.02
# An exiting unit may pass its neighbours only within their authored overlap plus this slack.
_EXIT_OVERLAP_SLACK = 0.02
_EPS = 1e-6
# A planned exit travels like any other motion: it smears along its path with the same
# exposure Motion uses for the elements it moves (visual sprint B3).
EXIT_MOTION_BLUR = {"owner": "BOUNDARY", "shutter": MOTION_BLUR_SHUTTER,
                    "min_length": MIN_LENGTH, "max_length": MAX_LENGTH}
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
    text and timing may downgrade it: OVERLAP -> EXACT_END -> HARD_CUT. An eligible
    exact-end release may instead hold an already completed, proven semantic state
    until the unchanged opener when Motion's existing rhythm requires that interval.
    A collision is a safety fact, never evidence that two scenes are related.
    """

    def __init__(self, *, horizontal_padding: float = 0.0, vertical_padding: float = 0.0) -> None:
        self.classifier = VisualTransitionPolicy()
        self.footprints = AlphaFootprintResolver()
        # Both margins are needed: a 16:9 frame projected on Reels can have large
        # TOP/BOTTOM letterbox regions, not just side padding.
        self.exit_margin = _OFFSCREEN_MARGIN + max(0.0, float(horizontal_padding))
        self.vertical_exit_margin = _OFFSCREEN_MARGIN + max(0.0, float(vertical_padding))

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
            row = self._plan_one(
                segment, layouts=layouts, cues=cues, assets=assets_by_id,
                text_boxes=text_boxes.get(segment.beat.id, []), fps=fps,
            )
            output.append(self._hero_overlap_exit(
                row, segment, layouts=layouts, cues=cues, assets=assets_by_id,
                text_boxes=text_boxes.get(segment.beat.id, []), fps=fps,
            ))
        return output

    def _hero_overlap_exit(
        self,
        row: SceneBoundaryRelease,
        segment: BeatSegment,
        *,
        layouts: dict[str, CompositionBeat],
        cues: dict[tuple[str, str], MotionCue],
        assets: dict[str, VisualAsset],
        text_boxes: list[tuple[float, float, Box]],
        fps: int,
    ) -> SceneBoundaryRelease:
        """VP4 full-frame exit of the outgoing scene's hero, inside the incoming segment.

        Authorized contract (2026-10-14): only the hero Motion marked for the outgoing
        scene, only on a planned crisp change (HARD_CUT / CRISP_HANDOFF / HOLD_TO_OPENER),
        never a referent that continues, never a split Pass2 family. It stays still until
        the unchanged incoming opener, then leaves along a smoothstep path with the
        HERO_TRAVEL speed cap until it is outside the frame on every projection; the
        incoming scene's timing, read holds and narration are unchanged. Any incoming
        artwork or text on the path, or any incoming reveal after the opener while it is
        still leaving (competing motion), makes it a clean cut instead.
        """
        beat, previous = segment.beat, segment.previous_beat
        assert previous is not None
        hero = next((cue for (beat_id, _), cue in cues.items()
                     if beat_id == previous.id and cue.params.get("scene_hero")), None)
        if hero is None:
            return row

        def decided(decision: str, **update) -> SceneBoundaryRelease:
            return row.model_copy(update={**update, "audit": {**row.audit, "hero_exit": decision}})

        if row.mode not in {"HARD_CUT", "CRISP_HANDOFF", "HOLD_TO_OPENER"} or row.reason.startswith("abstain:"):
            return decided(f"clean_cut:boundary_{row.mode.lower()}:{row.reason}")
        wash = next((cue.params["focus_wash"] for (beat_id, _), cue in cues.items()
                     if beat_id == previous.id and isinstance(cue.params.get("focus_wash"), dict)), None)
        if wash is not None and hero.asset_id not in (wash.get("focus_asset_ids") or []):
            # It receded behind the scene's resolution: it leaves with the cut, never crisp again.
            return decided("clean_cut:hero_receded_behind_resolution")
        layout, previous_layout = layouts.get(beat.id), layouts.get(previous.id)
        item = next((row_item for row_item in (previous_layout.items if previous_layout else [])
                     if row_item.asset_id == hero.asset_id), None)
        incoming = self._active_items(beat, layout)
        if item is None or not incoming:
            return decided("clean_cut:no_outgoing_hero_or_incoming_artwork")
        legacy = self.classifier.decide(previous, previous_layout, layout, current_beat=beat)
        if hero.asset_id not in legacy.carry_outgoing_asset_ids or hero.asset_id in legacy.persistent_asset_ids:
            return decided("clean_cut:hero_not_an_outgoing_carry")
        if any(isinstance(spec := cue.params.get("handoff_from"), dict) and spec.get("asset_id") == hero.asset_id
               for (beat_id, _), cue in cues.items() if beat_id == beat.id):
            return decided("clean_cut:referent_continues")
        def family_of(asset_id: str) -> str:
            row_asset = assets.get(asset_id)
            return AssetManager.family_id(row_asset) if row_asset is not None else asset_id

        # A Pass2 family leaves rigidly as one unit: every layer, one path, one clock.
        members = [row_item for row_item in previous_layout.items
                   if family_of(row_item.asset_id) == family_of(hero.asset_id)]
        if any(member.asset_id not in legacy.carry_outgoing_asset_ids for member in members):
            return decided("clean_cut:family_layer_not_an_outgoing_carry")
        unit = (min(float(m.x) - float(m.width) / 2 for m in members),
                min(float(m.y) - float(m.height) / 2 for m in members),
                max(float(m.x) + float(m.width) / 2 for m in members),
                max(float(m.y) + float(m.height) / 2 for m in members))
        start_time = segment.start_frame / fps
        first = {it.asset_id: first_visible_frame(self._visible_start(beat, cues.get((beat.id, it.asset_id)))
                                                   - start_time, fps) for it in incoming}
        footprints = {it.asset_id: self.footprints.resolve(it, assets.get(it.asset_id)).box for it in incoming}
        # Outgoing artwork that may stay on screen in the new segment - an authored referent
        # carrier (Sprint 7 can hold it until its successor) or persistent artwork - is an
        # obstacle for the whole exit; the hero never slides behind or over it.
        held = [
            self.footprints.resolve(row_item, assets.get(row_item.asset_id)).box
            for row_item in previous_layout.items
            if family_of(row_item.asset_id) != family_of(hero.asset_id) and (
                row_item.asset_id in legacy.persistent_asset_ids
                or (cues.get((previous.id, row_item.asset_id)) is not None
                    and cues[(previous.id, row_item.asset_id)].params.get("referent_carrier")))
        ]
        opener = int(row.audit.get("opener_frame", min(first.values())))
        start = (segment.start_frame + opener) / fps
        solid_opener = any(
            frame == opener and not self._has_entry_opacity(cues.get((beat.id, key)))
            and _area(footprints[key]) >= _SOLID_OPENER_AREA
            for key, frame in first.items())
        reasons = []
        left = unit[2] + self.exit_margin
        right = 1.0 - unit[0] + self.exit_margin
        top = unit[3] + self.vertical_exit_margin
        bottom = 1.0 - unit[1] + self.vertical_exit_margin
        # Four directions; prefer the shortest safe exit while preserving timing.
        directions = ((0.0, -1.0, top), (0.0, 1.0, bottom),
                      (-1.0, 0.0, left), (1.0, 0.0, right))
        for dx_sign, dy_sign, distance in sorted(directions, key=lambda row: (row[2], abs(row[1]))):
            seconds = max(HERO_TRAVEL.minimum_seconds,
                          SMOOTHSTEP_PEAK * distance / HERO_TRAVEL.max_normalized_speed)
            frames = ceil(seconds * fps - _EPS)
            end_frame = opener + frames
            if end_frame >= segment.frame_count:
                reasons.append("incoming_scene_too_short")
                continue
            end = (segment.start_frame + end_frame) / fps
            blocker = None
            if solid_opener and any(opener < frame < end_frame for frame in first.values()):
                # One leaving hero beside the arriving opener reads as a handoff; further
                # incoming arrivals during the exit would make the opening busy and rushed.
                # A faint or tiny opener needs the leaving hero as cover (else near-white).
                reasons.append("incoming_arrivals_during_exit")
                continue
            for frame in range(opener, end_frame + 1):
                progress = (frame - opener) / frames
                shift = distance * (3 * progress ** 2 - 2 * progress ** 3)
                moved = (unit[0] + dx_sign * shift, unit[1] + dy_sign * shift,
                         unit[2] + dx_sign * shift, unit[3] + dy_sign * shift)
                if any(first[key] <= frame and self._intersects(moved, footprint)
                       for key, footprint in footprints.items()):
                    blocker = "path_crosses_incoming_artwork"
                    break
                if any(self._intersects(moved, footprint) for footprint in held):
                    blocker = "path_crosses_held_outgoing_artwork"
                    break
                now = (segment.start_frame + frame) / fps
                if any(t0 <= now + _EPS and t1 > now and self._intersects(moved, box)
                       for t0, t1, box in text_boxes):
                    blocker = "path_crosses_incoming_text"
                    break
            if blocker is not None:
                reasons.append(blocker)
                continue
            leaving = {member.asset_id for member in members}
            exits = {key: value for key, value in row.exit_starts.items() if key not in leaving}
            spec = {"start": round(start, 6), "end": round(end, 6),
                    "direction": dx_sign if dx_sign else dy_sign,
                    "axis": 1.0 if dy_sign else 0.0}
            return decided("full_frame_exit", exit_starts=exits,
                           overlap_exits={member.asset_id: dict(spec) for member in members},
                           exit_motion_blur=dict(EXIT_MOTION_BLUR))
        return decided("clean_cut:" + ",".join(reasons))

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
                exit_starts=(exit_starts := audit.pop("exit_starts", None) or {}),
                exit_motion_blur=dict(EXIT_MOTION_BLUR) if exit_starts else {},
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
        hold = self._hold_to_opener(
            previous=previous, outgoing=outgoing, cues=cues, text_boxes=text_boxes,
            incoming=incoming, beat=beat, opener_frame=k_open,
            release_start_frame=k_open - release_frames, segment=segment, fps=fps,
        )
        if hold is not None:
            return result(
                "HOLD_TO_OPENER", "protected_completed_state", blocker,
                opener_at=at(k_open), release_start=at(k_open), release_end=at(k_open),
                **audit, **hold,
            )
        # An ordinary completed scene with explicit Story visibility can retain
        # ownership until the legal opener. Text and protected incoming action
        # that precede the opener keep the certified exact-end release instead.
        if (
            previous.active_visual_semantic_state is not None
            and not self._protected_motion_visible_before(
                beat=beat, incoming=incoming, cues=cues,
                segment_start=start_time, opener_frame=k_open, fps=fps,
            )
            and not any(first_visible_frame(start - start_time, fps) < k_open
                        for start, _end, _box in text_boxes)
        ):
            exits = self._exit_schedule(
                previous=previous, outgoing=outgoing, cues=cues, assets=assets,
                outgoing_done=outgoing_done, segment=segment, opener_frame=k_open, fps=fps,
                margin=self.exit_margin,
                boxes={item.asset_id: self.footprints.resolve(item, assets.get(item.asset_id)).box
                       for item in outgoing},
            )
            audit["exit"] = exits.pop("audit")
            return result(
                "CRISP_HANDOFF", "ordinary_scene_owner_until_opener", blocker,
                opener_at=at(k_open), release_start=at(k_open), release_end=at(k_open),
                exit_starts=exits["starts"], **audit,
            )
        return result(
            "EXACT_END", "exact_end_release", blocker,
            opener_at=at(k_open), release_start=at(k_open - release_frames), release_end=at(k_open),
            release_frames=release_frames, overlap_frames=0, **audit,
        )

    @classmethod
    def _exit_schedule(
        cls, *, previous: StoryBeat, outgoing: list[LayoutItem],
        cues: dict[tuple[str, str], MotionCue], assets: dict[str, VisualAsset],
        outgoing_done: float, segment: BeatSegment, opener_frame: int, fps: int,
        margin: float = _OFFSCREEN_MARGIN, boxes: dict[str, Box] | None = None,
    ) -> dict[str, object]:
        """Complete outgoing exits inside the pre-opener interval, or none (clean cut).

        An exit may only use time the outgoing scene no longer needs: it starts after the
        last outgoing motion has settled plus Motion's own minimum read hold, and ends on
        the unchanged opener frame. The last unit in order (the semantic result) always
        stays as cover until the opener. An exit is planned only when it can finish: the unit (a
        Pass2 family leaves as one) slides out through its nearest side edge until it is
        off the frame on every projection (``margin``), along a smoothstep path within the
        HERO_TRAVEL speed cap and minimum duration. A unit that cannot leave in the
        available time stays still and leaves with the opener (a clean cut), so nothing
        vanishes halfway through an exit. Every unit leaves on its own: an exit whose path
        would run over another outgoing unit (still or leaving, beyond their authored
        overlap; ``boxes`` are the alpha footprints) is not planned, so no unit ever drags
        another along. Without Motion's rhythm authority it abstains.
        """
        min_frames = ceil(HERO_TRAVEL.minimum_seconds * fps - _EPS)
        holds = []
        for item in outgoing:
            cue = cues.get((previous.id, item.asset_id))
            focus = cue.params.get("semantic_focus") if cue and isinstance(cue.params, dict) else None
            rhythm = focus.get("rhythm") if isinstance(focus, dict) else None
            hold_ms = rhythm.get("minimum_read_hold_ms") if isinstance(rhythm, dict) else None
            if type(hold_ms) in (int, float) and isfinite(hold_ms) and hold_ms > 0:
                holds.append(float(hold_ms) / 1000)
        if not holds:
            return {"starts": {}, "audit": {"decision": "abstain:no_motion_read_hold_authority"}}
        ready_frame = max(0, ceil((outgoing_done + max(holds)) * fps - _EPS) - segment.start_frame)
        window = opener_frame - ready_frame
        if window < min_frames:
            return {"starts": {}, "audit": {"decision": "clean_cut:insufficient_time_after_read_hold",
                                            "ready_frame": ready_frame, "window_frames": window}}

        def rank(item: LayoutItem) -> int:
            cue = cues.get((previous.id, item.asset_id))
            focus = cue.params.get("semantic_focus") if cue and isinstance(cue.params, dict) else None
            focus = focus if isinstance(focus, dict) else {}
            roles = {str(focus.get(key) or "").upper() for key in ("visual_focus", "role", "semantic_role")}
            if roles & {"RESULT"}:
                return 2
            if roles & {"SUPPORT", "CONTEXT", "ACTION"} and not roles & {"PRIMARY", "SUBJECT"}:
                return 0
            return 1

        families: dict[str, list[LayoutItem]] = {}
        for item in outgoing:
            asset = assets.get(item.asset_id)
            families.setdefault(AssetManager.family_id(asset) if asset else item.asset_id, []).append(item)
        groups = sorted(families.values(), key=lambda members: (
            min(rank(m) for m in members), min(m.z for m in members), min(m.asset_id for m in members)))
        boxes = boxes or {}

        def rest_box(members: list[LayoutItem]) -> Box:
            rows = [boxes.get(m.asset_id) or (float(m.x) - float(m.width) / 2, float(m.y) - float(m.height) / 2,
                                              float(m.x) + float(m.width) / 2, float(m.y) + float(m.height) / 2)
                    for m in members]
            return (min(r[0] for r in rows), min(r[1] for r in rows), max(r[2] for r in rows), max(r[3] for r in rows))

        units = []
        for index, members in enumerate(groups):
            frames, shift = cls._complete_exit_path(members, fps=fps, margin=margin)
            # The last unit (the semantic result) never leaves early: it covers the frame
            # until the opener, so completed exits can never leave a near-white frame.
            fits = index != len(groups) - 1 and frames <= window
            units.append({"members": members, "box": rest_box(members), "frames": frames, "shift": shift,
                          "exits": False, "why": None if fits else "time", "fits": fits})
        # Units decide in order (supporting first): earlier units at their decision, later
        # ones still. Each pair is checked once, when the later of the two decides, against
        # the earlier one's real path, so a planned exit never meets another outgoing unit.
        for current in units:
            if not current["fits"]:
                continue
            current["exits"] = True
            if cls._exit_path_collides(current, units, opener_frame):
                current["exits"], current["why"] = False, "path"
        starts: dict[str, float] = {}
        leaving, staying, crossing = [], [], []
        for unit in units:
            ids = sorted(m.asset_id for m in unit["members"])
            if not unit["exits"]:
                staying.append(ids)
                if unit["why"] == "path":
                    crossing.append(ids)
                continue
            leaving.append(ids)
            begin = (segment.start_frame + opener_frame - unit["frames"]) / fps
            starts.update({member.asset_id: begin for member in unit["members"]})
        audit = {
            "decision": "complete_exit" if leaving else (
                "clean_cut:exit_path_crosses_another_outgoing_unit" if crossing
                else "clean_cut:exit_cannot_leave_the_frame_in_time" if len(groups) > 1
                else "clean_cut:single_unit_covers_until_opener"),
            "ready_frame": ready_frame, "window_frames": window, "order": leaving, "clean_cut_units": staying}
        if crossing:
            audit["path_blocked_units"] = crossing
        return {"starts": starts, "audit": audit}

    @staticmethod
    def _exit_path_collides(current: dict, units: list[dict], opener_frame: int) -> bool:
        """True when ``current``'s planned exit runs over another outgoing unit on any frame
        before the opener (each unit at its own pose on that frame; authored overlap kept)."""

        def at(unit: dict, frame: int) -> Box:
            box = unit["box"]
            if not unit["exits"]:
                return box
            first = opener_frame - unit["frames"]
            progress = min(1.0, max(0.0, (frame - first) / max(1, unit["frames"] - 1)))
            offset = unit["shift"] * (3 * progress ** 2 - 2 * progress ** 3)
            return (box[0] + offset, box[1], box[2] + offset, box[3])

        def ratio(a: Box, b: Box) -> float:
            inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
            return inter / max(1e-9, min(_area(a), _area(b)))

        for other in units:
            if other is current:
                continue
            allowed = ratio(current["box"], other["box"]) + _EXIT_OVERLAP_SLACK
            for frame in range(opener_frame - current["frames"], opener_frame):
                if ratio(at(current, frame), at(other, frame)) > allowed + _EPS:
                    return True
        return False

    @staticmethod
    def _complete_exit_path(members: list[LayoutItem], *, fps: int, margin: float) -> tuple[int, float]:
        """(frames, horizontal shift) for a unit leaving through its nearest side edge (the
        direction the renderer executes)."""
        left = max(float(m.x) + float(m.width) / 2 for m in members) + margin
        right = 1.0 - min(float(m.x) - float(m.width) / 2 for m in members) + margin
        distance, shift = (left, -left) if left <= right else (right, right)
        seconds = max(HERO_TRAVEL.minimum_seconds, SMOOTHSTEP_PEAK * distance / HERO_TRAVEL.max_normalized_speed)
        return ceil(seconds * fps - _EPS), shift

    @classmethod
    def _hold_to_opener(
        cls, *, previous: StoryBeat, outgoing: list[LayoutItem],
        cues: dict[tuple[str, str], MotionCue], text_boxes: list[tuple[float, float, Box]],
        incoming: list[LayoutItem], beat: StoryBeat, opener_frame: int,
        release_start_frame: int, segment: BeatSegment, fps: int,
    ) -> dict[str, object] | None:
        """Keep a proven completed state crisp when a release would consume its read window.

        This uses Motion's existing rhythm decision. Story/cue times and the incoming
        opener never move; only the outgoing release mode changes on the frame grid.
        """
        if opener_frame <= release_start_frame:
            return None
        segment_start = segment.start_frame / fps
        if cls._protected_motion_visible_before(
            beat=beat, incoming=incoming, cues=cues,
            segment_start=segment_start, opener_frame=opener_frame, fps=fps,
        ):
            return None
        if any(
            first_visible_frame(start - segment_start, fps) < opener_frame
            for start, _end, _box in text_boxes
        ):
            return None
        active: list[tuple[float, MotionCue, float]] = []
        for item in outgoing:
            cue = cues.get((previous.id, item.asset_id))
            focus = cue.params.get("semantic_focus") if cue and isinstance(cue.params, dict) else None
            if not isinstance(focus, dict) or focus.get("active") is not True:
                continue
            rhythm = focus.get("rhythm")
            hold_ms = rhythm.get("minimum_read_hold_ms") if isinstance(rhythm, dict) else None
            if type(hold_ms) not in (int, float):
                continue
            try:
                hold = float(hold_ms) / 1000
            except OverflowError:
                continue
            if not isfinite(hold) or hold <= 0:
                continue
            active.append((cls._motion_end(cue), cue, hold))
        if not active:
            return None
        settled, cue, hold = max(active, key=lambda row: (row[0], row[1].asset_id))
        stable_frame = ceil(settled * fps - _EPS)
        release_frame = segment.start_frame + release_start_frame
        open_frame = segment.start_frame + opener_frame
        required = max(1, round(hold * fps))
        if release_frame - stable_frame >= required or open_frame - stable_frame < required:
            return None
        return {
            "protected_asset_id": cue.asset_id,
            "semantic_event_id": (cue.params.get("semantic_focus") or {}).get("semantic_event_id"),
            "settled_at": settled,
            "minimum_read_hold_ms": round(hold * 1000),
            "stable_frames_before_release": release_frame - stable_frame,
            "stable_frames_to_opener": open_frame - stable_frame,
            "required_stable_frames": required,
        }

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
    def _protected_motion_visible_before(
        *, beat: StoryBeat, incoming: list[LayoutItem],
        cues: dict[tuple[str, str], MotionCue], segment_start: float,
        opener_frame: int, fps: int,
    ) -> bool:
        """Use encoded visibility, so subframe action starts on the opener are legal."""
        for item in incoming:
            cue = cues.get((beat.id, item.asset_id))
            for action in cue.segments if cue is not None else ():
                protected = (
                    action.phase in _PROTECTED_PHASES or action.connection
                    or action.semantic_action is not None
                )
                if protected and first_visible_frame(
                    action.start - segment_start, fps,
                ) < opener_frame:
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


def _area(box: Box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
