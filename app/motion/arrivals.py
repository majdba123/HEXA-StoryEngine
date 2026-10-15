"""Reference arrivals for every entering asset (Cinematic VNext2).

The approved references move most of what enters: SCALE pops and SLIDEs are 39-58 % of
their entries, fades only 9-11 % (``style_probe`` on both references). After hero
travel and the PAYOFF resolution have taken their subjects, this pass gives each other
entering asset one reference gesture, chosen from its own geometry so a scene never
animates uniformly:

* SLIDE - an asset near a side edge slides in from that edge (reference slides: 0.10-0.15
  frame widths over 8-13 frames, peak 0.8-1.2 w/s), when the whole swept path is clear of
  every asset visible meanwhile (authored overlap respected) and of hero travel paths;
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
from .resolution import POP_MAX_GROWTH, POP_MIN_ACTIVITY_PX, POP_MIN_SECONDS, POP_SECONDS, POP_START_SCALE
from .timing import projected_motion_activity_px

_EPS = 1e-6
_FRAME = 1 / 30
SLIDE_DISTANCE = 0.12        # frame widths (reference median travel 0.15, q25 0.11)
SLIDE_MIN_DISTANCE = 0.06
SLIDE_EDGE_REACH = 0.16      # an asset whose box is this close to a side edge slides
SLIDE_SECONDS = 10 / 30
SLIDE_MIN_SECONDS = 5 / 30
SLIDE_MAX_PEAK_SPEED = 1.25  # w/s (reference slide peak q50 0.83, q75 1.22)
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


def _is_nudge(program: dict | None) -> bool:
    """Sprint 4.4's restrained leader scale-in (0.94 -> 1, optional small path)."""
    return str((program or {}).get("name") or "") in {"reference_entry_scale_in", "reference_hero_spatial_scale_in"}


def pop_frames(start_scale: float, settle: float) -> list[dict]:
    settle = max(0.0, min(1.0, settle))
    frames = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": round(start_scale, 5), "easing": "ease_out_cubic"},
              {"progress": round(settle, 6), "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"}]
    if settle < 1.0 - _EPS:
        frames.append({"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"})
    return frames


def slide_frames(dx: float, settle: float) -> list[dict]:
    settle = max(0.0, min(1.0, settle))
    frames = [{"progress": 0.0, "dx": round(dx, 6), "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
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
            for position in sorted(positions, key=lambda p: (float(motion[p].start), motion[p].asset_id)):
                cue = output[position]
                item = layout.get(cue.asset_id)
                gesture, reason, updated = self._arrive(
                    cue, item=item, asset=assets_by_id.get(cue.asset_id),
                    family_size=families.get(self._family(cue.asset_id, assets_by_id), 1),
                    beat_cues=[output[p] for p in positions], layout=layout,
                    sweeps={key: value for key, value in sweeps.items() if key[0] == beat.id},
                )
                if updated is not None:
                    output[position] = updated
                    if gesture == "SLIDE":
                        sweeps[(beat.id, cue.asset_id)] = self._slides[(beat.id, cue.asset_id)]
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
        return output

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
                beat_cues=beat_cues, layout={}, sweeps={}, allow_slide=False,
            )
            if updated is not None:
                output[position] = updated
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
    ) -> tuple[str, str, MotionCue | None]:
        params = cue.params if isinstance(cue.params, dict) else {}
        if item is None:
            return "FADE", "no_layout", None
        if (params.get("semantic_continuity") or {}).get("mode", "ENTER") != "ENTER":
            return "FADE", "not_entering", None
        if params.get("hero_travel"):
            return "TRAVEL", "hero_travel", None
        if params.get("reference_pop"):
            return "POP", "payoff_resolution", None
        if family_size != 1 or (params.get("render_constraints") or {}).get("geometry_lock"):
            return "FADE", "family_or_locked", None
        if asset is not None and asset.parent_asset_id:
            return "FADE", "child_asset", None
        if params.get("handoff_from") or params.get("referent_carrier"):
            return "FADE", "referent_continuity", None
        program = params.get("program") or {}
        if _moves(program) and not _is_nudge(program):
            return "FADE", "certified_gesture_owns_entry", None
        window = float(cue.end) - float(cue.start)
        if window + _EPS < POP_MIN_SECONDS:
            return "FADE", "window_below_three_frames", None
        arrival_end = float(cue.start) + min(max(SLIDE_SECONDS, POP_SECONDS), window)
        for row in cue.segments:
            if row.phase == "ENTRY":
                if abs(float(row.start) - float(cue.start)) > _EPS or (_moves(row.program) and not _is_nudge(row.program)):
                    return "FADE", "entry_segment_owns_motion", None
            elif float(row.start) < arrival_end - _EPS:
                return "FADE", "accent_inside_arrival", None
        for other in beat_cues:
            pulse = (other.params or {}).get("hero_emphasis") if other.asset_id != cue.asset_id else None
            if isinstance(pulse, dict) and float(pulse["start"]) < arrival_end - _EPS \
                    and float(pulse["end"]) > float(cue.start) + _EPS:
                return "FADE", "yields_to_hero_emphasis", None
        slide = (self._slide(cue, item=item, beat_cues=beat_cues, layout=layout, sweeps=sweeps, window=window)
                 if allow_slide else None)
        pop = self._pop(cue, item=item, window=window)
        if slide is not None:
            if pop is not None:
                self._pop_fallback[(cue.beat_id, cue.asset_id)] = pop
            return "SLIDE", "edge_slide", slide
        if pop is not None:
            return "POP", "reference_pop", pop
        return "FADE", "pop_below_visible_floor", None

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
        start_scale = max(POP_START_SCALE, 1.0 - POP_MAX_GROWTH * seconds / max(float(item.height), 1e-6))
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
    ) -> MotionCue | None:
        final = box(item, (0.0, 0.0, 1.0))
        left_gap, right_gap = final[0], 1.0 - final[2]
        gap, sign = (left_gap, -1.0) if left_gap <= right_gap else (right_gap, 1.0)
        if gap > SLIDE_EDGE_REACH + _EPS:
            return None
        seconds = min(SLIDE_SECONDS, window)
        if seconds + _EPS < SLIDE_MIN_SECONDS:
            return None
        distance = min(SLIDE_DISTANCE, SLIDE_MAX_PEAK_SPEED * seconds / SMOOTHSTEP_PEAK)
        if distance + _EPS < SLIDE_MIN_DISTANCE:
            return None
        dx = sign * distance
        begin = box(item, (dx, 0.0, 1.0))
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
        params["reference_slide"] = {"dx": round(dx, 6), "seconds": round(seconds, 6),
                                     "peak_speed": round(SMOOTHSTEP_PEAK * distance / seconds, 4),
                                     "profile": "REFERENCE_SLIDE"}
        params["entry_grammar"] = {**(params.get("entry_grammar") or {}), "arrival": "SLIDE"}
        self._slides[(cue.beat_id, cue.asset_id)] = (start, end, sweep)
        return self._gesture(cue, params, "reference_slide_arrival", lambda settle: slide_frames(dx, settle), seconds)
