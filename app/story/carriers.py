from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from app.canonical import CanonicalPackage, CanonicalScene
from app.models import StoryBeat, VisualAsset
from app.shared.errors import StageFailedError

from .carrier_resolver import CarrierConfidence, SceneCarrierResolution
from .identity import VisualIdentityBinder


class SemanticCarrierAuditor:
    """Prove that every required authored event asset keeps a visible carrier.

    Required assets are ``CanonicalScene.semantic_carrier_roles`` (event leaders,
    participants, results, text anchors and progression targets). Each one ends in
    exactly one status:

    ``CARRIED``         a Story activation/proxy carrier is in the scene's visible state.
    ``MERGED_VISIBLE``  no own carrier, but nothing in the scene that could hold its
                        pixels is hidden (identity merged into a visible cutout).
    ``HIDDEN``          a proven carrier exists but the scene lifecycle hides it.
    ``UNRESOLVED``      no carrier is provable and a hidden cutout could hold it.

    ``HIDDEN`` and ``UNRESOLVED`` fail before Composition/FFmpeg: rendering would
    otherwise silently drop authored content. The audit never binds or unhides
    anything itself; it only reports what Story decided.
    """

    _LOCATOR_OVERLAP = 0.10
    # A hidden cutout lying mostly inside a required locator is authored content
    # of that asset being suppressed, even if another cutout already carries it.
    _HIDDEN_INSIDE = 0.60
    # Hidden-content significance, as a fraction of the scene canvas.
    _SIGNIFICANT_AREA = 0.010
    _LOCATED_FRAGMENT_AREA = 0.002
    _DUST_AREA = 0.001

    def __init__(self) -> None:
        self._geometry = VisualIdentityBinder()

    def audit(
        self,
        *,
        package: CanonicalPackage,
        assets: list[VisualAsset],
        beats: list[StoryBeat],
        resolutions: Mapping[str, SceneCarrierResolution] | None = None,
    ) -> list[dict[str, Any]]:
        beats_by_scene: dict[str, list[StoryBeat]] = defaultdict(list)
        for beat in beats:
            beats_by_scene[beat.scene_id].append(beat)
        assets_by_scene: dict[str, list[VisualAsset]] = defaultdict(list)
        for asset in assets:
            assets_by_scene[asset.scene_id].append(asset)

        records: list[dict[str, Any]] = []
        for scene in package.scenes:
            required = scene.semantic_carrier_roles
            scene_beats = beats_by_scene.get(scene.id, [])
            if not required or not scene_beats:
                continue
            rows = self._audit_scene(
                scene=scene,
                required=required,
                beats=scene_beats,
                assets=assets_by_scene.get(scene.id, []),
            )
            resolution = next(
                (
                    (resolutions or {})[beat.id]
                    for beat in scene_beats if beat.id in (resolutions or {})
                ),
                None,
            )
            for row in rows:
                assignment = (
                    resolution.assignments.get(row["semantic_asset_id"])
                    if resolution is not None else None
                )
                if assignment is None:
                    continue
                row["resolution"] = assignment.to_payload()
                # A near-tied ownership the resolver refused to guess is not proof,
                # even when the contested cutouts happen to be on screen.
                if (
                    assignment.confidence is CarrierConfidence.AMBIGUOUS
                    and row["status"] in {"MERGED_VISIBLE", "UNRESOLVED"}
                ):
                    row["status"] = "AMBIGUOUS"
                    row["reason"] = "ambiguous_carrier_ownership"
            records.extend(rows)
        return records

    def require(self, records: list[dict[str, Any]]) -> None:
        hidden = [row for row in records if row["status"] == "HIDDEN"]
        unresolved = [row for row in records if row["status"] == "UNRESOLVED"]
        ambiguous = [row for row in records if row["status"] == "AMBIGUOUS"]
        if not hidden and not unresolved and not ambiguous:
            return
        code = (
            "SEMANTIC_CARRIER_UNRESOLVED" if unresolved
            else "SEMANTIC_CARRIER_AMBIGUOUS" if ambiguous
            else "SEMANTIC_CARRIER_HIDDEN"
        )
        violations = unresolved + ambiguous or hidden
        first = violations[0]
        raise StageFailedError(
            f"{first['scene_id']}: authored {'/'.join(first['roles'])} "
            f"{first['semantic_asset_id']} has no provable visible carrier "
            f"({first['reason']})",
            details={
                "code": code,
                "violation_count": len(violations),
                "violations": violations,
            },
        )

    def audit_hidden_content(
        self,
        *,
        package: CanonicalPackage,
        assets: list[VisualAsset],
        beats: list[StoryBeat],
    ) -> list[dict[str, Any]]:
        """Report hidden cutouts that are authored artwork rather than fragments.

        The Sprint 1 lifecycle legitimately hides cutouts nothing in Story claimed
        (segmentation dust, dotted-line pieces, decorative fragments). A hidden cutout
        is authored content being dropped when it is visually significant, inherits an
        authored ``primary`` role, or lies inside an authored locator. Cutouts inside
        a *required* locator are reported by the carrier audit instead.
        """
        visible_by_scene: dict[str, set[str]] = defaultdict(set)
        mapping: dict[str, dict[str, Any]] = {}
        for beat in beats:
            visible_by_scene[beat.scene_id].update(beat.active_visual_semantic_state or {})
            for row in beat.asset_activations:
                mapping.setdefault(row.asset_id, {
                    "semantic_unit_id": row.semantic_unit_id,
                    "activation_policy": getattr(row, "activation_policy", None),
                    "source": row.source,
                    "evidence": list(row.evidence),
                })
        records: list[dict[str, Any]] = []
        for scene in package.scenes:
            if scene.id not in visible_by_scene:
                continue
            visible = visible_by_scene[scene.id]
            required = scene.semantic_carrier_roles
            locators = {
                unit.asset_id: box
                for unit in scene.assets
                if (box := self._geometry.locator_box(unit.visual_locator)) is not None
            }
            for asset in sorted(assets, key=lambda row: row.id):
                if (
                    asset.scene_id != scene.id
                    or not asset.can_animate_independently
                    or asset.id in visible
                ):
                    continue
                box = self._geometry.asset_box(asset)
                inside = sorted(
                    unit_id for unit_id, locator in locators.items()
                    if box is not None
                    and self._geometry.contained_share(box, locator) >= self._HIDDEN_INSIDE
                )
                if any(unit_id in required for unit_id in inside):
                    continue
                area = float(asset.source_area_ratio or 0.0)
                role = (asset.role or "").casefold()
                reason = None
                if area >= self._SIGNIFICANT_AREA:
                    reason = "visually_significant_hidden_cutout"
                elif role == "primary" and area >= self._DUST_AREA:
                    reason = "hidden_cutout_with_authored_primary_role"
                elif inside and area >= self._LOCATED_FRAGMENT_AREA:
                    reason = "hidden_cutout_inside_authored_locator"
                if reason is None:
                    continue
                records.append({
                    "scene_id": scene.id,
                    "runtime_asset_id": asset.id,
                    "reason": reason,
                    "area_ratio": round(area, 5),
                    "runtime_role": asset.role,
                    "bbox": [round(value, 4) for value in box] if box else None,
                    "inside_authored_locators": inside,
                    "runtime_mapping": mapping.get(asset.id),
                    "visible_scene_asset_ids": sorted(visible),
                    "locator_count": len(locators),
                })
        return records

    @staticmethod
    def require_hidden_content(records: list[dict[str, Any]]) -> None:
        if not records:
            return
        first = records[0]
        raise StageFailedError(
            f"{first['scene_id']}: authored artwork {first['runtime_asset_id']} would be "
            f"hidden ({first['reason']}, area={first['area_ratio']})",
            details={
                "code": "AUTHORED_CONTENT_HIDDEN",
                "violation_count": len(records),
                "violations": records,
            },
        )

    def _audit_scene(
        self,
        *,
        scene: CanonicalScene,
        required: dict[str, tuple[str, ...]],
        beats: list[StoryBeat],
        assets: list[VisualAsset],
    ) -> list[dict[str, Any]]:
        visible: set[str] = set()
        for beat in beats:
            visible.update(beat.active_visual_semantic_state or {})
        carriers: dict[str, set[str]] = defaultdict(set)
        sources: dict[str, set[str]] = defaultdict(set)
        runtime_mapping: dict[str, dict[str, Any]] = {}
        for beat in beats:
            for row in beat.asset_activations:
                runtime_mapping.setdefault(row.asset_id, {
                    "semantic_unit_id": row.semantic_unit_id,
                    "semantic_event_id": row.semantic_event_id,
                    "activation_policy": getattr(row, "activation_policy", None),
                    "source": row.source,
                    "visible": row.asset_id in visible,
                })
                if (
                    row.semantic_unit_id
                    and getattr(row, "activation_policy", None) != "SAFE_ABSTENTION"
                ):
                    carriers[str(row.semantic_unit_id)].add(row.asset_id)
                    sources[str(row.semantic_unit_id)].add("activation")
            for proxy in beat.semantic_event_proxies:
                carriers[proxy.semantic_unit_id].add(proxy.asset_id)
                sources[proxy.semantic_unit_id].add(proxy.authority)

        hidden_assets = sorted(
            (
                asset for asset in assets
                if asset.can_animate_independently and asset.id not in visible
            ),
            key=lambda asset: asset.id,
        )
        units = {unit.asset_id: unit for unit in scene.units}
        assets_by_id = {asset.id: asset for asset in assets}
        events_by_asset: dict[str, list[str]] = defaultdict(list)
        for event in scene.semantic_events:
            for asset_id in (
                event.visual_leader_asset_id,
                *event.participant_asset_ids,
                *event.result_asset_ids,
                event.text_anchor_asset_id,
            ):
                if asset_id and event.semantic_event_id not in events_by_asset[asset_id]:
                    events_by_asset[asset_id].append(event.semantic_event_id)
        window = (
            round(min(beat.start for beat in beats), 4),
            round(max(beat.end for beat in beats), 4),
        )

        records: list[dict[str, Any]] = []
        for semantic_id, roles in sorted(required.items()):
            unit = units.get(semantic_id)
            if unit is None or unit.type.upper() != "VISUAL_ASSET_INTENT":
                continue
            locator = self._geometry.locator_box(unit.visual_locator)
            own = sorted(carriers.get(semantic_id, ()))
            candidates: list[str] = []
            visible_own = [
                asset_id for asset_id in own
                if asset_id in visible
            ]
            explicit = semantic_id in assets_by_id
            hidden_inside = [
                asset.id for asset in hidden_assets
                if locator is not None
                and not explicit
                and (box := self._geometry.asset_box(asset)) is not None
                and self._geometry.contained_share(box, locator) >= self._HIDDEN_INSIDE
            ]
            if explicit:
                # Explicit real-asset identity (runtime id == semantic id) is the
                # strongest proof; the locator is not the geometry authority then.
                if semantic_id in visible or visible_own:
                    status, reason = "CARRIED", "explicit_identity_visible"
                else:
                    status, reason = "UNRESOLVED", "explicit_identity_cutout_hidden"
                    candidates = [semantic_id]
            elif hidden_inside:
                status, reason = "UNRESOLVED", "hidden_cutout_inside_required_locator"
                candidates = hidden_inside
            elif visible_own and locator is not None and not any(
                self._overlaps(locator, assets_by_id[asset_id])
                for asset_id in visible_own
                if asset_id in assets_by_id
            ):
                status, reason = "UNRESOLVED", "carrier_outside_authored_locator"
                candidates = visible_own
            elif (
                visible_own
                and locator is None
                and hidden_assets
                and "activation" not in sources.get(semantic_id, ())
            ):
                # Only borrowed another unit's cutout (group/dependency proxy) while
                # cutouts that may hold its own pixels stay hidden: not provable.
                status, reason = "UNRESOLVED", "proxy_carrier_while_scene_hides_candidates"
                candidates = [asset.id for asset in hidden_assets]
            elif visible_own:
                status, reason = "CARRIED", "visible_story_carrier"
            elif own:
                status, reason = "HIDDEN", "proven_carrier_not_in_scene_visible_state"
                candidates = own
            elif locator is not None and not any(
                self._overlaps(locator, asset) for asset in assets if asset.can_animate_independently
            ):
                # The authored locator points at no runtime cutout at all: the asset
                # is not on screen, merged or otherwise.
                status, reason = "UNRESOLVED", "authored_locator_covers_no_runtime_cutout"
            elif not hidden_assets:
                status, reason = "MERGED_VISIBLE", "no_own_carrier_all_scene_cutouts_visible"
            elif locator is not None:
                candidates = [
                    asset.id for asset in hidden_assets
                    if self._overlaps(locator, asset)
                ]
                status, reason = (
                    ("UNRESOLVED", "locator_overlaps_hidden_cutout")
                    if candidates
                    else ("MERGED_VISIBLE", "locator_outside_hidden_cutouts")
                )
            else:
                status, reason = "UNRESOLVED", "no_locator_and_scene_hides_cutouts"
                candidates = [asset.id for asset in hidden_assets]
            records.append({
                "scene_id": scene.id,
                "semantic_asset_id": semantic_id,
                "roles": list(roles),
                "semantic_event_ids": events_by_asset.get(semantic_id, []),
                "status": status,
                "reason": reason,
                "carrier_asset_ids": own,
                "carrier_sources": sorted(sources.get(semantic_id, ())),
                "candidate_hidden_asset_ids": candidates,
                "hidden_scene_asset_ids": [asset.id for asset in hidden_assets],
                "visible_scene_asset_ids": sorted(visible),
                "runtime_mapping": {
                    asset_id: runtime_mapping.get(asset_id)
                    for asset_id in sorted({*own, *candidates})
                },
                "locator_present": locator is not None,
                "locator": [round(value, 4) for value in locator] if locator else None,
                "segmentation_ambiguity": len(candidates) > 1,
                "scene_window_seconds": list(window),
                "beat_ids": [beat.id for beat in beats],
            })
        return records

    def _overlaps(self, locator: tuple[float, float, float, float], asset: VisualAsset) -> bool:
        box = self._geometry.asset_box(asset)
        return box is not None and (
            self._geometry.overlap_share(locator, box) >= self._LOCATOR_OVERLAP
        )
