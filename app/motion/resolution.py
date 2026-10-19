"""PAYOFF resolution (Cinematic VNext2): one clear, readable resolution per beat.

Reference grammar, measured on the two approved references with one instrument
(``style_probe``): when a scene resolves, the established context recedes -- the backdrop
blurs and washes toward grey while the resolving subject stays crisp above it (11-15 % of
reference frames, one wash every 7-17 s) -- and the resolving subject arrives with a
scale pop (median start size 0.61, 5 frames). Story and Choreography decide *what*
resolves and *when*; this pass only decides how visibly, and never moves a Story instant.

Cases (from Story event authority only, never from words or package content):
  BUILD_UP      the result is revealed after the scene's other assets (sequential causal)
  RELATION      the result's event carries an authored relation: its partners stay crisp
  MULTI_OBJECT  the result is more than one visual unit (a Pass2 family counts once)
  SIMULTANEOUS  several resolving events in one beat: the last revealed one resolves
  SHORT_FINAL   too little time after the result settles: crisp arrival only
  OPENING       the result is the first thing on screen: nothing to recede
Priorities: P0 BUILD_UP / RELATION with a readable hold, P1 MULTI_OBJECT with a hold,
P2 a resolution whose backdrop cannot recede safely, P3 SHORT_FINAL / OPENING.

Cause -> consequence (visual sprint, 2026-10-16): when the result's authored relation is a
directional flow/cause relation (the Choreography ``CONNECTABLE_RELATIONS``) and the event's
leader of another family is already on screen, the result is marked ``causal_arrival``:
the arrival pass then lets it arrive moving away from that cause (a short slide along the
cause -> result direction, scale unchanged) when the path is safe, and keeps the pop
otherwise. Without that evidence nothing is invented: the pop stays.

Fail-closed rules for the backdrop wash: something must already be on screen to recede;
nothing else may reveal or still move once it starts; the focus overlaps no backdrop
asset (the renderer draws it above the wash); no backdrop asset continues into the next
scene; a readable hold remains before the cut; washes keep the reference spacing.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from app.assets import AssetManager
from app.choreography.interactions import is_connectable_relation
from app.models import CompositionBeat, LayoutItem, MotionCue, StoryBeat, VisualAsset

from .collision import box
from .contract import accent_readability_floor, comfort_profile_for, segment_contract_violations
from .emphasis_leader import PULSES, grows
from .family import follow, rigid_followers
from .timing import projected_motion_activity_px

_EPS = 1e-6
_FRAME = 1 / 30

# Scale pop. The references pop from 0.43-0.61 size in 4-5 frames (style_probe, n = 55),
# but reviewed HEXA renders read that as rushed and cheap for an explainer: the pop now
# grows from 84 % over up to 9 frames on a smoothstep (zero speed at both ends), and a
# reveal -> settle window shorter than 6 frames keeps the calm opacity entry instead.
# No overshoot.
POP_START_SCALE = 0.84
POP_SECONDS = 9 / 30
POP_MIN_SECONDS = 6 / 30
POP_MAX_GROWTH = 0.85  # frame heights per second
POP_MAX_SCALE_RATE = 1.0  # peak relative growth per second (smoothstep peak = 1.5 x mean)
POP_MIN_ACTIVITY_PX = 20.0

# Icon-focused PAYOFF hit: rest -> ~1.07 -> brief held peak -> rest, owned by the result
# icon. A hit that replaces a Planner PAYOFF must still meet that window's shared
# readability floor (the peak may rise to ICON_HIT_MAX_PEAK_SCALE for it) and every ramp
# keeps the window's comfort ceiling. When no such hit fits, the reference pop is used;
# when that would also break the shared contract, the Planner's validated program stays.
ICON_HIT_PEAK_SCALE = 1.07
ICON_HIT_MAX_PEAK_SCALE = 1.08
ICON_HIT_MIN_RAMP = 0.30  # share of the hit spent on each ramp
ICON_HIT_MIN_HOLD_SECONDS = _FRAME

# Backdrop wash (reference grey-wash runs: median luminance of the washed frame 168-212).
WASH_RAMP_SECONDS = 6 / 30
WASH_MIN_HOLD_SECONDS = 0.55
WASH_MIN_GAP_SECONDS = 7.0
WASH_MAX_LAG_SECONDS = 4 / 30
WASH_FOCUS_OVERLAP = 0.02


@dataclass(frozen=True, slots=True)
class WashStyle:
    name: str
    blur_px: float
    tint: str
    tint_alpha: float


# Candidate A: a white veil (others recede to ~45 %). Candidate B: the reference wash.
VEIL = WashStyle("veil", 0.0, "#FFFFFF", 0.55)
REFERENCE_WASH = WashStyle("reference_wash", 9.0, "#9C9C9C", 0.42)


@dataclass(frozen=True, slots=True)
class ResolutionDecision:
    beat_id: str
    event_id: str | None
    case: str
    priority: str
    focus_asset_ids: tuple[str, ...] = ()
    wash: str = "none"
    arrival: str = "none"
    reasons: tuple[str, ...] = field(default_factory=tuple)
    subject_asset_id: str | None = None
    pulse: str = "none"

    def to_payload(self) -> dict[str, object]:
        return {
            "beat_id": self.beat_id, "event_id": self.event_id, "case": self.case,
            "priority": self.priority, "focus_asset_ids": list(self.focus_asset_ids),
            "subject_asset_id": self.subject_asset_id, "wash": self.wash, "arrival": self.arrival,
            "pulse": self.pulse, "reasons": list(self.reasons),
        }


def _motion_end(cue: MotionCue) -> float:
    return max([float(cue.end)] + [float(row.end) for row in cue.segments])


def _arrival_end(cue: MotionCue) -> float:
    """When the cue's arrival (entry and its own PAYOFF accent) is complete."""
    return max([float(cue.end)] + [float(row.end) for row in cue.segments
                                   if row.phase in {"ENTRY", "PAYOFF"}])


