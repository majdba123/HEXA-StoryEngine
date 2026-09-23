from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.models import (
    PackageModel,
    SceneSource,
    StoryBeat,
    Transcript,
    TranscriptWord,
    VisualAsset,
)
from app.story.activation import SemanticActivationPlanner
from app.story.identity import VisualIdentityBinder


def _asset(
    tmp_path: Path,
    asset_id: str,
    bbox: tuple[int, int, int, int],
    *,
    area: float,
    parent: str | None = None,
    family: str | None = None,
) -> VisualAsset:
    return VisualAsset(
        id=asset_id,
        scene_id="s",
        role="object",
        image_path=tmp_path / f"{asset_id}.png",
        extraction_method="test",
        source_bbox=bbox,
        source_canvas_width=1000,
        source_canvas_height=1000,
        source_area_ratio=area,
        parent_asset_id=parent,
        asset_family_id=family,
    )


def _locator(cx: float, cy: float, width: float, height: float) -> dict:
    return {
        "coordinate_space": "normalized_scene",
        "cx": cx,
        "cy": cy,
        "width": width,
        "height": height,
    }


def test_visual_locator_binds_semantic_intent_to_geometry_not_visual_weight(tmp_path: Path) -> None:
    scene = SceneSource(id="s", image_path=tmp_path / "scene.png", order=0)
    assets = [
        _asset(tmp_path, "small-left", (100, 200, 120, 120), area=0.02),
        _asset(tmp_path, "large-right", (650, 180, 280, 280), area=0.25),
    ]
    semantic_assets = [
        {"asset_id": "intent-password", "visual_locator": _locator(0.16, 0.26, 0.12, 0.12)},
        {"asset_id": "intent-shield", "visual_locator": _locator(0.79, 0.32, 0.28, 0.28)},
    ]

    result = VisualIdentityBinder().bind(
        scene=scene,
        semantic_assets=semantic_assets,
        assets=assets,
    )

    assert result.matches["intent-password"].real_asset_id == "small-left"
    assert result.matches["intent-shield"].real_asset_id == "large-right"
    assert result.unresolved_locator_ids == frozenset()
    assert all(row.source == "visual_locator" for row in result.matches.values())


def test_visual_locator_abstains_when_two_cutouts_are_not_separable(tmp_path: Path) -> None:
    scene = SceneSource(id="s", image_path=tmp_path / "scene.png", order=0)
    assets = [
        _asset(tmp_path, "a", (410, 410, 180, 180), area=0.04),
        _asset(tmp_path, "b", (420, 410, 180, 180), area=0.04),
    ]

    result = VisualIdentityBinder().bind(
        scene=scene,
        semantic_assets=[{
            "asset_id": "intent",
            "visual_locator": _locator(0.505, 0.50, 0.18, 0.18),
        }],
        assets=assets,
    )

    assert "intent" not in result.matches
    assert result.unresolved_locator_ids == frozenset({"intent"})
    assert result.has_incomplete_locator_binding is True


def test_absent_visual_locator_does_not_change_legacy_identity_path(tmp_path: Path) -> None:
    scene = SceneSource(id="s", image_path=tmp_path / "scene.png", order=0)
    result = VisualIdentityBinder().bind(
        scene=scene,
        semantic_assets=[{"asset_id": "intent-a"}, {"asset_id": "intent-b"}],
        assets=[_asset(tmp_path, "real", (100, 100, 200, 200), area=0.04)],
    )

    assert result.locator_semantic_ids == frozenset()
    assert result.matches == {}
    assert result.has_incomplete_locator_binding is False


