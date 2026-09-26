from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.choreography import ChoreographyPlan, HookKind
from app.models import CompositionBeat, MotionCue, PackageModel, StoryBeat, TextMotionCue, TextPlan
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class StorytellingReport:
    beat_count: int
    rich_semantic_beats: int
    semantic_context_beats: int
    directive_semantic_beats: int
    explicit_relationships: int
    represented_relationships: int
    executable_interactions: int
    meaningful_state_beats: int
    dynamic_composition_beats: int
    motion_semantic_cues: int
    rich_motion_cue_count: int
    text_semantic_cues: int
    text_cue_count: int
    hook_count: int
    semantic_hook_count: int
    grammar_sequence_count: int
    grammar_compliant_sequences: int
    incomplete_grammar_sequences: tuple[str, ...]
    asset_requirement_count: int
    missing_asset_requirements: tuple[str, ...]
    neutral_hold_motion_count: int
    meaning_motion_count: int
    forbidden_jitter_programs: tuple[str, ...]
    authored_semantic_events: int
    represented_semantic_events: int
    missing_semantic_events: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def metadata_complete(self) -> bool:
        if self.rich_semantic_beats == 0:
            return True
        return (
            self.semantic_context_beats >= self.rich_semantic_beats
            and self.directive_semantic_beats >= self.rich_semantic_beats
        )

    @property
    def interaction_semantics_complete(self) -> bool:
        return self.represented_relationships >= self.explicit_relationships

    @property
    def semantic_event_coverage_complete(self) -> bool:
        return not self.missing_semantic_events

    @property
    def downstream_metadata_complete(self) -> bool:
        if self.rich_semantic_beats == 0:
            return True
        composition_complete = self.dynamic_composition_beats >= self.rich_semantic_beats
        motion_complete = (
            self.rich_motion_cue_count == 0
            or self.motion_semantic_cues >= self.rich_motion_cue_count
        )
        text_complete = (
            self.text_cue_count == 0
            or self.text_semantic_cues >= self.text_cue_count
        )
        return composition_complete and motion_complete and text_complete

    @property
    def anti_jitter_pass(self) -> bool:
        return not self.forbidden_jitter_programs

    @property
    def reference_grammar_complete(self) -> bool:
        return self.grammar_compliant_sequences >= self.grammar_sequence_count

    @property
    def ready_for_render_review(self) -> bool:
        return (
            self.metadata_complete
            and self.interaction_semantics_complete
            and self.semantic_event_coverage_complete
            and self.downstream_metadata_complete
            and self.anti_jitter_pass
            and self.reference_grammar_complete
        )


