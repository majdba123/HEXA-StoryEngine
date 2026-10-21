"""Reference grammar G19: objects land in place from a high scale (the "high scale" entry).

Frame-by-frame review of the approved references (2026-10-20, A 7.68-7.95 s magnet, A
16.68-16.85 s cross, B 30.60-30.84 s coin bag): an object that is named does not slide in
from a frame edge. It appears in place, faint, about a quarter larger than its size and
out of focus, then shrinks onto its authored size while it sharpens, in ~8 frames, and
stays still. Characters keep their own entrances (slides, hero travel).

This pass runs on the final Motion. For every entering, non-character object it replaces
the programs that start with the reveal (the base program and every segment that starts
with it, whatever its phase, since the renderer shows the last one) by one landing:
scale ``start_scale -> 1`` on an ease-out, no translation. The landing is committed only
when the shared segment contract (the same one encoded QA applies) accepts it; the start
scale steps down for very large objects and the original entry stays otherwise. Phases,
windows, relation fields, Story instants and authored final geometry never change.

Variety (2026-10-21): half of all entries are landings, and one gesture every two seconds
becomes a pattern the eye stops reading. Four in-place styles express the same "it is here"
moment: ``high`` (the reference G19 landing above), ``grow`` (rises from smaller onto its
size), ``soft`` (a gentle, slower settle with light defocus) and ``bloom`` (grows from smaller
with a small overshoot). A video's first landing is always ``high``; after it a seeded,
weighted rotation never repeats the previous style, and elements revealed together land
together in one style. Every style is scale-only and inside the 1.28x footprint the Boundary
board already reserves, so no path, overlap or text decision changes; each is validated by
the same segment contract, falling back through the other styles, then the original entry.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from app.assets import AssetManager
from app.models import CompositionBeat, LayoutItem, MotionCue, StoryBeat, VisualAsset

from .contract import segment_contract_violations
from .family import follow, rigid_followers

LANDING_PREFIX = "reference_landing"
LANDING_SCALES = (1.28, 1.2, 1.12)
LANDING_SECONDS = 8 / 30
LANDING_MIN_SECONDS = 3 / 30   # short Story windows land faster; the contract lowers the scale
LANDING_FADE_SECONDS = 5 / 30
LANDING_INITIAL_OPACITY = 0.3   # faint, never a blank frame on a scene's first element
LANDING_DEFOCUS_PX = 12.0       # reference-pixel gaussian sigma on the first landing frame
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class LandingStyle:
    name: str
    scales: tuple[float, ...]  # start scales tried in order (the contract may reject them)
    seconds: float
    defocus_px: float
    initial_opacity: float
    overshoot: float = 0.0  # peak scale above rest on the way in (0: none)


LANDING_VARIETY = True
LANDING_STYLES: dict[str, LandingStyle] = {
    "high": LandingStyle("high", LANDING_SCALES, LANDING_SECONDS, LANDING_DEFOCUS_PX, LANDING_INITIAL_OPACITY),
    "grow": LandingStyle("grow", (0.72, 0.8, 0.88), LANDING_SECONDS, 0.0, 0.25),
    "soft": LandingStyle("soft", (1.12, 1.08), 10 / 30, 5.0, 0.2),
    "bloom": LandingStyle("bloom", (0.8, 0.86), 9 / 30, 0.0, 0.25, overshoot=0.04),
}
# Rotation weights: the reference landing stays the most frequent voice.
STYLE_WEIGHTS = {"high": 3.0, "grow": 2.0, "soft": 2.0, "bloom": 1.5}
GROUP_SECONDS = 0.1  # elements revealed this close together land in one style


class StyleRotation:
    """Seeded weighted choice that never repeats the previous style; the first is ``high``."""

    def __init__(self, seed: int) -> None:
        self.rng = np.random.default_rng(seed)
        self.last: str | None = None
        self._pending: str | None = None

    def peek(self) -> str:
        """The next style (stable until committed): never the last one seen."""
        if getattr(self, "_pending", None) is None:
            if self.last is None:
                self._pending = "high"
            else:
                names = [name for name in STYLE_WEIGHTS if name != self.last]
                weights = np.array([STYLE_WEIGHTS[name] for name in names])
                self._pending = names[int(self.rng.choice(len(names), p=weights / weights.sum()))]
        return self._pending

    def commit(self, seen: str) -> None:
        self.last, self._pending = seen, None


def story_seed(story: list[StoryBeat]) -> int:
    text = chr(31).join(f"{beat.id}:{beat.narration}" for beat in story)
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little")


@dataclass(frozen=True, slots=True)
class LandingDecision:
    beat_id: str
    asset_id: str
    landed: bool
    reason: str


def _program(base: dict, name: str, start_scale: float, settle: float, overshoot: float = 0.0) -> dict:
    settle = max(0.05, min(1.0, settle))
    frames = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": round(start_scale, 5), "easing": "ease_out_cubic"}]
    if overshoot > 0:
        frames[0]["easing"] = "ease_in_out_cubic"
        frames.append({"progress": round(settle * 0.62, 6), "dx": 0.0, "dy": 0.0, "scale": round(1.0 + overshoot, 5),
                       "easing": "ease_in_out_cubic"})
    frames.append({"progress": round(settle, 6), "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"})
    if settle < 1.0 - _EPS:
        frames.append({"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"})
    clean = {key: value for key, value in base.items() if key not in {"semantic_active_duration"}}
    return {**clean, "name": name, "settle_progress": round(settle, 6), "keyframes": frames}


def is_landing(program: dict | None) -> bool:
    return str((program or {}).get("name") or "").startswith(LANDING_PREFIX)


class ReferenceLandingPolicy:
    def __init__(self) -> None:
        self.decisions: list[LandingDecision] = []

    def apply(
        self, *, story: list[StoryBeat], composition: list[CompositionBeat], motion: list[MotionCue],
        assets: list[VisualAsset],
    ) -> list[MotionCue]:
        self.decisions = []
        assets_by_id = {asset.id: asset for asset in assets}
        layouts = {row.beat_id: {item.asset_id: item for item in row.items} for row in composition}
        characters = self._characters(story)
        output = list(motion)
        index = {(cue.beat_id, cue.asset_id): position for position, cue in enumerate(output)}
        rotation = StyleRotation(story_seed(story))
        group: tuple[float, str] | None = None  # (reveal start, style) of the last landing group
        for beat in story:
            layout = layouts.get(beat.id, {})
            beat_cues = [cue for cue in output if cue.beat_id == beat.id]
            followed: set[str] = set()
            for cue in sorted(beat_cues, key=lambda row: (float(row.start), row.asset_id)):
                if cue.asset_id in followed:
                    continue
                if not LANDING_VARIETY:
                    style = "high"
                elif group is not None and abs(float(cue.start) - group[0]) <= GROUP_SECONDS:
                    style = group[1]
                else:
                    style = rotation.peek()
                landed, reason = self._land(cue, item=layout.get(cue.asset_id),
                                            character=(beat.id, cue.asset_id) in characters,
                                            asset=assets_by_id.get(cue.asset_id), beat_cues=beat_cues,
                                            layout=layout, assets_by_id=assets_by_id, style=style)
                if landed is not None and LANDING_VARIETY:
                    seen = landed.params["reference_landing"]["style"]
                    if group is None or abs(float(cue.start) - group[0]) > GROUP_SECONDS:
                        rotation.commit(seen)  # what the viewer saw is what the next must differ from
                    group = (float(cue.start), seen)
                self.decisions.append(LandingDecision(beat.id, cue.asset_id, landed is not None, reason))
                if landed is None:
                    continue
                output[index[(beat.id, cue.asset_id)]] = landed
                for member in rigid_followers(cue, beat_cues, layout, assets_by_id) or []:
                    output[index[(beat.id, member.asset_id)]] = follow(member, landed)
                    followed.add(member.asset_id)
        return output

    @staticmethod
    def _characters(story: list[StoryBeat]) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        for beat in story:
            context = beat.semantic_context
            roles = {entity.unit_id: str(entity.role or "").upper()
                     for entity in (context.entities if context else [])}
            for row in beat.asset_activations:
                if roles.get(row.semantic_unit_id or "") == "CHARACTER":
                    found.add((beat.id, row.asset_id))
        return found

    def _land(
        self, cue: MotionCue, *, item: LayoutItem | None, character: bool, asset: VisualAsset | None,
        beat_cues: list[MotionCue], layout: dict[str, LayoutItem], assets_by_id: dict[str, VisualAsset],
        style: str = "high",
    ) -> tuple[MotionCue | None, str]:
        params = cue.params if isinstance(cue.params, dict) else {}
        if item is None:
            return None, "no_layout"
        if character or params.get("scene_hero") or params.get("hero_travel") or params.get("hero_entry"):
            return None, "character_keeps_its_entrance"
        if (params.get("semantic_continuity") or {}).get("mode", "ENTER") != "ENTER":
            return None, "not_entering"
        if (params.get("render_constraints") or {}).get("geometry_lock") or params.get("family_follow"):
            return None, "family_layer"
        if asset is not None and asset.parent_asset_id:
            return None, "child_asset"
        family = AssetManager.family_id(asset) if asset is not None else cue.asset_id
        size = sum(1 for row in beat_cues
                   if (AssetManager.family_id(assets_by_id[row.asset_id]) if row.asset_id in assets_by_id
                       else row.asset_id) == family)
        if size > 1 and rigid_followers(cue, beat_cues, layout, assets_by_id) is None:
            return None, "family_cannot_move_as_one"
        start = float(cue.start)
        reveal_rows = [row for row in cue.segments if abs(float(row.start) - start) <= _EPS]
        window = float(cue.end) - start
        limit = min([window] + [float(row.end) - float(row.start) for row in reveal_rows])
        if min(LANDING_SECONDS, limit) + _EPS < LANDING_MIN_SECONDS:
            return None, "window_below_landing_minimum"
        order = [style] + [name for name in LANDING_STYLES if name != style]
        for candidate in (LANDING_STYLES[name] for name in order):
            seconds = min(candidate.seconds, limit)
            for start_scale in candidate.scales:
                landed = self._try(cue, params, item, candidate, start_scale, seconds, start, window)
                if landed is not None:
                    reason = "landed" if candidate.name == style else f"landed:{candidate.name}_after_{style}"
                    return landed, reason
        return None, "contract_rejects_every_landing_scale"

    @staticmethod
    def _try(cue: MotionCue, params: dict, item: LayoutItem, style: LandingStyle, start_scale: float,
             seconds: float, start: float, window: float) -> MotionCue | None:
        """One candidate landing, or None when the shared contract rejects any of its programs."""
        new_params = {key: value for key, value in params.items()
                      if key not in {"reference_slide", "reference_pop", "causal_arrival"}}
        new_params["reference_landing"] = {
            "start_scale": start_scale, "seconds": round(seconds, 6), "defocus_px": style.defocus_px,
            "profile": "REFERENCE_POP", "style": style.name,
        }
        new_params["entry_opacity"] = {"initial": style.initial_opacity, "start": round(start, 6),
                                       "settle": round(start + min(LANDING_FADE_SECONDS, seconds), 6)}
        new_params["entry_grammar"] = {**(params.get("entry_grammar") or {}), "arrival": "LANDING"}
        base = dict(params.get("program") or {})
        new_params["program"] = _program(base, f"{LANDING_PREFIX}_arrival", start_scale,
                                         seconds / max(window, _EPS), style.overshoot)
        broken = False
        if not cue.segments and segment_contract_violations(
                phase="ENTRY", program=new_params["program"], params=new_params, segment_duration=window,
                item_width=item.width, item_height=item.height, base_entry=True):
            broken = True
        segments = []
        for row in cue.segments:
            if abs(float(row.start) - start) <= _EPS and not broken:
                duration = float(row.end) - float(row.start)
                program = _program(dict(row.program), f"{LANDING_PREFIX}_{row.phase.lower()}",
                                   start_scale, seconds / max(duration, _EPS), style.overshoot)
                if segment_contract_violations(phase=row.phase, program=program, params=new_params,
                                               segment_duration=duration, item_width=item.width,
                                               item_height=item.height, base_entry=row.phase == "ENTRY"):
                    broken = True
                    break
                row = row.model_copy(update={"program": program})
            segments.append(row)
        if not broken:
            return cue.model_copy(update={"params": new_params, "segments": segments})
        return None
