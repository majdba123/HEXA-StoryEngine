"""Velocity-aware directional motion blur: Motion owns it (visual sprint B1/B4).

A camera exposes each frame for part of the frame interval, so a moving element is smeared
along the path it travels during that exposure and is sharp when it rests. Measured in the
approved references (2026-10-16): a sliding character's smear is ~velocity x 0.03 s, is
strongest at peak speed and disappears below ~0.1 width/s; arriving foreground objects
stay legible while they smear.

Motion marks the cues whose drawn position travels far enough during a half-frame
exposure (180-degree shutter at the 30 fps output) to show a visible smear, and records the
exposure in ``params["motion_blur"]``. The renderer evaluates the exact position it draws
and blurs each frame along that frame's own displacement: direction and length follow the
real motion, frames at rest stay untouched. Scale-only motion (pulses, pops) is never
blurred; a Pass2 family follower inherits its leader's blur through the shared transform.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.layout.footprint import AlphaFootprintResolver
from app.models import CompositionBeat, MotionCue, VisualAsset
from app.render.expression import compile_expression
from app.render.motion import FFmpegMotionAdapter

MOTION_BLUR_SHUTTER = 0.5          # fraction of the frame interval (180 degrees)
# Smear lengths as fractions of the content height (the target's reference frame):
MIN_LENGTH = 0.0019                # shorter smears are invisible (about two lines)
MAX_LENGTH = 0.06                  # never smear an element into an unreadable streak
CUT_LENGTH = 4 * MAX_LENGTH        # a larger jump within one exposure is a cut, not motion


@dataclass(frozen=True, slots=True)
class MotionBlurDecision:
    beat_id: str
    asset_id: str
    blurred: bool
    reason: str
    peak_length: float  # fraction of the content height

    def to_payload(self) -> dict:
        return {"beat_id": self.beat_id, "asset_id": self.asset_id, "blurred": self.blurred,
                "reason": self.reason, "peak_length": round(self.peak_length, 5)}


def exposure_lengths(
    x_of_t, y_of_t, times: list[float], *, fps: int, shutter: float,
) -> list[tuple[float, float, float]]:
    """(length px, dx px, dy px) travelled during each frame's exposure, centred on it."""
    half = shutter / (2.0 * fps)
    rows = []
    for t in times:
        dx = x_of_t(t + half) - x_of_t(t - half)
        dy = y_of_t(t + half) - y_of_t(t - half)
        rows.append((math.hypot(dx, dy), dx, dy))
    return rows


class MotionBlurPolicy:
    def __init__(self) -> None:
        self.adapter = FFmpegMotionAdapter()
        self.footprints = AlphaFootprintResolver()
        self.decisions: list[MotionBlurDecision] = []

    def plan(
        self, motion: list[MotionCue], composition: list[CompositionBeat], *,
        width: int, height: int, fps: int, assets: list[VisualAsset] | None = None,
    ) -> list[MotionCue]:
        self.decisions = []
        laid_out = {(beat.beat_id, item.asset_id) for beat in composition for item in beat.items}
        # Assign the strongest visible shutter to the largest laid-out moving icon.
        # Single-asset scenes keep the certified exposure; split/followers abstain.
        assets_by_id = {asset.id: asset for asset in assets or []}
        areas = {}
        for beat in composition:
            for item in beat.items:
                box = self.footprints.resolve(item, assets_by_id.get(item.asset_id)).box
                areas[(beat.beat_id, item.asset_id)] = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
        peaks: dict[tuple[str, str], float] = {}
        for candidate in motion:
            params = candidate.params or {}
            key = (candidate.beat_id, candidate.asset_id)
            if key in laid_out and self.adapter.supports(candidate) and not params.get("family_follow") \
                    and not (params.get("render_constraints") or {}).get("geometry_lock"):
                peaks[key] = self._peak_length(candidate, width=width, height=height, fps=fps)
        movers: dict[str, list[tuple[str, float]]] = {}
        for (beat_id, asset_id), length in peaks.items():
            if length >= MIN_LENGTH:
                movers.setdefault(beat_id, []).append((asset_id, areas.get((beat_id, asset_id), 0.0)))
        lead_blur = {(beat_id, max(rows, key=lambda row: (row[1], row[0]))[0])
                     for beat_id, rows in movers.items() if len(rows) > 1}
        output: list[MotionCue] = []
        for cue in motion:
            params = cue.params if isinstance(cue.params, dict) else {}
            peak = 0.0
            if (cue.beat_id, cue.asset_id) not in laid_out:
                reason = "abstain:not_laid_out"
            elif not self.adapter.supports(cue):
                reason = "abstain:no_motion_program"
            elif (params.get("render_constraints") or {}).get("geometry_lock"):
                reason = "abstain:geometry_locked"
            elif params.get("family_follow"):
                reason = "abstain:family_follows_leader_transform"
            else:
                peak = peaks[(cue.beat_id, cue.asset_id)]
                reason = "blur:visible_smear" if peak >= MIN_LENGTH else "abstain:below_visible_smear"
            blurred = reason.startswith("blur:")
            self.decisions.append(MotionBlurDecision(cue.beat_id, cue.asset_id, blurred, reason, peak))
            if blurred:
                dominant = (cue.beat_id, cue.asset_id) in lead_blur
                cue = cue.model_copy(update={"params": {**params, "motion_blur": {
                    "owner": "MOTION", "shutter": 0.65 if dominant else MOTION_BLUR_SHUTTER,
                    "min_length": MIN_LENGTH, "max_length": MAX_LENGTH,
                    "peak_length": round(peak, 5),
                    **({"visual_mass_lead": True} if dominant else {})}}})
            output.append(cue)
        return output

    def _peak_length(self, cue: MotionCue, *, width: int, height: int, fps: int) -> float:
        starts = [float(cue.start)] + [float(row.start) for row in cue.segments]
        ends = [float(cue.end)] + [float(row.end) for row in cue.segments]
        first, last = max(0.0, min(starts)), max(ends)
        x_expr, y_expr = self.adapter.position_expressions(
            cue=cue, target_x=0, target_y=0, canvas_width=width, canvas_height=height,
            segment_start=0.0, segment_duration=last + 1.0,
        )
        x_of_t, y_of_t = compile_expression(x_expr), compile_expression(y_expr)
        # drawn frames only: the last segment's window closes at ``last``
        frames = range(math.ceil(first * fps - 1e-9), math.ceil(last * fps - 1e-9))
        lengths = exposure_lengths(x_of_t, y_of_t, [n / fps for n in frames], fps=fps,
                                   shutter=MOTION_BLUR_SHUTTER)
        cut = CUT_LENGTH * height
        peak = max((row[0] for row in lengths if row[0] <= cut), default=0.0)
        return peak / max(1, height)