def test_activation_uses_locator_identity_before_heuristic_semantic_map(tmp_path: Path) -> None:
    script = "alpha beta"
    scene = SceneSource(
        id="s",
        image_path=tmp_path / "scene.png",
        order=0,
        script_char_start=0,
        script_char_end=len(script) - 1,
        units=[
            {"unit_id": "intent-a", "type": "VISUAL_ASSET_INTENT", "role": "PRIMARY"},
            {"unit_id": "intent-b", "type": "VISUAL_ASSET_INTENT", "role": "OBJECT"},
        ],
    )
    package = PackageModel(
        root=tmp_path,
        package_id="identity",
        scenes=[scene],
        script=script,
        semantic_bindings={
            "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
            "scenes": [{
                "scene_id": "s",
                "semantic_groups": [{
                    "semantic_group_id": "g",
                    "script_text": script,
                    "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                    "asset_ids": ["intent-a", "intent-b"],
                }],
                "assets": [
                    {
                        "asset_id": "intent-a",
                        "script_text": script,
                        "binding_type": "EXPLICIT",
                        "semantic_group_id": "g",
                        "sequence_order": 1,
                        "confidence": 1.0,
                        "visual_locator": _locator(0.15, 0.25, 0.10, 0.10),
                    },
                    {
                        "asset_id": "intent-b",
                        "script_text": script,
                        "binding_type": "SEMANTIC",
                        "semantic_group_id": "g",
                        "sequence_order": 2,
                        "confidence": 0.95,
                        "visual_locator": _locator(0.78, 0.30, 0.26, 0.26),
                    },
                ],
            }],
        },
    )
    transcript = Transcript(
        language="en",
        duration=2.0,
        segments=[],
        words=[
            TranscriptWord(text="alpha", start=0.2, end=0.5, char_start=0, char_end=5),
            TranscriptWord(text="beta", start=0.7, end=1.1, char_start=6, char_end=10),
        ],
    )
    # The old heuristic would assign PRIMARY intent-a to the much larger right cutout.
    assets = [
        _asset(tmp_path, "left-small", (100, 200, 100, 100), area=0.01),
        _asset(tmp_path, "right-large", (650, 170, 260, 260), area=0.20),
    ]
    beat = StoryBeat(
        id="b",
        scene_id="s",
        start=0.0,
        end=1.3,
        audio_start=0.2,
        audio_end=1.1,
        narration=script,
        action="INTRODUCE",
    )

    result = SemanticActivationPlanner().enrich(package, transcript, assets, [beat])[0]
    own = [row for row in result.asset_activations if row.policy in {"EXPLICIT", "SEMANTIC"}]
    by_semantic = {row.semantic_unit_id: row for row in own}

    assert by_semantic["intent-a"].asset_id == "left-small"
    assert by_semantic["intent-b"].asset_id == "right-large"
    assert by_semantic["intent-a"].sequence_order == 1
    assert by_semantic["intent-b"].sequence_order == 2
    assert any("visual_identity_binding" in item for item in by_semantic["intent-a"].evidence)


def test_ambiguous_locator_disables_single_group_support_guessing(tmp_path: Path) -> None:
    script = "alpha beta"
    scene = SceneSource(
        id="s",
        image_path=tmp_path / "scene.png",
        order=0,
        script_char_start=0,
        script_char_end=len(script) - 1,
        units=[{"unit_id": "intent-a", "type": "VISUAL_ASSET_INTENT", "role": "PRIMARY"}],
    )
    package = PackageModel(
        root=tmp_path,
        package_id="ambiguous",
        scenes=[scene],
        script=script,
        semantic_bindings={
            "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
            "scenes": [{
                "scene_id": "s",
                "semantic_groups": [{
                    "semantic_group_id": "g",
                    "script_text": script,
                    "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                    "asset_ids": ["intent-a"],
                }],
                "assets": [{
                    "asset_id": "intent-a",
                    "script_text": script,
                    "binding_type": "EXPLICIT",
                    "semantic_group_id": "g",
                    "sequence_order": 1,
                    "confidence": 1.0,
                    "visual_locator": _locator(0.505, 0.50, 0.18, 0.18),
                }],
            }],
        },
    )
    transcript = Transcript(
        language="en",
        duration=1.5,
        segments=[],
        words=[
            TranscriptWord(text="alpha", start=0.2, end=0.5, char_start=0, char_end=5),
            TranscriptWord(text="beta", start=0.6, end=0.9, char_start=6, char_end=10),
        ],
    )
    assets = [
        _asset(tmp_path, "a", (410, 410, 180, 180), area=0.04),
        _asset(tmp_path, "b", (420, 410, 180, 180), area=0.04),
        _asset(tmp_path, "extra", (100, 100, 100, 100), area=0.01),
    ]
    beat = StoryBeat(
        id="b",
        scene_id="s",
        start=0.0,
        end=1.1,
        audio_start=0.2,
        audio_end=0.9,
        narration=script,
        action="INTRODUCE",
    )

    result = SemanticActivationPlanner().enrich(package, transcript, assets, [beat])[0]

    assert all(row.policy == "FALLBACK" for row in result.asset_activations)
    assert all(row.source != "final_package_scene_support" for row in result.asset_activations)


def test_scene_unit_visual_locator_is_supported_without_duplicate_semantic_metadata(
    tmp_path: Path,
) -> None:
    scene = SceneSource(
        id="s",
        image_path=tmp_path / "scene.png",
        order=0,
        units=[{
            "unit_id": "intent",
            "type": "VISUAL_ASSET_INTENT",
            "visual_locator": _locator(0.20, 0.30, 0.10, 0.10),
        }],
    )
    result = VisualIdentityBinder().bind(
        scene=scene,
        semantic_assets=[{"asset_id": "intent"}],
        assets=[_asset(tmp_path, "real", (150, 250, 100, 100), area=0.01)],
    )

    assert result.matches["intent"].real_asset_id == "real"
    assert result.matches["intent"].source == "visual_locator"


