"""Hero travel entry (VP4): one authoritative leader per scene arrives from off-frame.

Authorized product contract (2026-10-14), deliberately narrow:

* Only ONE asset per scene beat may travel: Choreography's primary asset, else the beat's
  single unique authored event owner (RESULT, else LEADER). Everything else keeps the
  certified entry contracts.
* Anticipation: travel begins after the latest earlier reveal in the same beat (never
  before the beat, never ahead of an earlier authored sibling) and lands exactly on the
  hero's existing Motion settle, which Story ties to the spoken word. Story timing,
  narration alignment and scene duration are unchanged. A scene opener never travels
  (its first frames would be an empty canvas).
* HERO_TRAVEL comfort profile: smoothstep path (zero velocity at both ends) whose peak
  speed is at most ``HERO_TRAVEL.max_normalized_speed`` frame units per second and whose
  duration is at least ``HERO_TRAVEL.minimum_seconds``.
* The start pose is outside the visible frame on every supported projection (projected
  letterbox padding included), so it genuinely enters. Travel is horizontal only.
* The full continuous sweep (union of the start and final boxes; every edge is linear in
  progress) may not cover another visible asset beyond its authored overlap, nor any text
  visible during the travel. When no direction is safe and fast enough the hero keeps its
  certified entry and the exact reason is recorded.
* The hero's own RESULT arrival pop (PAYOFF, no relation, no connection) is superseded by
  the travel; any relation/interaction segment during the travel window makes it abstain.

Post-settle hero emphasis (a separate animation, never the 0.94 entry scale): after the
hero has fully settled and rested long enough to be recognised, one restrained
1.0 -> 1+d (rise) -> 1+d (held, so the viewer registers it) -> 1.0 (release) scale
gesture that finishes before Rhythm's read hold. d is the strongest restrained amplitude
(5 % down to 3 %, at most 6 % where the readability floor needs it; reviewed renders found
the 7-8 % reference pulses aggressive) that passes the readability floor, the ESTABLISH
comfort speed, the frame and every authored neighbour; composed text later trims it again
(``fit_emphasis_to_text``). Without time for
the whole held gesture there is no pulse. Selective: one emphasis leader per beat (see
``emphasis_leader``), never in two consecutive scenes for the same subject, never while
another asset makes an independent accent.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from app.assets import AssetManager
from app.choreography import ChoreographyPlan
from app.targets import frame_size
from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment, StoryBeat, VisualAsset

from .collision import authored_overlap_ratio, box
from .family import family_of, follow, rigid_followers
from .visual_flow.direction import focus_handoff_direction
from .timing import (
    MotionComfortProfile,
    motion_comfort,
    semantic_readability_floor_px,
)

# Authorized VP4 hero-travel contract (2026-10-14): at most 1.0 frame widths/s, at least
# 0.40 s. VNext2 had raised it to 1.25 w/s / 0.30 s; reviewed renders found entries and
# exits at that speed rushed, so travel (and the Boundary exits timed with it) is back
# inside the authorized contract. A path that needs more speed keeps its fallback.
HERO_TRAVEL = MotionComfortProfile(target_seconds=0.60, minimum_seconds=0.40, max_normalized_speed=1.0)
SMOOTHSTEP_PEAK = 1.5  # peak derivative of 3p^2 - 2p^3
_OFFSCREEN_MARGIN = 0.01
_ANTICIPATION_GAP = 2 / 30  # never share a first frame with the earlier reveal
_OVERLAP_SLACK = 0.02
EMPHASIS_RANGE = (0.03, 0.06)  # certified default upper bound
# Existing amplitudes remain stable for old callers, scenes and tests.
EMPHASIS_CANDIDATES = (0.05, 0.045, 0.04, 0.035, 0.03)
# Only prominent subjects with a proved cross-scene gaze handoff may grow more.
FLOW_EMPHASIS_LIMIT = 0.07
FLOW_EMPHASIS_CANDIDATES = (0.07, 0.065, 0.06, *EMPHASIS_CANDIDATES)
# The held gesture: rise over the first 35 %, hold to 65 %, release over the last 35 %.
EMPHASIS_SECONDS = 0.90
EMPHASIS_MIN_SECONDS = 0.60
EMPHASIS_RISE, EMPHASIS_HOLD_END = 0.35, 0.65
# A scene opener that holds the frame alone at least this long gets the reference pulse.
HOLD_ALONE_SECONDS = 1.0
# Reference grammar (docs/reference-motion-grammar.md, 2026-10-20 full-length review): the
# approved references never pulse a subject that is already at rest. Emphasis is carried
# by arrival, a drawn arrow and the grey wash, so every post-settle pulse abstains.
POST_SETTLE_PULSES = False
_EMPHASIS_PAUSE = 6 / 30  # the settled subject is recognised before it is emphasised
_HOLD_GRID_MARGIN = 2 / 30
_YIELD_ACTIONS = {"DEEMPHASIZE", "FOCUS_HANDOFF"}
_EPS = 1e-6

Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class HeroTravelDecision:
    beat_id: str
    asset_id: str | None
    decision: str  # "TRAVEL" or "ABSTAIN"
    reason: str
    start: float | None = None
    settle: float | None = None
    dx: float | None = None
    peak_speed: float | None = None
    emphasis: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__slots__}


def _amplitudes(readable: float, *, boost: bool = False) -> list[float]:
    """Reference amplitudes; larger focus subjects may use a gated stronger set."""
    floor = max(EMPHASIS_RANGE[0], readable)
    candidates = FLOW_EMPHASIS_CANDIDATES if boost else EMPHASIS_CANDIDATES
    return sorted({c for c in candidates if c + _EPS >= floor} | {round(floor, 5)}, reverse=True)


def _intersection(a: Box, b: Box) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(a: Box) -> float:
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


class HeroTravelPlanner:
    def __init__(self, *, horizontal_padding: float = 0.0) -> None:
        # Extra reference-frame padding so the start pose is off-screen on every projection.
        self.margin = _OFFSCREEN_MARGIN + max(0.0, float(horizontal_padding))
        self.decisions: list[HeroTravelDecision] = []
        self._sweeps: dict[tuple[str, str], tuple[float, float, Box]] = {}
        self.withdrawn: set[tuple[str, str]] = set()

    def plan(
        self,
        *,
        story: list[StoryBeat],
        composition: list[CompositionBeat],
        choreography: ChoreographyPlan | None,
        motion: list[MotionCue],
        assets: list[VisualAsset],
        text_boxes: dict[str, list[tuple[float, float, Box]]] | None = None,
        referent_carriers: set[tuple[str, str]] | None = None,
    ) -> list[MotionCue]:
        """Plan hero travel + emphasis. Text may be unknown yet (``text_boxes`` None): the
        pipeline composes Text once against this Motion, then calls ``revoke_through_text``."""
        text_boxes = text_boxes or {}
        self.decisions = []
        self._sweeps = {}
        self._emphases: dict[tuple[str, str], tuple[LayoutItem, dict[str, LayoutItem]]] = {}
        assets_by_id = {asset.id: asset for asset in assets}
        layouts = {layout.beat_id: {item.asset_id: item for item in layout.items} for layout in composition}
        layout_beats = {row.beat_id: row for row in composition}
        index = {(cue.beat_id, cue.asset_id): position for position, cue in enumerate(motion)}
        continuing = {  # outgoing carriers a later cue continues (Sprint 7 referents)
            (spec.get("beat_id"), spec.get("asset_id"))
            for cue in motion
            if isinstance(spec := cue.params.get("handoff_from"), dict)
        } | set(referent_carriers or ())  # authored referent carriers belong to Sprint 7
        output = [
            # Boundary must see authored referent carriers whether or not Sprint 7 has
            # attached its handoff yet (it may hold them into the next scene).
            cue.model_copy(update={"params": {**cue.params, "referent_carrier": True}})
            if (cue.beat_id, cue.asset_id) in (referent_carriers or ()) else cue
            for cue in motion
        ]
        emphasized_previous: str | None = None  # family pulsed in the previous scene
        for beat_index, beat in enumerate(story):
            cues = [cue for cue in motion if cue.beat_id == beat.id]
            hero_id, reason = self._hero(beat, choreography, cues)
            if hero_id is None:
                self.decisions.append(HeroTravelDecision(beat.id, None, "ABSTAIN", reason))
                emphasized_previous = None
                continue
            position = index[(beat.id, hero_id)]
            if (beat.id, hero_id) in continuing:
                # An authored referent carrier belongs to Sprint 7 continuity: no travel, no
                # emphasis, and no hero mark, so Boundary's exit never depends on whether
                # the continuity transaction has attached its handoff yet.
                self.decisions.append(HeroTravelDecision(beat.id, hero_id, "ABSTAIN",
                                                         "locked_family_or_referent_carrier",
                                                         emphasis="abstain:referent_carrier"))
                emphasized_previous = None
                continue
            # Motion's hero authority for later owners (Boundary's full-frame exit).
            output[position] = output[position].model_copy(
                update={"params": {**output[position].params, "scene_hero": True}})
            cue = output[position]
            item = layouts.get(beat.id, {}).get(hero_id)
            plan, reason = self._fit(
                beat=beat, cue=cue, item=item, cues=cues, layout=layouts.get(beat.id, {}),
                assets_by_id=assets_by_id, text=text_boxes.get(beat.id, []),
                continues=(beat.id, hero_id) in continuing,
            )
            row = HeroTravelDecision(beat.id, hero_id, "ABSTAIN", reason)
            if plan is not None:
                start, dx, speed = plan
                output[position] = self._apply(cue, start=start, dx=dx, speed=speed)
                # A rigid Pass2 family travels as one unit: its layers follow the primary.
                for member in rigid_followers(cue, cues, layouts.get(beat.id, {}), assets_by_id) or []:
                    output[index[(beat.id, member.asset_id)]] = follow(member, output[position])
                row = HeroTravelDecision(beat.id, hero_id, "TRAVEL", reason, round(start, 6),
                                         round(float(cue.end), 6), round(dx, 6), round(speed, 4))
            family = (AssetManager.family_id(assets_by_id[hero_id]) if hero_id in assets_by_id else hero_id)
            # Reference pulses come every 2-10 s (n = 25); only the same subject pulsing
            # again in the very next scene reads as repetition.
            if emphasized_previous == family:
                emphasis, why = None, "abstain:same_subject_pulsed_in_previous_scene"
            else:
                previous = story[beat_index - 1] if beat_index else None
                # A large, new narrative-focus leader can receive a stronger held
                # pulse, but the certified default is untouched for other scenes.
                boosted = (
                    item is not None and float(item.width) * float(item.height) >= 0.04
                    and beat.primary_asset_ids == [hero_id]
                    and focus_handoff_direction(previous, beat, layout_beats) is not None
                )
                emphasis, why = self._emphasis(
                    beat=beat, cue=output[position], item=item, cues=cues,
                    layout=layouts.get(beat.id, {}), continues=(beat.id, hero_id) in continuing,
                    scale_boost=boosted,
                )
            if emphasis is not None:
                output[position] = emphasis
                self._emphases[(beat.id, hero_id)] = (item, layouts.get(beat.id, {}))
            emphasized_previous = family if emphasis is not None else None
            self.decisions.append(HeroTravelDecision(
                row.beat_id, row.asset_id, row.decision, row.reason, row.start, row.settle, row.dx,
                row.peak_speed, why))
        return output

    def hold_emphasis(
        self,
        *,
        story: list[StoryBeat],
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        assets: list[VisualAsset],
    ) -> list[MotionCue]:
        """A subject that opens its scene and then holds the frame alone for at least
        HOLD_ALONE_SECONDS gets the reference pulse after it settles (references pulse
        held subjects every 2-10 s). Every pulse rule applies; never the same subject in
        two consecutive scenes."""
        assets_by_id = {asset.id: asset for asset in assets}
        layouts = {row.beat_id: {item.asset_id: item for item in row.items} for row in composition}
        index = {(cue.beat_id, cue.asset_id): position for position, cue in enumerate(motion)}
        output = list(motion)
        self.hold_decisions: list[dict[str, str]] = []
        previous: set[str] = set()
        for beat in story:
            cues = [cue for cue in output if cue.beat_id == beat.id]
            pulsed = {family_of(cue.asset_id, assets_by_id) for cue in cues if cue.params.get("hero_emphasis")}
            if not cues:
                previous = set()
                continue
            opener = min(cues, key=lambda cue: (float(cue.start), cue.asset_id))
            family = family_of(opener.asset_id, assets_by_id)
            settle = max([float(opener.end)] + [float(row.end) for row in opener.segments])
            alone_until = min((float(cue.start) for cue in cues if family_of(cue.asset_id, assets_by_id) != family),
                              default=float(beat.end))
            reason = None
            if opener.params.get("hero_emphasis"):
                reason = "opener_already_pulses"
            elif (pulsed or any(row.semantic_action == "EMPHASIZE" for cue in cues for row in cue.segments)
                  # A resolved result's held icon hit already owns this beat's emphasis.
                  or any(cue.params.get("payoff_icon_hit") for cue in cues)):
                reason = "beat_already_has_emphasis_leader"  # one emphasis leader per beat
            elif (opener.params.get("render_constraints") or {}).get("geometry_lock"):
                reason = "locked_layer"
            elif alone_until - settle < HOLD_ALONE_SECONDS - _EPS:
                reason = "not_alone_long_enough"
            elif family in previous:
                reason = "same_subject_pulsed_in_previous_scene"
            else:
                pulsed_cue, why = self.secondary_emphasis(
                    beat=beat, cue=opener, item=layouts.get(beat.id, {}).get(opener.asset_id), cues=cues,
                    layout=layouts.get(beat.id, {}))
                if pulsed_cue is not None:
                    output[index[(beat.id, opener.asset_id)]] = pulsed_cue
                    pulsed = pulsed | {family}
                reason = why
            self.hold_decisions.append({"beat_id": beat.id, "asset_id": opener.asset_id, "decision": reason})
            previous = pulsed
        return output

    def secondary_emphasis(
        self, *, beat: StoryBeat, cue: MotionCue, item: LayoutItem | None, cues: list[MotionCue],
        layout: dict[str, LayoutItem],
    ) -> tuple[MotionCue | None, str]:
        """The same post-settle pulse for a beat's resolved subject when it is not the hero
        (secondary focus). Every hero rule applies (competing accents, comfort speed,
        collisions, frame, read hold); composed text trims it later like the hero's."""
        emphasis, why = self._emphasis(beat=beat, cue=cue, item=item, cues=cues, layout=layout, continues=False)
        if emphasis is not None and item is not None:
            self._emphases[(beat.id, cue.asset_id)] = (item, layout)
        return emphasis, why

    @property
    def sweeps(self) -> dict[tuple[str, str], tuple[float, float, Box]]:
        """Planned travel paths: (start, settle, swept box) per (beat, hero)."""
        return dict(self._sweeps)

    def revoke_through_text(
        self, motion: list[MotionCue], baseline: list[MotionCue],
        text_boxes: dict[str, list[tuple[float, float, Box]]],
    ) -> list[MotionCue]:
        """After Text is composed (once) against this Motion: a travel whose sweep crosses a
        text box visible during the travel returns to its certified baseline cue. Text
        composed against the earlier-visible hero stays collision-free for the later one."""
        revoked = set()
        self.withdrawn: set[tuple[str, str]] = revoked
        for (beat_id, asset_id), (start, settle, sweep) in self._sweeps.items():
            if any(t0 < settle - _EPS and t1 > start + _EPS and _intersection(sweep, tb) > 0
                   for t0, t1, tb in text_boxes.get(beat_id, [])):
                revoked.add((beat_id, asset_id))
        if not revoked:
            return motion
        self.decisions = [
            HeroTravelDecision(row.beat_id, row.asset_id, "ABSTAIN", "path_crosses_composed_text",
                               emphasis=("revoked_with_travel" if row.emphasis == "applied" else row.emphasis))
            if (row.beat_id, row.asset_id) in revoked else row
            for row in self.decisions
        ]
        base = {(cue.beat_id, cue.asset_id): cue for cue in baseline}
        # The layers of a family that travelled as one unit return with it.
        layers = {(cue.beat_id, cue.asset_id) for cue in motion
                  if (cue.beat_id, (cue.params or {}).get("family_follow")) in revoked}
        return [
            base[key].model_copy(update={"params": {**base[key].params, "scene_hero": True}})
            if (key := (cue.beat_id, cue.asset_id)) in revoked
            else base[key] if key in layers else cue
            for cue in motion
        ]

    def fit_emphasis_to_text(
        self, motion: list[MotionCue], text_boxes: dict[str, list[tuple[float, float, Box]]],
    ) -> list[MotionCue]:
        """After Text is composed: an emphasis never grows the hero into visible text.

        The pulse steps down through the reference amplitudes until the scaled hero adds no
        overlap with any text box visible during the pulse; below the readable amplitude
        it is removed and the hero simply rests. Recorded on the hero's decision.
        """
        changes: dict[tuple[str, str], str] = {}
        output = list(motion)
        for position, cue in enumerate(motion):
            key = (cue.beat_id, cue.asset_id)
            pulse = (cue.params or {}).get("hero_emphasis") if isinstance(cue.params, dict) else None
            if key not in self._emphases or not isinstance(pulse, dict):
                continue
            item, layout = self._emphases[key]
            start, end, scale = float(pulse["start"]), float(pulse["end"]), float(pulse["scale"])
            visible = [tb for t0, t1, tb in text_boxes.get(cue.beat_id, [])
                       if t0 < end - _EPS and t1 > start + _EPS]
            rest = box(item, (0.0, 0.0, 1.0))

            def adds_overlap(delta: float) -> bool:
                scaled = box(item, (0.0, 0.0, 1.0 + delta))
                return any(_intersection(scaled, tb) > _intersection(rest, tb) + 1e-9 for tb in visible)

            current = scale - 1.0
            if not adds_overlap(current):
                continue
            frame_w, frame_h = frame_size()
            asset_px = min(float(item.width) * frame_w, float(item.height) * frame_h)
            readable = semantic_readability_floor_px("ESTABLISH", item_width=item.width, item_height=item.height,
                                                     duration=end - start) * 1.05 / max(asset_px, 1.0)
            delta = next((c for c in _amplitudes(readable)
                          if c < current - _EPS
                          and not adds_overlap(c)
                          and self._scaled_problem(item, cue.asset_id, layout, c) is None), None)
            segments = []
            for row in cue.segments:
                if row.semantic_action == "HERO_EMPHASIS":
                    if delta is None:
                        continue
                    frames = [{**f, "scale": round(1.0 + delta, 5)} if abs(float(f.get("scale", 1.0)) - 1.0) > 1e-9
                              else f for f in row.program.get("keyframes") or []]
                    row = row.model_copy(update={"program": {**row.program, "keyframes": frames}})
                segments.append(row)
            params = dict(cue.params)
            if delta is None:
                params.pop("hero_emphasis", None)
                # The entry segment the pulse carried in leaves with it: the cue is restored.
                segments = [row for row in segments if row.program.get("carried_for") != "hero_emphasis"]
                changes[key] = "revoked:pulse_would_grow_into_composed_text"
            else:
                params["hero_emphasis"] = {**pulse, "scale": round(1.0 + delta, 5)}
                changes[key] = f"applied:trimmed_for_text_{1.0 + delta:.2f}"
            output[position] = cue.model_copy(update={"segments": segments, "params": params})
        if changes:
            self.decisions = [
                HeroTravelDecision(row.beat_id, row.asset_id, row.decision, row.reason, row.start, row.settle,
                                   row.dx, row.peak_speed, changes[(row.beat_id, row.asset_id)])
                if (row.beat_id, row.asset_id) in changes else row
                for row in self.decisions
            ]
        return output

    @staticmethod
    def _hero(beat: StoryBeat, choreography: ChoreographyPlan | None,
              cues: list[MotionCue]) -> tuple[str | None, str]:
        present = {cue.asset_id for cue in cues}
        directive = choreography.for_beat(beat.id) if choreography is not None else None
        if directive is not None and directive.primary_asset_id in present:
            return directive.primary_asset_id, "choreography_primary"
        owners = set()
        for event in beat.event_authorities:
            if event.needs_review:
                continue
            ids = event.result_asset_ids or event.leader_asset_ids
            if len(ids) == 1 and ids[0] in present:
                owners.add(ids[0])
        if len(owners) == 1:
            return next(iter(owners)), "unique_event_owner"
        return None, "no_unique_authoritative_leader"

    def _fit(
        self, *, beat: StoryBeat, cue: MotionCue, item: LayoutItem | None, cues: list[MotionCue],
        layout: dict[str, LayoutItem], assets_by_id: dict[str, VisualAsset],
        text: list[tuple[float, float, Box]], continues: bool,
    ) -> tuple[tuple[float, float, float] | None, str]:
        params = cue.params if isinstance(cue.params, dict) else {}
        if item is None:
            return None, "no_composition_item"
        if (params.get("semantic_continuity") or {}).get("mode", "ENTER") != "ENTER":
            return None, "not_entering"
        if (params.get("render_constraints") or {}).get("geometry_lock") or params.get("handoff_from") or continues:
            return None, "locked_family_or_referent_carrier"
        followers = rigid_followers(cue, cues, layout, assets_by_id)
        if followers is None:
            return None, "pass2_family_cannot_move_as_one_unit"
        unit = {cue.asset_id} | {row.asset_id for row in followers}
        settle = float(cue.end)
        if any(row.phase != "ENTRY" and float(row.start) < settle - _EPS and not self._result_pop(row)
               for row in cue.segments):
            return None, "relation_segment_during_travel"
        earlier = [float(other.start) for other in cues
                   if other.asset_id != cue.asset_id and float(other.start) < float(cue.start) - _EPS]
        if not earlier:
            return None, "scene_opener_would_travel_over_empty_canvas"
        start = max(max(earlier) + _ANTICIPATION_GAP, float(beat.start))
        duration = settle - start
        if duration + _EPS < HERO_TRAVEL.minimum_seconds:
            return None, f"insufficient_time:{duration:.3f}s<{HERO_TRAVEL.minimum_seconds:.2f}s"
        left = -(float(item.x) + float(item.width) / 2 + self.margin)
        right = 1.0 - (float(item.x) - float(item.width) / 2) + self.margin
        reasons = []
        for dx in sorted((left, right), key=abs):
            speed = SMOOTHSTEP_PEAK * abs(dx) / duration
            if speed > HERO_TRAVEL.max_normalized_speed + _EPS:
                reasons.append(f"speed:{speed:.2f}/s")
                continue
            begin, final = box(item, (dx, 0.0, 1.0)), box(item, (0.0, 0.0, 1.0))
            sweep = (min(begin[0], final[0]), min(begin[1], final[1]),
                     max(begin[2], final[2]), max(begin[3], final[3]))
            blocker = None
            for other in cues:
                if other.asset_id in unit or float(other.start) >= settle - _EPS:
                    continue
                other_item = layout.get(other.asset_id)
                if other_item is None:
                    continue
                target = box(other_item, (0.0, 0.0, 1.0))
                allowed = authored_overlap_ratio(item, other_item) + _OVERLAP_SLACK
                if _intersection(sweep, target) / max(1e-9, min(_area(final), _area(target))) > allowed:
                    blocker = "path_crosses_visible_asset"
                    break
            if blocker is None and any(t0 < settle - _EPS and t1 > start + _EPS and _intersection(sweep, tb) > 0
                                       for t0, t1, tb in text):
                blocker = "path_crosses_visible_text"
            if blocker is None:
                self._sweeps[(beat.id, cue.asset_id)] = (start, settle, sweep)
                return (start, dx, speed), "travel"
            reasons.append(blocker)
        return None, "no_safe_direction:" + ",".join(reasons)

    @staticmethod
    def _emphasis(
        *, beat: StoryBeat, cue: MotionCue, item: LayoutItem | None, cues: list[MotionCue],
        layout: dict[str, LayoutItem], continues: bool, scale_boost: bool = False,
    ) -> tuple[MotionCue | None, str]:
        params = cue.params if isinstance(cue.params, dict) else {}
        if not POST_SETTLE_PULSES:
            return None, "abstain:reference_has_no_held_pulse"
        if item is None:
            return None, "abstain:no_composition_item"
        if (params.get("render_constraints") or {}).get("geometry_lock") or continues:
            return None, "abstain:locked_family_or_referent_carrier"
        settle = max([float(cue.end)] + [float(row.end) for row in cue.segments])
        rhythm = (params.get("semantic_focus") or {}).get("rhythm")
        hold_ms = rhythm.get("minimum_read_hold_ms") if isinstance(rhythm, dict) else None
        if not isinstance(hold_ms, (int, float)) or hold_ms <= 0:
            return None, "abstain:no_rhythm_read_hold_authority"
        start = settle + _EMPHASIS_PAUSE
        # The read hold is measured on encoded frames: the pulse's last moving frame and
        # the cut both land on the frame grid, so keep a 2-frame margin before the hold.
        end = min(start + EMPHASIS_SECONDS, float(beat.end) - float(hold_ms) / 1000 - _HOLD_GRID_MARGIN)
        if end - start + _EPS < EMPHASIS_MIN_SECONDS:
            # No room to rise, be registered and release calmly: a rushed pulse is worse
            # than none, so the subject simply rests.
            return None, f"abstain:no_time_after_settle({max(0.0, end - start):.3f}s)"
        duration = end - start
        frame_w, frame_h = frame_size()
        asset_px = min(float(item.width) * frame_w, float(item.height) * frame_h)
        floor = semantic_readability_floor_px("ESTABLISH", item_width=item.width, item_height=item.height,
                                              duration=duration)
        readable = floor * 1.05 / max(asset_px, 1.0)
        upper_limit = FLOW_EMPHASIS_LIMIT if scale_boost else EMPHASIS_RANGE[1]
        if readable > upper_limit + _EPS:
            return None, f"abstain:readable_emphasis_needs_{readable:.3f}_scale"
        extent = min(float(item.width), float(item.height))
        delta, why = None, "abstain:no_safe_reference_amplitude"
        for candidate in _amplitudes(readable, boost=scale_boost):
            if candidate * extent / (EMPHASIS_RISE * duration) > motion_comfort("ESTABLISH").max_normalized_speed:
                why = "abstain:emphasis_exceeds_comfort_speed"
                continue
            problem = HeroTravelPlanner._scaled_problem(item, cue.asset_id, layout, candidate)
            if problem is not None:
                why = problem
                continue
            delta = candidate
            break
        if delta is None:
            return None, why
        for other in cues:
            if other.asset_id == cue.asset_id:
                continue
            for row in other.segments:
                if (row.semantic_action not in _YIELD_ACTIONS and float(row.start) < end - _EPS
                        and float(row.end) > start + _EPS and HeroTravelPlanner._moves(row.program)):
                    return None, "abstain:competing_accent_from_other_asset"
            if (float(other.start) < end - _EPS and float(other.end) > start + _EPS
                    and HeroTravelPlanner._moves((other.params or {}).get("program") or {})):
                return None, "abstain:competing_entry_from_other_asset"
        program = {
            "name": "hero_settle_emphasis",
            "settle_progress": 1.0,
            "keyframes": [
                {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
                {"progress": EMPHASIS_RISE, "dx": 0.0, "dy": 0.0, "scale": round(1.0 + delta, 5),
                 "easing": "smoothstep"},
                {"progress": EMPHASIS_HOLD_END, "dx": 0.0, "dy": 0.0, "scale": round(1.0 + delta, 5),
                 "easing": "smoothstep"},
                {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
            ],
        }
        segments = list(cue.segments)
        if not any(row.phase == "ENTRY" for row in segments):
            # Segmented cues render their entry from an ENTRY segment only.
            # Same convention as MotionPlanner._carried_entry_segment: the carried base entry
            # keeps its qa_base_entry verification class.
            segments.insert(0, MotionSegment(phase="ENTRY", start=float(cue.start), end=float(cue.end),
                                             program={**deepcopy(params.get("program") or {}), "qa_base_entry": True,
                                                      "carried_for": "hero_emphasis"}))
        segments.append(MotionSegment(phase="ESTABLISH", start=start, end=end, program=program,
                                      semantic_action="HERO_EMPHASIS", involvement="FOCUS"))
        new_params = dict(params)
        new_params["hero_emphasis"] = {"start": round(start, 6), "end": round(end, 6),
                                       "scale": round(1 + delta, 5)}
        return cue.model_copy(update={"segments": segments, "params": new_params}), "applied"

    @staticmethod
    def _scaled_problem(item: LayoutItem, asset_id: str, layout: dict[str, LayoutItem], delta: float) -> str | None:
        """Why the hero scaled by ``1 + delta`` would be unsafe, or None."""
        scaled = box(item, (0.0, 0.0, 1.0 + delta))
        for other_id, other in layout.items():
            if other_id == asset_id:
                continue
            allowed = authored_overlap_ratio(item, other) + _OVERLAP_SLACK
            target = box(other, (0.0, 0.0, 1.0))
            if _intersection(scaled, target) / max(1e-9, min(_area(scaled), _area(target))) > allowed:
                return "abstain:scaled_hero_would_collide"
        if scaled[0] < -_EPS or scaled[1] < -_EPS or scaled[2] > 1 + _EPS or scaled[3] > 1 + _EPS:
            return "abstain:scaled_hero_would_clip"
        return None

    @staticmethod
    def _moves(program: dict) -> bool:
        return any(abs(float(f.get("dx", 0.0))) > 1e-9 or abs(float(f.get("dy", 0.0))) > 1e-9
                   or abs(float(f.get("scale", 1.0)) - 1.0) > 1e-9 for f in program.get("keyframes") or [])

    @staticmethod
    def _result_pop(row: MotionSegment) -> bool:
        """The RESULT's own arrival accent: no relation, no connection, no other asset."""
        return (row.phase == "PAYOFF" and str(row.involvement or "").upper() == "RESULT"
                and not row.connection and not row.target_asset_id and not row.source_asset_id
                and not row.relationship)

    @staticmethod
    def _apply(cue: MotionCue, *, start: float, dx: float, speed: float) -> MotionCue:
        program = {
            "name": "hero_travel_entry",
            "settle_progress": 1.0,
            "keyframes": [
                {"progress": 0.0, "dx": dx, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
                {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
            ],
        }
        params = {key: value for key, value in cue.params.items() if key not in ("entry_opacity", "hero_entry")}
        # Independent copies: a projected target rescales every program in place, so a
        # shared keyframe list would be scaled twice.
        params["program"] = deepcopy(program)
        # A travelling hero enters fully opaque: it is off-screen until it crosses the edge.
        params["entry_grammar"] = {"opacity": False, "reason": "hero_travel"}
        params["hero_travel"] = {"start": round(start, 6), "settle": round(float(cue.end), 6),
                                 "dx": round(dx, 6), "peak_speed": round(speed, 4),
                                 "profile": "HERO_TRAVEL", "story_reveal": round(float(cue.start), 6)}
        settle = float(cue.end)
        segments = [
            MotionSegment(phase="ENTRY", start=start, end=settle, program=deepcopy(program),
                          semantic_event_id=row.semantic_event_id, involvement=row.involvement)
            if row.phase == "ENTRY" else row
            for row in cue.segments
            if not (row.phase != "ENTRY" and float(row.start) < settle - _EPS and HeroTravelPlanner._result_pop(row))
        ]
        if len(segments) < len(cue.segments):
            params["hero_travel"]["superseded"] = "result_arrival_pop"
        if segments and not any(row.phase == "ENTRY" for row in segments):
            # Segmented cues render their entry from an ENTRY segment only.
            segments.insert(0, MotionSegment(phase="ENTRY", start=start, end=settle, program=deepcopy(program)))
        return cue.model_copy(update={"start": start, "params": params, "segments": segments})