def _overlap(a: LayoutItem, b: LayoutItem) -> float:
    left, right = box(a, (0.0, 0.0, 1.0)), box(b, (0.0, 0.0, 1.0))
    inter = max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0.0, min(left[3], right[3]) - max(left[1], right[1]))
    area = min((left[2] - left[0]) * (left[3] - left[1]), (right[2] - right[0]) * (right[3] - right[1]))
    return inter / max(1e-9, area)


def pop_start_scale(seconds: float, item_height: float) -> float:
    """Start size of a pop that rests at 1.0 after ``seconds``: never below POP_START_SCALE,
    never faster than POP_MAX_GROWTH frame heights nor POP_MAX_SCALE_RATE per second."""
    return max(POP_START_SCALE, 1.0 - POP_MAX_GROWTH * seconds / max(float(item_height), 1e-6),
               1.0 - POP_MAX_SCALE_RATE * seconds / 1.5)


def _pop_frames(start_scale: float, settle: float) -> list[dict]:
    """Ease-out scale pop from ``start_scale`` that rests at 1.0 from ``settle`` on."""
    settle = max(0.0, min(1.0, settle))
    frames = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": round(start_scale, 5), "easing": "smoothstep"},
              {"progress": round(settle, 6), "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"}]
    if settle < 1.0 - _EPS:
        frames.append({"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"})
    return frames


def _icon_hit_safe(item: LayoutItem, layout: dict[str, LayoutItem] | None,
                   peak: float = ICON_HIT_PEAK_SCALE) -> bool:
    """An icon-only pulse must not invent an overlap or leave the frame at its peak."""
    radius_w, radius_h = float(item.width) * peak / 2, float(item.height) * peak / 2
    boosted = (float(item.x) - radius_w, float(item.y) - radius_h,
               float(item.x) + radius_w, float(item.y) + radius_h)
    if min(boosted[0], boosted[1]) < 0.01 or max(boosted[2], boosted[3]) > 0.99:
        return False
    for other in (layout or {}).values():
        if other.asset_id == item.asset_id:
            continue
        normal = (float(item.x) - float(item.width) / 2,
                  float(item.y) - float(item.height) / 2,
                  float(item.x) + float(item.width) / 2,
                  float(item.y) + float(item.height) / 2)
        outside = (float(other.x) - float(other.width) / 2,
                   float(other.y) - float(other.height) / 2,
                   float(other.x) + float(other.width) / 2,
                   float(other.y) + float(other.height) / 2)
        def area(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
            return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
                0.0, min(a[3], b[3]) - max(a[1], b[1]))
        if area(boosted, outside) > area(normal, outside) + 1e-6:
            return False
    return True


