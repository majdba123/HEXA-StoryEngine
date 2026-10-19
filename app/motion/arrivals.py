"""Reference arrivals for every entering asset (Cinematic VNext2).

The approved references move most of what enters: SCALE pops and SLIDEs are 39-58 % of
their entries, fades only 9-11 % (``style_probe`` on both references). After hero
travel and the PAYOFF resolution have taken their subjects, this pass gives each other
entering asset one reference gesture, chosen from its own geometry so a scene never
animates uniformly:

* SLIDE - an asset near a side edge slides in from that edge (reference slides: 0.10-0.15
  frame widths over 8-13 frames, peak 0.8-1.2 w/s), when the whole swept path is clear of
  every asset visible meanwhile (authored overlap respected) and of hero travel paths; an
  asset near no side edge but near the top or bottom slides in vertically from that edge
  over the same physical distance, reach and speed (the references' objects rise in from
  the bottom; visual sprint, 2026-10-16);
* POP   - otherwise a scale pop from the reference start size (0.62) in <= 5 frames;
* FADE  - kept when the pop would not be visible (below 20 px) or the asset belongs to a
  Pass2 family, is geometry-locked, continues from an earlier beat, or already carries a
  certified or semantic gesture inside its arrival.

Story instants are never moved: every gesture starts at the cue's reveal and rests by
the cue's settle. Text is composed afterwards against this Motion; a slide whose path
would cross composed text becomes a pop (``settle_against_text``), which stays inside
the asset's own box.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.assets import AssetManager
from app.models import CompositionBeat, LayoutItem, MotionCue, StoryBeat, VisualAsset

from .collision import authored_overlap_ratio, box
from .family import family_of, follow, rigid_followers
from app.targets.context import active_target

from .resolution import POP_MIN_ACTIVITY_PX, POP_MIN_SECONDS, POP_SECONDS, pop_start_scale
from .timing import projected_motion_activity_px
from .visual_flow.direction import focus_handoff_direction, spatial_entry_direction

_EPS = 1e-6
_FRAME = 1 / 30
# Edge slide. The references slide 0.10-0.15 frame widths in 4-13 frames at up to 1.2 w/s;
# reviewed HEXA renders found that rushed, so a slide is a short calm settle into place:
# at most 0.08 w, at most 0.6 w/s peak, never shorter than 8 frames (else a pop or fade).
SLIDE_DISTANCE = 0.08        # frame widths
SLIDE_MIN_DISTANCE = 0.04
SLIDE_EDGE_REACH = 0.16      # an asset whose box is this close to a side edge slides
SLIDE_SECONDS = 12 / 30
SLIDE_MIN_SECONDS = 8 / 30
SLIDE_MAX_PEAK_SPEED = 0.6   # w/s
SMOOTHSTEP_PEAK = 1.5
_OVERLAP_SLACK = 0.02

Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class ArrivalDecision:
    beat_id: str
    asset_id: str
    gesture: str  # SLIDE / POP / FADE
    reason: str

    def to_payload(self) -> dict[str, str]:
        return {"beat_id": self.beat_id, "asset_id": self.asset_id, "gesture": self.gesture, "reason": self.reason}


def _inter(a: Box, b: Box) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(a: Box) -> float:
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


def _moves(program: dict | None) -> bool:
    return any(
        abs(float(f.get("dx", 0.0))) > 1e-9 or abs(float(f.get("dy", 0.0))) > 1e-9
        or abs(float(f.get("scale", 1.0)) - 1.0) > 1e-9
        for f in (program or {}).get("keyframes") or []
    )


def _replaceable_decorative_entry(cue: MotionCue) -> bool:
    """Replace modest generic entry wiggles, never authored event execution."""
    params = cue.params or {}
    semantic = params.get("semantic_focus") or {}
    execution = semantic.get("event_flow_execution")
    event = semantic.get("event_flow") or {}
    if execution not in (None, "NONE", "ENTRY_FALLBACK"):
        return False
    if execution == "ENTRY_FALLBACK":
        # A non-causal ESTABLISH/ADD event is a visual introduction, not a
        # protected interaction. Preserve every explicit/cause/result event.
        if event.get("relation_only") or event.get("relationship") or (
                event.get("source_asset_id") or event.get("target_asset_id")
                or event.get("result_asset_id") or event.get("incoming_from_asset_id")
                or event.get("handoff_to_asset_ids") or event.get("handoff_to_event_ids")
                or event.get("handoff_to_event_id")):
            return False
        phases = event.get("phase_chain") or []
        if any(row.get("stage") not in ("ESTABLISH", "ADD") or row.get("relationship")
               or row.get("semantic_action") not in (None, "ESTABLISH", "ADD", "REVEAL")
               for row in phases):
            return False
    if params.get("causal_arrival") or params.get("hero_emphasis") or params.get("payoff_resolution"):
        return False
    if any(row.phase != "ENTRY" or row.semantic_action or row.connection
           or "semantic_peak_progress" in row.program for row in cue.segments):
        return False
    program = params.get("program") or {}
    name = str(program.get("name") or "")
    if name.startswith("density_safe_"):
        name = name[len("density_safe_"):]
    if name.startswith("event_chain_"):
        if execution != "ENTRY_FALLBACK":
            return False
    elif not name.startswith("reference_") or name.startswith(("reference_pop", "reference_slide")):
        return False
    frames = program.get("keyframes") or []
    if not frames or "semantic_peak_progress" in program:
        return False
    return all(abs(float(row.get("dx", 0.0))) <= 0.065
               and abs(float(row.get("dy", 0.0))) <= 0.065
               and 0.93 <= float(row.get("scale", 1.0)) <= 1.085
               for row in frames)


def _is_nudge(program: dict | None, item: LayoutItem | None = None) -> bool:
    """An entry gesture the reference arrival may replace: Sprint 4.4's restrained leader
    scale-in (0.94 -> 1), or any planner gesture that stays below the visible arrival floor
    (20 px) and carries no spoken accent (nothing grows above rest, no semantic peak)."""
    program = program or {}
    if str(program.get("name") or "") in {"reference_entry_scale_in", "reference_hero_spatial_scale_in"}:
        return True
    if item is None or "semantic_peak_progress" in program:
        return False
    frames = program.get("keyframes") or []
    if any(float(f.get("scale", 1.0)) > 1.0 + 1e-9 for f in frames):
        return False
    return max((projected_motion_activity_px(dx=float(f.get("dx", 0.0)), dy=float(f.get("dy", 0.0)),
                                             scale=float(f.get("scale", 1.0)), item_width=item.width,
                                             item_height=item.height) for f in frames), default=0.0) \
        < POP_MIN_ACTIVITY_PX


def pop_frames(start_scale: float, settle: float) -> list[dict]:
    settle = max(0.0, min(1.0, settle))
    frames = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": round(start_scale, 5), "easing": "smoothstep"},
              {"progress": round(settle, 6), "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"}]
    if settle < 1.0 - _EPS:
        frames.append({"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"})
    return frames


def slide_frames(dx: float, settle: float, dy: float = 0.0, *, start_scale: float = 1.0) -> list[dict]:
    settle = max(0.0, min(1.0, settle))
    frames = [{"progress": 0.0, "dx": round(dx, 6), "dy": round(dy, 6), "scale": start_scale,
               "easing": "smoothstep"},
              {"progress": round(settle, 6), "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"}]
    if settle < 1.0 - _EPS:
        frames.append({"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"})
    return frames


class SecondaryArrivalPlanner:
    def __init__(self) -> None:
        self.decisions: list[ArrivalDecision] = []
        self._slides: dict[tuple[str, str], tuple[float, float, Box]] = {}
        self._pop_fallback: dict[tuple[str, str], MotionCue] = {}

    def plan(
        self,
        *,
        story: list[StoryBeat],
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        assets: list[VisualAsset],
        travel_sweeps: dict[tuple[str, str], tuple[float, float, Box]] | None = None,
    ) -> list[MotionCue]:
        self.decisions, self._slides, self._pop_fallback = [], {}, {}
        assets_by_id = {asset.id: asset for asset in assets}
        layouts = {row.beat_id: {item.asset_id: item for item in row.items} for row in composition}
        sweeps = dict(travel_sweeps or {})
        output = list(motion)
        layout_beats = {row.beat_id: row for row in composition}
        directions: dict[tuple[str, str], tuple[float, float]] = {}
        for index, beat in enumerate(story):
            if len(story) < 2:
                continue  # single-beat callers retain the certified local entry grammar
            previous = story[index - 1] if index else None
            focus = focus_handoff_direction(previous, beat, layout_beats)
            for item in (layout_beats[beat.id].items if beat.id in layout_beats else []):
                # Each independent illustration receives a physical staging edge.
                # A unique primary can instead follow the previous scene's focus.
                directions[(beat.id, item.asset_id)] = (
                    focus if focus is not None and len(beat.primary_asset_ids) == 1
                    and item.asset_id == beat.primary_asset_ids[0]
                    else spatial_entry_direction(item)
                )
        by_beat: dict[str, list[int]] = {}
        for position, cue in enumerate(motion):
            by_beat.setdefault(cue.beat_id, []).append(position)
        for beat in story:
            positions = by_beat.get(beat.id, [])
            layout = layouts.get(beat.id, {})
            families: dict[str, int] = {}
            for position in positions:
                families[self._family(motion[position].asset_id, assets_by_id)] = families.get(
                    self._family(motion[position].asset_id, assets_by_id), 0) + 1
            index = {output[p].asset_id: p for p in positions}
            followed: set[str] = set()
            for position in sorted(positions, key=lambda p: (float(motion[p].start), motion[p].asset_id)):
                cue = output[position]
                if cue.asset_id in followed:
                    continue
                item = layout.get(cue.asset_id)
                beat_cues = [output[p] for p in positions]
                gesture, reason, updated = self._arrive(
                    cue, item=item, asset=assets_by_id.get(cue.asset_id),
                    family_size=families.get(self._family(cue.asset_id, assets_by_id), 1),
                    beat_cues=beat_cues, layout=layout,
                    sweeps={key: value for key, value in sweeps.items() if key[0] == beat.id},
                    assets_by_id=assets_by_id,
                    flow_direction=directions.get((beat.id, cue.asset_id)),
                )
                if updated is not None:
                    output[position] = updated
                    if gesture == "SLIDE":
                        sweeps[(beat.id, cue.asset_id)] = self._slides[(beat.id, cue.asset_id)]
                    # A rigid Pass2 family moves as one unit: its layers follow the primary.
                    for member in rigid_followers(cue, beat_cues, layout, assets_by_id) or []:
                        output[index[member.asset_id]] = follow(member, updated)
                        followed.add(member.asset_id)
                        self.decisions.append(ArrivalDecision(beat.id, member.asset_id, "FOLLOW",
                                                              f"family_layer_follows:{cue.asset_id}"))
                self.decisions.append(ArrivalDecision(beat.id, cue.asset_id, gesture, reason))
        return output

    def settle_against_text(
        self, motion: list[MotionCue], text_boxes: dict[str, list[tuple[float, float, Box]]],
    ) -> list[MotionCue]:
        """A slide whose swept path meets composed text visible meanwhile becomes its pop."""
        revoked = {
            key for key, (start, end, sweep) in self._slides.items()
            if any(t0 < end - _EPS and t1 > start + _EPS and _inter(sweep, tb) > 0
                   for t0, t1, tb in text_boxes.get(key[0], []))
        }
        if not revoked:
            return motion
        self.decisions = [
            ArrivalDecision(row.beat_id, row.asset_id, "POP" if (row.beat_id, row.asset_id) in self._pop_fallback
                            else "FADE", "slide_path_crosses_composed_text")
            if (row.beat_id, row.asset_id) in revoked else row
            for row in self.decisions
        ]
        output = []
        for cue in motion:
            key = (cue.beat_id, cue.asset_id)
            output.append(self._pop_fallback.get(key, self._fade_fallback(cue)) if key in revoked else cue)
        leaders = {(cue.beat_id, cue.asset_id): cue for cue in output if (cue.beat_id, cue.asset_id) in revoked}
        return [
            follow(cue, leaders[(cue.beat_id, cue.params["family_follow"])])
            if (cue.beat_id, cue.params.get("family_follow")) in leaders
            and (cue.params.get("entry_grammar") or {}).get("arrival") == "FOLLOW" else cue
            for cue in output
        ]

    def pop_withdrawn(
        self,
        motion: list[MotionCue],
        keys: set[tuple[str, str]],
        *,
        composition: list[CompositionBeat],
        assets: list[VisualAsset],
    ) -> list[MotionCue]:
        """A hero whose travel was withdrawn through composed text arrives with the
        reference pop: the pop stays inside its own box, so composed text stays clear."""
        if not keys:
            return motion
        assets_by_id = {asset.id: asset for asset in assets}
        layouts = {row.beat_id: {item.asset_id: item for item in row.items} for row in composition}
        output = list(motion)
        for position, cue in enumerate(motion):
            if (cue.beat_id, cue.asset_id) not in keys:
                continue
            beat_cues = [row for row in motion if row.beat_id == cue.beat_id]
            family = self._family(cue.asset_id, assets_by_id)
            gesture, reason, updated = self._arrive(
                cue, item=layouts.get(cue.beat_id, {}).get(cue.asset_id), asset=assets_by_id.get(cue.asset_id),
                family_size=sum(1 for row in beat_cues if self._family(row.asset_id, assets_by_id) == family),
                beat_cues=beat_cues, layout=layouts.get(cue.beat_id, {}), sweeps={}, allow_slide=False,
                assets_by_id=assets_by_id,
            )
            if updated is not None:
                output[position] = updated
                where = {row.asset_id: i for i, row in enumerate(output) if row.beat_id == cue.beat_id}
                for member in rigid_followers(cue, beat_cues, layouts.get(cue.beat_id, {}), assets_by_id) or []:
                    output[where[member.asset_id]] = follow(member, updated)
            self.decisions.append(ArrivalDecision(cue.beat_id, cue.asset_id, gesture, f"travel_withdrawn:{reason}"))
        return output

    @staticmethod
    def _fade_fallback(cue: MotionCue) -> MotionCue:
        def still(program: dict) -> dict:
            return {**program, "name": "static_reveal_reference_slide_withdrawn",
                    "keyframes": [{**f, "dx": 0.0, "dy": 0.0, "scale": 1.0} for f in program.get("keyframes") or []]}

        params = {k: v for k, v in cue.params.items() if k != "reference_slide"}
        params["program"] = still(dict(params.get("program") or {}))
        segments = [row.model_copy(update={"program": still(row.program)}) if row.phase == "ENTRY" else row
                    for row in cue.segments]
        return cue.model_copy(update={"params": params, "segments": segments})

    @staticmethod
    def _family(asset_id: str, assets_by_id: dict[str, VisualAsset]) -> str:
        asset = assets_by_id.get(asset_id)
        return AssetManager.family_id(asset) if asset is not None else asset_id

    def _arrive(
        self,
        cue: MotionCue,
        *,
        item: LayoutItem | None,
        asset: VisualAsset | None,
        family_size: int,
        beat_cues: list[MotionCue],
        layout: dict[str, LayoutItem],
        sweeps: dict[tuple[str, str], tuple[float, float, Box]],
        allow_slide: bool = True,
        assets_by_id: dict[str, VisualAsset] | None = None,
        flow_direction: tuple[float, float] | None = None,
    ) -> tuple[str, str, MotionCue | None]:
        params = cue.params if isinstance(cue.params, dict) else {}
        if item is None:
            return "FADE", "no_layout", None
        if (params.get("semantic_continuity") or {}).get("mode", "ENTER") != "ENTER":
            return "FADE", "not_entering", None
        if params.get("hero_travel"):
            return "TRAVEL", "hero_travel", None
        if params.get("reference_pop"):
            causal = params.get("causal_arrival")
            if isinstance(causal, dict) and allow_slide and item is not None:
                family = family_of(cue.asset_id, assets_by_id or {})
                others = [row for row in beat_cues if family_of(row.asset_id, assets_by_id or {}) != family]
                slide, why = self._causal_slide(cue, item=item, cause=layout.get(str(causal.get("cause_asset_id"))),
                                                beat_cues=others, layout=layout, sweeps=sweeps)
                if slide is not None:
                    self._pop_fallback[(cue.beat_id, cue.asset_id)] = cue
                    return "SLIDE", "causal_slide", slide
                return "POP", f"payoff_resolution:causal_{why}", None
            return "POP", "payoff_resolution", None
        if (params.get("render_constraints") or {}).get("geometry_lock"):
            return "FADE", "geometry_locked_layer", None
        if family_size != 1 and rigid_followers(cue, beat_cues, layout, assets_by_id or {}) is None:
            return "FADE", "family_cannot_move_as_one", None
        if asset is not None and asset.parent_asset_id:
            return "FADE", "child_asset", None
        if params.get("handoff_from") or params.get("referent_carrier"):
            return "FADE", "referent_continuity", None
        program = params.get("program") or {}
        decorative = flow_direction is not None and _replaceable_decorative_entry(cue)
        if _moves(program) and not _is_nudge(program, item) and not decorative:
            return "FADE", "certified_gesture_owns_entry", None
        window = float(cue.end) - float(cue.start)
        if window + _EPS < POP_MIN_SECONDS:
            return "FADE", "window_below_pop_minimum", None
        arrival_end = float(cue.start) + min(max(SLIDE_SECONDS, POP_SECONDS), window)
        for row in cue.segments:
            if row.phase == "ENTRY":
                if abs(float(row.start) - float(cue.start)) > _EPS or (
                        _moves(row.program) and not _is_nudge(row.program, item)
                        and not decorative):
                    return "FADE", "entry_segment_owns_motion", None
            elif float(row.start) < arrival_end - _EPS:
                return "FADE", "accent_inside_arrival", None
        for other in beat_cues:
            pulse = (other.params or {}).get("hero_emphasis") if other.asset_id != cue.asset_id else None
            if isinstance(pulse, dict) and float(pulse["start"]) < arrival_end - _EPS \
                    and float(pulse["end"]) > float(cue.start) + _EPS:
                return "FADE", "yields_to_hero_emphasis", None
        family = family_of(cue.asset_id, assets_by_id or {})
        others = [row for row in beat_cues if family_of(row.asset_id, assets_by_id or {}) != family]
        slide = (self._slide(cue, item=item, beat_cues=others, layout=layout, sweeps=sweeps,
                             window=window, flow_direction=flow_direction)
                 if allow_slide else None)
        pop = self._pop(cue, item=item, window=window)
        if slide is not None:
            if pop is not None:
                self._pop_fallback[(cue.beat_id, cue.asset_id)] = pop
            vertical = bool((slide.params.get("reference_slide") or {}).get("dy"))
            reason = ("flow_staged_vertical" if vertical else "flow_staged_horizontal") if flow_direction else (
                "edge_slide_vertical" if vertical else "edge_slide")
            return "SLIDE", reason, slide
        if pop is not None:
            return "POP", "reference_pop", pop
        return "FADE", "pop_below_visible_floor", None

    def _causal_slide(
        self,
        cue: MotionCue,
        *,
        item: LayoutItem,
        cause: LayoutItem | None,
        beat_cues: list[MotionCue],
        layout: dict[str, LayoutItem],
        sweeps: dict[tuple[str, str], tuple[float, float, Box]],
    ) -> tuple[MotionCue | None, str]:
        """A resolving result arrives moving away from its authored cause (cause -> consequence).

        Replaces the result's reference pop by a short slide along the cause -> result
        direction, with the edge slide's distance, timing and speed limits, scale unchanged
        (no enlargement), never starting beyond the halfway point to the cause. The swept
        path must be clear of every other visible asset (the cause only when the result is
        drawn above it, so it emerges from it) and of hero travel paths; else (None, why).
        """
        if cause is None:
            return None, "cause_not_laid_out"
        frame = active_target()
        width, height = frame.width, frame.height
        dx_px, dy_px = (item.x - cause.x) * width, (item.y - cause.y) * height
        span = (dx_px * dx_px + dy_px * dy_px) ** 0.5
        if span < 1.0:
            return None, "cause_at_result"
        start = float(cue.start)
        # the pop's own window: the base program and every program starting with the reveal
        window = min([float(cue.end) - start] + [float(row.end) - float(row.start) for row in cue.segments
                                                  if abs(float(row.start) - start) <= _EPS])
        seconds = min(SLIDE_SECONDS, window)
        if seconds + _EPS < SLIDE_MIN_SECONDS:
            return None, "window_below_slide_minimum"
        distance_px = min(SLIDE_DISTANCE, SLIDE_MAX_PEAK_SPEED * seconds / SMOOTHSTEP_PEAK) * width
        distance_px = min(distance_px, 0.5 * span)
        if distance_px + _EPS < SLIDE_MIN_DISTANCE * width:
            return None, "cause_too_close"
        dx, dy = -dx_px / span * distance_px / width, -dy_px / span * distance_px / height
        final, begin = box(item, (0.0, 0.0, 1.0)), box(item, (dx, dy, 1.0))
        sweep = (min(begin[0], final[0]), min(begin[1], final[1]), max(begin[2], final[2]), max(begin[3], final[3]))
        end = start + seconds
        for other in beat_cues:
            if other.asset_id == cue.asset_id or float(other.start) >= end - _EPS:
                continue
            other_item = layout.get(other.asset_id)
            if other_item is None or (other_item is cause and item.z > cause.z):
                continue
            target = box(other_item, (0.0, 0.0, 1.0))
            allowed = authored_overlap_ratio(item, other_item) + _OVERLAP_SLACK
            if _inter(sweep, target) / max(1e-9, min(_area(final), _area(target))) > allowed:
                return None, "path_crosses_visible_asset"
        for (_, asset_id), (t0, t1, path) in sweeps.items():
            if asset_id != cue.asset_id and t0 < end - _EPS and t1 > start + _EPS and _inter(sweep, path) > 0:
                return None, "path_crosses_hero_travel"
        params = self._with_opacity({k: v for k, v in cue.params.items() if k != "reference_pop"}, cue, seconds)
        params["reference_slide"] = {"dx": round(dx, 6), "dy": round(dy, 6), "seconds": round(seconds, 6),
                                     "peak_speed": round(SMOOTHSTEP_PEAK * distance_px / width / seconds, 4),
                                     "profile": "REFERENCE_SLIDE", "from_cause": params["causal_arrival"]}
        params["entry_grammar"] = {**(params.get("entry_grammar") or {}), "arrival": "SLIDE"}
        params["payoff_resolution"] = {**(params.get("payoff_resolution") or {}), "arrival": "causal_slide"}
        self._slides[(cue.beat_id, cue.asset_id)] = (start, end, sweep)

        def frames(settle: float) -> list[dict]:
            return slide_frames(dx, settle, dy)

        window_all = float(cue.end) - start
        params["program"] = {**(params.get("program") or {}), "name": "reference_slide_arrival",
                             "settle_progress": 1.0, "keyframes": frames(seconds / window_all)}
        segments = [
            row.model_copy(update={"program": {**row.program, "name": f"reference_slide_{row.phase.lower()}",
                                               "settle_progress": 1.0, "keyframes": frames(
                                                   seconds / (float(row.end) - float(row.start)))}})
            if abs(float(row.start) - start) <= _EPS and row.phase in {"ENTRY", "PAYOFF"} else row
            for row in cue.segments
        ]
        return cue.model_copy(update={"params": params, "segments": segments}), "applied"

    @staticmethod
    def _gesture(cue: MotionCue, params: dict, name: str, frames, seconds: float) -> MotionCue:
        """One gesture on the base program and on every carried ENTRY segment, each over its
        own window (the renderer draws a segmented cue's entry from its ENTRY segment)."""
        window = float(cue.end) - float(cue.start)
        params["program"] = {**(params.get("program") or {}), "name": name, "settle_progress": 1.0,
                             "keyframes": frames(seconds / window)}
        segments = [
            row.model_copy(update={"program": {**row.program, "name": name, "settle_progress": 1.0,
                                               "keyframes": frames(seconds / (float(row.end) - float(row.start)))}})
            if row.phase == "ENTRY" else row
            for row in cue.segments
        ]
        return cue.model_copy(update={"params": params, "segments": segments})

    @staticmethod
    def _with_opacity(params: dict, cue: MotionCue, seconds: float) -> dict:
        opacity = params.get("entry_opacity")
        if isinstance(opacity, dict):
            params["entry_opacity"] = {**opacity, "settle": round(
                min(float(opacity.get("settle", cue.end)), float(cue.start) + max(seconds, 3 * _FRAME)), 6)}
        return params

    def _pop(self, cue: MotionCue, *, item: LayoutItem, window: float) -> MotionCue | None:
        seconds = min(POP_SECONDS, window)
        start_scale = pop_start_scale(seconds, item.height)
        if projected_motion_activity_px(dx=0.0, dy=0.0, scale=start_scale, item_width=item.width,
                                        item_height=item.height) < POP_MIN_ACTIVITY_PX:
            return None
        params = self._with_opacity(dict(cue.params), cue, seconds)
        params.pop("hero_entry", None)
        params["reference_pop"] = {"start_scale": round(start_scale, 5), "seconds": round(seconds, 6),
                                   "profile": "REFERENCE_POP"}
        params["entry_grammar"] = {**(params.get("entry_grammar") or {}), "arrival": "POP"}
        return self._gesture(cue, params, "reference_pop_arrival",
                             lambda settle: pop_frames(start_scale, settle), seconds)

    def _slide(
        self,
        cue: MotionCue,
        *,
        item: LayoutItem,
        beat_cues: list[MotionCue],
        layout: dict[str, LayoutItem],
        sweeps: dict[tuple[str, str], tuple[float, float, Box]],
        window: float,
        flow_direction: tuple[float, float] | None = None,
    ) -> MotionCue | None:
        final = box(item, (0.0, 0.0, 1.0))
        frame = active_target()
        aspect = frame.width / max(1, frame.height)  # one width unit in height units
        left_gap, right_gap = final[0], 1.0 - final[2]
        gap, sign = (left_gap, -1.0) if left_gap <= right_gap else (right_gap, 1.0)
        vertical = gap > SLIDE_EDGE_REACH + _EPS
        if flow_direction is not None:
            # Cross-scene primary may enter from four sides even near the centre.
            # Existing sweep, text, speed and family constraints still govern it.
            vertical = abs(flow_direction[1]) > 0.5
            sign = flow_direction[1] if vertical else flow_direction[0]
        elif vertical:
            # Legacy edge rule for all other arrivals.
            top_gap, bottom_gap = final[1], 1.0 - final[3]
            gap, sign = (top_gap, -1.0) if top_gap <= bottom_gap else (bottom_gap, 1.0)
            if gap / aspect > SLIDE_EDGE_REACH + _EPS:
                return None
        # The actual renderer draws the ENTRY segment, not the base cue, when
        # segments exist. Never compress a half-second slide into a shorter
        # authored ENTRY window: that creates motion above the encoded comfort
        # speed and can abort an otherwise valid Final Package export.
        entry_windows = [
            float(row.end) - float(row.start)
            for row in cue.segments if row.phase == "ENTRY"
        ]
        available_window = min([window, *entry_windows])
        seconds = min(0.50 if flow_direction is not None else SLIDE_SECONDS, available_window)
        if seconds + _EPS < SLIDE_MIN_SECONDS:
            return None
        distance = min(0.12 if flow_direction is not None else SLIDE_DISTANCE,
                       SLIDE_MAX_PEAK_SPEED * seconds / SMOOTHSTEP_PEAK)
        if distance + _EPS < SLIDE_MIN_DISTANCE:
            return None
        dx, dy = (0.0, sign * distance * aspect) if vertical else (sign * distance, 0.0)
        begin = box(item, (dx, dy, 1.0))
        sweep = (min(begin[0], final[0]), min(begin[1], final[1]), max(begin[2], final[2]), max(begin[3], final[3]))
        start, end = float(cue.start), float(cue.start) + seconds
        for other in beat_cues:
            if other.asset_id == cue.asset_id or float(other.start) >= end - _EPS:
                continue
            other_item = layout.get(other.asset_id)
            if other_item is None:
                continue
            target = box(other_item, (0.0, 0.0, 1.0))
            allowed = authored_overlap_ratio(item, other_item) + _OVERLAP_SLACK
            if _inter(sweep, target) / max(1e-9, min(_area(final), _area(target))) > allowed:
                return None
        for (_, asset_id), (t0, t1, path) in sweeps.items():
            if asset_id != cue.asset_id and t0 < end - _EPS and t1 > start + _EPS and _inter(sweep, path) > 0:
                return None
        params = self._with_opacity(dict(cue.params), cue, seconds)
        params.pop("hero_entry", None)
        start_scale = 0.93 if flow_direction is not None else 1.0
        params["reference_slide"] = {"dx": round(dx, 6), **({"dy": round(dy, 6)} if vertical else {}),
                                     "seconds": round(seconds, 6),
                                     **({"start_scale": start_scale} if flow_direction is not None else {}),
                                     "peak_speed": round(SMOOTHSTEP_PEAK * distance / seconds, 4),
                                     "profile": "REFERENCE_SLIDE",
                                     **({"scene_flow": True} if flow_direction is not None else {})}
        params["entry_grammar"] = {**(params.get("entry_grammar") or {}), "arrival": "SLIDE"}
        self._slides[(cue.beat_id, cue.asset_id)] = (start, end, sweep)
        return self._gesture(cue, params, "reference_slide_arrival",
                             lambda settle: slide_frames(dx, settle, dy, start_scale=start_scale), seconds)
