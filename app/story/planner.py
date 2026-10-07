from __future__ import annotations

from collections import defaultdict
from app.canonical import (
    CanonicalPackage,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalVisualProgression,
    ensure_canonical_package,
)
from app.models import StoryBeat, StorySemanticContext, StorySemanticDiagnostic, Transcript, VisualAsset
from app.shared.errors import StageFailedError

from .activation import SemanticActivationPlanner
from .event_authority import event_authority
from .carriers import SemanticCarrierAuditor
from .graph import StoryGraph, StoryGraphBuilder
from .semantic import PackageStoryInterpreter


class StoryPlanner:
    """Build narration-locked visual beats from package intent.

    ``audio_start/audio_end`` preserve the semantic narration timing. ``start/end`` own
    the visual timeline and may begin slightly earlier so an entrance settles on the
    narrated idea instead of reacting after the listener has already heard it.
    """

    _DEFAULT_VISUAL_LEAD = 0.42
    _MAX_VISUAL_LEAD = 0.62
    _MIN_VISUAL_BEAT = 0.08

    def __init__(
        self,
        *,
        semantic_model_name: str | None = None,
        semantic_model_required: bool = False,
    ) -> None:
        self.semantic_interpreter = PackageStoryInterpreter()
        self.graph_builder = StoryGraphBuilder()
        self.carrier_auditor = SemanticCarrierAuditor()
        self.semantic_carrier_audit: list[dict] = []
        self.hidden_content_audit: list[dict] = []
        self.carrier_resolution_report: list[dict] = []
        self.semantic_diagnostics: list[StorySemanticDiagnostic] = []
        self.activation = SemanticActivationPlanner(
            semantic_model_name=semantic_model_name,
            semantic_model_required=semantic_model_required,
        )

    def build_graph(self, beats: list[StoryBeat]) -> StoryGraph:
        return self.graph_builder.build(beats)

    def plan(
        self,
        package: CanonicalPackage,
        transcript: Transcript,
        assets: list[VisualAsset],
    ) -> list[StoryBeat]:
        package = ensure_canonical_package(package)
        self.carrier_resolution_report = []
        self.semantic_diagnostics = []
        assets_by_scene: dict[str, list[VisualAsset]] = defaultdict(list)
        for asset in assets:
            assets_by_scene[asset.scene_id].append(asset)
        for rows in assets_by_scene.values():
            rows.sort(key=lambda asset: (asset.source_area_ratio or 0.0), reverse=True)

        beats: list[StoryBeat] = []
        previous_primary: str | None = None
        beat_number = 1
        for scene in package.scenes:
            scene_assets = assets_by_scene.get(scene.id, [])
            if not scene_assets:
                continue
            authored_progression = bool(scene.visual_progression)
            events = scene.visual_progression or [self._default_event(scene)]
            for event_index, event in enumerate(events):
                char_start = scene.script_char_start
                char_end = scene.script_char_end
                if authored_progression and event.trigger is not None:
                    if event.trigger.global_char_start is not None:
                        char_start = event.trigger.global_char_start
                    if event.trigger.global_char_end is not None:
                        char_end = event.trigger.global_char_end
                fallback_segment = None
                if transcript.segments:
                    fallback_segment = transcript.segments[min(scene.order, len(transcript.segments) - 1)]
                audio_start, audio_end, narration = self._timing_for_span(
                    transcript,
                    package.script,
                    char_start,
                    char_end,
                    scene.narration_hint,
                    fallback_segment,
                )
                if event_index > 0 and beats:
                    previous_audio_start = beats[-1].audio_start
                    if previous_audio_start is not None and audio_start <= previous_audio_start:
                        audio_start = previous_audio_start + 0.05
                audio_end = max(audio_end, audio_start + 0.12)

                selected = self._select_assets(scene_assets)
                primary = selected[0].id if selected else None
                support = [asset.id for asset in selected[1:]]
                raw_action = str(event.action or "EXPLAIN").upper()
                action = self._story_action(raw_action, previous_primary, primary)
                targets = [str(value) for value in event.targets if value]
                semantic_context = self.semantic_interpreter.interpret(
                    scene,
                    event,
                    is_first_beat=(beat_number == 1),
                    default_event=not authored_progression,
                )
                semantic_context = self._resolve_relation_timing(
                    semantic_context,
                    transcript=transcript,
                    script=package.script,
                    beat_start=audio_start,
                    beat_end=audio_end,
                )
                beats.append(StoryBeat(
                    id=f"beat-{beat_number:03d}",
                    scene_id=scene.id,
                    start=audio_start,
                    end=audio_end,
                    audio_start=audio_start,
                    audio_end=audio_end,
                    narration=narration,
                    primary_asset_ids=[primary] if primary else [],
                    support_asset_ids=support,
                    action=action,
                    handoff_from=previous_primary if previous_primary and primary != previous_primary else None,
                    semantic_targets=targets,
                    semantic_context=semantic_context,
                ))
                beat_number += 1
                if primary:
                    previous_primary = primary

        beats.sort(key=lambda beat: (
            beat.audio_start if beat.audio_start is not None else beat.start,
            beat.audio_end if beat.audio_end is not None else beat.end,
            beat.id,
        ))
        beats = self._assign_visual_timeline(
            beats,
            transcript.duration,
            preserve_spoken_completion=package.has_authoritative_semantics,
        )
        planned = self.activation.enrich(package, transcript, assets, beats)
        scene_by_id = {scene.id: scene for scene in package.scenes}
        with_authority: list[StoryBeat] = []
        for beat in planned:
            scene = scene_by_id[beat.scene_id]
            authorities, diagnostics = event_authority(scene, beat)
            self.semantic_diagnostics.extend(diagnostics)
            with_authority.append(beat.model_copy(update={"event_authorities": authorities}))
        planned = with_authority
        self.semantic_carrier_audit = []
        self.hidden_content_audit = []
        self.carrier_resolution_report = [
            {"beat_id": beat_id, **resolution.to_payload()}
            for beat_id, resolution in sorted(self.activation.carrier_resolutions.items())
        ]
        if package.has_authoritative_semantics:
            planned = self._resolve_active_visual_semantic_state(planned)
            self.semantic_carrier_audit = self.carrier_auditor.audit(
                package=package, assets=assets, beats=planned,
                resolutions=self.activation.carrier_resolutions,
            )
            self.hidden_content_audit = self.carrier_auditor.audit_hidden_content(
                package=package, assets=assets, beats=planned,
            )
        self._require_quality_contract(package=package, assets=assets, beats=planned)
        self.carrier_auditor.require(self.semantic_carrier_audit)
        self.carrier_auditor.require_hidden_content(self.hidden_content_audit)
        return planned

    @staticmethod
    def _resolve_active_visual_semantic_state(
        beats: list[StoryBeat],
    ) -> list[StoryBeat]:
        """Materialize the monotonic visual lifetime owned by each Scene."""
        output: list[StoryBeat] = []
        active_state: dict[str, str] = {}
        previous_scene_id: str | None = None

        for beat in beats:
            if previous_scene_id != beat.scene_id:
                active_state = {}
            current_state = {
                row.asset_id: str(row.semantic_unit_id or row.asset_id)
                for row in beat.asset_activations
                if (
                    getattr(row, "activation_policy", None) != "SAFE_ABSTENTION"
                    and getattr(row, "policy", None) != "SAFE_ABSTENTION"
                )
            }
            # A semantic-event proxy is Story's proven carrier for an authored event on
            # an existing cutout; that cutout must be visible even if its own
            # activation abstained, otherwise the authored event renders nothing.
            for proxy in beat.semantic_event_proxies:
                current_state.setdefault(proxy.asset_id, proxy.semantic_unit_id)
            # The runtime asset is the Scene-local lifecycle identity. Semantic-event,
            # focus, and role changes may enrich it, but may never retire or re-enter it.
            for asset_id, semantic_unit_id in current_state.items():
                active_state.setdefault(asset_id, semantic_unit_id)

            output.append(beat.model_copy(update={
                "active_visual_semantic_state": dict(active_state),
            }))
            previous_scene_id = beat.scene_id
        return output

    @staticmethod
    def _require_quality_contract(
        *,
        package: CanonicalPackage,
        assets: list[VisualAsset],
        beats: list[StoryBeat],
    ) -> None:
        """Fail at Story ownership instead of emitting incomplete semantic output."""
        beats_by_scene: dict[str, list[StoryBeat]] = defaultdict(list)
        for beat in beats:
            beats_by_scene[beat.scene_id].append(beat)

        rich_scene_ids = {
            scene.id
            for scene in package.scenes
            if (
                scene.units
                or scene.visual_progression
                or scene.semantic_events
                or scene.relations
                or scene.relation_to_previous
            )
        }
        missing_metadata = [
            beat.id
            for beat in beats
            if beat.scene_id in rich_scene_ids and beat.semantic_context is None
        ]
        missing_rich_scenes = sorted(
            scene_id for scene_id in rich_scene_ids if not beats_by_scene.get(scene_id)
        )
        if missing_metadata or missing_rich_scenes:
            raise StageFailedError(
                "Story could not preserve Final Package semantic metadata",
                details={
                    "code": "FINAL_PACKAGE_METADATA_COVERAGE",
                    "beats": missing_metadata,
                    "scenes": missing_rich_scenes,
                },
            )

        eligible_assets = {
            asset.id for asset in assets if asset.can_animate_independently
        }
        represented_assets = {
            asset_id
            for beat in beats
            for asset_id in (*beat.primary_asset_ids, *beat.support_asset_ids)
        }
        missing_assets = sorted(eligible_assets - represented_assets)
        if missing_assets:
            raise StageFailedError(
                "Story dropped independently animatable visual assets",
                details={"code": "ASSET_REACHES_STORY", "asset_ids": missing_assets},
            )

        authored_events = {
            (scene.id, event.semantic_event_id)
            for scene in package.scenes
            for event in scene.semantic_events
            if event.semantic_event_id
        }
        represented_events = {
            (beat.scene_id, event_id)
            for beat in beats
            for event_id in (
                *(
                    activation.semantic_event_id
                    for activation in beat.asset_activations
                    if activation.semantic_event_id
                    and getattr(activation, "activation_policy", None) != "SAFE_ABSTENTION"
                ),
                *(proxy.semantic_event_id for proxy in beat.semantic_event_proxies),
            )
        }
        missing_events = sorted(authored_events - represented_events)
        if missing_events:
            raise StageFailedError(
                "Story could not assign every authored semantic event to a proven visual carrier",
                details={
                    "code": "FINAL_PACKAGE_SEMANTIC_EVENT_COVERAGE",
                    "missing_events": [
                        f"{scene_id}:{event_id}" for scene_id, event_id in missing_events
                    ],
                },
            )

    @classmethod
    def _resolve_relation_timing(
        cls,
        context: StorySemanticContext,
        *,
        transcript: Transcript,
        script: str | None,
        beat_start: float,
        beat_end: float,
    ) -> StorySemanticContext:
        """Resolve authored relation char spans onto Story's narration clock."""
        if not context.relations:
            return context

        lower = max(0.0, float(beat_start))
        upper = max(lower, min(float(beat_end), float(transcript.duration)))
        relations = []
        for relation in context.relations:
            if relation.trigger_char_start is None or relation.trigger_char_end is None:
                relations.append(relation)
                continue
            spoken_start, spoken_end, _ = cls._timing_for_span(
                transcript,
                script,
                relation.trigger_char_start,
                relation.trigger_char_end,
                relation.trigger_text,
            )
            start = max(lower, min(upper, float(spoken_start)))
            end = max(start, min(upper, float(spoken_end)))
            if end - start < 0.025:
                relations.append(relation)
                continue
            relations.append(
                relation.model_copy(update={"spoken_start": start, "spoken_end": end})
            )
        return context.model_copy(update={"relations": relations})

    def _assign_visual_timeline(
        self,
        beats: list[StoryBeat],
        duration: float,
        *,
        preserve_spoken_completion: bool = False,
    ) -> list[StoryBeat]:
        if not beats:
            return beats

        starts: list[float] = []
        previous_start = -self._MIN_VISUAL_BEAT
        previous_audio_end = 0.0
        for index, beat in enumerate(beats):
            audio_start = beat.audio_start if beat.audio_start is not None else beat.start
            gap_before = max(0.0, audio_start - previous_audio_end)
            if index == 0:
                lead = min(self._DEFAULT_VISUAL_LEAD, audio_start)
            else:
                lead = min(
                    self._MAX_VISUAL_LEAD,
                    max(0.18, min(self._DEFAULT_VISUAL_LEAD, gap_before * 0.80 + 0.14)),
                )
            proposed = max(0.0, audio_start - lead)
            visual_start = max(proposed, previous_start + self._MIN_VISUAL_BEAT)
            if preserve_spoken_completion and index > 0:
                visual_start = max(
                    visual_start,
                    min(previous_audio_end, audio_start),
                )
            starts.append(min(visual_start, max(0.0, duration - self._MIN_VISUAL_BEAT)))
            previous_start = starts[-1]
            previous_audio_end = beat.audio_end if beat.audio_end is not None else beat.end

        output: list[StoryBeat] = []
        for index, beat in enumerate(beats):
            start = starts[index]
            if index + 1 < len(beats):
                end = max(start + self._MIN_VISUAL_BEAT, starts[index + 1])
            else:
                end = max(start + self._MIN_VISUAL_BEAT, duration)
            end = min(duration, end)
            output.append(beat.model_copy(update={"start": start, "end": end}))
        return output

    @staticmethod
    def _select_assets(scene_assets: list[VisualAsset]) -> list[VisualAsset]:
        # Final Package geometry already defines the complete scene. Story may rank
        # primary/support meaning, but it must never discard extracted scene assets
        # simply because the scene is dense. Motion becomes calmer as density grows.
        return list(scene_assets)

    @staticmethod
    def _default_event(scene: CanonicalScene) -> CanonicalVisualProgression:
        return CanonicalVisualProgression(
            action="EXPLAIN",
            targets=tuple(unit.unit_id for unit in scene.units if unit.unit_id),
            trigger=CanonicalScriptSpan(
                text=scene.narration_hint,
                global_char_start=scene.script_char_start,
                global_char_end=scene.script_char_end,
            ),
        )

    @staticmethod
    def _story_action(raw_action: str, previous_primary: str | None, primary: str | None) -> str:
        # Semantic action and visual continuity are independent concerns. Changing the
        # primary asset creates ``handoff_from`` on StoryBeat, but it must not erase a
        # RESULT/COMPARE/EMPHASIZE intent coming from the package. Motion consumes both
        # signals separately. ``primary`` is retained in the signature for compatibility.
        del primary
        mapping = {
            "INTRODUCE": "INTRODUCE",
            "REVEAL": "REVEAL_DETAIL",
            "EMPHASIZE": "EMPHASIZE",
            "COMPARE": "COMPARE",
            "RESULT": "RESULT",
            "REJECT": "RESULT",
            "HANDOFF": "HANDOFF",
            "EXPLAIN": "INTRODUCE" if previous_primary is None else "REVEAL_DETAIL",
        }
        return mapping.get(raw_action, "REVEAL_DETAIL")

    @staticmethod
    def _timing_for_span(
        transcript: Transcript,
        script: str | None,
        char_start: int | None,
        char_end: int | None,
        hint: str | None,
        fallback_segment=None,
    ) -> tuple[float, float, str]:
        if char_start is not None and char_end is not None:
            # Canonical script spans are half-open [char_start, char_end): a word that
            # starts at char_end belongs to the NEXT span and is never included.
            words = [
                word for word in transcript.words
                if word.char_start is not None
                and word.char_end is not None
                and word.char_end > char_start
                and word.char_start < char_end
            ]
            if words:
                narration = (script[char_start:char_end] if script else hint) or " ".join(
                    word.text for word in words
                )
                return words[0].start, words[-1].end, narration.strip()

            if script:
                script_length = max(1, len(script))
                start = transcript.duration * max(0, char_start) / script_length
                end = transcript.duration * min(script_length, char_end) / script_length
                narration = script[char_start:char_end].strip() or (hint or "")
                return start, max(start + 0.12, end), narration

        if hint:
            normalized = hint.strip()
            for segment in transcript.segments:
                if normalized and (normalized in segment.text or segment.text in normalized):
                    return segment.start, segment.end, normalized
        if fallback_segment is not None:
            return fallback_segment.start, fallback_segment.end, hint or fallback_segment.text
        if transcript.segments:
            segment = transcript.segments[0]
            return segment.start, segment.end, hint or segment.text
        return 0.0, transcript.duration, hint or ""

    @staticmethod
    def _int_or_none(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