def _icon_hit_frames(settle: float, *, peak: float = ICON_HIT_PEAK_SCALE, ramp: float = 0.55) -> list[dict]:
    """One eased scale-up, short readable plateau, single return. No lateral jiggle.

    ``ramp`` is the share of the hit (``settle``) spent growing and, again, returning."""
    settle = max(0.0, min(1.0, settle))
    ramp = max(0.0, min(0.5, ramp))
    peak = round(peak, 5)
    frames = [
        {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
        {"progress": round(settle * ramp, 6), "dx": 0.0, "dy": 0.0,
         "scale": peak, "easing": "smoothstep"},
        {"progress": round(settle * (1.0 - ramp), 6), "dx": 0.0, "dy": 0.0,
         "scale": peak, "easing": "smoothstep"},
        {"progress": round(settle, 6), "dx": 0.0, "dy": 0.0,
         "scale": 1.0, "easing": "smoothstep"},
    ]
    if settle < 1.0 - _EPS:
        frames.append({"progress": 1.0, "dx": 0.0, "dy": 0.0,
                       "scale": 1.0, "easing": "smoothstep"})
    return frames


def _icon_hit_keyframes(
    *, phase: str, window: float, settle: float, item: LayoutItem, params: dict, name: str,
) -> tuple[list[dict] | None, str]:
    """A held icon hit for a ``window``-second program that rests from ``settle`` on.

    The peak is ICON_HIT_PEAK_SCALE, or the smallest larger peak that meets the shared
    readability floor of this window (accent phases); each ramp keeps the comfort ceiling
    rendered QA applies to this program. None when no such hit fits."""
    extent = max(1e-6, min(float(item.width), float(item.height)))
    hit_seconds = max(1e-6, float(window) * float(settle))
    floor = accent_readability_floor(phase, segment_duration=window, active_duration=window,
                                     item_width=item.width, item_height=item.height)
    # A 0.1 % margin keeps the committed (rounded) peak on the readable side of the floor.
    delta = max(ICON_HIT_PEAK_SCALE - 1.0, floor / extent * 1.001)
    if 1.0 + delta > ICON_HIT_MAX_PEAK_SCALE + 1e-9:
        return None, "below_readability_floor"
    speed = comfort_profile_for(phase, program_name=name, params=params).max_normalized_speed
    ramp = max(ICON_HIT_MIN_RAMP, delta * extent / max(speed * hit_seconds, 1e-9))
    if (1.0 - 2.0 * ramp) * hit_seconds < ICON_HIT_MIN_HOLD_SECONDS - _EPS:
        return None, "no_comfortable_hold"
    return _icon_hit_frames(settle, peak=1.0 + delta, ramp=ramp), "applied"


def _static(program: dict | None) -> bool:
    return not any(
        abs(float(f.get("dx", 0.0))) > 1e-9 or abs(float(f.get("dy", 0.0))) > 1e-9
        or abs(float(f.get("scale", 1.0)) - 1.0) > 1e-9
        for f in (program or {}).get("keyframes") or []
    )


class PayoffResolutionDirector:
    def __init__(self, style: WashStyle = REFERENCE_WASH, *, icon_focus_mode: bool = False) -> None:
        self.style = style
        self.icon_focus_mode = icon_focus_mode
        self.decisions: list[ResolutionDecision] = []

    def plan(
        self,
        *,
        story: list[StoryBeat],
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        assets: list[VisualAsset],
        emphasize: Callable[..., tuple[MotionCue | None, str]] | None = None,
    ) -> list[MotionCue]:
        """``emphasize`` (HeroTravelPlanner.secondary_emphasis) gives a resolved subject
        that is not the scene hero, and has no backdrop wash, the reference pulse."""
        self.decisions = []
        assets_by_id = {asset.id: asset for asset in assets}
        layouts = {row.beat_id: {item.asset_id: item for item in row.items} for row in composition}
        index = {(cue.beat_id, cue.asset_id): position for position, cue in enumerate(motion)}
        continuing = self._continuing(story, motion)
        output = list(motion)
        candidates = []
        for beat in story:
            cues = [cue for cue in output if cue.beat_id == beat.id]
            decision, updates, candidate = self._resolve(
                beat=beat, cues=cues, layout=layouts.get(beat.id, {}), assets_by_id=assets_by_id,
                continuing=continuing,
            )
            self.decisions.append(decision)
            for cue in updates:
                output[index[(cue.beat_id, cue.asset_id)]] = cue
            if candidate is not None:
                candidates.append((len(self.decisions) - 1, candidate))
        # The strongest resolutions keep the reference rhythm (one wash per 7 s at most);
        # deterministic: strength, then earlier beat.
        chosen: list[float] = []
        for position, (score, start, anchor, spec) in sorted(candidates, key=lambda row: (-row[1][0][0], -row[1][0][1],
                                                                                          -row[1][0][2], row[0])):
            decision = self.decisions[position]
            if self.icon_focus_mode:
                # Keep the backdrop crisp; focus the actual authored result icon
                # rather than greying/defocusing unrelated scene artwork.
                self.decisions[position] = replace(decision, reasons=decision.reasons +
                                                   ("wash:icon_focused_payoff",))
                continue
            if any(abs(start - other) < WASH_MIN_GAP_SECONDS - _EPS for other in chosen):
                self.decisions[position] = replace(decision, reasons=decision.reasons + ("wash:reference_spacing",))
                continue
            chosen.append(start)
            key = index[(decision.beat_id, anchor)]
            cue = output[key]
            output[key] = cue.model_copy(update={"params": {
                **cue.params, "focus_wash": spec,
                "payoff_resolution": {**(cue.params.get("payoff_resolution") or {}), "wash": self.style.name}}})
            self.decisions[position] = replace(decision, wash=self.style.name)
        if emphasize is not None:
            beats = {beat.id: beat for beat in story}
            for position, decision in enumerate(self.decisions):
                subject = decision.subject_asset_id
                if subject is None or decision.wash != "none" or decision.priority not in {"P0", "P1", "P2"}:
                    continue
                cue = output[index[(decision.beat_id, subject)]]
                if cue.params.get("payoff_icon_hit"):
                    # One held hit already focuses the result icon. Never stack a
                    # second post-settle pulse on the same narrative result.
                    self.decisions[position] = replace(decision, pulse="icon_hit_owns_payoff")
                    continue
                if cue.params.get("scene_hero") or cue.params.get("hero_emphasis"):
                    self.decisions[position] = replace(decision, pulse="abstain:hero_owns_pulse")
                    continue
                if any(row.params.get("hero_emphasis") or any(seg.semantic_action == "EMPHASIZE"
                                                              for seg in row.segments)
                       for row in output if row.beat_id == decision.beat_id):
                    # One emphasis leader per beat: another asset already owns it.
                    self.decisions[position] = replace(decision, pulse="abstain:beat_has_emphasis_leader")
                    continue
                layout = layouts.get(decision.beat_id, {})
                pulsed, why = emphasize(beat=beats[decision.beat_id], cue=cue, item=layout.get(subject),
                                        cues=[row for row in output if row.beat_id == decision.beat_id], layout=layout)
                if pulsed is not None:
                    output[index[(decision.beat_id, subject)]] = pulsed
                self.decisions[position] = replace(decision, pulse=why)
        return output

    @staticmethod
    def _continuing(story: list[StoryBeat], motion: list[MotionCue]) -> set[tuple[str, str]]:
        """(beat, asset) pairs whose picture continues into the next beat."""
        order = [beat.id for beat in story]
        following = dict(zip(order, order[1:]))
        present = {(cue.beat_id, cue.asset_id): cue for cue in motion}
        out: set[tuple[str, str]] = set()
        for cue in motion:
            spec = cue.params.get("handoff_from") if isinstance(cue.params, dict) else None
            if isinstance(spec, dict):
                out.add((str(spec.get("beat_id")), str(spec.get("asset_id"))))
            if isinstance(cue.params, dict) and cue.params.get("referent_carrier"):
                out.add((cue.beat_id, cue.asset_id))
        for (beat_id, asset_id), cue in present.items():
            nxt = following.get(beat_id)
            later = present.get((nxt, asset_id)) if nxt else None
            if later is not None and (later.params.get("semantic_continuity") or {}).get("mode", "ENTER") != "ENTER":
                out.add((beat_id, asset_id))
        return out

    def _resolve(
        self,
        *,
        beat: StoryBeat,
        cues: list[MotionCue],
        layout: dict[str, LayoutItem],
        assets_by_id: dict[str, VisualAsset],
        continuing: set[tuple[str, str]],
    ) -> tuple[ResolutionDecision, list[MotionCue], tuple | None]:
        by_asset = {cue.asset_id: cue for cue in cues}

        def family(asset_id: str) -> str:
            asset = assets_by_id.get(asset_id)
            return AssetManager.family_id(asset) if asset is not None else asset_id

        events = []
        for event in beat.event_authorities:
            if event.needs_review or not event.result_asset_ids:
                continue
            results = [asset_id for asset_id in event.result_asset_ids if asset_id in by_asset]
            if results:
                reveal = min(float(by_asset[asset_id].start) for asset_id in results)
                events.append((reveal, event, results))
        if not events:
            return ResolutionDecision(beat.id, None, "NONE", "-", reasons=("no_resolving_event",)), [], None
        events.sort(key=lambda row: (row[0], row[1].sequence_order or 0, row[1].event_id))
        reveal, event, results = events[-1]
        reasons: list[str] = []
        families = {family(asset_id) for asset_id in results}
        focus = {cue.asset_id for cue in cues if family(cue.asset_id) in families}
        partners = set()
        for asset_id in results:
            for row in by_asset[asset_id].segments:
                partners.update(x for x in (row.source_asset_id, row.target_asset_id) if x and x in by_asset)
        relation = bool(event.relation_kinds) or bool(partners - focus)
        if relation:
            partner_families = {family(asset_id) for asset_id in partners}
            focus |= {cue.asset_id for cue in cues if family(cue.asset_id) in partner_families}
        settle = max(_arrival_end(by_asset[asset_id]) for asset_id in focus if asset_id in results)
        others = [cue for cue in cues if cue.asset_id not in focus]
        earlier = [cue for cue in others if float(cue.start) < reveal - _EPS]
        later = [cue for cue in others if float(cue.start) >= reveal - _EPS]
        if len(events) > 1:
            case = "SIMULTANEOUS"
        elif relation:
            case = "RELATION"
        elif len(families) > 1:
            case = "MULTI_OBJECT"
        elif not earlier:
            case = "OPENING"
        else:
            case = "BUILD_UP"
        hold = float(beat.end) - settle
        if hold < WASH_MIN_HOLD_SECONDS:
            case = "SHORT_FINAL" if case in {"BUILD_UP", "OPENING"} else case
        priority = {"BUILD_UP": "P0", "RELATION": "P0", "MULTI_OBJECT": "P1", "SIMULTANEOUS": "P2",
                    "SHORT_FINAL": "P3", "OPENING": "P3"}[case]

        updates: dict[str, MotionCue] = {}
        arrival = "none"
        # EmphasisLeaderPolicy gives a beat's single growth slot to an explicit pulse first;
        # a held hit beside one would be flattened to a static (unreadable) PAYOFF. The
        # reference pop never grows above rest, so it is used instead.
        pulsed = any(row.semantic_action in PULSES and grows(row.program) for cue in cues for row in cue.segments)
        if self.icon_focus_mode and pulsed:
            reasons.append("icon_hit:beat_has_emphasis_pulse")
        for asset_id in sorted(results):
            cue = updates.get(asset_id, by_asset[asset_id])
            followers = rigid_followers(cue, cues, layout, assets_by_id)
            popped, why = self._pop(cue, layout.get(asset_id), assets_by_id,
                                    family_size=1 if followers is not None else 2,
                                    icon_focus_mode=self.icon_focus_mode and not pulsed, layout=layout)
            if popped is not None:
                if why != "applied":
                    reasons.append(f"{asset_id}:{why}")  # e.g. icon hit abstained, pop kept
                cause = self._cause(event, popped, by_asset=by_asset, layout=layout, family=family)
                if cause is not None:
                    popped = popped.model_copy(update={"params": {**popped.params, "causal_arrival": cause}})
                updates[asset_id] = popped
                arrival = "reference_pop"
                for member in followers or []:
                    # A rigid Pass2 family pops as one unit: its layers follow the primary.
                    updates[member.asset_id] = follow(updates.get(member.asset_id, member), popped)
            elif arrival == "none":
                arrival = f"kept:{why}"

        candidate = None
        if priority in {"P0", "P1"}:
            backdrop_end = max((_motion_end(cue) for cue in others), default=reveal)
            wash_start = max(reveal, backdrop_end)
            lower = {o.asset_id for o in others if o.asset_id in layout}
            if not earlier:
                reasons.append("wash:nothing_to_recede")
            elif later:
                reasons.append("wash:backdrop_reveals_after_result")
            elif wash_start > settle + WASH_MAX_LAG_SECONDS + _EPS:
                reasons.append("wash:backdrop_still_moving")
            elif float(beat.end) - max(wash_start + WASH_RAMP_SECONDS, settle) < WASH_MIN_HOLD_SECONDS - _EPS:
                reasons.append("wash:no_readable_hold")
            elif any(_overlap(layout[a], layout[o]) > WASH_FOCUS_OVERLAP and layout[a].z <= layout[o].z
                     for a in focus if a in layout for o in lower):
                # The renderer draws the focus above the wash; an overlapping backdrop asset
                # that was above it would change the picture.
                reasons.append("wash:backdrop_above_focus")
            elif any((beat.id, cue.asset_id) in continuing for cue in others):
                reasons.append("wash:backdrop_continues_into_next_scene")
            else:
                anchor = sorted(results)[0]
                spec = {
                    "start": round(wash_start, 6), "end": round(float(beat.end), 6),
                    "ramp": round(WASH_RAMP_SECONDS, 6), "blur_px": self.style.blur_px,
                    "tint": self.style.tint, "tint_alpha": self.style.tint_alpha,
                    "focus_asset_ids": sorted(focus), "case": case, "priority": priority,
                    "event_id": event.event_id, "style": self.style.name,
                }
                receding = len({family(cue.asset_id) for cue in others})
                score = (2 if priority == "P0" else 1, min(receding, 6), round(min(hold, 2.0), 3))
                candidate = (score, wash_start, anchor, spec)
        else:
            reasons.append(f"wash:{case.lower()}")

        for asset_id, cue in list(updates.items()):
            params = dict(cue.params)
            params["payoff_resolution"] = {"case": case, "priority": priority, "event_id": event.event_id,
                                           "arrival": arrival}
            updates[asset_id] = cue.model_copy(update={"params": params})
        if candidate is not None and candidate[2] not in updates:
            anchor_cue = by_asset[candidate[2]]
            updates[candidate[2]] = anchor_cue.model_copy(update={"params": {
                **anchor_cue.params, "payoff_resolution": {"case": case, "priority": priority,
                                                           "event_id": event.event_id, "arrival": arrival}}})
        return (
            ResolutionDecision(beat.id, event.event_id, case, priority, tuple(sorted(focus)), "none", arrival,
                               tuple(reasons), subject_asset_id=sorted(results)[0] if len(families) == 1
                               and sum(1 for cue in cues if family(cue.asset_id) in families) == 1 else None),
            list(updates.values()),
            candidate,
        )

    @staticmethod
    def _cause(event, cue: MotionCue, *, by_asset: dict[str, MotionCue], layout: dict[str, LayoutItem],
               family: Callable[[str], str]) -> dict | None:
        """The authored cause a resolving result may visibly come from, or None.

        Evidence only: a directional flow/cause relation on the result (Choreography) and an
        event leader of another family that is laid out and revealed before the result."""
        choreography = (cue.params or {}).get("choreography") or {}
        relation = choreography.get("relationship") or next(iter(event.relation_kinds or []), None)
        if not is_connectable_relation(relation):
            return None
        for leader in event.leader_asset_ids or []:
            other = by_asset.get(leader)
            if (other is None or leader not in layout or family(leader) == family(cue.asset_id)
                    or float(other.start) >= float(cue.start) - _EPS):
                continue
            return {"cause_asset_id": leader, "relationship": str(relation).upper(), "event_id": event.event_id}
        return None

    @staticmethod
    def _pop(
        cue: MotionCue, item: LayoutItem | None, assets_by_id: dict[str, VisualAsset], *,
        family_size: int, icon_focus_mode: bool = False,
        layout: dict[str, LayoutItem] | None = None,
    ) -> tuple[MotionCue | None, str]:
        """Give a resolving subject the reference scale pop when nothing else owns its entry."""
        params = cue.params if isinstance(cue.params, dict) else {}
        if item is None:
            return None, "no_layout"
        if (params.get("semantic_continuity") or {}).get("mode", "ENTER") != "ENTER":
            return None, "not_entering"
        if params.get("hero_travel"):
            return None, "travel_owns_arrival"
        if (params.get("render_constraints") or {}).get("geometry_lock"):
            return None, "geometry_locked_layer"
        if family_size != 1:
            return None, "family_cannot_move_as_one"
        asset = assets_by_id.get(cue.asset_id)
        if asset is not None and asset.parent_asset_id:
            return None, "child_asset"
        if any(row.phase not in {"ENTRY", "PAYOFF", "ESTABLISH"} for row in cue.segments):
            return None, "relation_segment_owns_motion"
        window = float(cue.end) - float(cue.start)
        # Every program that starts with the reveal draws the same pop: the shortest bounds it.
        seconds = min([POP_SECONDS, window] + [float(row.end) - float(row.start) for row in cue.segments
                                               if abs(float(row.start) - float(cue.start)) <= _EPS])
        if seconds + _EPS < POP_MIN_SECONDS:
            return None, "window_below_pop_minimum"
        start_scale = pop_start_scale(seconds, item.height)
        if projected_motion_activity_px(dx=0.0, dy=0.0, scale=start_scale, item_width=item.width,
                                        item_height=item.height) < POP_MIN_ACTIVITY_PX:
            return None, "pop_below_visible_floor"
        hit_reason = None
        if icon_focus_mode and seconds >= 0.29:
            # Begin at rest: a 0.93 -> 1.07 jump over a short authored window
            # exceeds the encoded ESTABLISH comfort bound for a large icon.
            hit, hit_reason = PayoffResolutionDirector._replace_entry(
                cue, item, layout, seconds=seconds, start_scale=1.0, hit=True)
            if hit is not None:
                return hit, "applied"
        popped, why = PayoffResolutionDirector._replace_entry(
            cue, item, layout, seconds=seconds, start_scale=start_scale, hit=False)
        if hit_reason is not None and hit_reason != why:
            # Record why the held hit abstained next to what the reference pop did.
            why = f"{why}:icon_hit_{hit_reason}" if popped is not None else f"{why}+icon_hit_{hit_reason}"
        return popped, why

    @staticmethod
    def _replace_entry(
        cue: MotionCue, item: LayoutItem, layout: dict[str, LayoutItem] | None, *,
        seconds: float, start_scale: float, hit: bool,
    ) -> tuple[MotionCue | None, str]:
        """Replace the reveal's static entry (or the PAYOFF accent that starts with it) by
        one pop or one held icon hit. A replacement is committed only when it satisfies the
        shared segment contract rendered QA applies; otherwise the original cue stays."""
        params = cue.params if isinstance(cue.params, dict) else {}
        window = float(cue.end) - float(cue.start)
        new_params = dict(params)
        new_params["reference_pop"] = {"start_scale": round(start_scale, 5), "seconds": round(seconds, 6),
                                       "profile": "REFERENCE_POP"}
        opacity = params.get("entry_opacity")
        if isinstance(opacity, dict):
            # The pop carries the arrival; the faint first frames shorten to the pop itself.
            new_params["entry_opacity"] = {**opacity, "settle": round(
                min(float(opacity.get("settle", cue.end)), float(cue.start) + max(seconds, 3 * _FRAME)), 6)}

        def build(phase: str, base: dict, duration: float, *, base_entry: bool) -> tuple[dict | None, str]:
            if base_entry:
                name = "reference_icon_hit" if hit else "reference_pop_arrival"
            else:
                name = f"reference_icon_hit_{phase.lower()}" if hit else f"reference_pop_{phase.lower()}"
            program = {**base, "name": name, "settle_progress": 1.0}
            if hit:
                # A PAYOFF accent is judged over its whole window: the hit fills it.
                settle = 1.0 if phase == "PAYOFF" and not base_entry else seconds / duration
                frames, why = _icon_hit_keyframes(phase="ENTRY" if base_entry else phase, window=duration,
                                                  settle=settle, item=item, params=new_params, name=name)
                if frames is None:
                    return None, why
                if not _icon_hit_safe(item, layout, max(row["scale"] for row in frames)):
                    return None, "unsafe_overlap_or_frame"
                program["keyframes"] = frames
                if phase == "PAYOFF" and not base_entry:
                    program["semantic_active_duration"] = round(duration, 6)
            else:
                program["keyframes"] = _pop_frames(start_scale, seconds / duration)
            broken = segment_contract_violations(
                phase="ENTRY" if base_entry else phase, program=program, params=new_params,
                segment_duration=duration, item_width=item.width, item_height=item.height,
                base_entry=base_entry)
            if broken:
                return None, "contract_" + "+".join(sorted({row.code for row in broken})).lower()
            return program, "applied"

        segments = list(cue.segments)
        peak = 1.0
        if not segments:
            if not _static(params.get("program")):
                return None, "certified_gesture_owns_entry"
            program, why = build("ENTRY", dict(params.get("program") or {}), window, base_entry=True)
            if program is None:
                return None, why
            new_params["program"] = program
            peak = max(row["scale"] for row in program["keyframes"])
        else:
            replaced = False
            for position, row in enumerate(segments):
                if float(row.start) >= float(cue.start) + seconds - _EPS:
                    continue
                if row.phase not in {"ENTRY", "PAYOFF"}:
                    return None, "accent_inside_arrival"
                if abs(float(row.start) - float(cue.start)) > _EPS:
                    return None, "segment_starts_inside_arrival"
                if row.phase == "ENTRY" and not _static(row.program):
                    return None, "certified_gesture_owns_entry"
                # A PAYOFF accent that starts with the reveal overrides the entry on screen, so
                # it carries the pop itself (one gesture), keeping its phase and its window.
                program, why = build(row.phase, dict(row.program), float(row.end) - float(row.start),
                                     base_entry=False)
                if program is None:
                    return None, why
                segments[position] = row.model_copy(update={"program": program})
                peak = max([peak] + [frame["scale"] for frame in program["keyframes"]])
                replaced = True
            if not replaced:
                return None, "no_static_entry_to_replace"
        if hit:
            new_params["payoff_icon_hit"] = {"peak_scale": round(peak, 5), "duration": round(seconds, 6),
                                             "motion": "held_scale_no_jitter"}
        return cue.model_copy(update={"params": new_params, "segments": segments}), "applied"
