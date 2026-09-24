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


def same_precise_trigger(left: AssetActivation, right: AssetActivation) -> bool:
    """Sequence order may split only genuinely identical semantic trigger windows.

    Precise narration timing is the stronger authority whenever assets point at
    different script spans. This prevents an authored visual-order hint from moving an
    ACTION after a later OBJECT/RESULT phrase. Sequence order remains useful for several
    visuals intentionally bound to the exact same phrase.
    """
    left_chars = (left.trigger_char_start, left.trigger_char_end)
    right_chars = (right.trigger_char_start, right.trigger_char_end)
    if None not in left_chars and None not in right_chars:
        return left_chars == right_chars
    if (
        left.spoken_start is None
        or left.spoken_end is None
        or right.spoken_start is None
        or right.spoken_end is None
    ):
        return False
    return (
        abs(float(left.spoken_start) - float(right.spoken_start)) <= 0.04
        and abs(float(left.spoken_end) - float(right.spoken_end)) <= 0.06
    )


def semantic_visual_order(row: AssetActivation) -> tuple[int, int]:
    """Return one shared deterministic visual-order key for Story and QA.

    Explicit Final Package semantic_event_order remains authoritative whenever it is
    present. Assets without event metadata occupy lane 0 so contextual/support visuals
    cannot disable authored event progression for the rest of the exact trigger cohort.
    """
    return (
        int(row.semantic_event_order) if row.semantic_event_order is not None else 0,
        int(row.sequence_order) if row.sequence_order is not None else 10_000,
    )


