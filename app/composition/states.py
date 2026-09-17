from __future__ import annotations

from app.choreography import ChoreographyPlan, ParticipantRole, SequencePhase
from app.models import CompositionBeat, LayoutItem, StoryBeat


class CompositionStateDirector:
    """Author bounded per-beat layout states from Choreography semantics.

    The source Final Package composition remains the baseline. State direction may change
    hierarchy, z-order and negative space, but it never invents new assets or large layout
    jumps. Motion receives the resulting semantic resting positions and owns the path.
    """

    MAX_SHIFT = 0.075
    MAX_SCALE_UP = 1.12
    MIN_SCALE_DOWN = 0.92

    def apply(
        self,
        beats: list[StoryBeat],
        composition: list[CompositionBeat],
        choreography: ChoreographyPlan | None,
    ) -> list[CompositionBeat]:
        if choreography is None:
            return composition
        beat_by_id = {beat.id: beat for beat in beats}
        output: list[CompositionBeat] = []
        for layout in composition:
            directive = choreography.for_beat(layout.beat_id)
            beat = beat_by_id.get(layout.beat_id)
            if directive is None or beat is None or not layout.items:
                output.append(layout)
                continue
            output.append(self._direct(layout, directive))
        return output

    def _direct(self, layout: CompositionBeat, directive) -> CompositionBeat:
        by_id = {item.asset_id: item for item in layout.items}
        primary = by_id.get(directive.primary_asset_id or "")
        target = by_id.get(directive.interaction_asset_id or "")
        result_asset_id = directive.interaction.result_asset_id if directive.interaction else None
        result = by_id.get(result_asset_id or "")

        directed: list[LayoutItem] = []
        for item in layout.items:
            role = directive.participant_role(item.asset_id)
            x, y = item.x, item.y
            width, height = item.width, item.height
            z = item.z

            if item is primary:
                scale = self._primary_scale(directive.phase)
                width, height = self._scaled(width, height, scale)
                z = max(z, 30)
                if target is not None:
                    x, y = self._toward(item, target, 0.055 if directive.phase == SequencePhase.ACTION else 0.035)
            elif item is result and directive.phase == SequencePhase.CONSEQUENCE:
                width, height = self._scaled(width, height, 1.10)
                x = self._lerp(x, 0.52, 0.20)
                y = self._lerp(y, 0.49, 0.12)
                z = max(z, 32)
            elif item is target:
                width, height = self._scaled(width, height, 1.04)
                z = max(z, 25)
                if primary is not None:
                    x, y = self._toward(item, primary, 0.025)
            elif role == ParticipantRole.ACTOR:
                # Actors stay readable but do not compete with the causal object.
                width, height = self._scaled(width, height, 0.96)
                if primary is not None:
                    x = self._away(x, primary.x, 0.025)
                z = min(z, 18)
            else:
                width, height = self._scaled(width, height, 0.96)
                if primary is not None:
                    x = self._away(x, primary.x, 0.018)
                z = min(z, 16)

            directed.append(LayoutItem(
                asset_id=item.asset_id,
                x=self._clamp(x, 0.04, 0.96),
                y=self._clamp(y, 0.05, 0.95),
                width=self._clamp(width, 0.05, 0.76),
                height=self._clamp(height, 0.07, 0.86),
                z=z,
            ))

        state_name = self._state_name(directive)
        evidence = list(directive.package_evidence)
        if directive.relationship:
            evidence.append(f"relationship:{directive.relationship}")
        evidence.extend(
            f"state:{row.from_state}->{row.to_state}"
            for row in directive.state_transitions[:4]
        )
        evidence.extend(f"grammar:{stage.value}" for stage in directive.grammar_stages)
        return CompositionBeat(
            beat_id=layout.beat_id,
            items=directed,
            state_name=state_name,
            semantic_focus_asset_id=directive.primary_asset_id,
            state_evidence=list(dict.fromkeys(evidence)),
        )

    @staticmethod
    def _primary_scale(phase: SequencePhase) -> float:
        if phase == SequencePhase.ACTION:
            return 1.06
        if phase == SequencePhase.CONSEQUENCE:
            return 1.09
        if phase == SequencePhase.HANDOFF:
            return 1.03
        return 1.02

    @staticmethod
    def _state_name(directive) -> str:
        if directive.state_transitions:
            return directive.state_transitions[0].to_state
        return directive.phase.value

    @classmethod
    def _toward(cls, source: LayoutItem, target: LayoutItem, amount: float) -> tuple[float, float]:
        dx = cls._clamp(target.x - source.x, -cls.MAX_SHIFT, cls.MAX_SHIFT)
        dy = cls._clamp(target.y - source.y, -cls.MAX_SHIFT, cls.MAX_SHIFT)
        return source.x + dx * min(1.0, amount / cls.MAX_SHIFT), source.y + dy * min(1.0, amount / cls.MAX_SHIFT)

    @classmethod
    def _away(cls, value: float, focus_value: float, amount: float) -> float:
        direction = -1.0 if value <= focus_value else 1.0
        return value + direction * min(cls.MAX_SHIFT, amount)

    @classmethod
    def _scaled(cls, width: float, height: float, scale: float) -> tuple[float, float]:
        scale = cls._clamp(scale, cls.MIN_SCALE_DOWN, cls.MAX_SCALE_UP)
        return width * scale, height * scale

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))
