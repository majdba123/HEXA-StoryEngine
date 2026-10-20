from __future__ import annotations

from app.assets import AssetManager
from app.choreography import ChoreographyDirective, ChoreographyPlan
from app.models import CompositionBeat, LayoutItem, MotionCue, StoryBeat, TextPlan, VisualAsset
from app.motion.timing import story_activation_window
from app.text.timing.visibility import TextVisibilityPolicy

from .collision import authored_overlap_ratio, box
from .timing import encoded_motion_renderability_floor_px, motion_comfort, projected_motion_activity_px

# Sprint 4.4: reference-derived entry motion. Measured reference entries ramp opacity over
# 3-13 frames (median 6) and half of them also scale in from ~0.94; none pop in one frame.
# The reveal frame itself must already be visible, so the ramp starts at a small opacity.
ENTRY_OPACITY_INITIAL = 0.14
ENTRY_OPACITY_MIN_SECONDS = 3 / 30
ENTRY_SCALE_IN = 0.94
_EPS = 1e-6
_FRAME = 1 / 30


class EntryMotionGrammar:
    """Give every newly entering asset an opacity entry inside its own Story window.

    Runs after the Reference contract, so it never competes with it: the opacity clock is
    a separate cue parameter, and the only transform it adds is a restrained scale-in for
    the Choreography leader, or for a Story event's unique authored owner (its RESULT, else
    its LEADER), when nothing else moves that asset; owners whose entries overlap keep one
    accent, by authority. Supporting assets keep the opacity entry. Story timing is input
    only: the clock is exactly ``[cue.start, cue.end]`` (reveal -> settle). Existing
    programs, segments and Sprint 4.1/4.2 motion are never rewritten. An eligible
    leader may also receive an eased spatial path when Story hold, visible text,
    Composition geometry and motion comfort leave room for it.
    """

    def apply(
        self,
        cues: list[MotionCue],
        *,
        composition: list[CompositionBeat],
        choreography: ChoreographyPlan | None,
        assets: list[VisualAsset] | None,
        story: list[StoryBeat] | None = None,
        text: TextPlan | None = None,
    ) -> list[MotionCue]:
        assets_by_id = {asset.id: asset for asset in assets or []}
        beat_ends = {beat.id: float(beat.end) for beat in story or []}
        event_owners = {beat.id: self._event_owners(beat) for beat in story or []}
        activation_settles = {}
        for beat in story or []:
            for activation in beat.asset_activations:
                _has_v2, window = story_activation_window(activation, beat)
                if window is not None:
                    activation_settles[(beat.id, activation.asset_id)] = float(window.settle_at)
        layouts = {layout.beat_id: {item.asset_id: item for item in layout.items}
                   for layout in composition}
        text_windows: dict[str, list[tuple[float, float]]] = {}
        if text is not None:
            for beat in story or []:
                siblings = [row for row in text.cues if row.beat_id == beat.id]
                text_windows[beat.id] = [
                    (float(row.spoken_start), TextVisibilityPolicy.reading_end(row, beat, siblings))
                    for row in siblings
                ]
        by_beat: dict[str, list[int]] = {}
        for index, cue in enumerate(cues):
            by_beat.setdefault(cue.beat_id, []).append(index)
        output = list(cues)
        for beat_id, indices in by_beat.items():
            directive = choreography.for_beat(beat_id) if choreography is not None else None
            leader = directive.primary_asset_id if directive is not None else None
            beat_cues = [cues[i] for i in indices]
            families = self._family_sizes(beat_cues, assets_by_id)
            mismatched = self._mismatched_families(beat_cues, assets_by_id)
            openers = self._scene_opening_families(beat_cues, directive, assets_by_id)
            owners = event_owners.get(beat_id, {})
            accented: list[tuple[float, float]] = []

            def authority(i: int) -> tuple[int, float, str]:
                asset_id = cues[i].asset_id
                rank = 0 if asset_id == leader else {"RESULT": 1, "LEADER": 2}.get(owners.get(asset_id, ""), 3)
                return rank, float(cues[i].start), asset_id

            # Owners are visited in authority order so a lower owner never takes the
            # accent from a higher one whose entry overlaps it; others keep plain order.
            for i in sorted(indices, key=authority):
                candidate = cues[i].asset_id == leader or cues[i].asset_id in owners
                if candidate and any(
                    min(float(cues[i].end), end) - max(float(cues[i].start), start) > _FRAME - _EPS
                    for start, end in accented
                ):
                    candidate = False  # one restrained accent at a time inside a beat
                output[i] = self._apply_one(
                    cues[i],
                    item=layouts.get(beat_id, {}).get(cues[i].asset_id),
                    asset=assets_by_id.get(cues[i].asset_id),
                    is_leader=candidate,
                    family_size=families.get(self._family(cues[i], assets_by_id), 1),
                    family_mismatch=self._family(cues[i], assets_by_id) in mismatched,
                    opens_scene=self._family(cues[i], assets_by_id) in openers
                    and self._in_opening_frame(cues[i], beat_cues),
                    beat_end=beat_ends.get(beat_id),
                    authored_settle=activation_settles.get((beat_id, cues[i].asset_id)),
                    layout_items=list(layouts.get(beat_id, {}).values()),
                    text_clear=text is not None and (not text.cues or beat_id in text_windows) and not any(
                        TextVisibilityPolicy.overlaps(
                            float(cues[i].start), float(cues[i].end), start, end,
                        ) for start, end in text_windows.get(beat_id, [])
                    ),
                )
                if (output[i].params.get("entry_grammar") or {}).get("scale_in"):
                    accented.append((float(output[i].start), float(output[i].end)))
        return output

    @staticmethod
    def _event_owners(beat: StoryBeat) -> dict[str, str]:
        """Unique authored owner of each confident Story event: its RESULT, else its LEADER."""
        owners: dict[str, str] = {}
        for event in beat.event_authorities:
            if event.needs_review:
                continue
            ids, kind = ((event.result_asset_ids, "RESULT") if event.result_asset_ids
                         else (event.leader_asset_ids, "LEADER"))
            if len(ids) == 1:
                owners.setdefault(ids[0], kind)
        return owners

    def _apply_one(
        self,
        cue: MotionCue,
        *,
        item: LayoutItem | None,
        asset: VisualAsset | None,
        is_leader: bool,
        family_size: int,
        family_mismatch: bool,
        opens_scene: bool,
        beat_end: float | None,
        authored_settle: float | None,
        layout_items: list[LayoutItem],
        text_clear: bool,
    ) -> MotionCue:
        params = dict(cue.params) if isinstance(cue.params, dict) else {}
        reason = self._opacity_blocker(cue, params, family_mismatch, opens_scene)
        if reason is not None:
            params["entry_grammar"] = {"opacity": False, "reason": reason}
            return cue.model_copy(update={"params": params})
        # One clock per cue; every layer of a Pass2 family shares identical start/settle,
        # so the family fades as one synchronized unit.
        params["entry_opacity"] = {
            "initial": ENTRY_OPACITY_INITIAL,
            "start": float(cue.start),
            "settle": float(cue.end),
        }
        scale_in = (
            is_leader and family_size == 1 and item is not None and asset is not None
            and self._has_read_hold(cue, params, beat_end, settle_override=authored_settle)
            and self._scale_in_allowed(cue, params, item, asset)
        )
        if scale_in:
            dx, spatial_mode = self._hero_entry_offset(
                cue, item=item, layout_items=layout_items, text_clear=text_clear,
            )
            program = dict(params["program"])
            program["name"] = (
                "reference_hero_spatial_scale_in" if spatial_mode else "reference_entry_scale_in"
            )
            program["settle_progress"] = 1.0
            program["keyframes"] = [
                {"progress": 0.0, "dx": dx, "dy": 0.0, "scale": ENTRY_SCALE_IN,
                 "easing": "smoothstep" if spatial_mode else "ease_out_cubic"},
                {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0,
                 "easing": "smoothstep" if spatial_mode else "ease_out_cubic"},
            ]
            params["program"] = program
            if spatial_mode:
                params["hero_entry"] = {"mode": spatial_mode, "start_dx": round(dx, 6)}
        params["entry_grammar"] = {"opacity": True, "scale_in": scale_in}
        settle = self._opacity_read_hold_settle(cue, params, beat_end, scale_in=scale_in)
        if settle is not None:
            # The ramp is the only change on this asset, so it may finish at the read-hold
            # deadline with its own 3-frame minimum instead of the spatial ENTRY minimum.
            params["entry_opacity"] = {**params["entry_opacity"], "settle": settle}
            params["entry_grammar"]["read_hold_settle"] = {"from": round(float(cue.end), 6),
                                                           "to": round(settle, 6)}
            return cue.model_copy(update={"params": params, "end": settle})
        return cue.model_copy(update={"params": params})

    @staticmethod
    def _opacity_read_hold_settle(
        cue: MotionCue, params: dict, beat_end: float | None, *, scale_in: bool,
    ) -> float | None:
        """Earlier opacity settle that leaves Rhythm's read hold before the cut, or None.

        Only a static entry (no transform, no semantic segment) qualifies: its window is
        just the opacity ramp. Story reveal, semantic settle/peak params (Text's sync
        anchor) and every moving entry are untouched.
        """
        if scale_in or beat_end is None or cue.segments:
            return None
        frames = (params.get("program") or {}).get("keyframes") or []
        if any(abs(float(f.get("dx", 0.0))) > 1e-9 or abs(float(f.get("dy", 0.0))) > 1e-9
               or abs(float(f.get("scale", 1.0)) - 1.0) > 1e-9 for f in frames):
            return None
        rhythm = (params.get("semantic_focus") or {}).get("rhythm")
        hold_ms = rhythm.get("minimum_read_hold_ms") if isinstance(rhythm, dict) else None
        if not isinstance(hold_ms, (int, float)) or hold_ms <= 0:
            return None
        deadline = float(beat_end) - float(hold_ms) / 1000
        if float(cue.end) <= deadline + _EPS:
            return None
        if deadline - float(cue.start) + _EPS < ENTRY_OPACITY_MIN_SECONDS:
            return None  # not even the 3-frame ramp fits: Story's reveal is too late
        return deadline

    @staticmethod
    def _hero_entry_offset(
        cue: MotionCue, *, item: LayoutItem, layout_items: list[LayoutItem], text_clear: bool,
    ) -> tuple[float, str | None]:
        """Fit one eased spatial path without changing Composition or authored collisions."""
        if not text_clear:
            return 0.0, None  # Text geometry is resolved later; do not move through visible text.
        duration = float(cue.end) - float(cue.start)
        extent = min(float(item.width), float(item.height))
        # smoothstep's peak derivative is 1.5. Position and scale share one speed budget.
        budget = motion_comfort("ENTRY").max_normalized_speed * duration / 1.5
        scale_activity = (1.0 - ENTRY_SCALE_IN) * extent
        if budget <= scale_activity:
            return 0.0, None
        spatial_budget = max(0.0, (budget * budget - scale_activity * scale_activity) ** 0.5)
        sign = -1.0 if float(item.x) < 0.5 else 1.0
        edge_distance = (
            float(item.x) + float(item.width) / 2.0 + 0.01
            if sign < 0 else 1.0 - float(item.x) + float(item.width) / 2.0 + 0.01
        )
        candidates = []
        if edge_distance <= spatial_budget:
            candidates.append((sign * edge_distance, "offscreen"))
        candidates.append((sign * min(0.04, spatial_budget * 0.85), "in_frame"))
        for dx, mode in candidates:
            if abs(dx) < 0.01:
                continue
            start = box(item, (dx, 0.0, ENTRY_SCALE_IN))
            finish = box(item, (0.0, 0.0, 1.0))
            # Every edge is linear in progress; smoothstep changes only the rate.
            # The union of the endpoint boxes encloses the entire continuous path.
            sweep = (min(start[0], finish[0]), min(start[1], finish[1]),
                     max(start[2], finish[2]), max(start[3], finish[3]))
            if mode == "in_frame" and (sweep[0] < 0 or sweep[2] > 1):
                continue
            smallest_area = (start[2] - start[0]) * (start[3] - start[1])
            safe = True
            for other in layout_items:
                if other.asset_id == item.asset_id:
                    continue
                target = box(other, (0.0, 0.0, 1.0))
                target_area = (target[2] - target[0]) * (target[3] - target[1])
                intersection = max(0.0, min(sweep[2], target[2]) - max(sweep[0], target[0])) * (
                    max(0.0, min(sweep[3], target[3]) - max(sweep[1], target[1])))
                upper_overlap = intersection / max(1e-9, min(smallest_area, target_area))
                if upper_overlap > authored_overlap_ratio(item, other) + 0.02:
                    safe = False
                    break
            if safe:
                return dx, mode
        return 0.0, None

    @staticmethod
    def _has_read_hold(
        cue: MotionCue, params: dict, beat_end: float | None, *, settle_override: float | None = None,
    ) -> bool:
        """Omit optional scale when its settled result cannot be read before the cut."""
        if beat_end is None:
            return True  # Standalone callers without Story keep their existing contract.
        focus = params.get("semantic_focus") or {}
        rhythm = focus.get("rhythm") if isinstance(focus, dict) else None
        hold_ms = rhythm.get("minimum_read_hold_ms") if isinstance(rhythm, dict) else None
        if not isinstance(hold_ms, (int, float)) or hold_ms <= 0:
            return True  # No Rhythm authority to suppress the existing gesture.
        settle = float(cue.end) if settle_override is None else max(float(cue.end), settle_override)
        return beat_end - settle + _EPS >= float(hold_ms) / 1000

    @staticmethod
    def _opacity_blocker(
        cue: MotionCue, params: dict, family_mismatch: bool, opens_scene: bool,
    ) -> str | None:
        continuity = params.get("semantic_continuity") or {}
        if continuity.get("mode", "ENTER") != "ENTER":
            return "not_entering"  # already on screen (or not visible): nothing to fade in
        if opens_scene:
            # The scene's authored opener carries the scene change at full opacity: a
            # faint first frame over an empty canvas is a near-white flash.
            return "opens_scene"
        if float(cue.end) - float(cue.start) + _EPS < ENTRY_OPACITY_MIN_SECONDS:
            return "short_window"
        if any(float(segment.start) < float(cue.start) - _EPS for segment in cue.segments):
            return "visible_before_reveal"  # a proxy segment shows it earlier: never hide it
        if family_mismatch:
            return "family_clock_mismatch"  # fail closed: a family fades together or not at all
        return None

    @staticmethod
    def _scale_in_allowed(cue: MotionCue, params: dict, item: LayoutItem, asset: VisualAsset) -> bool:
        """Leader scale-in only when no existing motion owns this asset's entry."""
        if cue.segments or asset.parent_asset_id:
            return False
        if (params.get("render_constraints") or {}).get("geometry_lock"):
            return False
        program = params.get("program") or {}
        frames = program.get("keyframes") or []
        if not frames or "compound_unit" in str(program.get("name") or ""):
            return False
        if any(
            abs(float(f.get("dx", 0.0))) > 1e-9 or abs(float(f.get("dy", 0.0))) > 1e-9
            or abs(float(f.get("scale", 1.0)) - 1.0) > 1e-9
            for f in frames
        ):
            return False  # a certified entry gesture already moves it: keep that, add opacity only
        delta = 1.0 - ENTRY_SCALE_IN
        activity = projected_motion_activity_px(
            dx=0.0, dy=0.0, scale=ENTRY_SCALE_IN, item_width=item.width, item_height=item.height,
        )
        if activity + _EPS < encoded_motion_renderability_floor_px():
            return False
        # ease_out_cubic peaks at 3x the mean speed at t=0; stay inside the ENTRY comfort speed.
        mean_speed = delta * min(item.width, item.height) / (float(cue.end) - float(cue.start))
        return mean_speed <= motion_comfort("ENTRY").max_normalized_speed

    @staticmethod
    def _in_opening_frame(cue: MotionCue, beat_cues: list[MotionCue]) -> bool:
        first = min(float(row.start) for row in beat_cues)
        return float(cue.start) < first + _FRAME + _EPS

    @classmethod
    def _scene_opening_families(
        cls,
        beat_cues: list[MotionCue],
        directive: ChoreographyDirective | None,
        assets_by_id: dict[str, VisualAsset],
    ) -> set[str]:
        """Families that keep the certified hard reveal in the beat's opening frame.

        Motion never ranks importance itself. One family opening alone is the opener by
        construction. Among several, existing authority decides: the single authored
        event leader, else Choreography's primary asset. Without such evidence every
        opening family keeps its hard reveal (fail closed).
        """
        opening = [cue for cue in beat_cues if cls._in_opening_frame(cue, beat_cues)]
        families = {cls._family(cue, assets_by_id) for cue in opening}
        if len(families) <= 1 or directive is None:
            return families
        leaders = {asset_id for flow in directive.event_flows for asset_id in flow.leader_asset_ids}
        led = {cls._family(cue, assets_by_id) for cue in opening if cue.asset_id in leaders}
        if len(led) == 1:
            return led
        primary = {cls._family(cue, assets_by_id) for cue in opening
                   if cue.asset_id == directive.primary_asset_id}
        return primary or families

    @staticmethod
    def _family(cue: MotionCue, assets_by_id: dict[str, VisualAsset]) -> str:
        asset = assets_by_id.get(cue.asset_id)
        return AssetManager.family_id(asset) if asset is not None else cue.asset_id

    @classmethod
    def _family_sizes(cls, cues: list[MotionCue], assets_by_id: dict[str, VisualAsset]) -> dict[str, int]:
        sizes: dict[str, int] = {}
        for cue in cues:
            family = cls._family(cue, assets_by_id)
            sizes[family] = sizes.get(family, 0) + 1
        return sizes

    @classmethod
    def _mismatched_families(cls, cues: list[MotionCue], assets_by_id: dict[str, VisualAsset]) -> set[str]:
        clocks: dict[str, set[tuple[float, float]]] = {}
        for cue in cues:
            clocks.setdefault(cls._family(cue, assets_by_id), set()).add(
                (round(float(cue.start), 6), round(float(cue.end), 6)))
        return {family for family, rows in clocks.items() if len(rows) > 1}
