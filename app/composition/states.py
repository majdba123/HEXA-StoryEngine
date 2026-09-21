from __future__ import annotations

from app.choreography import ChoreographyPlan
from app.models import CompositionBeat, StoryBeat


class CompositionStateDirector:
    """Attach semantic state to a layout without changing authored geometry.

    Final Package pixels already define the final spatial composition. Choreography may
    select focus, relationship and state evidence, but geometry changes belong nowhere in
    this layer. Motion can emphasize an asset transiently and must settle back to these
    exact authored coordinates.
    """

    def apply(
        self,
        beats: list[StoryBeat],
        composition: list[CompositionBeat],
        choreography: ChoreographyPlan | None,
    ) -> list[CompositionBeat]:
        if choreography is None:
            return composition
        output: list[CompositionBeat] = []
        for layout in composition:
            directive = choreography.for_beat(layout.beat_id)
            if directive is None:
                output.append(layout)
                continue
            evidence = [*layout.state_evidence, *directive.package_evidence]
            if directive.relationship:
                evidence.append(f"relationship:{directive.relationship}")
            evidence.extend(
                f"state:{row.from_state}->{row.to_state}"
                for row in directive.state_transitions[:4]
            )
            evidence.extend(f"grammar:{stage.value}" for stage in directive.grammar_stages)
            output.append(layout.model_copy(update={
                "state_name": self._state_name(directive),
                "semantic_focus_asset_id": directive.primary_asset_id,
                "state_evidence": list(dict.fromkeys(evidence)),
                # ``items`` intentionally unchanged.
            }))
        return output

    @staticmethod
    def _state_name(directive) -> str:
        if directive.state_transitions:
            return directive.state_transitions[0].to_state
        return directive.phase.value
