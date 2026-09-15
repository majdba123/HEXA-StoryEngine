from __future__ import annotations

from collections import defaultdict

from app.models import PackageModel, StoryBeat, Transcript, VisualAsset


class StoryPlanner:
    """Builds visual beats; it does not decide pixels or animation curves."""

    def plan(
        self,
        package: PackageModel,
        transcript: Transcript,
        assets: list[VisualAsset],
    ) -> list[StoryBeat]:
        assets_by_scene: dict[str, list[VisualAsset]] = defaultdict(list)
        for asset in assets:
            assets_by_scene[asset.scene_id].append(asset)
        scenes = package.scenes
        beats: list[StoryBeat] = []
        previous_primary: str | None = None
        for index, segment in enumerate(transcript.segments):
            scene = scenes[min(index * len(scenes) // max(1, len(transcript.segments)), len(scenes) - 1)]
            scene_assets = assets_by_scene.get(scene.id, [])
            primary = scene_assets[0].id if scene_assets else None
            support = [asset.id for asset in scene_assets[1:3]]
            action = "INTRODUCE" if previous_primary != primary else "REVEAL_DETAIL"
            if previous_primary and primary and previous_primary != primary:
                action = "HANDOFF"
            beats.append(StoryBeat(
                id=f"beat-{index + 1:03d}",
                scene_id=scene.id,
                start=segment.start,
                end=segment.end,
                narration=segment.text,
                primary_asset_ids=[primary] if primary else [],
                support_asset_ids=support,
                action=action,
                handoff_from=previous_primary if action == "HANDOFF" else None,
            ))
            if primary:
                previous_primary = primary
        return beats
