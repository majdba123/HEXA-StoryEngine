from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageOps

from app.models import SceneSource, StoryBeat, VisualAsset


_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VisualSemanticAsset:
    asset_id: str
    description: str
    category: str | None
    confidence: float
    semantic: bool
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VisualSemanticInventory:
    scene_id: str
    assets: dict[str, VisualSemanticAsset] = field(default_factory=dict)
    contact_sheet_path: Path | None = None
    source: str = "none"

    def for_asset(self, asset_id: str) -> VisualSemanticAsset | None:
        return self.assets.get(asset_id)


class VisualSemanticResolver:
    """Understand extracted assets without owning extraction or timing.

    Inventory creation is deliberately narration-blind so the VLM cannot copy the
    answer from the script. Story later compares the visual descriptions against
    forced-aligned narration.
    """

    _MIN_DESCRIPTION_CONFIDENCE = 0.62
    _MAX_ASSETS_PER_SHEET = 24
    _CONTACT_WIDTH = 1600
    _SCENE_HEIGHT = 620
    _TILE_WIDTH = 360
    _TILE_HEIGHT = 260

    def __init__(self, backend: Any | None, *, cache_root: Path | None = None) -> None:
        self.backend = backend
        if cache_root is None:
            configured = os.getenv("HEXA_SEMANTIC_CACHE_ROOT", "").strip()
            cache_root = (
                Path(configured).expanduser()
                if configured
                else Path.home() / ".hexa-storyengine" / "semantic-cache"
            )
        self.cache_root = cache_root.resolve()
        self._memory: dict[str, VisualSemanticInventory] = {}
        self._digest_cache: dict[tuple[str, int, int], str] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.backend is not None and getattr(self.backend, "enabled", False))

    def resolve(
        self, *, scene: SceneSource, assets: list[VisualAsset], beat: StoryBeat,
    ) -> VisualSemanticInventory:
        del beat
        eligible = self._eligible_assets(assets)
        if not self.enabled or not eligible:
            return VisualSemanticInventory(scene_id=scene.id)

        cache_key = self._inventory_key(scene, eligible)
        cached = self._memory.get(cache_key)
        if cached is not None:
            return cached

        cache_file = self.cache_root / "inventory" / f"{cache_key}.json"
        sheet_path = self.cache_root / "contact-sheets" / f"{cache_key}.png"
        disk = self._read_cache(cache_file, scene.id, eligible, sheet_path)
        if disk is not None:
            self._memory[cache_key] = disk
            return disk

        sheet_path.parent.mkdir(parents=True, exist_ok=True)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._build_contact_sheet(scene, eligible, sheet_path)
        except Exception as exc:
            _LOG.warning(
                "VISUAL_SEMANTIC_CONTACT_SHEET_FAILED scene=%s error=%s", scene.id, exc
            )
            inventory = VisualSemanticInventory(scene_id=scene.id)
            self._memory[cache_key] = inventory
            return inventory

        prompt = self._inventory_prompt(eligible)
        try:
            payload = self.backend.decide(sheet_path, prompt)
        except Exception as exc:
            _LOG.warning("VISUAL_SEMANTIC_RUNTIME_FAILED scene=%s error=%s", scene.id, exc)
            payload = None

        parsed = self._parse_inventory(payload, eligible)
        inventory = VisualSemanticInventory(
            scene_id=scene.id,
            assets=parsed,
            contact_sheet_path=sheet_path,
            source="vlm_contact_sheet" if parsed else "none",
        )
        self._write_cache(cache_file, inventory)
        self._memory[cache_key] = inventory
        return inventory

    def _eligible_assets(self, assets: Iterable[VisualAsset]) -> list[VisualAsset]:
        rows = [
            asset for asset in assets
            if asset.can_animate_independently
            and (asset.role or "").casefold() not in {"background", "decorative"}
            and asset.image_path.is_file()
        ]
        rows.sort(key=lambda asset: (
            -(asset.source_area_ratio or 0.0),
            asset.parent_asset_id is not None,
            asset.id,
        ))
        return rows[: self._MAX_ASSETS_PER_SHEET]

    def _inventory_key(self, scene: SceneSource, assets: list[VisualAsset]) -> str:
        digest = hashlib.sha256()
        digest.update(b"visual-semantic-resolver-v2\0")
        digest.update(scene.id.encode("utf-8"))
        digest.update(self._file_digest(scene.image_path).encode("ascii"))
        for asset in assets:
            digest.update(asset.id.encode("utf-8"))
            digest.update((asset.role or "").encode("utf-8"))
            digest.update(self._file_digest(asset.image_path).encode("ascii"))
            digest.update(str(asset.source_bbox).encode("ascii"))
            digest.update(str(asset.parent_asset_id).encode("utf-8"))
        return digest.hexdigest()

    def _file_digest(self, path: Path) -> str:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        cached = self._digest_cache.get(key)
        if cached is not None:
            return cached
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        value = digest.hexdigest()
        self._digest_cache[key] = value
        return value

    def _build_contact_sheet(
        self, scene: SceneSource, assets: list[VisualAsset], output: Path,
    ) -> None:
        scene_image = Image.open(scene.image_path).convert("RGB")
        scene_panel = ImageOps.contain(
            scene_image, (self._CONTACT_WIDTH - 40, self._SCENE_HEIGHT - 80),
        )
        cols = max(1, self._CONTACT_WIDTH // self._TILE_WIDTH)
        rows = (len(assets) + cols - 1) // cols
        height = self._SCENE_HEIGHT + rows * self._TILE_HEIGHT + 30
        canvas = Image.new("RGB", (self._CONTACT_WIDTH, height), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text((18, 12), f"AUTHORED SCENE — {scene.id}", fill="black")
        sx = (self._CONTACT_WIDTH - scene_panel.width) // 2
        canvas.paste(scene_panel, (sx, 38))
        draw.rectangle(
            (sx - 2, 36, sx + scene_panel.width + 1, 38 + scene_panel.height + 1),
            outline="black", width=2,
        )
        grid_y = self._SCENE_HEIGHT
        for index, asset in enumerate(assets):
            col = index % cols
            row = index // cols
            x = col * self._TILE_WIDTH + 8
            y = grid_y + row * self._TILE_HEIGHT
            tile_box = (x, y, x + self._TILE_WIDTH - 16, y + self._TILE_HEIGHT - 14)
            draw.rectangle(tile_box, outline="black", width=2)
            draw.text((x + 8, y + 7), asset.id, fill="black")
            draw.text((x + 8, y + 24), f"role={asset.role}", fill="black")
            try:
                image = Image.open(asset.image_path).convert("RGBA")
                background = Image.new("RGBA", image.size, "white")
                background.alpha_composite(image)
                rendered = ImageOps.contain(
                    background.convert("RGB"),
                    (self._TILE_WIDTH - 36, self._TILE_HEIGHT - 70),
                )
                px = x + (self._TILE_WIDTH - rendered.width) // 2 - 8
                py = y + 50 + (self._TILE_HEIGHT - 70 - rendered.height) // 2
                canvas.paste(rendered, (px, py))
            except Exception as exc:
                _LOG.warning(
                    "VISUAL_SEMANTIC_ASSET_PREVIEW_FAILED asset=%s error=%s", asset.id, exc
                )
        output.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output, format="PNG", optimize=True)

    @staticmethod
    def _inventory_prompt(assets: list[VisualAsset]) -> str:
        rows = [{
            "asset_id": asset.id,
            "role": asset.role,
            "bbox": list(asset.source_bbox) if asset.source_bbox else None,
            "parent_asset_id": asset.parent_asset_id,
            "independent": asset.can_animate_independently,
        } for asset in assets]
        return (
            "You are the visual semantic inventory stage of a production video editor. "
            "The contact sheet contains the authored final scene followed by isolated "
            "cutouts labelled with exact asset IDs. Do not use narration or infer timing. "
            "For each clearly recognizable, meaningful cutout, return a short concrete "
            "description of what the visible object/action represents in context. Describe "
            "visual meaning, not layout. Do not invent asset IDs. Decorative shapes, "
            "shadows, fragments, masks, and ambiguous cutouts must have semantic=false. "
            "Return JSON only: "
            "{\"assets\":[{\"asset_id\":string,\"description\":string,"
            "\"category\":string,\"semantic\":boolean,\"confidence\":0..1}]}. "
            f"Allowed assets: {json.dumps(rows, ensure_ascii=False)}"
        )

    def _parse_inventory(
        self, payload: Any, assets: list[VisualAsset],
    ) -> dict[str, VisualSemanticAsset]:
        if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
            return {}
        valid = {asset.id for asset in assets}
        parsed: dict[str, VisualSemanticAsset] = {}
        for row in payload["assets"]:
            if not isinstance(row, dict):
                continue
            asset_id = str(row.get("asset_id") or "")
            description = str(row.get("description") or "").strip()
            category_raw = row.get("category")
            category = str(category_raw).strip() if category_raw is not None else None
            semantic = row.get("semantic") is True
            try:
                confidence = float(row.get("confidence"))
            except (TypeError, ValueError):
                continue
            if (
                asset_id not in valid
                or not 0.0 <= confidence <= 1.0
                or not description
                or len(description) > 320
                or confidence < self._MIN_DESCRIPTION_CONFIDENCE
            ):
                continue
            parsed[asset_id] = VisualSemanticAsset(
                asset_id=asset_id,
                description=description,
                category=category,
                confidence=confidence,
                semantic=semantic,
                evidence=("vlm_contact_sheet_inventory",),
            )
        return parsed

    @staticmethod
    def _write_cache(path: Path, inventory: VisualSemanticInventory) -> None:
        payload = {
            "version": 2,
            "scene_id": inventory.scene_id,
            "source": inventory.source,
            "assets": [
                {
                    "asset_id": row.asset_id,
                    "description": row.description,
                    "category": row.category,
                    "confidence": row.confidence,
                    "semantic": row.semantic,
                    "evidence": list(row.evidence),
                }
                for row in inventory.assets.values()
            ],
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        tmp.replace(path)

    def _read_cache(
        self, path: Path, scene_id: str, assets: list[VisualAsset], sheet_path: Path,
    ) -> VisualSemanticInventory | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if payload.get("version") != 2 or payload.get("scene_id") != scene_id:
            return None
        parsed = self._parse_inventory({"assets": payload.get("assets")}, assets)
        return VisualSemanticInventory(
            scene_id=scene_id,
            assets=parsed,
            contact_sheet_path=sheet_path if sheet_path.is_file() else None,
            source="cache" if parsed else "none",
        )
