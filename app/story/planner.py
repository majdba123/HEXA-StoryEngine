from __future__ import annotations

from collections import defaultdict

from app.models import PackageModel, SceneSource, StoryBeat, Transcript, VisualAsset


class StoryPlanner:
    """Build narration-locked visual beats from package intent.

    ``audio_start/audio_end`` preserve the semantic narration timing. ``start/end`` own
    the visual timeline and may begin slightly earlier so an entrance settles on the
    narrated idea instead of reacting after the listener has already heard it.
    """

    _DEFAULT_VISUAL_LEAD = 0.24
    _MAX_VISUAL_LEAD = 0.30
    _MIN_VISUAL_BEAT = 0.08

    def plan(
        self,
        package: PackageModel,
        transcript: Transcript,
        assets: list[VisualAsset],
    ) -> list[StoryBeat]:
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
            events = scene.visual_progression or [self._default_event(scene)]
            for event_index, event in enumerate(events):
                trigger = event.get("trigger") if isinstance(event.get("trigger"), dict) else {}
                char_start = self._int_or_none(trigger.get("global_char_start"))
                char_end = self._int_or_none(trigger.get("global_char_end"))
                if char_start is None:
                    char_start = scene.script_char_start
                if char_end is None:
                    char_end = scene.script_char_end
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
                raw_action = str(event.get("action") or "EXPLAIN").upper()
                action = self._story_action(raw_action, previous_primary, primary)
                targets = [str(value) for value in event.get("targets", []) if value]
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
                ))
                beat_number += 1
                if primary:
                    previous_primary = primary

        beats.sort(key=lambda beat: (
            beat.audio_start if beat.audio_start is not None else beat.start,
            beat.audio_end if beat.audio_end is not None else beat.end,
            beat.id,
        ))
        return self._assign_visual_timeline(beats, transcript.duration)

    def _assign_visual_timeline(self, beats: list[StoryBeat], duration: float) -> list[StoryBeat]:
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
        if len(scene_assets) <= 6:
            return scene_assets
        return scene_assets[:6]

    @staticmethod
    def _default_event(scene: SceneSource) -> dict:
        return {
            "action": "EXPLAIN",
            "targets": [unit.get("unit_id") for unit in scene.units if unit.get("unit_id")],
            "trigger": {
                "global_char_start": scene.script_char_start,
                "global_char_end": scene.script_char_end,
                "phrase": scene.narration_hint,
            },
        }

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
            effective_end = char_end + 1
            words = [
                word for word in transcript.words
                if word.char_start is not None
                and word.char_end is not None
                and word.char_end > char_start
                and word.char_start < effective_end
            ]
            if words:
                narration = (script[char_start:effective_end] if script else hint) or " ".join(
                    word.text for word in words
                )
                return words[0].start, words[-1].end, narration.strip()

            if script:
                script_length = max(1, len(script))
                start = transcript.duration * max(0, char_start) / script_length
                end = transcript.duration * min(script_length, effective_end) / script_length
                narration = script[char_start:effective_end].strip() or (hint or "")
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
