"""The element the narrator is talking about pulses when it is spoken (user direction 2026-10-20).

When the narration says an element's word (its Final Package activation trigger, or a
keyword cue anchored to it) while that element is already on screen and settled, it gives
one quick "high scale" pulse on that word: up to ``PULSE_SCALES[0]`` in a few frames, then
back to its authored size, ~12 frames in all. The viewer's eye is taken to exactly what is
being said. A first mention needs no pulse: the element lands at that moment (G19).

Fail-closed: one pulse per element per scene; never on a character pose layer that cannot
move as one unit; never where another segment would draw over the pulse; never outside its
beat; every pulse is validated by the shared segment contract encoded QA applies (the peak
steps down for very large elements, else no pulse).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.assets import AssetManager
from app.models import CompositionBeat, MotionCue, MotionSegment, StoryBeat, TextPlan, VisualAsset

from .contract import segment_contract_violations

PULSE_NAME = "reference_spoken_pulse"
PULSE_SCALES = (1.14, 1.1, 1.07)
PULSE_SECONDS = 12 / 30
PULSE_PEAK = 0.3            # share of the pulse spent rising
PULSE_MIN_DELAY = 0.05      # the element must have settled before its word
PULSE_SNAP = 0.15           # a semantic segment this close to the word carries the pulse
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class PulseDecision:
    beat_id: str
    asset_id: str
    at: float
    pulsed: bool
    reason: str


def pulse_program(peak: float, share: float = 1.0, delay: float = 0.0) -> dict:
    """The pulse over ``share`` of its segment, starting after ``delay`` (shares of the
    segment), at rest before and after."""
    share = max(0.05, min(1.0, share))
    delay = max(0.0, min(1.0 - share, delay))
    frames = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0,
               "easing": "ease_out_cubic" if delay <= _EPS else "linear"}]
    if delay > _EPS:
        frames.append({"progress": round(delay, 6), "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"})
    frames.append({"progress": round(delay + PULSE_PEAK * share, 6), "dx": 0.0, "dy": 0.0,
                   "scale": round(peak, 5), "easing": "ease_in_out_cubic"})
    frames.append({"progress": round(delay + share, 6), "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"})
    if delay + share < 1.0 - _EPS:
        frames.append({"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"})
    return {"name": PULSE_NAME, "settle_progress": round(delay + share, 6), "keyframes": frames}


def settled_at(cue: MotionCue) -> float:
    """When the element's entrance is actually over (a landing's own length, else the entry
    segment or the cue window)."""
    params = cue.params if isinstance(cue.params, dict) else {}
    landing = params.get("reference_landing")
    if isinstance(landing, dict):
        return float(cue.start) + float(landing.get("seconds", 0.0))
    start, window = float(cue.start), float(cue.end) - float(cue.start)
    # A slide / pop / travel records its own length as the program's settle_progress.
    ends = [start + window * float((params.get("program") or {}).get("settle_progress", 1.0))]
    ends += [float(row.start) + (float(row.end) - float(row.start)) * float(row.program.get("settle_progress", 1.0))
             for row in cue.segments if row.phase == "ENTRY"]
    return max(ends)


def is_spoken_pulse(program: dict | None) -> bool:
    return str((program or {}).get("name") or "") == PULSE_NAME


class SpokenPulsePolicy:
    def __init__(self) -> None:
        self.decisions: list[PulseDecision] = []

    def apply(
        self, *, story: list[StoryBeat], composition: list[CompositionBeat], motion: list[MotionCue],
        assets: list[VisualAsset], text: TextPlan | None = None,
    ) -> list[MotionCue]:
        self.decisions = []
        assets_by_id = {asset.id: asset for asset in assets}
        layouts = {row.beat_id: {item.asset_id: item for item in row.items} for row in composition}
        output = list(motion)
        index = {(cue.beat_id, cue.asset_id): position for position, cue in enumerate(output)}
        mentions: dict[tuple[str, str], list[float]] = {}
        for beat in story:
            for row in beat.asset_activations:
                if row.spoken_start is not None:
                    mentions.setdefault((beat.id, row.asset_id), []).append(float(row.spoken_start))
        for cue in (text.cues if text is not None else []):
            if cue.anchor_asset_id:
                mentions.setdefault((cue.beat_id, cue.anchor_asset_id), []).append(float(cue.spoken_start))
        beats = {beat.id: beat for beat in story}
        # A spoken reminder is optional. Several animated icons in one short sentence
        # compete with the authored entrances and relation action, so give each picture
        # at most one such accent and leave dense pictures to their primary arrival.
        family_count = {
            beat.id: len({AssetManager.family_id(assets_by_id[item.asset_id])
                          for item in layouts.get(beat.id, {}).values()
                          if item.asset_id in assets_by_id})
            for beat in story
        }
        accented = {cue.beat_id for cue in output
                    if any(is_spoken_pulse(row.program) for row in cue.segments)}
        for (beat_id, asset_id), times in sorted(
            mentions.items(), key=lambda item: (
                float(beats[item[0][0]].start) if item[0][0] in beats else float("inf"),
                min(item[1]), item[0][1]),
        ):
            position = index.get((beat_id, asset_id))
            beat = beats.get(beat_id)
            if position is None or beat is None:
                continue
            cue = output[position]
            settled = settled_at(cue)
            candidates = sorted(t for t in times if t >= settled + PULSE_MIN_DELAY - _EPS)
            if not candidates:
                continue
            at = candidates[0]
            if beat_id in accented or (family_count[beat_id] >= 3
                                       and float(beat.end) - float(beat.start) < 2.4):
                self.decisions.append(PulseDecision(beat_id, asset_id, round(at, 3), False,
                                                    "attention_budget"))
                continue
            pulsed, reason = pulse_at(cue, at=at, beat=beat, item=layouts.get(beat_id, {}).get(asset_id),
                                      beat_cues=[row for row in output if row.beat_id == beat_id],
                                      assets_by_id=assets_by_id)
            self.decisions.append(PulseDecision(beat_id, asset_id, round(at, 3), pulsed is not None, reason))
            if pulsed is not None:
                output[position] = pulsed
                accented.add(beat_id)
        return output


def _still(row: MotionSegment) -> bool:
    return all(abs(float(f.get("dx", 0.0))) <= _EPS and abs(float(f.get("dy", 0.0))) <= _EPS
               and abs(float(f.get("scale", 1.0)) - 1.0) <= _EPS for f in row.program.get("keyframes") or [])


def pulse_at(cue: MotionCue, *, at: float, beat: StoryBeat, item, beat_cues: list[MotionCue],
             assets_by_id: dict[str, VisualAsset], action: str = "EMPHASIZE") -> tuple[MotionCue | None, str]:
    """One pulse of ``cue`` at absolute time ``at`` (shared by the spoken pulse and the
    relation interaction): placed inside a still semantic segment that holds that moment
    (keeping its phase and window), else in its own ESTABLISH segment; fail-closed."""
    params = cue.params if isinstance(cue.params, dict) else {}
    if item is None:
        return None, "no_layout"
    if (params.get("render_constraints") or {}).get("geometry_lock") or params.get("family_follow"):
        return None, "family_layer_follows_its_leader"
    asset = assets_by_id.get(cue.asset_id)
    if asset is not None and asset.parent_asset_id:
        return None, "child_asset"
    family = AssetManager.family_id(asset) if asset is not None else cue.asset_id
    loose = [row for row in beat_cues if row.asset_id != cue.asset_id
             and row.asset_id in assets_by_id and AssetManager.family_id(assets_by_id[row.asset_id]) == family
             and not (row.params.get("render_constraints") or {}).get("geometry_lock")]
    if loose:
        return None, "family_cannot_pulse_as_one"
    if any(is_spoken_pulse(row.program) for row in cue.segments):
        return None, "already_pulsed"
    if at + PULSE_SECONDS > float(beat.end) - 2 / 30:
        return None, "pulse_outside_its_beat"
    for row in beat_cues:
        wash = row.params.get("focus_wash") if isinstance(row.params, dict) else None
        if (isinstance(wash, dict) and cue.asset_id not in (wash.get("focus_asset_ids") or [])
                and at + PULSE_SECONDS > float(wash.get("start", 0.0))):
            return None, "receded_behind_wash"  # a washed backdrop is still
    # A still semantic segment that holds this moment carries the pulse itself.
    host = next((position for position, row in enumerate(cue.segments)
                 if row.phase != "ENTRY" and _still(row)
                 and float(row.start) - PULSE_SNAP <= at and at + PULSE_SECONDS <= float(row.end) + PULSE_SNAP),
                None)
    if host is not None:
        row = cue.segments[host]
        start, duration = float(row.start), float(row.end) - float(row.start)
        begin = max(start, min(at, float(row.end) - PULSE_SECONDS))
        share = min(1.0, PULSE_SECONDS / duration)
        for peak in PULSE_SCALES:
            program = {**row.program, **pulse_program(peak, share, (begin - start) / duration)}
            if segment_contract_violations(phase=row.phase, program=program, params=params,
                                           segment_duration=duration, item_width=item.width,
                                           item_height=item.height):
                continue
            segments = list(cue.segments)
            segments[host] = row.model_copy(update={"program": program})
            return cue.model_copy(update={"segments": segments}), f"pulsed_in_{row.phase.lower()}"
        return None, "contract_rejects_every_peak"
    end = at + PULSE_SECONDS
    # The renderer draws the latest-starting active segment: an overlapping segment wins over
    # the pulse only when it starts with or after it; one that started earlier only yields if
    # it is still (identity), so nothing moving is cut mid-gesture.
    if any(row.phase != "ENTRY" and float(row.start) < end and float(row.end) > at
           and (float(row.start) >= at - _EPS or not _still(row)) for row in cue.segments):
        return None, "another_segment_draws_over_the_pulse"
    for peak in PULSE_SCALES:
        program = pulse_program(peak)
        if segment_contract_violations(phase="ESTABLISH", program=program, params=params,
                                       segment_duration=PULSE_SECONDS, item_width=item.width,
                                       item_height=item.height):
            continue
        segment = MotionSegment(phase="ESTABLISH", start=round(at, 6), end=round(end, 6), program=program,
                                semantic_action=action)
        return cue.model_copy(update={"segments": [*cue.segments, segment]}), "pulsed"
    return None, "contract_rejects_every_peak"
