from __future__ import annotations

from app.assets import AssetManager
from app.director.models import SceneDirection
from app.director.qwen import Qwen3VLBackend
from app.models import PackageModel, StoryBeat, VisualAsset


class VisualDirector:
    """Turn story semantics into scene intent; never emit raw coordinates."""

    def __init__(self, backend: Qwen3VLBackend | None = None) -> None:
        self.backend = backend or Qwen3VLBackend()

    def plan(
        self,
        package: PackageModel,
        story: list[StoryBeat],
        assets: list[VisualAsset],
    ) -> list[SceneDirection]:
        by_scene: dict[str, list[VisualAsset]] = {}
        for asset in assets:
            by_scene.setdefault(asset.scene_id, []).append(asset)
        scene_by_id = {scene.id: scene for scene in package.scenes}

        output: list[SceneDirection] = []
        for beat in story:
            ids = tuple(dict.fromkeys([*beat.primary_asset_ids, *beat.support_asset_ids]))
            primary = beat.primary_asset_ids[0] if beat.primary_asset_ids else (ids[0] if ids else None)
            interaction = beat.support_asset_ids[0] if beat.support_asset_ids else None
            layout_intent = self._layout_intent(len({AssetManager.family_id(a) for a in by_scene.get(beat.scene_id, []) if a.id in ids}))
            motion_intent = str(beat.action or "REVEAL").upper()
            text_intent = "semantic_keywords"
            evidence = ["story_semantics", "final_package_geometry"]

            scene = scene_by_id.get(beat.scene_id)
            if scene and self.backend.enabled:
                proposal = self.backend.decide(
                    scene.image_path,
                    self._prompt(beat, ids),
                )
                if proposal:
                    candidate_primary = proposal.get("primary_asset_id")
                    candidate_interaction = proposal.get("interaction_asset_id")
                    if candidate_primary in ids:
                        primary = candidate_primary
                    if candidate_interaction in ids:
                        interaction = candidate_interaction
                    layout_intent = str(proposal.get("layout_intent") or layout_intent)
                    motion_intent = str(proposal.get("motion_intent") or motion_intent)
                    text_intent = str(proposal.get("text_intent") or text_intent)
                    evidence.append("qwen3_vl")

            output.append(SceneDirection(
                beat_id=beat.id,
                primary_asset_id=primary,
                interaction_asset_id=interaction,
                active_asset_ids=ids,
                layout_intent=layout_intent,
                motion_intent=motion_intent,
                text_intent=text_intent,
                evidence=tuple(evidence),
            ))
        return output

    @staticmethod
    def _layout_intent(count: int) -> str:
        if count <= 1:
            return "single_focus"
        if count == 2:
            return "two_element_authored"
        if count == 3:
            return "three_element_authored"
        return "four_element_authored"

    @staticmethod
    def _prompt(beat: StoryBeat, ids: tuple[str, ...]) -> str:
        return (
            "You are the HEXA visual director. Return one JSON object only. "
            "Do not return coordinates. Choose only asset ids from the provided list. "
            f"Narration: {beat.narration!r}. Action: {beat.action}. Assets: {list(ids)!r}. "
            "Keys: primary_asset_id, interaction_asset_id, layout_intent, motion_intent, text_intent."
        )
