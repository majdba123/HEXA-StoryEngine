from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from app.canonical import CanonicalAsset, CanonicalScene
from app.models import VisualAsset
from app.shared.errors import StageFailedError

from .identity import Box, VisualIdentityBinder, VisualIdentityBinding


class CarrierConfidence(StrEnum):
    PROVEN = "PROVEN"                    # explicit identity or a strong, uncontested locator match
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"  # accepted locator / group / elimination evidence
    INFERRED = "INFERRED"                # locator-less size/order hint only (recorded, not proof)
    AMBIGUOUS = "AMBIGUOUS"              # near-tied ownership: never guessed
    UNRESOLVED = "UNRESOLVED"            # no usable evidence


class CarrierKind(StrEnum):
    EXPLICIT = "EXPLICIT"          # runtime cutout id equals the authored asset id
    EXCLUSIVE = "EXCLUSIVE"        # scene-global 1:1 locator assignment
    GROUP = "GROUP"                # one intent -> many cutouts (segmentation split it)
    ELIMINATION = "ELIMINATION"    # the only locator-less intent left for the only cutout left
    ORDER_HINT = "ORDER_HINT"      # locator-less size/order hint nobody else claimed
    SHARED = "SHARED"              # many intents -> one compound cutout (proxy carrier only)
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class CarrierResolverConfig:
    """Decision thresholds that are the resolver's own (geometry ones live in the binder)."""

    proven_score: float = 0.85
    proven_margin: float = 0.25
    diagnostic_candidates: int = 6


@dataclass(frozen=True, slots=True)
class CarrierMember:
    cutout_id: str
    source: str
    score: float | None = None
    runner_up_score: float | None = None
    margin: float | None = None
    locator: Box | None = None


@dataclass(frozen=True, slots=True)
class CarrierAssignment:
    semantic_asset_id: str
    roles: tuple[str, ...]
    required: bool
    locator_present: bool
    kind: CarrierKind
    confidence: CarrierConfidence
    members: tuple[CarrierMember, ...] = ()
    shared: CarrierMember | None = None
    candidates: tuple[tuple[str, float], ...] = ()
    rival: str | None = None
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        def member(row: CarrierMember) -> dict[str, Any]:
            return {
                "cutout_id": row.cutout_id,
                "source": row.source,
                "score": None if row.score is None else round(row.score, 4),
                "runner_up_score": (
                    None if row.runner_up_score is None else round(row.runner_up_score, 4)
                ),
                "margin": None if row.margin is None else round(row.margin, 4),
            }

        return {
            "semantic_asset_id": self.semantic_asset_id,
            "roles": list(self.roles),
            "required": self.required,
            "locator_present": self.locator_present,
            "kind": self.kind.value,
            "confidence": self.confidence.value,
            "selected": [member(row) for row in self.members],
            "shared_carrier": member(self.shared) if self.shared else None,
            "candidates": [
                {"cutout_id": cutout_id, "score": round(score, 4)}
                for cutout_id, score in self.candidates
            ],
            "rejected": [
                cutout_id for cutout_id, _ in self.candidates
                if cutout_id not in {row.cutout_id for row in self.members}
            ],
            "ownership_conflict": self.rival,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SceneCarrierResolution:
    scene_id: str
    assignments: dict[str, CarrierAssignment]
    identity: VisualIdentityBinding
    cutout_ids: tuple[str, ...] = ()
    owners: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def members(self, semantic_asset_id: str) -> tuple[CarrierMember, ...]:
        row = self.assignments.get(semantic_asset_id)
        return row.members if row is not None else ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "runtime_cutouts": list(self.cutout_ids),
            "assignments": [
                self.assignments[key].to_payload() for key in sorted(self.assignments)
            ],
            "cutout_owners": {key: list(self.owners[key]) for key in sorted(self.owners)},
            "unowned_cutouts": [key for key in self.cutout_ids if key not in self.owners],
        }


