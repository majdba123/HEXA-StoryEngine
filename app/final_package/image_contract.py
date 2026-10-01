from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.shared.errors import InvalidPackageError

from .models import UnifiedFinalPackagePayload


_GEOMETRY_TOLERANCE = 1e-9


class ImageContractRepair:
    """Normalize scene images in a materialized package before strict validation."""

    def repair(
        self,
        package: UnifiedFinalPackagePayload,
        root: Path,
        diagnostics_path: Path,
    ) -> None:
        expected = (package.image_spec.width, package.image_spec.height)
        rows: list[dict[str, object]] = []
        payload_changed = False

        for scene in package.scenes:
            image = self._safe_scene_image(root, scene.image, scene.scene_id)
            if not image.is_file():
                raise InvalidPackageError(f"missing scene image: {scene.scene_id}:{scene.image}")
            try:
                with Image.open(image) as source:
                    source.load()
                    actual = source.size
                    if actual[0] <= 0 or actual[1] <= 0:
                        self._reject(scene.scene_id, scene.image, actual, expected, "image dimensions are not positive")

                    if actual == expected:
                        rows.append(self._diagnostic(scene.scene_id, scene.image, actual, expected, "UNCHANGED"))
                        continue

                    same_aspect = actual[0] * expected[1] == actual[1] * expected[0]
                    if same_aspect:
                        scale = expected[0] / actual[0]
                        repaired = self._rgb_on_white(source).resize(expected, Image.Resampling.LANCZOS)
                        padding = (0, 0)
                        repair_type = "RESIZED_SAME_ASPECT"
                        transformed = False
                    else:
                        scale = min(expected[0] / actual[0], expected[1] / actual[1])
                        resized = (
                            max(1, min(expected[0], round(actual[0] * scale))),
                            max(1, min(expected[1], round(actual[1] * scale))),
                        )
                        padding = ((expected[0] - resized[0]) // 2, (expected[1] - resized[1]) // 2)
                        fitted = self._rgb_on_white(source).resize(resized, Image.Resampling.LANCZOS)
                        repaired = Image.new("RGB", expected, "white")
                        repaired.paste(fitted, padding)
                        transformed = self._remap_locators(scene.objects, actual, expected, scale, padding)
                        payload_changed = transformed or payload_changed
                        repair_type = "FIT_PAD_AND_REMAP_LOCATORS"

                    self._save(repaired, image, package.image_spec.format)
                    rows.append(
                        self._diagnostic(
                            scene.scene_id,
                            scene.image,
                            actual,
                            expected,
                            repair_type,
                            scale=scale,
                            padding=padding,
                            transformed=transformed,
                        )
                    )
            except InvalidPackageError:
                raise
            except (OSError, ValueError, UnidentifiedImageError) as exc:
                self._reject(scene.scene_id, scene.image, None, expected, f"image is unreadable or corrupt: {exc}")

        if payload_changed:
            package_path = root / "package.json"
            package_path.write_text(
                json.dumps(package.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_path.write_text(
            json.dumps({"expected_width": expected[0], "expected_height": expected[1], "scenes": rows}, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _safe_scene_image(root: Path, value: str, scene_id: str) -> Path:
        root = root.resolve()
        candidate = (root / value).resolve()
        if root not in candidate.parents:
            raise InvalidPackageError(f"path escapes Final Package: scene image {scene_id}")
        return candidate

    def _remap_locators(
        self,
        objects: list,
        actual: tuple[int, int],
        expected: tuple[int, int],
        scale: float,
        padding: tuple[int, int],
    ) -> bool:
        transformed = False
        for obj in objects:
            locator = obj.visual_locator
            values = (locator.cx, locator.cy, locator.width, locator.height)
            if all(value is None for value in values):
                continue
            if locator.coordinate_space != "normalized_scene" or any(value is None for value in values):
                self._reject_locator(obj.scene_id, obj.asset_id, "visual_locator is incomplete or unsupported")
            cx, cy, width, height = (float(value) for value in values)
            self._verify_locator((cx, cy, width, height), obj.scene_id, obj.asset_id)
            mapped = (
                (cx * actual[0] * scale + padding[0]) / expected[0],
                (cy * actual[1] * scale + padding[1]) / expected[1],
                width * actual[0] * scale / expected[0],
                height * actual[1] * scale / expected[1],
            )
            mapped = tuple(self._noise_clamp(value) for value in mapped)
            self._verify_locator(mapped, obj.scene_id, obj.asset_id)
            locator.cx, locator.cy, locator.width, locator.height = mapped
            transformed = True
        return transformed

    @staticmethod
    def _noise_clamp(value: float) -> float:
        if -_GEOMETRY_TOLERANCE <= value < 0.0:
            return 0.0
        if 1.0 < value <= 1.0 + _GEOMETRY_TOLERANCE:
            return 1.0
        return value

    def _verify_locator(self, values: tuple[float, float, float, float], scene_id: str, asset_id: str) -> None:
        cx, cy, width, height = values
        if not all(math.isfinite(value) for value in values):
            self._reject_locator(scene_id, asset_id, "visual_locator transformation is non-finite")
        if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < width <= 1 and 0 < height <= 1):
            self._reject_locator(scene_id, asset_id, "visual_locator transformation is outside normalized bounds")
        if (
            cx - width / 2 < -_GEOMETRY_TOLERANCE
            or cx + width / 2 > 1 + _GEOMETRY_TOLERANCE
            or cy - height / 2 < -_GEOMETRY_TOLERANCE
            or cy + height / 2 > 1 + _GEOMETRY_TOLERANCE
        ):
            self._reject_locator(scene_id, asset_id, "visual_locator rectangle leaves the target image")

    @staticmethod
    def _rgb_on_white(source: Image.Image) -> Image.Image:
        rgba = source.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        return Image.alpha_composite(background, rgba).convert("RGB")

    @staticmethod
    def _save(image: Image.Image, path: Path, image_format: str) -> None:
        format_name = "JPEG" if image_format.casefold() in {"jpg", "jpeg"} else image_format.upper()
        options = {"quality": 95, "subsampling": 0} if format_name == "JPEG" else {}
        image.save(path, format=format_name, **options)

    @staticmethod
    def _diagnostic(
        scene_id: str,
        filename: str,
        actual: tuple[int, int],
        expected: tuple[int, int],
        repair_type: str,
        *,
        scale: float = 1.0,
        padding: tuple[int, int] = (0, 0),
        transformed: bool = False,
    ) -> dict[str, object]:
        return {
            "scene_id": scene_id,
            "image_filename": filename,
            "original_width": actual[0],
            "original_height": actual[1],
            "expected_width": expected[0],
            "expected_height": expected[1],
            "repair_type": repair_type,
            "scale_factor": scale,
            "padding_x": padding[0],
            "padding_y": padding[1],
            "locators_transformed": transformed,
        }

    @staticmethod
    def _reject(
        scene_id: str,
        filename: str,
        actual: tuple[int, int] | None,
        expected: tuple[int, int],
        reason: str,
    ) -> None:
        raise InvalidPackageError(
            f"unsafe scene image cannot be normalized: {scene_id}:{filename}: {reason}",
            details={
                "code": "IMAGE_CONTRACT_REPAIR_FAILED",
                "scene_id": scene_id,
                "image_filename": filename,
                "actual_dimensions": actual,
                "expected_dimensions": expected,
                "repair_type": "REJECTED_UNSAFE_IMAGE",
            },
        )

    @staticmethod
    def _reject_locator(scene_id: str, asset_id: str, reason: str) -> None:
        raise InvalidPackageError(
            f"unsafe visual_locator cannot be normalized: {scene_id}:{asset_id}: {reason}",
            details={"code": "IMAGE_CONTRACT_REPAIR_FAILED", "scene_id": scene_id, "asset_id": asset_id},
        )