def test_pass2_family_canvas_uses_alpha_footprint_for_identity(tmp_path: Path) -> None:
    family_bbox = (200, 200, 600, 400)
    parent_path = tmp_path / "family-main.png"
    child_path = tmp_path / "family-child.png"

    parent_image = Image.new("RGBA", (600, 400), (255, 255, 255, 0))
    ImageDraw.Draw(parent_image).rectangle((40, 80, 240, 320), fill=(10, 10, 10, 255))
    parent_image.save(parent_path)
    child_image = Image.new("RGBA", (600, 400), (255, 255, 255, 0))
    ImageDraw.Draw(child_image).rectangle((390, 120, 550, 280), fill=(10, 10, 10, 255))
    child_image.save(child_path)

    parent = VisualAsset(
        id="family", scene_id="s", role="object", image_path=parent_path,
        extraction_method="test+pass2_main", source_bbox=family_bbox,
        source_canvas_width=1000, source_canvas_height=1000,
        source_area_ratio=0.12, asset_family_id="family",
        render_as_family_canvas=True,
    )
    child = VisualAsset(
        id="family:secondary-01", scene_id="s", role="secondary_object",
        image_path=child_path, extraction_method="test+pass2_secondary",
        source_bbox=family_bbox, source_canvas_width=1000, source_canvas_height=1000,
        source_area_ratio=0.04, parent_asset_id="family", asset_family_id="family",
        render_as_family_canvas=True,
    )
    scene = SceneSource(id="s", image_path=tmp_path / "scene.png", order=0)

    result = VisualIdentityBinder().bind(
        scene=scene,
        semantic_assets=[
            {
                "asset_id": "parent-intent",
                "visual_locator": _locator(0.34, 0.40, 0.20, 0.24),
            },
            {
                "asset_id": "child-intent",
                "parent_asset_id": "parent-intent",
                "visual_locator": _locator(0.67, 0.40, 0.16, 0.16),
            },
        ],
        assets=[parent, child],
    )

    assert result.matches["parent-intent"].real_asset_id == "family"
    assert result.matches["child-intent"].real_asset_id == "family:secondary-01"


def test_locator_claim_cannot_be_overridden_by_heuristic_semantic_map(tmp_path: Path) -> None:
    script = "alpha beta"
    scene = SceneSource(
        id="s",
        image_path=tmp_path / "scene.png",
        order=0,
        script_char_start=0,
        script_char_end=len(script) - 1,
        units=[
            {"unit_id": "intent-a", "type": "VISUAL_ASSET_INTENT", "role": "PRIMARY"},
            {"unit_id": "intent-b", "type": "VISUAL_ASSET_INTENT", "role": "OBJECT"},
        ],
    )
    package = PackageModel(
        root=tmp_path,
        package_id="locator-reservation",
        scenes=[scene],
        script=script,
        semantic_bindings={
            "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
            "scenes": [{
                "scene_id": "s",
                "semantic_groups": [{
                    "semantic_group_id": "g",
                    "script_text": script,
                    "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                    "asset_ids": ["intent-a", "intent-b"],
                }],
                "assets": [
                    {
                        "asset_id": "intent-a",
                        "script_text": script,
                        "binding_type": "EXPLICIT",
                        "semantic_group_id": "g",
                        "sequence_order": 1,
                        "confidence": 1.0,
                        "visual_locator": _locator(0.15, 0.25, 0.10, 0.10),
                    },
                    {
                        "asset_id": "intent-b",
                        "script_text": script,
                        "binding_type": "SEMANTIC",
                        "semantic_group_id": "g",
                        "sequence_order": 2,
                        "confidence": 0.9,
                    },
                ],
            }],
        },
    )
    transcript = Transcript(
        language="en",
        duration=2.0,
        segments=[],
        words=[
            TranscriptWord(text="alpha", start=0.2, end=0.5, char_start=0, char_end=5),
            TranscriptWord(text="beta", start=0.7, end=1.1, char_start=6, char_end=10),
        ],
    )
    assets = [
        _asset(tmp_path, "left-small", (100, 200, 100, 100), area=0.01),
        _asset(tmp_path, "right-large", (650, 170, 260, 260), area=0.20),
    ]
    beat = StoryBeat(
        id="b",
        scene_id="s",
        start=0.0,
        end=1.3,
        audio_start=0.2,
        audio_end=1.1,
        narration=script,
        action="INTRODUCE",
    )

    result = SemanticActivationPlanner().enrich(package, transcript, assets, [beat])[0]

    own = [row for row in result.asset_activations if row.policy in {"EXPLICIT", "SEMANTIC"}]
    assert len(own) == 1
    assert own[0].semantic_unit_id == "intent-a"
    assert own[0].asset_id == "left-small"
    assert not any(
        row.semantic_unit_id == "intent-b" and row.policy in {"EXPLICIT", "SEMANTIC"}
        for row in result.asset_activations
    )
