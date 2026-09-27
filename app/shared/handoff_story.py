from __future__ import annotations

from math import isfinite

from app.canonical import CanonicalPackage
from app.models import StoryBeat, Transcript, VisualAsset

from .handoff_core import _EPS, _HandoffCore


class AssetStoryHandoffMixin(_HandoffCore):
    @classmethod
    def require_assets_for_story(
        cls,
        *,
        package: CanonicalPackage,
        assets: list[VisualAsset],
    ) -> None:
        violations: list[dict[str, object]] = []
        scene_ids = set(package.scene_by_id)
        cls._duplicates(
            (asset.id for asset in assets),
            kind="duplicate_asset_id",
            field="asset_id",
            violations=violations,
        )
        for asset in assets:
            if asset.scene_id not in scene_ids:
                cls._add(
                    violations,
                    "foreign_asset_scene",
                    asset_id=asset.id,
                    scene_id=asset.scene_id,
                )
        cls._raise(
            "assets->story",
            "ASSET_HANDOFF_CONTRACT_VIOLATIONS",
            violations,
        )

    @classmethod
    def require_story_for_choreography(
        cls,
        *,
        package: CanonicalPackage,
        transcript: Transcript,
        assets: list[VisualAsset],
        story: list[StoryBeat],
    ) -> None:
        violations: list[dict[str, object]] = []
        asset_by_id = {asset.id: asset for asset in assets}
        scene_by_id = package.scene_by_id
        events_by_scene = {
            scene.id: {event.semantic_event_id for event in scene.semantic_events}
            for scene in package.scenes
        }
        cls._duplicates(
            (beat.id for beat in story),
            kind="duplicate_story_beat_id",
            field="beat_id",
            violations=violations,
        )

        for beat in story:
            if beat.scene_id not in scene_by_id:
                cls._add(
                    violations,
                    "story_unknown_scene",
                    beat_id=beat.id,
                    scene_id=beat.scene_id,
                )
                continue

            if not cls._window(beat.start, beat.end, lower=0.0, upper=transcript.duration):
                cls._add(
                    violations,
                    "story_window_outside_transcript",
                    beat_id=beat.id,
                    start=beat.start,
                    end=beat.end,
                    transcript_duration=transcript.duration,
                )
            if (beat.audio_start is None) != (beat.audio_end is None):
                cls._add(
                    violations,
                    "partial_story_audio_window",
                    beat_id=beat.id,
                    audio_start=beat.audio_start,
                    audio_end=beat.audio_end,
                )
            elif beat.audio_start is not None and beat.audio_end is not None:
                # Story deliberately separates narration ownership from visual timing:
                # start/end may lead the spoken phrase and may hand off visually before
                # audio_end. The cross-layer contract therefore bounds narration to the
                # transcript, not to the visual beat window.
                if not cls._window(
                    beat.audio_start,
                    beat.audio_end,
                    lower=0.0,
                    upper=transcript.duration,
                    allow_equal=True,
                ):
                    cls._add(
                        violations,
                        "story_audio_window_outside_transcript",
                        beat_id=beat.id,
                        audio_start=beat.audio_start,
                        audio_end=beat.audio_end,
                        transcript_duration=transcript.duration,
                    )

            referenced_assets = [*beat.primary_asset_ids, *beat.support_asset_ids]
            cls._duplicates(
                referenced_assets,
                kind="duplicate_story_asset_role",
                field="asset_id",
                violations=violations,
                context={"beat_id": beat.id},
            )
            for asset_id in referenced_assets:
                cls._require_asset_scene(
                    violations,
                    asset_by_id=asset_by_id,
                    asset_id=asset_id,
                    scene_id=beat.scene_id,
                    kind="story_asset_reference",
                    beat_id=beat.id,
                )

            cls._duplicates(
                (activation.asset_id for activation in beat.asset_activations),
                kind="duplicate_story_activation",
                field="asset_id",
                violations=violations,
                context={"beat_id": beat.id},
            )
            scene_event_ids = events_by_scene.get(beat.scene_id, set())
            for activation in beat.asset_activations:
                cls._require_asset_scene(
                    violations,
                    asset_by_id=asset_by_id,
                    asset_id=activation.asset_id,
                    scene_id=beat.scene_id,
                    kind="activation_asset_reference",
                    beat_id=beat.id,
                )
                if (
                    activation.semantic_event_id
                    and activation.semantic_event_id not in scene_event_ids
                ):
                    cls._add(
                        violations,
                        "activation_unknown_semantic_event",
                        beat_id=beat.id,
                        asset_id=activation.asset_id,
                        event_id=activation.semantic_event_id,
                    )
                if (activation.spoken_start is None) != (activation.spoken_end is None):
                    cls._add(
                        violations,
                        "partial_activation_spoken_window",
                        beat_id=beat.id,
                        asset_id=activation.asset_id,
                    )
                elif activation.spoken_start is not None and activation.spoken_end is not None:
                    if not cls._window(
                        activation.spoken_start,
                        activation.spoken_end,
                        lower=beat.start,
                        upper=beat.end,
                    ):
                        cls._add(
                            violations,
                            "activation_window_outside_beat",
                            beat_id=beat.id,
                            asset_id=activation.asset_id,
                            spoken_start=activation.spoken_start,
                            spoken_end=activation.spoken_end,
                            beat_start=beat.start,
                            beat_end=beat.end,
                        )

            proxy_keys: list[tuple[str, str]] = []
            for proxy in beat.semantic_event_proxies:
                proxy_keys.append((proxy.asset_id, proxy.semantic_event_id))
                cls._require_asset_scene(
                    violations,
                    asset_by_id=asset_by_id,
                    asset_id=proxy.asset_id,
                    scene_id=beat.scene_id,
                    kind="proxy_asset_reference",
                    beat_id=beat.id,
                )
                if proxy.semantic_event_id not in scene_event_ids:
                    cls._add(
                        violations,
                        "proxy_unknown_semantic_event",
                        beat_id=beat.id,
                        asset_id=proxy.asset_id,
                        event_id=proxy.semantic_event_id,
                    )
                if not (
                    isfinite(proxy.reveal_start)
                    and isfinite(proxy.semantic_peak)
                    and isfinite(proxy.settle_at)
                    and beat.start - _EPS <= proxy.reveal_start
                    <= proxy.semantic_peak
                    <= proxy.settle_at <= beat.end + _EPS
                ):
                    cls._add(
                        violations,
                        "proxy_window_outside_beat",
                        beat_id=beat.id,
                        asset_id=proxy.asset_id,
                        event_id=proxy.semantic_event_id,
                        reveal_start=proxy.reveal_start,
                        semantic_peak=proxy.semantic_peak,
                        settle_at=proxy.settle_at,
                        beat_start=beat.start,
                        beat_end=beat.end,
                    )
            cls._duplicates(
                proxy_keys,
                kind="duplicate_story_proxy",
                field="asset_event",
                violations=violations,
                context={"beat_id": beat.id},
            )

        cls._raise(
            "story->choreography",
            "STORY_HANDOFF_CONTRACT_VIOLATIONS",
            violations,
        )