class StorytellingValidator:
    """Authoring QA gate before expensive rendering.

    This validates semantic coverage and anti-jitter invariants. It deliberately does not
    claim visual parity with reference videos without an encoded render; it only proves
    the authoring plan is rich enough to justify that render.
    """

    _FORBIDDEN_MOTION_TOKENS = ("jitter", "shake", "wiggle", "idle_bounce", "idle_pulse")
    _MEANING_PROGRAM_TOKENS = (
        "reject",
        "block",
        "lock",
        "travel",
        "connect",
        "compare",
        "protect",
        "resolve",
        "reveal",
        "react",
        "result",
        "repeat",
    )

    @classmethod
    def inspect(
        cls,
        *,
        package: PackageModel,
        story: list[StoryBeat],
        choreography: ChoreographyPlan,
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        text: TextPlan,
        text_motion: list[TextMotionCue],
    ) -> StorytellingReport:
        rich_scene_ids = {
            scene.id
            for scene in package.scenes
            if scene.units or scene.visual_progression or scene.relation_to_previous
        }
        rich_beats = [beat for beat in story if beat.scene_id in rich_scene_ids]
        semantic_context_beats = sum(1 for beat in rich_beats if beat.semantic_context is not None)
        directives = [
            row
            for beat in rich_beats
            if (row := choreography.for_beat(beat.id)) is not None
        ]
        directive_semantic_beats = sum(
            1
            for row in directives
            if row.semantic_unit_ids or row.package_evidence or row.relationship
        )

        explicit_relation_authorities = {
            "FINAL_PACKAGE_INTERACTION_TARGET",
            "FINAL_PACKAGE_ASSET_RELATION",
        }
        explicit_relationships = sum(
            1
            for beat in story
            for relation in (beat.semantic_context.relations if beat.semantic_context else [])
            if relation.authority in explicit_relation_authorities
        )
        represented_relationships = sum(
            1
            for row in choreography.directives
            for interaction in (
                row.interactions
                or ((row.interaction,) if row.interaction is not None else ())
            )
            if interaction.authority in explicit_relation_authorities
        )

        authored_event_keys = {
            (str(scene.get("scene_id")), str(event.get("semantic_event_id")))
            for scene in package.semantic_bindings.get("scenes", [])
            if isinstance(scene, dict) and scene.get("scene_id")
            for event in scene.get("semantic_events", [])
            if isinstance(event, dict) and event.get("semantic_event_id")
        }
        beat_scene = {beat.id: beat.scene_id for beat in story}
        represented_event_keys = {
            (beat_scene.get(row.beat_id, ""), flow.event_id)
            for row in choreography.directives
            for flow in row.event_flows
            if flow.event_id and beat_scene.get(row.beat_id)
        }
        missing_semantic_events = tuple(sorted(
            f"{scene_id}:{event_id}"
            for scene_id, event_id in authored_event_keys - represented_event_keys
        ))
        executable_interactions = sum(
            1
            for row in choreography.directives
            for interaction in (
                row.interactions
                or ((row.interaction,) if row.interaction is not None else ())
            )
            if interaction.executable
        )
        meaningful_state_beats = sum(
            1 for row in choreography.directives if row.has_meaningful_state_change
        )
        dynamic_composition_beats = sum(
            1 for row in composition if row.state_name != "AUTHORED" or row.state_evidence
        )
        rich_beat_ids = {beat.id for beat in rich_beats}
        rich_motion = [cue for cue in motion if cue.beat_id in rich_beat_ids]
        motion_semantic_cues = sum(
            1
            for cue in rich_motion
            if isinstance(cue.params.get("choreography"), dict)
            and (
                cue.params["choreography"].get("semantic_unit_ids")
                or cue.params["choreography"].get("package_evidence")
                or cue.params["choreography"].get("relationship")
            )
        )
        text_semantic_cues = sum(
            1
            for cue in text.cues
            if cue.story_role or cue.choreography_action or cue.semantic_unit_ids or cue.package_evidence
        )
        hook_rows = [row for row in choreography.directives if row.hook != HookKind.NONE]
        sequence_by_id = {row.id: row for row in choreography.sequences}
        semantic_hook_count = sum(
            1
            for row in hook_rows
            if row.has_meaningful_state_change
            or sequence_by_id.get(row.sequence_id, None) is not None
            and sequence_by_id[row.sequence_id].meaningful_state_change_count > 0
        )

        grammar_sequence_count = len(choreography.sequences)
        grammar_compliant_sequences = 0
        incomplete_grammar_sequences: list[str] = []
        for sequence in choreography.sequences:
            if cls._grammar_sequence_is_compliant(sequence):
                grammar_compliant_sequences += 1
            else:
                ordered_stages = ",".join(stage.value for stage in sequence.grammar_stages)
                incomplete_grammar_sequences.append(
                    f"{sequence.id}[beats={len(sequence.beat_ids)};stages={ordered_stages}]"
                )

        asset_requirements = [
            requirement
            for row in choreography.directives
            for requirement in row.asset_requirements
        ]
        missing_asset_requirements = tuple(sorted({
            f"{row.semantic_unit_id}:{row.participant_role.value}:{row.required_for_action}"
            for row in asset_requirements
            if not row.satisfied
        }))

        forbidden: list[str] = []
        neutral_hold = 0
        meaning_motion = 0
        for cue in motion:
            program = str(cue.params.get("program", {}).get("name") or "")
            low = program.casefold()
            if any(token in low for token in cls._FORBIDDEN_MOTION_TOKENS):
                forbidden.append(f"{cue.beat_id}:{cue.asset_id}:{program}")
            if program in {"focus_settle_hold", "support_settle_hold", "minimal_settle"}:
                neutral_hold += 1
            if any(token in low for token in cls._MEANING_PROGRAM_TOKENS):
                meaning_motion += 1

        warnings: list[str] = []
        if rich_beats and semantic_context_beats < len(rich_beats):
            warnings.append("FINAL_PACKAGE_METADATA_NOT_FULLY_REPRESENTED_IN_STORY")
        if explicit_relationships > represented_relationships:
            warnings.append("FINAL_PACKAGE_RELATIONSHIP_DROPPED_BEFORE_CHOREOGRAPHY")
        if missing_semantic_events:
            warnings.append("FINAL_PACKAGE_SEMANTIC_EVENT_DROPPED_BEFORE_CHOREOGRAPHY")
        if choreography.directives and meaningful_state_beats == 0:
            warnings.append("NO_MEANINGFUL_VISUAL_STATE_CHANGE")
        if hook_rows and semantic_hook_count < len(hook_rows):
            warnings.append("MOTION_ONLY_HOOK_PRESENT")
        if rich_motion and motion_semantic_cues < len(rich_motion):
            warnings.append("MOTION_CUE_MISSING_FINAL_PACKAGE_SEMANTICS")
        if text.cues and text_semantic_cues < len(text.cues):
            warnings.append("TEXT_CUE_MISSING_STORY_SEMANTICS")
        if rich_beats and dynamic_composition_beats < len(rich_beats):
            warnings.append("COMPOSITION_MISSING_FINAL_PACKAGE_SEMANTICS")
        if grammar_compliant_sequences < grammar_sequence_count:
            warnings.append("REFERENCE_VISUAL_GRAMMAR_INCOMPLETE")
        if missing_asset_requirements:
            warnings.append("CHOREOGRAPHY_ASSET_REQUIREMENT_UNSATISFIED")
        if len(text_motion) != len(text.cues) and text.cues:
            warnings.append("TEXT_MOTION_COVERAGE_INCOMPLETE")

        return StorytellingReport(
            beat_count=len(story),
            rich_semantic_beats=len(rich_beats),
            semantic_context_beats=semantic_context_beats,
            directive_semantic_beats=directive_semantic_beats,
            explicit_relationships=explicit_relationships,
            represented_relationships=represented_relationships,
            executable_interactions=executable_interactions,
            meaningful_state_beats=meaningful_state_beats,
            dynamic_composition_beats=dynamic_composition_beats,
            motion_semantic_cues=motion_semantic_cues,
            rich_motion_cue_count=len(rich_motion),
            text_semantic_cues=text_semantic_cues,
            text_cue_count=len(text.cues),
            hook_count=len(hook_rows),
            semantic_hook_count=semantic_hook_count,
            grammar_sequence_count=grammar_sequence_count,
            grammar_compliant_sequences=grammar_compliant_sequences,
            incomplete_grammar_sequences=tuple(incomplete_grammar_sequences),
            asset_requirement_count=len(asset_requirements),
            missing_asset_requirements=missing_asset_requirements,
            neutral_hold_motion_count=neutral_hold,
            meaning_motion_count=meaning_motion,
            forbidden_jitter_programs=tuple(sorted(set(forbidden))),
            authored_semantic_events=len(authored_event_keys),
            represented_semantic_events=len(authored_event_keys & represented_event_keys),
            missing_semantic_events=missing_semantic_events,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _grammar_sequence_is_compliant(sequence) -> bool:
        """Validate progressive grammar without inventing meaning stages.

        A one-beat sequence has no later beat available to ADD/RELATE/RESULT. Requiring
        one of those stages would reject a structurally complete standalone beat. For
        multi-beat sequences the stronger progressive-meaning requirement remains.
        """
        stages = {stage.value for stage in sequence.grammar_stages}
        progressive = (
            "ENTER" in stages
            and "READ" in stages
            and "RELEASE" in stages
        )
        if not progressive:
            return False
        if len(sequence.beat_ids) == 1:
            return True
        return bool(stages & {"ADD", "RELATE", "RESULT"})

    @classmethod
    def validate(cls, **kwargs) -> StorytellingReport:
        report = cls.inspect(**kwargs)
        hard_failures: list[str] = []
        if not report.metadata_complete:
            hard_failures.append("FINAL_PACKAGE_METADATA_COVERAGE")
        if not report.interaction_semantics_complete:
            hard_failures.append("FINAL_PACKAGE_RELATIONSHIP_COVERAGE")
        if not report.semantic_event_coverage_complete:
            hard_failures.append("FINAL_PACKAGE_SEMANTIC_EVENT_COVERAGE")
        if not report.downstream_metadata_complete:
            hard_failures.append("FINAL_PACKAGE_DOWNSTREAM_METADATA_COVERAGE")
        if not report.anti_jitter_pass:
            hard_failures.append("FORBIDDEN_JITTER_MOTION")
        if not report.reference_grammar_complete:
            hard_failures.append("REFERENCE_VISUAL_GRAMMAR")
        if hard_failures:
            raise StageFailedError(
                "storytelling authoring QA failed before render",
                details={
                    "failures": hard_failures,
                    **asdict(report),
                },
            )
        return report

    @staticmethod
    def write(report: StorytellingReport, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**asdict(report), "ready_for_render_review": report.ready_for_render_review}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
