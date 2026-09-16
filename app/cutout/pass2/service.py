from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from app.models import VisualAsset
from app.cutout.pass2.completeness import WholeObjectCompleter
from app.cutout.pass2.extractor import Pass1StyleExtractor
from app.cutout.pass2.proposal import CVProposalEngine
from app.cutout.pass2.safety import PartitionSafetyGate
from app.cutout.pass2.segmenter import MaskBackend
from app.cutout.pass2.semantic import SemanticProposalBackend
from app.cutout.pass2.service_geometry import _GeometryHelpersMixin
from app.cutout.pass2.service_semantic import _SemanticRecoveryMixin
from app.cutout.pass2.validator import DetachedObjectValidator
from app.shared.errors import StageFailedError


class Pass2CutoutService(_SemanticRecoveryMixin, _GeometryHelpersMixin):
    """Detached-object recovery layer built around strict geometry preservation."""

    _MAX_SECONDARIES = 4
    _MAX_ASSETS_PER_SCENE = 6

    def __init__(
        self,
        *,
        semantic_backend: SemanticProposalBackend | None = None,
        mask_backend: MaskBackend | None = None,
    ) -> None:
        self.proposals = CVProposalEngine()
        self.validator = DetachedObjectValidator()
        self.extractor = Pass1StyleExtractor()
        self.completer = WholeObjectCompleter()
        self.safety = PartitionSafetyGate()
        self.semantic_backend = semantic_backend
        self.mask_backend = mask_backend

    def refine(
        self,
        assets: list[VisualAsset],
        workspace: Path,
        scene_unit_types: dict[str, list[str]] | None = None,
    ) -> list[VisualAsset]:
        output_dir = workspace / "cutout" / "pass2"
        output_dir.mkdir(parents=True, exist_ok=True)

        by_scene: dict[str, list[VisualAsset]] = {}
        order: list[str] = []
        for asset in assets:
            if asset.scene_id not in by_scene:
                by_scene[asset.scene_id] = []
                order.append(asset.scene_id)
            by_scene[asset.scene_id].append(asset)

        output: list[VisualAsset] = []
        for scene_id in order:
            rows = by_scene[scene_id]
            unit_types = (scene_unit_types or {}).get(scene_id, [])
            # Scene-plan units are semantic hints, not a hard object-count ceiling.
            # Pass 2's job is geometric recovery: if a truly detached object exists,
            # it should be available to Story/Motion even when authoring grouped the
            # scene into one semantic unit. Keep the global Story limit of six assets.
            scene_budget = max(0, self._MAX_ASSETS_PER_SCENE - len(rows))
            if scene_budget <= 0:
                output.extend(rows)
                continue
            target_types = unit_types

            ranked = sorted(
                enumerate(rows),
                key=lambda row: (
                    1 if row[1].compound else 0,
                    row[1].source_area_ratio or 0.0,
                ),
                reverse=True,
            )
            replacements: dict[int, list[VisualAsset]] = {}
            remaining = scene_budget
            for index, asset in ranked:
                if remaining <= 0:
                    break
                derived = self._refine_asset(
                    asset,
                    output_dir,
                    max_secondaries=remaining,
                    target_types=target_types,
                )
                if derived is None:
                    continue
                additions = len(derived) - 1
                if additions <= 0:
                    continue
                replacements[index] = derived
                remaining -= additions
            for index, asset in enumerate(rows):
                output.extend(replacements.get(index, [asset]))
        return output

    def _refine_asset(
        self,
        asset: VisualAsset,
        output_dir: Path,
        *,
        max_secondaries: int = 1,
        target_types: list[str] | None = None,
    ) -> list[VisualAsset] | None:
        if not asset.image_path.is_file():
            raise StageFailedError(
                "cutout pass2 input asset is missing",
                details={"asset_id": asset.id, "path": str(asset.image_path)},
            )
        with Image.open(asset.image_path) as opened:
            rgba = np.asarray(opened.convert("RGBA"))
        proposals = self.proposals.propose(rgba)
        if not proposals:
            return None

        dominant = max(proposals, key=lambda row: row.area_share)
        candidates = [row for row in proposals if row.id != dominant.id]
        candidates.sort(
            key=lambda row: self._candidate_priority(row, rgba.shape[:2], target_types or []),
            reverse=True,
        )
        accepted_masks: list[np.ndarray] = []
        for candidate in candidates:
            decision = self.validator.validate(rgba, candidate, dominant)
            protected = dominant.core_mask.copy()
            for other in proposals:
                if other.id not in {candidate.id, dominant.id}:
                    protected |= other.core_mask
            # Proposal profiles can overlap at object boundaries. Pixels that are part
            # of the candidate's own stable core must not be counted as foreign leak.
            protected &= ~candidate.core_mask

            extracted = None
            if decision.accepted:
                roi_bounds = self._safe_roi(candidate, proposals, rgba.shape[1], rgba.shape[0])
                extracted = self.extractor.extract(
                    rgba,
                    candidate,
                    protected,
                    roi_bounds=roi_bounds,
                )
                # If Pass-1-style expansion is bridged by weak pixels, fall back to
                # candidate-only hard structure. This never repartitions by nearest
                # pixel and still returns the exact parent canvas.
                if extracted is None and self._allow_hard_core_fallback(
                    rgba,
                    candidate,
                    dominant,
                    hard_contact=False,
                ):
                    extracted = self.extractor.extract_hard_core(rgba, candidate, protected)
            elif decision.reason == "hard contact" and self._allow_hard_core_fallback(
                rgba,
                candidate,
                dominant,
                hard_contact=True,
            ):
                # A thin connector/shadow may merge a large external figure into the
                # dominant hard component. Only whole-object-shaped external candidates
                # may use this path; attached sub-parts remain rejected.
                extracted = self.extractor.extract_hard_core(rgba, candidate, protected)
            elif (
                decision.reason == "insufficient real gap"
                and decision.touch_score <= 0.02
                and self._allow_hard_core_fallback(
                    rgba,
                    candidate,
                    dominant,
                    hard_contact=False,
                )
            ):
                # A real exterior object can sit extremely close to the parent cluster.
                # Recover it from its own hard core rather than lowering the global gap
                # threshold and risking widespread over-segmentation.
                extracted = self.extractor.extract_hard_core(rgba, candidate, protected)

            if extracted is None:
                continue

            # Pass2 proposals are based on strong structural ink. Complete the mask
            # against the original alpha canvas before it becomes independently
            # animatable, otherwise weak but visually-bound parts (rays, clock hands,
            # glows, antialiased shadows) can remain on the parent as a pre-entry ghost.
            completion_protected = protected.copy()
            for accepted in accepted_masks:
                completion_protected |= accepted
            completed = self.completer.complete(
                rgba,
                extracted.mask,
                protected=completion_protected,
            )
            if completed is None:
                # Whole-object-or-reject: a partial/ambiguous split is worse than a
                # compound asset because Motion would expose the segmentation defect.
                continue
            if any(np.any(mask & completed.mask) for mask in accepted_masks):
                continue
            accepted_masks.append(completed.mask)
            if len(accepted_masks) >= min(self._MAX_SECONDARIES, max_secondaries):
                break

        remaining_slots = min(self._MAX_SECONDARIES, max_secondaries) - len(accepted_masks)
        if remaining_slots > 0 and self.semantic_backend is not None and self.mask_backend is not None:
            semantic_masks = self._semantic_recovery(
                asset=asset,
                rgba=rgba,
                dominant=dominant,
                target_types=target_types or [],
                limit=remaining_slots,
                existing=accepted_masks,
            )
            for semantic_mask in semantic_masks:
                semantic_protected = dominant.core_mask.copy()
                for accepted in accepted_masks:
                    semantic_protected |= accepted
                completed = self.completer.complete(
                    rgba,
                    semantic_mask,
                    protected=semantic_protected,
                )
                if completed is None:
                    continue
                if any(np.any(mask & completed.mask) for mask in accepted_masks):
                    continue
                accepted_masks.append(completed.mask)

        if not self.safety.validate(rgba[:, :, 3], accepted_masks):
            return None
        return self._emit(asset, rgba, accepted_masks, output_dir)
