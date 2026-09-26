from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.choreography import ChoreographyPlan
from app.models import MotionCue, StoryBeat
from app.motion.rhythm import (
    MIN_FOCUS_OVERLAP_SECONDS,
    ReferenceRhythmPolicy,
    focus_progression_key,
)
from app.qa.failure_identity import violation_failure_details
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class ChoreographyRhythmViolation:
    code: str
    beat_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class ChoreographyRhythmReport:
    checked_beats: int
    checked_entry_cohorts: int
    violations: tuple[ChoreographyRhythmViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


class ChoreographyRhythmQA:
    """Validate global pacing/focus continuity before spending time on rendering.

    This validator intentionally consumes Motion's recorded rhythm contract rather than
    inventing a second set of thresholds. It catches regressions such as beat-to-beat
    snap/deliberate whiplash or several unrelated full-strength entries fighting for the
    same visual instant.
    """

    def inspect(
        self,
        *,
        story: list[StoryBeat],
        motion: list[MotionCue],
        choreography: ChoreographyPlan | None = None,
    ) -> ChoreographyRhythmReport:
        by_beat: dict[str, list[MotionCue]] = {}
        for cue in motion:
            by_beat.setdefault(cue.beat_id, []).append(cue)

        violations: list[ChoreographyRhythmViolation] = []
        checked_beats = 0
        checked_cohorts = 0
        previous_tier: str | None = None

        for beat in story:
            cues = by_beat.get(beat.id, [])
            if not cues:
                continue
            checked_beats += 1
            tiers = {
                str(cue.params.get("pace_tier"))
                for cue in cues
                if isinstance(cue.params, dict) and cue.params.get("pace_tier")
            }
            if len(tiers) != 1:
                violations.append(ChoreographyRhythmViolation(
                    code="INCONSISTENT_BEAT_PACE",
                    beat_id=beat.id,
                    detail=f"one beat compiled multiple pace tiers: {sorted(tiers)}",
                ))
                continue
            tier = next(iter(tiers))
            directive = choreography.for_beat(beat.id) if choreography else None
            allowed_contrast = bool(
                directive is not None
                and (
                    directive.hook.value != "NONE"
                    or (
                        str(directive.action).upper() in {"REJECT", "BLOCK", "LOOP"}
                        and float(directive.tension) >= 0.72
                    )
                )
            )
            if (
                previous_tier is not None
                and not allowed_contrast
                and ReferenceRhythmPolicy.tier_distance(previous_tier, tier) > 1
            ):
                violations.append(ChoreographyRhythmViolation(
                    code="PACE_WHIPLASH",
                    beat_id=beat.id,
                    detail=f"pace jumped from {previous_tier} to {tier}",
                ))
            previous_tier = tier

            # Consume the same overlap contract used by MotionPlanner. Attention
            # competition is about intervals that visibly move at the same time, not
            # merely cues whose start timestamps happen to be close.
            entries: list[tuple[float, float, MotionCue]] = []
            for cue in cues:
                segment = next((row for row in cue.segments if row.phase == "ENTRY"), None)
                start = float(segment.start) if segment is not None else float(cue.start)
                end = float(segment.end) if segment is not None else float(cue.end)
                entries.append((start, end, cue))

                focus = cue.params.get("semantic_focus") or {}
                execution = str(focus.get("event_flow_execution") or "NONE")
                program = cue.params.get("program") or {}
                program_name = str(program.get("name") or "")
                if execution == "EXPLICIT_TIMELINE" and program_name.startswith("event_chain_"):
                    violations.append(ChoreographyRhythmViolation(
                        code="DUPLICATE_SEMANTIC_ENTRY_ACCENT",
                        beat_id=beat.id,
                        detail=(
                            f"{cue.asset_id} embeds event-chain motion in ENTRY while "
                            "also owning an explicit semantic timeline"
                        ),
                    ))

            entries.sort(key=lambda row: (row[0], row[2].asset_id))
            cohorts: list[list[tuple[float, float, MotionCue]]] = []
            cohort_end: float | None = None
            for row in entries:
                start, end, _cue = row
                if not cohorts:
                    cohorts.append([row])
                    cohort_end = end
                    continue
                assert cohort_end is not None
                focus = row[2].params.get("semantic_focus") or {}
                motion_order = row[2].params.get("motion_order") or {}
                current_key = focus_progression_key(
                    focus.get("semantic_event_order"),
                    motion_order.get("sequence_order"),
                )
                anchor_focus = cohorts[-1][0][2].params.get("semantic_focus") or {}
                anchor_motion_order = cohorts[-1][0][2].params.get("motion_order") or {}
                anchor_key = focus_progression_key(
                    anchor_focus.get("semantic_event_order"),
                    anchor_motion_order.get("sequence_order"),
                )
                if (
                    cohort_end - start >= MIN_FOCUS_OVERLAP_SECONDS - 1e-9
                    and current_key == anchor_key
                ):
                    cohorts[-1].append(row)
                    cohort_end = max(cohort_end, end)
                else:
                    cohorts.append([row])
                    cohort_end = end

            for cohort in cohorts:
                if len(cohort) <= 1:
                    continue
                checked_cohorts += 1
                strong = []
                for _start, _end, cue in cohort:
                    focus = cue.params.get("semantic_focus") or {}
                    try:
                        gain = float(focus.get("cohort_gain", 1.0))
                    except (TypeError, ValueError):
                        gain = 1.0
                    role = str(focus.get("cohort_role") or "independent")
                    if gain >= 0.72 and role not in {"leader_member", "result_peer"}:
                        strong.append(cue.asset_id)
                if len(strong) > 1:
                    violations.append(ChoreographyRhythmViolation(
                        code="COMPETING_ENTRY_FOCUS",
                        beat_id=beat.id,
                        detail=f"overlapping full-strength entries: {strong}",
                    ))

        return ChoreographyRhythmReport(
            checked_beats=checked_beats,
            checked_entry_cohorts=checked_cohorts,
            violations=tuple(violations),
        )

    @staticmethod
    def write(report: ChoreographyRhythmReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "ok": report.ok,
                "checked_beats": report.checked_beats,
                "checked_entry_cohorts": report.checked_entry_cohorts,
                "violations": [asdict(row) for row in report.violations],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def require(report: ChoreographyRhythmReport) -> None:
        if report.ok:
            return
        raise StageFailedError(
            "choreography rhythm QA failed",
            details={
                **violation_failure_details(
                    report.violations,
                    aggregate_code="RHYTHM_CONTRACT_VIOLATIONS",
                ),
                "violations": [asdict(row) for row in report.violations[:12]],
            },
        )