def _semantic_sequence_windows(
    activations: list[AssetActivation],
    *,
    lower: float,
    visual_upper: float,
    speech_upper: float,
    next_semantic_hits: dict[str, float] | None = None,
) -> dict[str, tuple[float, float]]:
    """Allocate sequence sub-windows only inside one *identical* spoken trigger.

    Final Package sequence_order describes visual progression, but precise script spans
    describe WHEN meaning is spoken. Those authorities are compatible only when several
    visuals share the same semantic phrase. If the phrase spans differ, Story preserves
    their natural narration timing and sequence_order becomes a tie-breaker only.
    """
    semantic_groups: dict[str, list[AssetActivation]] = {}
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
        semantic_groups.setdefault(row.semantic_group_id, []).append(row)

    windows: dict[str, tuple[float, float]] = {}
    for group_rows in semantic_groups.values():
        clusters: list[list[AssetActivation]] = []
        for row in sorted(
            group_rows,
            key=lambda item: (
                float(item.spoken_start),
                item.trigger_char_start if item.trigger_char_start is not None else math.inf,
                item.sequence_order if item.sequence_order is not None else 10_000,
                item.asset_id,
            ),
        ):
            cluster = next(
                (
                    rows
                    for rows in clusters
                    if rows and same_precise_trigger(rows[0], row)
                ),
                None,
            )
            if cluster is None:
                clusters.append([row])
            else:
                cluster.append(row)

        for rows in clusters:
            orders = sorted({semantic_visual_order(row) for row in rows})
            if len(orders) <= 1:
                continue

            phrase_start = min(float(row.spoken_start) for row in rows)
            next_distinct_hit = min(
                (
                    float(next_semantic_hits[row.asset_id])
                    for row in rows
                    if next_semantic_hits is not None
                    and row.asset_id in next_semantic_hits
                ),
                default=visual_upper,
            )
            phrase_end = min(
                max(float(row.spoken_end) for row in rows),
                visual_upper,
                next_distinct_hit,
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
            maximum_motion_for_gap = (
                duration - minimum_start_gap * (distinct_count - 1)
            )
            if maximum_motion_for_gap >= 0.05:
                motion_duration = min(preferred_motion, maximum_motion_for_gap)
            else:
                motion_duration = 0.05
            motion_duration = min(duration, max(0.05, motion_duration))
            step = (duration - motion_duration) / (distinct_count - 1)
            if step <= 1e-6:
                continue

            rank_by_order = {
                order: index for index, order in enumerate(orders)
            }
            for row in rows:
                rank = rank_by_order[semantic_visual_order(row)]
                start = phrase_start + step * rank
                finish = start + motion_duration
                if rank == distinct_count - 1:
                    finish = phrase_end
                windows[row.asset_id] = (
                    start,
                    min(finish, phrase_end),
                )
    return windows


def _attention_role(row: AssetActivation, beat: StoryBeat) -> str:
    event_roles = set(row.semantic_event_roles)
    if "LEADER" in event_roles and "RESULT" in event_roles:
        return "RESULT"
    if "LEADER" in event_roles:
        return "PRIMARY"
    if "RESULT" in event_roles:
        return "RESULT"
    if "CONTEXT" in event_roles:
        return "CONTEXT"
    visual_focus = str(row.visual_focus or "").upper()
    if visual_focus in {"RESULT", "PRIMARY", "SUPPORT", "CONTEXT"}:
        return visual_focus
    if row.visual_state:
        return "STATE"
    if row.semantic_unit_id and beat.semantic_context is not None:
        entity = next(
            (
                item
                for item in beat.semantic_context.entities
                if item.unit_id == row.semantic_unit_id
            ),
            None,
        )
        if entity is not None and entity.role:
            return str(entity.role).upper()
    return "SUPPORT"


def _attention_focus_duration(
    row: AssetActivation,
    beat: StoryBeat,
    *,
    available: float,
) -> float:
    """Reference-style one-shot focus duration followed by a static authored hold."""
    role = _attention_role(row, beat)
    target = {
        "RESULT": 0.32,
        "STATE": 0.30,
        "PRIMARY": 0.25,
        "OBJECT": 0.23,
        "SUBJECT": 0.22,
        "ACTION": 0.18,
        "ACTIVE_FOCUS": 0.22,
        "ACTOR": 0.17,
        "CHARACTER": 0.16,
        "CONTEXT": 0.16,
        "SUPPORT": 0.16,
    }.get(role, 0.20)

    audio_start = beat.audio_start if beat.audio_start is not None else beat.start
    audio_end = beat.audio_end if beat.audio_end is not None else beat.end
    spoken_duration = max(0.12, audio_end - audio_start)
    words_per_second = max(1, len(beat.narration.split())) / spoken_duration
    if words_per_second >= 3.0:
        pace_factor = 0.80
    elif words_per_second >= 2.5:
        pace_factor = 0.90
    elif words_per_second >= 2.0:
        pace_factor = 1.0
    else:
        pace_factor = 1.12

    if str(beat.action or "").upper() in {"REJECT", "BLOCK", "LOOP"}:
        pace_factor *= 0.90
    elif str(beat.action or "").upper() in {"PROTECT", "REVEAL", "RESOLVE"}:
        pace_factor *= 1.05

    desired = max(0.12, min(0.40, target * pace_factor))
    # Narration owns the handoff.  A short gap compresses the current gesture;
    # a long gap never stretches it because the remainder is an intentional,
    # motionless hold at authored Composition geometry.
    safe_available = max(0.025, available * 0.82)
    return min(safe_available, desired)


def _next_semantic_hits(
    activations: list[AssetActivation],
) -> dict[str, float]:
    """Return the next distinct precise narration trigger for each activation."""
    precise = [
        row
        for row in activations
        if row.policy != "FALLBACK"
        and row.spoken_start is not None
        and row.spoken_end is not None
        and math.isfinite(row.spoken_start)
        and math.isfinite(row.spoken_end)
    ]
    result: dict[str, float] = {}
    for row in precise:
        later = [
            float(candidate.spoken_start)
            for candidate in precise
            if float(candidate.spoken_start) > float(row.spoken_start) + 1e-9
            and not same_precise_trigger(row, candidate)
        ]
        if later:
            result[row.asset_id] = min(later)
    return result


def _enforce_final_semantic_handoffs(
    activations: list[StoryAssetActivation],
    beat: StoryBeat,
) -> list[StoryAssetActivation]:
    """Clamp final Story windows against later scheduled semantic reveals.

    The first scheduling pass can only reason from raw spoken anchors. Locator/group
    mapping may later inherit or stagger a Story-owned window, which can create a new
    reveal boundary that was not visible to ``_next_semantic_hits``. This final pass
    treats the fully scheduled Story windows as the authority and guarantees that no
    distinct semantic gesture keeps moving through the next scheduled meaning.
    """
    trusted = [
        row
        for row in activations
        if row.activation_policy in {"OWN_WINDOW", "INHERITED_WINDOW"}
        and row.reveal_start is not None
        and row.settle_at is not None
    ]
    if len(trusted) <= 1:
        return activations

    output = list(activations)
    for index, row in enumerate(output):
        if row.activation_policy not in {"OWN_WINDOW", "INHERITED_WINDOW"}:
            continue
        # Final Package activations reveal exactly on their spoken/Story boundary.
        # Inferred legacy activations may intentionally pre-roll before phrase_start;
        # clipping those against a later reveal could make settle precede phrase_start.
        if row.source != "final_package_semantic_binding":
            continue
        if row.reveal_start is None or row.settle_at is None:
            continue
        later_reveals = [
            float(candidate.reveal_start)
            for candidate in trusted
            if candidate.asset_id != row.asset_id
            and candidate.reveal_start is not None
            and float(candidate.reveal_start) > float(row.reveal_start) + 1e-9
            and not same_precise_trigger(row, candidate)
        ]
        if not later_reveals:
            continue
        next_reveal = min(later_reveals)
        if float(row.settle_at) <= next_reveal + 1e-9:
            continue

        available = max(0.025, next_reveal - float(row.reveal_start))
        bounded_duration = _attention_focus_duration(row, beat, available=available)
        settle_at = min(
            float(row.settle_at),
            next_reveal,
            float(row.reveal_start) + bounded_duration,
        )
        if settle_at <= float(row.reveal_start) + 1e-9:
            settle_at = next_reveal
        if settle_at <= float(row.reveal_start) + 1e-9:
            continue

        peak = float(row.semantic_peak) if row.semantic_peak is not None else float(row.reveal_start)
        if peak > settle_at:
            peak = float(row.reveal_start) + (settle_at - float(row.reveal_start)) * 0.55
        peak = max(float(row.reveal_start), min(peak, settle_at))
        evidence = [
            *row.evidence,
            f"final_handoff_cap={next_reveal:.6f}",
            "handoff_policy=final_scheduled_reveal",
        ]
        data = row.model_dump()
        data.update(
            semantic_peak=peak,
            settle_at=settle_at,
            evidence=evidence,
        )
        output[index] = StoryAssetActivation(**data).with_legacy_evidence()
    return output

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
    next_semantic_hits = _next_semantic_hits(activations)
    sequence_windows = _semantic_sequence_windows(
        activations,
        lower=lower,
        visual_upper=visual_upper,
        speech_upper=speech_upper,
        next_semantic_hits=next_semantic_hits,
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
                *(
                    [f"assigned_semantic_event_order={row.semantic_event_order}"]
                    if row.semantic_event_order is not None
                    else []
                ),
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
        phrase_end = min(end, visual_upper)
        attention_role = _attention_role(row, beat)
        exact_package_binding = row.source == "final_package_semantic_binding"
        has_authored_attention = (
            exact_package_binding
            and (
                attention_role != "SUPPORT"
                or bool(row.visual_focus)
                or bool(row.visual_state)
            )
        )
        next_semantic_hit = next_semantic_hits.get(row.asset_id)
        available = max(0.025, phrase_end - start)
        if next_semantic_hit is not None:
            available = min(available, max(0.025, next_semantic_hit - start))
        # A precise package visual with a known later semantic handoff must finish its
        # entry before that next meaning even when it is only SUPPORT/CONTEXT. Otherwise
        # the support can keep moving through the next spoken concept. With no later
        # semantic hit, preserve the legacy full-phrase support window.
        bounded_precise_handoff = (
            exact_package_binding and next_semantic_hit is not None
        )
        focus_duration = (
            _attention_focus_duration(
                row,
                beat,
                available=available,
            )
            if has_authored_attention or bounded_precise_handoff
            else max(0.05, phrase_end - start)
        )
        settle_at = min(phrase_end, start + focus_duration)
        if settle_at <= start:
            data.update(policy="FALLBACK", spoken_start=None, spoken_end=None,
                        confidence=0.0, source="semantic_abstention")
            data["evidence"] = row.evidence + ["SAFE_ABSTENTION", "NO_VISUAL_SETTLE_CAPACITY"]
            output.append(StoryAssetActivation(**data).with_legacy_evidence())
            continue
        importance = 1.0 if row.asset_id in primary_ids else 0.75
        lead = 0.0 if exact_package_binding else min(
            duration * 0.5 * importance,
            capacity * 0.25,
            (visual_upper - lower) * 0.05,
            max(0.0, start - previous_peak),
        )
        semantic_peak = min(
            start + max(0.05, settle_at - start) * 0.55,
            settle_at,
        )
        attention_evidence = row.evidence + [
            f"attention_role={attention_role}",
            f"attention_focus_ms={round((settle_at - start) * 1000)}",
            "attention_decay=settle_hold",
        ]
        if next_semantic_hit is not None:
            attention_evidence.extend([
                f"next_semantic_hit={next_semantic_hit:.6f}",
                "handoff_policy=narration_first",
            ])
        output.append(StoryAssetActivation(
            **{**data, "evidence": attention_evidence},
            phrase_start=start, phrase_end=end,
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

    # Raw spoken anchors are not always the final reveal schedule. Locator/group
    # inheritance can create a later Story-owned reveal after the first pass. Enforce
    # narration-first handoff once more against the final scheduled windows so Motion
    # can never inherit a gesture that crosses the next semantic reveal.
    output = _enforce_final_semantic_handoffs(output, beat)

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
