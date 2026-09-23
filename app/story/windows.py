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


def _semantic_sequence_windows(
    activations: list[AssetActivation],
    *,
    lower: float,
    visual_upper: float,
    speech_upper: float,
) -> dict[str, tuple[float, float]]:
    """Allocate ordered sub-windows inside one spoken semantic phrase.

    Final Package owns semantic grouping/order, WhisperX owns the phrase bounds, and
    Story owns how that finite phrase window is shared. Distinct sequence orders must
    not collapse onto the same first frame. Same-order members intentionally share a
    window because they represent one visual unit.
    """
    groups: dict[str, list[AssetActivation]] = {}
    for row in activations:
        if (
            row.policy == "FALLBACK"
            or row.group_animation_policy != "SEQUENTIAL_WITHIN_PHRASE"
            or not row.semantic_group_id
            or row.sequence_order is None
            or row.spoken_start is None
            or row.spoken_end is None
        ):
            continue
        groups.setdefault(row.semantic_group_id, []).append(row)

    windows: dict[str, tuple[float, float]] = {}
    for rows in groups.values():
        orders = sorted({row.sequence_order for row in rows if row.sequence_order is not None})
        if len(orders) <= 1:
            continue
        # Exact asset phrases may legitimately differ inside one semantic group.
        # Final Package sequence_order still owns visual progression, so reconcile only
        # when those exact speech anchors would collapse or reverse the declared order.
        by_order: dict[int, list[AssetActivation]] = {
            order: [row for row in rows if row.sequence_order == order]
            for order in orders
        }
        natural_starts = [
            min(float(row.spoken_start) for row in by_order[order])
            for order in orders
        ]
        needs_reconciliation = any(
            right <= left + 1e-9
            for left, right in zip(natural_starts, natural_starts[1:])
        )
        if not needs_reconciliation:
            continue

        phrase_start = min(float(row.spoken_start) for row in rows)
        phrase_end = min(
            max(float(row.spoken_end) for row in rows),
            visual_upper,
        )
        if (
            not math.isfinite(phrase_start)
            or not math.isfinite(phrase_end)
            or phrase_start < lower
            or phrase_end > speech_upper + 1e-9
            or phrase_end <= phrase_start
        ):
            continue
        duration = phrase_end - phrase_start
        if duration <= 0.05:
            continue

        distinct_count = len(orders)
        preferred_motion = min(0.80, max(0.18, duration * 0.55))
        minimum_start_gap = 0.025
        maximum_motion_for_gap = duration - minimum_start_gap * (distinct_count - 1)
        if maximum_motion_for_gap >= 0.05:
            motion_duration = min(preferred_motion, maximum_motion_for_gap)
        else:
            motion_duration = 0.05
        motion_duration = min(duration, max(0.05, motion_duration))
        step = (duration - motion_duration) / (distinct_count - 1)
        if step <= 1e-6:
            continue

        rank_by_order = {order: index for index, order in enumerate(orders)}
        for row in rows:
            rank = rank_by_order[row.sequence_order]
            start = phrase_start + step * rank
            end = start + motion_duration
            if rank == distinct_count - 1:
                end = phrase_end
            windows[row.asset_id] = (start, min(end, phrase_end))
    return windows


def schedule_windows(
    activations: list[AssetActivation], beat: StoryBeat, audio_duration: float,
    primary_ids: set[str],
) -> list[StoryAssetActivation]:
    """Bound reveals by phrase rhythm, scene capacity and available pre-roll.

    Completion is reported, never hidden by stretching a semantic phrase into
    unrelated narration. Consumers can distinguish missing material from coverage.
    """
    lower = max(0.0, beat.start)
    visual_upper = min(beat.end, audio_duration)
    speech_upper = min(
        audio_duration, beat.audio_end if beat.audio_end is not None else beat.end,
    )
    if (not all(math.isfinite(value) for value in (lower, visual_upper, speech_upper))
            or visual_upper < lower or speech_upper < lower):
        raise ValueError("invalid Story/audio bounds")
    anchored = [row for row in activations if row.policy != "FALLBACK"
                and row.spoken_start is not None and row.spoken_end is not None]
    capacity = (visual_upper - lower) / max(1, len([r for r in anchored if r.policy != "GROUP"]))
    sequence_windows = _semantic_sequence_windows(
        activations, lower=lower, visual_upper=visual_upper, speech_upper=speech_upper,
    )
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
                or end <= start or start < lower or end > speech_upper
                or start >= visual_upper):
            data.update(policy="FALLBACK", spoken_start=None, spoken_end=None,
                        confidence=0.0, source="semantic_abstention")
            data["evidence"] = row.evidence + ["SAFE_ABSTENTION"]
            output.append(StoryAssetActivation(**data).with_legacy_evidence())
            continue
        sequence_window = sequence_windows.get(row.asset_id)
        if sequence_window is not None:
            reveal_start, settle_at = sequence_window
            semantic_peak = reveal_start + (settle_at - reveal_start) * 0.5
            sequence_evidence = row.evidence + [
                "semantic_group_sequential_window",
                f"group_phrase_start={start:.6f}",
                f"group_phrase_end={end:.6f}",
                f"assigned_sequence_order={row.sequence_order}",
            ]
            output.append(StoryAssetActivation(
                **{**data, "evidence": sequence_evidence},
                phrase_start=reveal_start,
                phrase_end=settle_at,
                reveal_start=reveal_start,
                semantic_peak=semantic_peak,
                settle_at=settle_at,
                activation_policy=(
                    "INHERITED_WINDOW" if row.policy == "GROUP" else "OWN_WINDOW"
                ),
            ).with_legacy_evidence())
            if row.policy != "GROUP":
                previous_peak = semantic_peak
            continue

        duration = end - start
        settle_at = min(end, visual_upper)
        if settle_at <= start:
            data.update(policy="FALLBACK", spoken_start=None, spoken_end=None,
                        confidence=0.0, source="semantic_abstention")
            data["evidence"] = row.evidence + ["SAFE_ABSTENTION", "NO_VISUAL_SETTLE_CAPACITY"]
            output.append(StoryAssetActivation(**data).with_legacy_evidence())
            continue
        importance = 1.0 if row.asset_id in primary_ids else 0.75
        exact_package_binding = row.source == "final_package_semantic_binding"
        lead = 0.0 if exact_package_binding else min(
            duration * 0.5 * importance,
            capacity * 0.25,
            (visual_upper - lower) * 0.05,
            max(0.0, start - previous_peak),
        )
        semantic_peak = min(start + duration * 0.5, settle_at)
        output.append(StoryAssetActivation(
            **data, phrase_start=start, phrase_end=end,
            reveal_start=start if exact_package_binding else max(lower, start - lead),
            semantic_peak=semantic_peak, settle_at=settle_at,
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
        gap = visual_upper - last.settle_at
        if gap > (visual_upper - audio_start) * 0.20:
            last.evidence.extend([
                "EARLY_SCENE_COMPLETION",
                "no_confident_unassigned_late_visual_material",
                f"uncovered_narration_seconds={gap:.6f}",
            ])
    elif output:
        output[0].evidence.append("NO_CONFIDENT_VISUAL_MATERIAL")
    return output
