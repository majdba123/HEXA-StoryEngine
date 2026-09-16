from __future__ import annotations

from dataclasses import dataclass

from app.models import RenderPlan
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class AssetUsageReport:
    assets_total: int
    eligible_assets: int
    story_used: int
    composition_used: int
    motion_used: int
    missing_story: tuple[str, ...]
    missing_composition: tuple[str, ...]
    missing_motion: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not (self.missing_story or self.missing_composition or self.missing_motion)


class AssetUsageValidator:
    """Guarantee that every independently animatable cutout reaches Motion.

    The check is package-agnostic. It operates only on the standard RenderPlan contract,
    so a richer Final Package may produce more assets without requiring scene-specific
    code. A cutout that disappears between Cutout -> Story -> Composition -> Motion is a
    pipeline error, not a valid optimization.
    """

    @staticmethod
    def inspect(plan: RenderPlan) -> AssetUsageReport:
        eligible = {
            asset.id
            for asset in plan.assets
            if asset.can_animate_independently
        }
        story_used = {
            asset_id
            for beat in plan.story
            for asset_id in [*beat.primary_asset_ids, *beat.support_asset_ids]
        }
        composition_used = {
            item.asset_id
            for beat in plan.composition
            for item in beat.items
        }
        motion_used = {cue.asset_id for cue in plan.motion}
        return AssetUsageReport(
            assets_total=len(plan.assets),
            eligible_assets=len(eligible),
            story_used=len(eligible & story_used),
            composition_used=len(eligible & composition_used),
            motion_used=len(eligible & motion_used),
            missing_story=tuple(sorted(eligible - story_used)),
            missing_composition=tuple(sorted(eligible - composition_used)),
            missing_motion=tuple(sorted(eligible - motion_used)),
        )

    @classmethod
    def validate(cls, plan: RenderPlan) -> AssetUsageReport:
        report = cls.inspect(plan)
        if report.complete:
            return report
        raise StageFailedError(
            "separated visual assets were dropped before render",
            details={
                "assets_total": report.assets_total,
                "eligible_assets": report.eligible_assets,
                "story_used": report.story_used,
                "composition_used": report.composition_used,
                "motion_used": report.motion_used,
                "missing_story": list(report.missing_story),
                "missing_composition": list(report.missing_composition),
                "missing_motion": list(report.missing_motion),
            },
        )