class SemanticCarrierResolver:
    """Single authority for ``semantic asset -> proven runtime cutout(s)`` in one scene.

    Stages (each only adds evidence the previous stage left open):

    1. candidates + scoring   locator geometry for every intent x eligible cutout
    2. global assignment      explicit ids, then one scene-wide 1:1 locator solution
    3. compound carriers      one intent -> many cutouts (multi-cutout unit, contained
                              members) and many intents -> one cutout (shared region)
    4. locator-less intents   unclaimed order hints, or 1:1 elimination
    5. classification         PROVEN / HIGH_CONFIDENCE / INFERRED / AMBIGUOUS / UNRESOLVED

    It never times, places, moves or hides anything, keeps no state between scenes,
    and returns the same result for the same inputs in any input order.
    """

    def __init__(
        self,
        geometry: VisualIdentityBinder | None = None,
        config: CarrierResolverConfig | None = None,
    ) -> None:
        self.geometry = geometry or VisualIdentityBinder()
        self.config = config or CarrierResolverConfig()

    def resolve(
        self,
        *,
        scene: CanonicalScene,
        assets: list[VisualAsset],
        order_hints: Mapping[str, str] | None = None,
    ) -> SceneCarrierResolution:
        assets = self._validated(scene, assets)
        asset_by_id = {asset.id: asset for asset in assets}
        semantic_assets = sorted(scene.assets, key=lambda row: row.asset_id)
        roles = scene.semantic_carrier_roles
        required_ids = frozenset(roles)
        hints = {
            key: value for key, value in (order_hints or {}).items() if value in asset_by_id
        }

        try:
            identity = self.geometry.bind(scene=scene, semantic_assets=semantic_assets, assets=assets)
        except ValueError as exc:
            raise StageFailedError(
                f"{scene.id}: runtime cutout geometry cannot be scored",
                details={"code": "SEMANTIC_CARRIER_INPUT_INVALID", "scene_id": scene.id,
                         "reason": str(exc)},
            ) from exc

        claimed = {
            match.real_asset_id: semantic_id
            for semantic_id in identity.locator_semantic_ids
            for match in identity.matches_for(semantic_id)
        }
        kept, eliminated = self._locator_less(
            semantic_assets, identity, claimed, hints, asset_by_id, required_ids,
        )
        explicit = {row.asset_id for row in semantic_assets if row.asset_id in asset_by_id}
        locators = {
            row.asset_id: box
            for row in semantic_assets
            if (box := self.geometry.locator_box(row.visual_locator)) is not None
        }
        reserved = {*claimed, *kept.values(), *eliminated.values(), *explicit}

        assignments: dict[str, CarrierAssignment] = {}
        for row in semantic_assets:
            assignments[row.asset_id] = self._assign(
                row=row,
                roles=roles.get(row.asset_id, ()),
                identity=identity,
                locators=locators,
                reserved=reserved,
                kept=kept,
                eliminated=eliminated,
                assets=assets,
                asset_by_id=asset_by_id,
            )

        owners: dict[str, list[str]] = {}
        for semantic_id in sorted(assignments):
            row = assignments[semantic_id]
            for member in (*row.members, *((row.shared,) if row.shared else ())):
                owners.setdefault(member.cutout_id, []).append(semantic_id)
        return SceneCarrierResolution(
            scene_id=scene.id,
            assignments=assignments,
            identity=identity,
            cutout_ids=tuple(sorted(asset_by_id)),
            owners={key: tuple(value) for key, value in owners.items()},
        )

    @staticmethod
    def _validated(scene: CanonicalScene, assets: list[VisualAsset]) -> list[VisualAsset]:
        duplicates = sorted(key for key, count in Counter(a.id for a in assets).items() if count > 1)
        foreign = sorted(a.id for a in assets if a.scene_id != scene.id)
        if duplicates or foreign:
            raise StageFailedError(
                f"{scene.id}: runtime cutouts are not a valid carrier candidate set",
                details={
                    "code": "SEMANTIC_CARRIER_INPUT_INVALID",
                    "scene_id": scene.id,
                    "duplicate_runtime_ids": duplicates,
                    "foreign_scene_runtime_ids": foreign,
                },
            )
        return sorted(assets, key=lambda asset: asset.id)

    @staticmethod
    def eligible(asset: VisualAsset | None, *, required: bool) -> bool:
        """Whether a runtime cutout may carry an authored semantic intent.

        ``decorative`` is a presentation role inherited from package units; it keeps
        optional intents off decorative cutouts but never hides a required carrier.
        """
        if asset is None or not asset.can_animate_independently:
            return False
        role = (asset.role or "").casefold()
        if role == "background":
            return False
        return required or role != "decorative"

    def _locator_less(
        self,
        semantic_assets: list[CanonicalAsset],
        identity: VisualIdentityBinding,
        claimed: dict[str, str],
        hints: Mapping[str, str],
        asset_by_id: dict[str, VisualAsset],
        required_ids: frozenset[str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        """``(kept order hints, eliminated)`` for intents without a usable locator.

        An order hint (legacy size/order evidence) survives only when no locator
        match claimed that cutout. One displaced *required* intent may take the one
        cutout nobody claimed; any other remainder is ambiguous and abstains.
        """
        kept: dict[str, str] = {}
        displaced: list[str] = []
        for row in semantic_assets:
            semantic_id = row.asset_id
            if (
                semantic_id in identity.locator_semantic_ids
                or not str(row.script_text or "").strip()
                or str(row.binding_type or "").upper() == "AMBIGUOUS"
            ):
                continue
            cutout_id = hints.get(semantic_id) or (
                semantic_id if semantic_id in asset_by_id else None
            )
            owner = claimed.get(cutout_id or "")
            if (
                cutout_id is not None
                and (owner is None or owner == semantic_id)
                and self.eligible(asset_by_id.get(cutout_id), required=semantic_id in required_ids)
            ):
                kept[semantic_id] = cutout_id
            elif semantic_id in required_ids:
                displaced.append(semantic_id)
        if len(displaced) != 1:
            return kept, {}
        taken = set(claimed) | set(kept.values())
        remainder = [
            cutout_id
            for cutout_id, asset in sorted(asset_by_id.items())
            if cutout_id not in taken
            and not asset.parent_asset_id
            # A decorative label was copied from another authored (decorative) unit's
            # locator, so that cutout is not an open candidate for this intent; counting
            # it would let one unrelated speck block a provable elimination.
            and self.eligible(asset, required=False)
        ]
        if len(remainder) != 1:
            return kept, {}
        return kept, {displaced[0]: remainder[0]}

    def _assign(
        self,
        *,
        row: CanonicalAsset,
        roles: tuple[str, ...],
        identity: VisualIdentityBinding,
        locators: dict[str, Box],
        reserved: set[str],
        kept: dict[str, str],
        eliminated: dict[str, str],
        assets: list[VisualAsset],
        asset_by_id: dict[str, VisualAsset],
    ) -> CarrierAssignment:
        semantic_id = row.asset_id
        required = bool(roles)
        base = {
            "semantic_asset_id": semantic_id,
            "roles": roles,
            "required": required,
            "locator_present": semantic_id in identity.locator_semantic_ids,
            "candidates": identity.candidates.get(semantic_id, ())[: self.config.diagnostic_candidates],
            "rival": identity.rivals.get(semantic_id),
        }

        def usable(cutout_id: str) -> bool:
            return self.eligible(asset_by_id.get(cutout_id), required=required)

        if semantic_id not in identity.locator_semantic_ids:
            if semantic_id in eliminated:
                return CarrierAssignment(
                    **base, kind=CarrierKind.ELIMINATION,
                    confidence=CarrierConfidence.HIGH_CONFIDENCE,
                    members=(CarrierMember(eliminated[semantic_id], "locatorless_elimination"),),
                    reason="only locator-less required intent left for the only unclaimed cutout",
                )
            if semantic_id in kept:
                explicit = kept[semantic_id] == semantic_id
                return CarrierAssignment(
                    **base,
                    kind=CarrierKind.EXPLICIT if explicit else CarrierKind.ORDER_HINT,
                    confidence=(
                        CarrierConfidence.PROVEN if explicit else CarrierConfidence.INFERRED
                    ),
                    members=(CarrierMember(
                        kept[semantic_id],
                        "explicit_real_asset_id" if explicit else "locatorless_order_hint",
                    ),),
                    reason=(
                        "runtime cutout id equals the authored asset id" if explicit
                        else "no locator: unclaimed size/order hint (not geometric proof)"
                    ),
                )
            return CarrierAssignment(
                **base, kind=CarrierKind.NONE, confidence=CarrierConfidence.UNRESOLVED,
                reason="no locator and no unclaimed cutout evidence",
            )

        matches = identity.matches_for(semantic_id)
        members = [
            CarrierMember(m.real_asset_id, m.source, m.score, m.runner_up_score, m.margin, m.locator)
            for m in matches
        ]
        # An authored unit may be several cutouts (ZERO_OR_ONE_OR_MANY): unreserved
        # cutouts lying wholly inside only this locator are its members too.
        if matches or required:
            seen = {member.cutout_id for member in members}
            members.extend(
                CarrierMember(m.real_asset_id, m.source, m.score, None, None, m.locator)
                for m in self.geometry.contained_carriers(
                    semantic_asset=row, scene_locators=locators, assets=assets,
                    reserved=reserved, standalone=not matches,
                )
                if m.real_asset_id not in seen
            )
        members = [member for member in members if usable(member.cutout_id)]

        shared = None
        if semantic_id in identity.unresolved_locator_ids:
            region = self.geometry.region_carrier(semantic_asset=row, assets=assets)
            if region is not None:
                shared = CarrierMember(
                    region.real_asset_id, region.source, region.score,
                    region.runner_up_score, region.margin, region.locator,
                )

        if members:
            first = members[0]
            if first.source == "explicit_real_asset_id":
                kind, confidence = CarrierKind.EXPLICIT, CarrierConfidence.PROVEN
                reason = "runtime cutout id equals the authored asset id"
            elif first.source == "visual_locator":
                kind = CarrierKind.EXCLUSIVE if len(members) == 1 else CarrierKind.GROUP
                strong = (
                    (first.score or 0.0) >= self.config.proven_score
                    and (first.margin or 0.0) >= self.config.proven_margin
                )
                confidence = CarrierConfidence.PROVEN if strong else CarrierConfidence.HIGH_CONFIDENCE
                reason = "scene-global locator assignment" + (
                    " with contained member cutouts" if len(members) > 1 else ""
                )
            else:
                kind, confidence = CarrierKind.GROUP, CarrierConfidence.HIGH_CONFIDENCE
                reason = "authored locator is covered by several member cutouts"
            return CarrierAssignment(
                **base, kind=kind, confidence=confidence, members=tuple(members),
                shared=shared, reason=reason,
            )
        if shared is not None:
            return CarrierAssignment(
                **base, kind=CarrierKind.SHARED, confidence=CarrierConfidence.HIGH_CONFIDENCE,
                shared=shared,
                reason="locator region is uniquely covered by one compound cutout (proxy carrier)",
            )
        if semantic_id in identity.ambiguous_ids:
            return CarrierAssignment(
                **base, kind=CarrierKind.NONE, confidence=CarrierConfidence.AMBIGUOUS,
                reason="near-tied ownership between candidates; refusing to guess",
            )
        return CarrierAssignment(
            **base, kind=CarrierKind.NONE, confidence=CarrierConfidence.UNRESOLVED,
            reason="authored locator matches no runtime cutout strongly enough",
        )
