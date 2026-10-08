from __future__ import annotations

import math
from collections import defaultdict

from app.choreography import ChoreographyDirective, ChoreographyPlan
from app.canonical import CanonicalPackage, ensure_canonical_package
from app.models import StoryBeat, TextCue, TextPlan, TextStyle, TextTokenCue, Transcript, VisualAsset
from app.text.semantic import KeywordCandidate, TextSemanticSelector
from app.text.style import TextStyleResolver
from app.text.timing import TextTimingPlanner, TextVisibilityPolicy


class TextPlanner:
    """Build sparse narration-locked text cues from Story + Final Package semantics.

    Text remains an independent layer. Choreography may provide semantic synchronization
    and anchor choice, but it never owns the wording or forced-aligned timing.
    """

    def __init__(
        self,
        *,
        semantic: TextSemanticSelector | None = None,
        timing: TextTimingPlanner | None = None,
        style: TextStyleResolver | None = None,
    ) -> None:
        self.semantic = semantic or TextSemanticSelector()
        self.timing = timing or TextTimingPlanner()
        self.style = style or TextStyleResolver()
        # Cues withheld by the last plan() call and why (structured diagnostics).
        self.abstentions: list[dict] = []

    def plan(
        self,
        *,
        transcript: Transcript,
        story: list[StoryBeat],
        assets: list[VisualAsset] | None = None,
        package: CanonicalPackage | None = None,
        choreography: ChoreographyPlan | None = None,
    ) -> TextPlan:
        package = ensure_canonical_package(package) if package is not None else None
        del assets
        self.abstentions = []
        scene_by_id = {scene.id: scene for scene in package.scenes} if package else {}
        cues: list[TextCue] = []
        styles: dict[str, TextStyle] = {}
        cue_number = 1

        for beat in story:
            directive = choreography.for_beat(beat.id) if choreography else None
            context = beat.semantic_context
            scene = scene_by_id.get(beat.scene_id)
            candidates = self.semantic.select(beat, transcript, package=package)
            for candidate in candidates:
                timed = self.timing.align(candidate, transcript)
                if timed is None:
                    continue
                style = self.style.resolve(timed)
                styles[style.id] = style
                anchor_asset_id = self._anchor_asset_id(
                    beat=beat,
                    candidate=candidate,
                    directive=directive,
                )
                package_evidence = list(context.evidence) if context else []
                if candidate.provenance:
                    package_evidence.append(f"text_selection:{candidate.provenance}")
                if scene and scene.relation_to_previous:
                    package_evidence.append(f"scene_relation:{scene.relation_to_previous}")
                if anchor_asset_id:
                    anchor_activation = next(
                        (row for row in beat.asset_activations if row.asset_id == anchor_asset_id),
                        None,
                    )
                    if anchor_activation is not None:
                        if anchor_activation.semantic_event_id:
                            package_evidence.append(
                                f"semantic_event:{anchor_activation.semantic_event_id}"
                            )
                        if "TEXT_ANCHOR" in anchor_activation.semantic_event_roles:
                            package_evidence.append("final_package_text_anchor")
                        if "LEADER" in anchor_activation.semantic_event_roles:
                            package_evidence.append("final_package_visual_leader")
                relationship = directive.relationship if directive is not None else None
                cues.append(TextCue(
                    id=f"text-{cue_number:03d}",
                    beat_id=beat.id,
                    text=candidate.display_text,
                    semantic_type=candidate.semantic_type,
                    source_char_start=candidate.source_char_start,
                    source_char_end=candidate.source_char_end,
                    spoken_start=timed.spoken_start,
                    spoken_end=timed.spoken_end,
                    emphasis_time=timed.emphasis_time,
                    anchor_asset_id=anchor_asset_id,
                    priority=min(
                        100,
                        self._priority(candidate.semantic_type)
                        + max(0, round((candidate.score - 0.74) * 20)),
                    ),
                    style_id=style.id,
                    placement_hint="anchor",
                    story_role=context.story_role if context else None,
                    choreography_action=directive.action if directive is not None else None,
                    semantic_unit_ids=list(directive.semantic_unit_ids) if directive is not None else [],
                    relationship=relationship,
                    package_evidence=list(dict.fromkeys(package_evidence)),
                    tokens=[
                        TextTokenCue(
                            text=token.display_text,
                            source_char_start=token.source_char_start,
                            source_char_end=token.source_char_end,
                            spoken_start=token.spoken_start,
                            spoken_end=token.spoken_end,
                        )
                        for token in timed.tokens
                    ],
                ))
                cue_number += 1

        beat_by_id = {beat.id: beat for beat in story}
        cues = self._apply_editorial_density(
            cues,
            beat_by_id,
            bounded=package is not None and package.has_authoritative_semantics,
            abstentions=self.abstentions,
        )

        return TextPlan(
            cues=sorted(cues, key=lambda cue: (cue.spoken_start, -cue.priority, cue.id)),
            styles=sorted(styles.values(), key=lambda style: style.id),
        )

    @classmethod
    def _apply_editorial_density(
        cls,
        cues: list[TextCue],
        beat_by_id: dict[str, StoryBeat] | None = None,
        *,
        bounded: bool = True,
        abstentions: list[dict] | None = None,
    ) -> list[TextCue]:
        """Keep semantic typography sparse and readable instead of subtitle-like.

        Every beat with useful text may keep one editorial cue: its strongest cue that
        can actually be read before the beat (or a stronger sibling) takes it away. A
        bounded global 25% accent budget can add a second cue to the strongest beats,
        but never a third; the extra cue must be a distinct spoken moment of a different
        Final Package semantic event, backed by phrase-level or numeric evidence, and must
        leave every kept cue of its beat readable. ``bounded`` is False only for packages
        without authoritative semantics, whose selector budget already bounds density.
        """
        beat_by_id = beat_by_id or {}
        visibility = TextVisibilityPolicy()

        def readable(kept: list[TextCue]) -> bool:
            beat = beat_by_id.get(kept[0].beat_id)
            if beat is None:
                return True
            return all(visibility.is_readable(row, beat, kept) for row in kept)

        def withhold(cue: TextCue, reason: str) -> None:
            if abstentions is not None:
                abstentions.append({
                    "beat_id": cue.beat_id, "text_cue_id": cue.id, "text": cue.text,
                    "reason": reason,
                })

        by_beat: dict[str, list[TextCue]] = defaultdict(list)
        for cue in cues:
            by_beat[cue.beat_id].append(cue)

        retained: dict[str, list[TextCue]] = {}
        extras: list[TextCue] = []
        for beat_id, rows in by_beat.items():
            ranked = sorted(rows, key=cls._editorial_rank, reverse=True)
            primary = next((row for row in ranked if readable([row])), None)
            if primary is None:
                for row in ranked:
                    withhold(row, "unreadable_window")
                continue
            for row in ranked[:ranked.index(primary)]:
                withhold(row, "unreadable_window")
            retained[beat_id] = [primary]
            for candidate in ranked[ranked.index(primary) + 1:]:
                if bounded and abs(float(candidate.spoken_start) - float(primary.spoken_start)) < 0.45:
                    withhold(candidate, "same_spoken_moment")
                    continue
                extras.append(candidate)

        # One cue per covered beat is the base contract. A quarter of the beats may
        # receive one additional accent when semantic evidence makes it worthwhile.
        # The accent budget is a quarter of the beats that actually show text.
        total = len(retained)
        max_total = math.ceil(total * 1.25) if bounded else None
        for candidate in sorted(extras, key=cls._editorial_rank, reverse=True):
            kept = retained[candidate.beat_id]
            if bounded and (total >= max_total or len(kept) >= 2):
                withhold(candidate, "editorial_density")
                continue
            if bounded and not cls._is_accent_evidence(candidate):
                # A single appearance word may be a beat's only label, never its accent.
                withhold(candidate, "accent_needs_phrase_evidence")
                continue
            if bounded and cls._semantic_event(candidate) is not None and any(
                cls._semantic_event(row) == cls._semantic_event(candidate) for row in kept
            ):
                # One editorial label per Final Package semantic event: a second label on
                # the same event repeats it instead of marking a distinct moment.
                withhold(candidate, "same_semantic_event")
                continue
            if not readable([*kept, candidate]):
                withhold(candidate, "unreadable_window")
                continue
            kept.append(candidate)
            total += 1

        return [cue for rows in retained.values() for cue in rows]

    @staticmethod
    def _semantic_event(cue: TextCue) -> str | None:
        return next(
            (row.split(":", 1)[1] for row in cue.package_evidence if row.startswith("semantic_event:")),
            None,
        )

    @staticmethod
    def _is_accent_evidence(cue: TextCue) -> bool:
        """Guard: a single appearance word is never a beat's second (accent) cue.

        Rejects only on positive evidence - one displayed word selected from a
        single-word visual trigger span or a lexical phrase window. Numbers and
        phrase-level evidence stay eligible.
        """
        if cue.semantic_type in {"warning_amount", "warning", "amount", "number"}:
            return True
        if len(cue.text.split()) > 1:
            return True
        evidence = set(cue.package_evidence)
        return not (
            "text_selection:exact_asset_span:EXACT_WORD" in evidence
            or "text_selection:semantic_phrase_window" in evidence
        )

    @staticmethod
    def _editorial_rank(cue: TextCue) -> tuple[int, int, float, str]:
        evidence = set(cue.package_evidence)
        score = int(cue.priority)
        if cue.semantic_type in {"warning_amount", "warning", "amount", "number"}:
            score += 25
        if "final_package_text_anchor" in evidence:
            score += 20
        if "final_package_visual_leader" in evidence:
            score += 10
        if cue.relationship and cue.relationship != "DECLARED_PROGRESSION":
            score += 4
        return score, int(cue.priority), -float(cue.spoken_start), cue.id

    @staticmethod
    def _anchor_asset_id(
        *,
        beat: StoryBeat,
        candidate: KeywordCandidate,
        directive: ChoreographyDirective | None,
    ) -> str | None:
        """Resolve text to the exact Story asset span before beat-level fallback.

        Final Package/Story already owns canonical character spans for semantic assets.
        Text wording and spoken timing stay untouched; this only chooses WHICH visual
        receives the text relationship.
        """
        cue_start = int(candidate.source_char_start)
        cue_end = int(candidate.source_char_end)
        matches = []
        for activation in beat.asset_activations:
            start = activation.trigger_char_start
            end = activation.trigger_char_end
            if start is None or end is None or end <= start:
                continue
            overlap = max(0, min(cue_end, end) - max(cue_start, start))
            if overlap <= 0:
                continue
            cue_len = max(1, cue_end - cue_start)
            activation_len = max(1, end - start)
            visual_focus = str(activation.visual_focus or "").upper()
            focus_rank = {
                "RESULT": 0,
                "PRIMARY": 1,
                "SUPPORT": 2,
                "CONTEXT": 3,
            }.get(visual_focus, 2)
            event_anchor_rank = (
                1 if "TEXT_ANCHOR" in activation.semantic_event_roles else 0
            )
            event_leader_rank = (
                1 if "LEADER" in activation.semantic_event_roles else 0
            )
            matches.append((
                overlap / cue_len,
                event_anchor_rank,
                event_leader_rank,
                overlap / activation_len,
                float(activation.confidence),
                -focus_rank,
                -activation_len,
                activation.asset_id,
            ))

        if matches:
            best_prefix = max(row[:-1] for row in matches)
            tied_ids = sorted(row[-1] for row in matches if row[:-1] == best_prefix)
            preferred = directive.primary_asset_id if directive is not None else None
            if preferred in tied_ids:
                return preferred
            for asset_id in beat.primary_asset_ids:
                if asset_id in tied_ids:
                    return asset_id
            return tied_ids[0]

        if directive is not None and directive.primary_asset_id:
            return directive.primary_asset_id
        return (beat.primary_asset_ids or [None])[0]

    @staticmethod
    def _priority(semantic_type: str) -> int:
        return {
            "warning_amount": 100,
            "warning": 95,
            "amount": 90,
            "number": 85,
            "emphasis": 75,
            "keyword": 60,
        }.get(semantic_type, 50)
