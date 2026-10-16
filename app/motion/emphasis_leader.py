"""One emphasis leader per beat (Cinematic VNext2 restraint pass).

Reviewed real renders showed several cutouts of one beat growing above their authored size
at the same moment (event-chain arrival overshoots, relation accents, hero / secondary /
hold pulses), and the same cutout growing twice in one beat. The rule, applied once every
Motion planner has run:

* at most ONE Pass2 family per beat grows above its authored rest size, and only once;
* the leader comes from planning authority, never from words: a Sprint 4.1 character
  emphasis, else the scene hero's settle emphasis, else another settle emphasis, else -
  when nobody pulses - the resolved PAYOFF subject, the scene hero or Composition's
  semantic focus, if its own arrival overshoots;
* a leader with a settle emphasis keeps that pulse and its arrival rests at authored size
  (no overshoot before the pulse); a leader without one keeps only its first overshoot;
* every other family keeps its translation and its scale-in from below, never grows above
  rest, and loses any settle pulse. A Sprint 4.1 character emphasis is certified and is
  never removed.

Only scale values above 1.0 are lowered to 1.0 (or a whole pulse is removed), so nothing
can grow into a neighbour or into composed text, Story instants and Composition geometry
are untouched, and supporting de-emphasis (a dip below rest) is kept.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models import CompositionBeat, MotionCue, StoryBeat, VisualAsset

from .family import family_of

_EPS = 1e-6
PROTECTED_PULSE = "EMPHASIZE"            # Sprint 4.1 character emphasis (certified)
PULSES = {"EMPHASIZE", "HERO_EMPHASIS"}  # explicit post-settle emphasis segments


def grows(program: dict | None) -> bool:
    """True when the program draws its cutout above the authored rest size."""
    return any(float(frame.get("scale", 1.0)) > 1.0 + _EPS for frame in (program or {}).get("keyframes") or [])


def _flatten(program: dict) -> dict:
    """The same program resting at authored size wherever it would grow above it."""
    return {**program, "keyframes": [
        {**frame, "scale": 1.0} if float(frame.get("scale", 1.0)) > 1.0 + _EPS else dict(frame)
        for frame in program.get("keyframes") or []
    ]}


@dataclass(frozen=True, slots=True)
class EmphasisLeaderDecision:
    beat_id: str
    leader: str | None
    source: str
    flattened: tuple[str, ...] = field(default_factory=tuple)
    removed_pulses: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, object]:
        return {"beat_id": self.beat_id, "leader": self.leader, "source": self.source,
                "flattened": list(self.flattened), "removed_pulses": list(self.removed_pulses)}


@dataclass(frozen=True, slots=True)
class _Lead:
    family: str
    keep: str        # "pulse" | "overshoot"
    start: float     # start of the kept gesture (family layers share it)


class EmphasisLeaderPolicy:
    def __init__(self) -> None:
        self.leaders: dict[str, _Lead | None] = {}
        self.decisions: list[EmphasisLeaderDecision] = []

    def plan(
        self,
        *,
        story: list[StoryBeat],
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        assets: list[VisualAsset],
    ) -> list[MotionCue]:
        """Choose each beat's leader once, then enforce it."""
        assets_by_id = {asset.id: asset for asset in assets}
        focus = {row.beat_id: row.semantic_focus_asset_id for row in composition}
        self.leaders, self._sources, self._changes = {}, {}, {}
        for beat in story:
            cues = [cue for cue in motion if cue.beat_id == beat.id]
            self.leaders[beat.id], self._sources[beat.id] = self._choose(cues, focus.get(beat.id), assets_by_id)
        return self.enforce(motion, assets=assets)

    def enforce(self, motion: list[MotionCue], *, assets: list[VisualAsset]) -> list[MotionCue]:
        """Apply the chosen leaders; called again after passes that may restore an earlier cue."""
        assets_by_id = {asset.id: asset for asset in assets}
        output = []
        for cue in motion:
            updated, flattened, removed = self._enforce_one(
                cue, self.leaders.get(cue.beat_id), family_of(cue.asset_id, assets_by_id))
            if flattened or removed:
                flat, gone = self._changes.get(cue.beat_id, (set(), set()))
                self._changes[cue.beat_id] = (flat | ({cue.asset_id} if flattened else set()),
                                              gone | ({cue.asset_id} if removed else set()))
            output.append(updated)
        self.decisions = [
            EmphasisLeaderDecision(beat_id, lead.family if lead else None, self._sources[beat_id],
                                   tuple(sorted(self._changes.get(beat_id, (set(), set()))[0])),
                                   tuple(sorted(self._changes.get(beat_id, (set(), set()))[1])))
            for beat_id, lead in self.leaders.items()
        ]
        return output

    @staticmethod
    def _choose(
        cues: list[MotionCue], focus_asset_id: str | None, assets_by_id: dict[str, VisualAsset],
    ) -> tuple[_Lead | None, str]:
        pulses = []
        for cue in cues:
            hero = bool((cue.params or {}).get("scene_hero"))
            for row in cue.segments:
                if row.semantic_action in PULSES and grows(row.program):
                    rank = 0 if row.semantic_action == PROTECTED_PULSE else (1 if hero else 2)
                    pulses.append((rank, float(row.start), cue.asset_id))
        if pulses:
            rank, start, asset_id = min(pulses)
            source = {0: "character_emphasis", 1: "hero_settle_emphasis", 2: "settle_emphasis"}[rank]
            return _Lead(family_of(asset_id, assets_by_id), "pulse", start), source

        def first_overshoot(cue: MotionCue) -> float | None:
            starts = [float(row.start) for row in cue.segments if grows(row.program)]
            if not cue.segments and grows((cue.params or {}).get("program")):
                starts.append(float(cue.start))
            return min(starts) if starts else None

        ranked = (
            ("payoff_subject", [cue for cue in cues if (cue.params or {}).get("payoff_resolution")]),
            ("scene_hero", [cue for cue in cues if (cue.params or {}).get("scene_hero")]),
            ("semantic_focus", [cue for cue in cues if cue.asset_id == focus_asset_id]),
        )
        for source, candidates in ranked:
            for cue in sorted(candidates, key=lambda row: (float(row.start), row.asset_id)):
                start = first_overshoot(cue)
                if start is not None:
                    return _Lead(family_of(cue.asset_id, assets_by_id), "overshoot", start), source
        return None, "none"

    @staticmethod
    def _enforce_one(cue: MotionCue, lead: _Lead | None, family: str) -> tuple[MotionCue, bool, bool]:
        is_leader = lead is not None and lead.family == family
        params = dict(cue.params or {})
        segments, flattened, removed = [], False, False
        drop_pulse = False
        for row in cue.segments:
            if row.semantic_action in PULSES and grows(row.program):
                keep = row.semantic_action == PROTECTED_PULSE or (
                    is_leader and lead.keep == "pulse" and abs(float(row.start) - lead.start) <= _EPS)
                if not keep:  # only a HERO_EMPHASIS pulse can reach here
                    removed = drop_pulse = True
                    continue
                segments.append(row)
                continue
            if grows(row.program) and not (
                    is_leader and lead.keep == "overshoot" and abs(float(row.start) - lead.start) <= _EPS):
                row = row.model_copy(update={"program": _flatten(row.program)})
                flattened = True
            segments.append(row)
        if drop_pulse:
            params.pop("hero_emphasis", None)
            # The ENTRY segment the pulse carried in leaves with it: the cue is restored.
            segments = [row for row in segments if row.program.get("carried_for") != "hero_emphasis"]
        program = params.get("program")
        keep_base = is_leader and lead.keep == "overshoot" and not cue.segments \
            and abs(float(cue.start) - lead.start) <= _EPS
        if isinstance(program, dict) and grows(program) and not keep_base:
            params["program"] = _flatten(program)
            flattened = True
        if not (flattened or removed):
            return cue, False, False
        params["emphasis_leader"] = {"leader": lead.family if lead else None, "is_leader": is_leader,
                                     "flattened": flattened, "removed_pulse": removed}
        return cue.model_copy(update={"params": params, "segments": segments}), flattened, removed
