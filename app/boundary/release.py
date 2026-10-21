from __future__ import annotations

from math import ceil, isfinite

from app.assets import AssetManager
from app.composition.idea_spread import GLIDE_FRAMES
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
from app.motion.visual_flow.direction import focus_handoff_direction
from app.render.transition import SceneTransitionMode, VisualTransitionPolicy
from app.shared.frame_grid import BeatSegment, beat_segments, first_visible_frame
from app.shared.narration import continues_sentence  # noqa: F401  (re-exported for callers)
from app.shared.narration import continues_idea
from app.text.timing.visibility import KEYWORD_HOLD_SECONDS

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
# Reference grammar G16 (docs/reference-motion-grammar.md): the approved references never
# hard-cut between ideas. At the moment the new scene's first element appears, the whole
# old scene leaves as one block in ~6 frames, smeared, travelling the same way as the
# arriving element (a camera-like whip), so the eye is carried from one idea to the next.
WHIP_FRAMES = 6
# Every other idea change clears the old scene to white in a few frames (reference A 12.5 s).
FADE_FRAMES = 5
# Pacing review 2026-10-21: a clear between ideas faded only from the opener frame, so for
# two frames the arriving element landed on the still-opaque old scene. The old scene now
# starts dimming SCENE_FADE_LEAD_FRAMES before the opener and fades over SCENE_FADE_FRAMES
# (a soft dip; it is still partly visible when the new element lands, never a blank frame).
SCENE_FADE_FRAMES = 8
SCENE_FADE_LEAD_FRAMES = 3
# Production switch for the whip; the certified hero-exit / crisp / cut machinery below it
# stays intact (and tested) for every boundary the whip abstains from.
SCENE_WHIP = True
# Idea boards (2026-10-21 frame review of both references): when the Final Package splits
# ONE sentence over several pictures, the references never clear the screen between them.
# Each old element stays until a new element or word lands on its spot and fades just
# before it (reference A 29.5-36 s: the character fades as the newspaper lands where it
# stood); the rest of the idea stays until the next picture is complete. Positions stay the
# authored ones; nothing moves.
IDEA_BOARD = True
# Idea clock (2026-10-21 review of Hacktivist v1: a new picture every 1.9 s, 22 of 40 cuts
# cleared to white): the references hold one idea 3-7 s and Final Package sentences last a
# median 2.7 s, so an idea spans several sentences. A sentence end therefore clears the
# screen only once the current idea has been on screen IDEA_MIN_SECONDS, or when the next
# sentence starts a new topic (no connective: clarity review 2026-10-21, blended scenes);
# otherwise the next picture is built on the same board. A character swap keeps its whip.
IDEA_CLOCK = True
IDEA_MIN_SECONDS = 3.5
BOARD_MAX_UNITS = 5            # carried + arrived element units on screen together
BOARD_LEAD_FRAMES = 2          # an old element starts fading this many frames before the new lands
# A word never shares its spot with fading artwork or another fading word: what it replaces
# has fully faded (FADE_FRAMES) before its first frame.
BOARD_LANDING_GROWTH = 0.15    # a landing starts ~1.28x its size: its footprint grows this share per side
BOARD_CLEARANCE = 0.015        # minimum gap kept between an old element and a new one
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
        # Both margins are needed: a wide reference frame projected onto a taller viewport can have large
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
        text_rows = self._text_rows(text, text_composition, text_motion)
        text_boxes = {beat_id: [(t0, t1, box) for _cue, t0, t1, box in rows] for beat_id, rows in text_rows.items()}
        output: list[SceneBoundaryRelease] = []
        idea_start: float | None = None
        for segment in beat_segments(story, duration=duration, fps=fps):
            if segment.previous_beat is None:
                idea_start = segment.start_frame / fps
                continue
            young = (IDEA_CLOCK and idea_start is not None
                     and segment.start_frame / fps - idea_start < IDEA_MIN_SECONDS)
            row = self._plan_one(
                segment, layouts=layouts, cues=cues, assets=assets_by_id,
                text_boxes=text_boxes.get(segment.beat.id, []), fps=fps,
            )
            whip = self._scene_whip(
                row, segment, layouts=layouts, cues=cues, fps=fps, assets=assets_by_id,
                text_boxes=text_boxes.get(segment.beat.id, []),
                outgoing_text=text_rows.get(segment.previous_beat.id, []), young_idea=young,
            ) if SCENE_WHIP else None
            output.append(whip if whip is not None else self._hero_overlap_exit(
                row, segment, layouts=layouts, cues=cues, assets=assets_by_id,
                text_boxes=text_boxes.get(segment.beat.id, []), fps=fps,
            ))
            if output[-1].audit.get("hero_exit") != "idea_board":
                idea_start = segment.start_frame / fps  # the screen was cleared: a new idea
        return output

    def _scene_whip(
        self,
        row: SceneBoundaryRelease,
        segment: BeatSegment,
        *,
        layouts: dict[str, CompositionBeat],
        cues: dict[tuple[str, str], MotionCue],
        fps: int,
        assets: dict[str, VisualAsset] | None = None,
        text_boxes: list[tuple[float, float, Box]] | None = None,
        outgoing_text: list[tuple[str, float, float, Box]] | None = None,
        young_idea: bool = False,
    ) -> SceneBoundaryRelease | None:
        """The whole outgoing scene whips out as one block when the new scene opens (G16).

        Inside one sentence (an idea board) the old scene is instead replaced in place,
        element by element (``_idea_board_exits``).

        Only on a planned crisp change (HARD_CUT / CRISP_HANDOFF / HOLD_TO_OPENER) and only
        when nothing of the old scene continues (no persistent artwork, referent carrier or
        handoff source, no receding wash): continuity owners keep their certified path. The
        old scene stays still until the unchanged opener frame, then leaves within
        WHIP_FRAMES under the incoming artwork, blurred; Story, narration and every incoming
        instant are unchanged. None keeps the existing boundary behaviour."""
        beat, previous = segment.beat, segment.previous_beat
        assert previous is not None
        layout, previous_layout = layouts.get(beat.id), layouts.get(previous.id)
        # Composition's idea spread built this picture beside the previous one: a free
        # overlap is no reason to let the previous picture go (the board holds it).
        spread = (layout.idea_spread or {}) if layout is not None else {}
        joining = IDEA_BOARD and bool(spread.get("joins")) and spread["joins"] == previous.scene_id
        if (row.mode not in {"HARD_CUT", "CRISP_HANDOFF", "HOLD_TO_OPENER"} and not joining) or row.reason.startswith(
                "abstain:"):
            return None
        if any(beat_id == previous.id and isinstance(cue.params.get("focus_wash"), dict)
               for (beat_id, _), cue in cues.items()):
            return None
        incoming = self._active_items(beat, layout)
        if previous_layout is None or not previous_layout.items or not incoming:
            return None
        legacy = self.classifier.decide(previous, previous_layout, layout, current_beat=beat)
        continuing = {
            spec.get("asset_id") for (beat_id, _), cue in cues.items()
            if beat_id == beat.id and isinstance(spec := cue.params.get("handoff_from"), dict)
        }
        for item in previous_layout.items:
            cue = cues.get((previous.id, item.asset_id))
            if (item.asset_id not in legacy.carry_outgoing_asset_ids
                    or item.asset_id in legacy.persistent_asset_ids or item.asset_id in continuing
                    or (cue is not None and cue.params.get("referent_carrier"))):
                return None
        start_time = segment.start_frame / fps
        first = {item.asset_id: first_visible_frame(
            self._visible_start(beat, cues.get((beat.id, item.asset_id))) - start_time, fps)
            for item in incoming}
        opener = int(row.audit.get("opener_frame", min(first.values())))
        leaving = {item.asset_id for item in previous_layout.items}
        roles_out, roles_in = self._roles(previous), self._roles(beat)
        whip = (any(roles_out.get(asset_id) == "CHARACTER" for asset_id in leaving)
                and any(roles_in.get(asset_id) == "CHARACTER" for asset_id, frame in first.items()
                        if frame == opener))
        # A young idea continues on the board only when the next sentence really continues it
        # (it opens with a connective); a new topic gets its clean change (no blended scenes).
        # Composition's idea spread already built this picture beside the previous one: the
        # board holds the previous picture there (its own glide included).
        if IDEA_BOARD and (joining or continues_sentence(previous.narration)
                           or (young_idea and not whip and continues_idea(beat.narration))):
            board = self._idea_board_exits(segment, previous_layout, incoming, first, opener,
                                           assets=assets or {}, text_boxes=text_boxes or [],
                                           outgoing_text=outgoing_text or [], fps=fps,
                                           spread=joining)
            if board is not None:
                specs, carry, audit = board
                return row.model_copy(update={
                    **({"mode": "HARD_CUT", "opener_at": None, "release_start": None, "release_end": None,
                        "downgrade_reason": f"idea_spread:{row.mode.lower()}"}
                       if row.mode not in {"HARD_CUT", "CRISP_HANDOFF", "HOLD_TO_OPENER"} else {}),
                    "exit_starts": {key: value for key, value in row.exit_starts.items() if key not in leaving},
                    "overlap_exits": specs,
                    "text_carry": carry,
                    "exit_motion_blur": {},
                    "audit": {**row.audit, "hero_exit": "idea_board", "idea_board": audit,
                              **({"idea_spread": {"slot": spread.get("slot"), "scale": spread.get("scale"),
                                                  "glide": audit.get("glide", False)}} if joining else {})},
                })
        if row.mode not in {"HARD_CUT", "CRISP_HANDOFF", "HOLD_TO_OPENER"}:
            return None  # only the idea spread takes over a planned overlap
        # References: a character swap is carried by a whip (A 41 s, B 5 s, B 35 s); every
        # other change of idea clears the old scene to white in a few frames (A 12.5 s).
        frames = WHIP_FRAMES if whip else SCENE_FADE_FRAMES
        begin_frame = opener if whip else max(0, opener - SCENE_FADE_LEAD_FRAMES)
        end_frame = begin_frame + frames
        if end_frame >= segment.frame_count:
            return None
        axis, direction = self._whip_direction(beat, cues, first, opener)
        spec = {"start": round((segment.start_frame + begin_frame) / fps, 6),
                "end": round((segment.start_frame + end_frame) / fps, 6),
                "direction": direction, "axis": axis, "fade": 0.0 if whip else 1.0}
        return row.model_copy(update={
            "exit_starts": {key: value for key, value in row.exit_starts.items() if key not in leaving},
            "overlap_exits": {asset_id: dict(spec) for asset_id in sorted(leaving)},
            "exit_motion_blur": dict(EXIT_MOTION_BLUR) if whip else {},
            "audit": {**row.audit, "hero_exit": "scene_whip" if whip else "scene_fade",
                      "scene_whip": {"frames": frames, "units": len(leaving), "mode": "whip" if whip else "fade",
                                     "axis": "vertical" if axis else "horizontal", "direction": direction}},
        })

    def _idea_board_exits(
        self,
        segment: BeatSegment,
        previous_layout: CompositionBeat,
        incoming: list[LayoutItem],
        first: dict[str, int],
        opener: int,
        *,
        assets: dict[str, VisualAsset],
        text_boxes: list[tuple[float, float, Box]],
        outgoing_text: list[tuple[str, float, float, Box]] | None = None,
        fps: int,
        spread: bool = False,
    ) -> tuple[dict[str, dict[str, float]], dict[str, float], dict] | None:
        """Per-unit exits that replace the old picture in place inside one idea.

        Every outgoing unit (a Pass2 family leaves as one) is held still in the incoming
        segment until the first incoming element or keyword whose footprint (a landing
        starts larger, so it is grown) touches it, and starts fading BOARD_LEAD_FRAMES
        before that frame. At most BOARD_MAX_UNITS units share the screen: beyond that the
        smallest held unit gives way to the arrival. Units nothing touches stay until the
        incoming picture is complete and fade before its segment ends.

        Idea spread (``spread``): the incoming picture was built in the other half, so no
        arrival lands on the old one and no unit cap applies: the whole old picture stays
        until its segment ends, unless a keyword lands on it. A picture still in its full
        frame layout first glides into its half (``hold_*`` of its CompositionBeat) over
        GLIDE_FRAMES from the segment's first frame; each exit spec then carries
        "glide_start"/"glide_end" (absolute seconds), "glide_scale" and the member's centre
        after the glide ("glide_x", "glide_y", frame units).

        A keyword still on screen at the cut stays too (reference G14: the word is part of
        the idea) until the first incoming keyword replaces it or an arrival lands on it,
        never beyond KEYWORD_HOLD_SECONDS after it was spoken. None when nothing would
        outlive the opener (the plain fade then applies).
        """
        last = segment.frame_count - FADE_FRAMES - 1
        if last <= opener:
            return None

        def family(asset_id: str) -> str:
            asset = assets.get(asset_id)
            return AssetManager.family_id(asset) if asset is not None else asset_id

        def footprint(item: LayoutItem) -> Box:
            return self.footprints.resolve(item, assets.get(item.asset_id)).box

        hold = (previous_layout.idea_spread or {}) if spread else {}
        scale = float(hold.get("hold_scale", 1.0))
        pivot = (float(hold.get("hold_pivot_x", 0.0)), float(hold.get("hold_pivot_y", 0.0)))
        to = (float(hold.get("hold_to_x", 0.0)), float(hold.get("hold_to_y", 0.0)))
        glide = spread and (abs(scale - 1.0) > 1e-6 or pivot != to)

        def moved(x: float, y: float) -> tuple[float, float]:
            return to[0] + (x - pivot[0]) * scale, to[1] + (y - pivot[1]) * scale

        units: dict[str, list[LayoutItem]] = {}
        for item in previous_layout.items:
            units.setdefault(family(item.asset_id), []).append(item)
        unit_box = {key: _union([footprint(member) for member in members]) for key, members in units.items()}
        if glide:
            unit_box = {key: (*moved(box[0], box[1]), *moved(box[2], box[3])) for key, box in unit_box.items()}
        arrivals: list[tuple[int, int, Box]] = [
            (first[item.asset_id], 1, _grow(footprint(item), BOARD_LANDING_GROWTH, BOARD_CLEARANCE))
            for item in incoming
        ]
        events = list(arrivals)
        start_time = segment.start_frame / fps
        for t0, _t1, box in text_boxes:
            frame = first_visible_frame(t0 - start_time, fps)
            if frame <= last:
                events.append((max(0, frame), 0, _grow(box, 0.0, BOARD_CLEARANCE)))
        alive = dict.fromkeys(units)
        exit_frame: dict[str, int] = {}
        arrived = 0
        # Idea spread: Text already kept its words off the held picture (within the overlap
        # its contract allows on any artwork), so nothing replaces the held picture.
        for frame, is_art, box in sorted([] if spread else events, key=lambda row: (row[0], row[1])):
            leave_at = max(0, min(last, frame - (BOARD_LEAD_FRAMES if is_art else FADE_FRAMES)))
            for key in [key for key in alive if self._intersects(unit_box[key], box)]:
                exit_frame[key] = leave_at
                alive.pop(key)
            arrived += is_art
            while not spread and alive and len(alive) + arrived > BOARD_MAX_UNITS:
                key = min(alive, key=lambda unit: _area(unit_box[unit]))
                exit_frame[key] = leave_at
                alive.pop(key)
        for key in alive:
            exit_frame[key] = last
        carry: dict[str, float] = {}
        cut = start_time
        # A gliding picture leaves its words behind: they belong to its full-frame layout.
        for cue_id, spoken, visible_end, box in [] if glide else outgoing_text or []:
            if visible_end < cut - 1.5 / fps:
                continue  # already gone before the cut
            word = _grow(box, 0.0, BOARD_CLEARANCE)
            stop = min(spoken + KEYWORD_HOLD_SECONDS, (segment.start_frame + last) / fps)
            for frame, is_art, other in sorted(events, key=lambda row: (row[0], row[1])):
                if not is_art or self._intersects(word, other):
                    lead = BOARD_LEAD_FRAMES if is_art else FADE_FRAMES
                    stop = min(stop, (segment.start_frame + max(0, frame - lead)) / fps)
                    break
            if stop >= cut + 6 / fps:
                carry[cue_id] = round(stop, 6)
        held = [frame - opener for frame in exit_frame.values() if frame > opener]
        if not held and not carry:
            return None
        specs: dict[str, dict[str, float]] = {}
        for key, members in units.items():
            begin = segment.start_frame + exit_frame[key]
            spec = {"start": round(begin / fps, 6), "end": round((begin + FADE_FRAMES) / fps, 6),
                    "direction": 0.0, "axis": 0.0, "fade": 1.0}
            for member in members:
                specs[member.asset_id] = dict(spec)
                if glide:
                    x, y = moved(member.x, member.y)
                    specs[member.asset_id].update({
                        "glide_start": round(segment.start_frame / fps, 6),
                        "glide_end": round((segment.start_frame + min(GLIDE_FRAMES, exit_frame[key])) / fps, 6),
                        "glide_scale": round(scale, 6), "glide_x": round(x, 6), "glide_y": round(y, 6)})
        audit = {"units": len(units), "held_units": len(held), "held_frames_max": max(held, default=0),
                 "left_at_opener": sum(1 for frame in exit_frame.values() if frame <= opener),
                 "replaced_in_place": sum(1 for frame in exit_frame.values() if opener < frame < last),
                 "held_to_picture_end": sum(1 for frame in exit_frame.values() if frame == last),
                 "carried_words": len(carry), **({"glide": True} if glide else {})}
        return specs, carry, audit


    @staticmethod
    def _roles(beat: StoryBeat) -> dict[str, str]:
        """Final Package semantic role of each activated asset of ``beat``."""
        context = beat.semantic_context
        roles = {entity.unit_id: str(entity.role or "").upper() for entity in (context.entities if context else [])}
        return {row.asset_id: roles.get(row.semantic_unit_id or "", "") for row in beat.asset_activations}

    @staticmethod
    def _whip_direction(
        beat: StoryBeat, cues: dict[tuple[str, str], MotionCue], first: dict[str, int], opener: int,
    ) -> tuple[float, float]:
        """(axis, direction) of the whip: the way the opener itself travels, else up."""
        for asset_id, frame in sorted(first.items()):
            if frame != opener:
                continue
            cue = cues.get((beat.id, asset_id))
            program = (cue.params or {}).get("program") if cue is not None else None
            frames = program.get("keyframes") if isinstance(program, dict) else None
            if not frames:
                continue
            dx, dy = float(frames[0].get("dx", 0.0)), float(frames[0].get("dy", 0.0))
            if abs(dy) > abs(dx) and abs(dy) > 1e-6:
                return 1.0, -1.0 if dy > 0 else 1.0   # rises from below: the old scene goes up
            if abs(dx) > 1e-6:
                return 0.0, -1.0 if dx > 0 else 1.0
        return 1.0, -1.0

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
        if held:
            # Protect certified cross-scene referents: even a new orthogonal exit
            # must not change a boundary with a held identity carrier.
            return decided("clean_cut:path_crosses_held_outgoing_artwork:held_referent_protected")
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
                margin=self.exit_margin, vertical_margin=self.vertical_exit_margin,
                # The outgoing direction complements the new subject's initial offset.
                flow_hint=focus_handoff_direction(previous, beat, layouts),
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
        vertical_margin: float = _OFFSCREEN_MARGIN,
        flow_hint: tuple[float, float] | None = None,
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
            box = rest_box(members)
            vector = (shift, 0.0)  # unchanged certified horizontal default
            if flow_hint is not None:
                options = ((-box[2] - margin, 0.0), (1.0 - box[0] + margin, 0.0),
                           (0.0, -box[3] - vertical_margin),
                           (0.0, 1.0 - box[1] + vertical_margin))
                target = (-flow_hint[0], -flow_hint[1])
                options = sorted(options, key=lambda row: (
                    0 if (row[0] * target[0] + row[1] * target[1]) > 0 else 1,
                    abs(row[0]) + abs(row[1])))
                for dx, dy in options:
                    length = abs(dx) + abs(dy)
                    seconds = max(HERO_TRAVEL.minimum_seconds,
                                  SMOOTHSTEP_PEAK * length / HERO_TRAVEL.max_normalized_speed)
                    option_frames = ceil(seconds * fps - _EPS)
                    if option_frames <= window:
                        frames, vector = option_frames, (dx, dy)
                        break
            # Last semantic result covers the scene until the next legal opener.
            fits = index != len(groups) - 1 and frames <= window
            units.append({"members": members, "box": box, "frames": frames, "shift": shift,
                          "vector": vector, "exits": False, "why": None if fits else "time",
                          "fits": fits})
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
        vectors: dict[str, tuple[float, float]] = {}
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
            if flow_hint is not None:
                vectors.update({member.asset_id: unit["vector"] for member in unit["members"]})
        audit = {
            "decision": "complete_exit" if leaving else (
                "clean_cut:exit_path_crosses_another_outgoing_unit" if crossing
                else "clean_cut:exit_cannot_leave_the_frame_in_time" if len(groups) > 1
                else "clean_cut:single_unit_covers_until_opener"),
            "ready_frame": ready_frame, "window_frames": window, "order": leaving, "clean_cut_units": staying}
        if crossing:
            audit["path_blocked_units"] = crossing
        if vectors:
            audit["vectors"] = {key: [round(v[0], 6), round(v[1], 6)]
                                for key, v in sorted(vectors.items())}
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
            x, y = unit.get("vector", (unit["shift"], 0.0))
            scale = 3 * progress ** 2 - 2 * progress ** 3
            return (box[0] + x * scale, box[1] + y * scale,
                    box[2] + x * scale, box[3] + y * scale)

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
    def _text_rows(
        text: TextPlan | None,
        text_composition: list[TextCompositionBeat] | None,
        text_motion: list[TextMotionCue] | None,
    ) -> dict[str, list[tuple[str, float, float, Box]]]:
        """Per beat: (cue id, spoken start, visible end, box) of every placed keyword."""
        cues = {cue.id: cue for cue in (text.cues if text is not None else [])}
        ends = {
            row.text_cue_id: float(row.params.get("visible_end", row.end))
            for row in (text_motion or []) if isinstance(row.params, dict)
        }
        output: dict[str, list[tuple[str, float, float, Box]]] = {}
        for beat in text_composition or []:
            for item in beat.items:
                cue = cues.get(item.text_cue_id)
                if cue is None:
                    continue
                width, height = TextPlacementDirector.estimated_box(cue, scale=item.font_scale)
                box = TextPlacementDirector._box(item.x, item.y, width, height)
                end = max(float(cue.spoken_end), ends.get(cue.id, float(cue.spoken_end)))
                output.setdefault(beat.beat_id, []).append((cue.id, float(cue.spoken_start), end, box))
        return output

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


def _union(boxes: list[Box]) -> Box:
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))


def _grow(box: Box, share: float, margin: float) -> Box:
    dx = (box[2] - box[0]) * share + margin
    dy = (box[3] - box[1]) * share + margin
    return (box[0] - dx, box[1] - dy, box[2] + dx, box[3] + dy)


def _area(box: Box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
