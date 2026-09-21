"""Story-owned V2 timing contract; legacy anchors remain consumable unchanged."""
from __future__ import annotations

import json
import math
from typing import Literal

from pydantic import Field, model_validator

from app.models import AssetActivation, StoryBeat


_WINDOW_EVIDENCE = "story_activation_v2:"


class StoryAssetActivation(AssetActivation):
    phrase_start: float | None = None
    phrase_end: float | None = None
    reveal_start: float | None = None
    semantic_peak: float | None = None
    settle_at: float | None = None
    activation_policy: Literal["OWN_WINDOW", "INHERITED_WINDOW", "SAFE_ABSTENTION"] = (
        "SAFE_ABSTENTION"
    )

    @model_validator(mode="after")
    def validate_window(self) -> StoryAssetActivation:
        times = (self.phrase_start, self.phrase_end, self.reveal_start,
                 self.semantic_peak, self.settle_at)
        if self.activation_policy == "SAFE_ABSTENTION":
            if any(value is not None for value in times):
                raise ValueError("abstention cannot carry a reveal window")
            return self
        if any(value is None or not math.isfinite(value) or value < 0 for value in times):
            raise ValueError("activation window must contain finite nonnegative times")
        if not (
            self.reveal_start <= self.phrase_start <= self.semantic_peak
            <= self.settle_at <= self.phrase_end
        ):
            raise ValueError("activation window must follow aligned phrase order")
        return self

    def with_legacy_evidence(self) -> StoryAssetActivation:
        # Base-typed Pydantic containers intentionally omit subclass fields. Keep a
        # versioned payload in the existing evidence field across that boundary.
        payload = {name: getattr(self, name) for name in (
            "phrase_start", "phrase_end", "reveal_start", "semantic_peak",
            "settle_at", "activation_policy",
        )}
        return self.model_copy(update={"evidence": [
            row for row in self.evidence if not row.startswith(_WINDOW_EVIDENCE)
        ] + [_WINDOW_EVIDENCE + json.dumps(payload, sort_keys=True, allow_nan=False)]})

    @classmethod
    def from_legacy(cls, activation: AssetActivation) -> StoryAssetActivation:
        data = activation.model_dump()
        for row in activation.evidence:
            if row.startswith(_WINDOW_EVIDENCE):
                data.update(json.loads(row[len(_WINDOW_EVIDENCE):]))
        return cls.model_validate(data)


class ScheduledStoryBeat(StoryBeat):
    asset_activations: list[StoryAssetActivation] = Field(default_factory=list)


def schedule_windows(
    activations: list[AssetActivation], beat: StoryBeat, audio_duration: float,
    primary_ids: set[str],
) -> list[StoryAssetActivation]:
    """Bound reveals by phrase rhythm, scene capacity and available pre-roll.

    Completion is reported, never hidden by stretching a semantic phrase into
    unrelated narration. Consumers can distinguish missing material from coverage.
    """
    lower = max(0.0, beat.start)
    upper = min(beat.end, audio_duration,
                beat.audio_end if beat.audio_end is not None else beat.end)
    if not all(math.isfinite(value) for value in (lower, upper)) or upper < lower:
        raise ValueError("invalid Story/audio bounds")
    anchored = [row for row in activations if row.policy != "FALLBACK"
                and row.spoken_start is not None and row.spoken_end is not None]
    capacity = (upper - lower) / max(1, len([r for r in anchored if r.policy != "GROUP"]))
    output: list[StoryAssetActivation] = []
    previous_peak = lower
    for row in sorted(activations, key=lambda r: (
        r.spoken_start if r.spoken_start is not None else math.inf,
        r.policy == "GROUP", r.asset_id,
    )):
        data = row.model_dump()
        start, end = row.spoken_start, row.spoken_end
        if (row.policy == "FALLBACK" or start is None or end is None
                or not math.isfinite(start) or not math.isfinite(end)
                or end <= start or start < lower or end > upper):
            data.update(policy="FALLBACK", spoken_start=None, spoken_end=None,
                        confidence=0.0, source="semantic_abstention")
            data["evidence"] = row.evidence + ["SAFE_ABSTENTION"]
            output.append(StoryAssetActivation(**data).with_legacy_evidence())
            continue
        duration = end - start
        importance = 1.0 if row.asset_id in primary_ids else 0.75
        lead = min(duration * 0.5 * importance, capacity * 0.25,
                   (upper - lower) * 0.05, max(0.0, start - previous_peak))
        output.append(StoryAssetActivation(
            **data, phrase_start=start, phrase_end=end,
            reveal_start=max(lower, start - lead),
            semantic_peak=start + duration * 0.5, settle_at=end,
            activation_policy="INHERITED_WINDOW" if row.policy == "GROUP" else "OWN_WINDOW",
        ).with_legacy_evidence())
        if row.policy != "GROUP":
            previous_peak = start + duration * 0.5

    # Group members receive precisely the parent's window, not a second schedule.
    by_unit = {r.semantic_unit_id: r for r in output
               if r.activation_policy == "OWN_WINDOW" and r.semantic_unit_id}
    for index, row in enumerate(output):
        if row.activation_policy == "INHERITED_WINDOW":
            parent = by_unit.get(row.semantic_unit_id)
            if parent is not None:
                data = row.model_dump()
                for name in ("phrase_start", "phrase_end", "reveal_start",
                             "semantic_peak", "settle_at"):
                    data[name] = getattr(parent, name)
                output[index] = StoryAssetActivation(**data).with_legacy_evidence()

    important = [r for r in output if r.activation_policy == "OWN_WINDOW"]
    if important:
        last = max(important, key=lambda r: r.settle_at)
        audio_start = max(lower, beat.audio_start if beat.audio_start is not None else lower)
        gap = upper - last.settle_at
        typical_phrase = sum(r.phrase_end - r.phrase_start for r in important) / len(important)
        if gap > max((upper - audio_start) * 0.20, typical_phrase):
            last.evidence.extend([
                "EARLY_SCENE_COMPLETION",
                "no_confident_unassigned_late_visual_material",
                f"uncovered_narration_seconds={gap:.6f}",
            ])
    elif output:
        output[0].evidence.append("NO_CONFIDENT_VISUAL_MATERIAL")
    return output
