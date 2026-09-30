"""Run one generated case through the real pipeline and compare it with its oracle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.story.carrier_resolver import CarrierConfidence, SceneCarrierResolution
from app.text import TextPlanner
from tests.support.carrier_scene import BuiltPackage, build_package

from .cases import Case

TYPED_FAILURES = frozenset({
    "SEMANTIC_CARRIER_UNRESOLVED", "SEMANTIC_CARRIER_AMBIGUOUS", "SEMANTIC_CARRIER_HIDDEN",
    "AUTHORED_CONTENT_HIDDEN", "FINAL_PACKAGE_SEMANTIC_EVENT_COVERAGE",
    "SEMANTIC_CARRIER_INPUT_INVALID",
})


@dataclass
class Outcome:
    built: BuiltPackage
    planner: StoryPlanner
    story: list | None
    resolution: SceneCarrierResolution | None
    error: StageFailedError | None

    @property
    def code(self) -> str | None:
        return self.error.effective_code if self.error is not None else None


def run_story(case: Case, *, images: Path | None = None) -> Outcome:
    built = build_package(
        [case.spec], namespace="CERT",
        **({"image_root": images, "write_images": True} if images is not None else {}),
    )
    planner = StoryPlanner()
    try:
        story = planner.plan(built.package, built.transcript, built.assets)
    except StageFailedError as exc:
        return Outcome(built, planner, None, None, exc)
    return Outcome(built, planner, story, planner.activation.carrier_resolutions[story[0].id], None)


def mismatches(case: Case, outcome: Outcome) -> list[tuple]:
    """Differences between the resolver's decision and ground truth (empty = correct)."""
    assert outcome.resolution is not None
    scene_id = outcome.built.scene_ids[0]
    real = {asset.id for asset in outcome.built.assets}
    bad: list[tuple] = []
    for unit in case.spec.units:
        row = outcome.resolution.assignments[f"{scene_id}_{unit.name}"]
        got = frozenset(m.cutout_id.split(":", 1)[1] for m in row.members)
        if not {m.cutout_id for m in row.members} <= real:
            bad.append((unit.name, "references a cutout that does not exist"))
        if row.confidence is CarrierConfidence.AMBIGUOUS and row.members:
            bad.append((unit.name, "ambiguous evidence produced an owner"))
        if unit.locator is None and any(m.score is not None for m in row.members):
            bad.append((unit.name, "locator-less intent carries fabricated geometry evidence"))
        if unit.name in case.shared:
            shared = row.shared.cutout_id.split(":", 1)[1] if row.shared else None
            if got or shared != case.shared[unit.name] or not row.reason:
                bad.append((unit.name, "shared", sorted(got), shared))
        elif unit.name in case.unowned:
            if got:
                bad.append((unit.name, "optional intent was forced onto", sorted(got)))
        elif got != case.truth[unit.name]:
            bad.append((unit.name, sorted(got), sorted(case.truth[unit.name]), row.confidence.value))
    return bad


def run_render_plan(case: Case, workspace: Path):
    outcome = run_story(case, images=workspace / "images")
    assert outcome.error is None, (case.label, outcome.code)
    built, story = outcome.built, outcome.story
    choreography = ChoreographyDirector().plan(built.package, story, built.assets)
    composition = CompositionPlanner().plan(story, built.assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, built.assets)
    text = TextPlanner().plan(
        transcript=built.transcript, story=story, assets=built.assets,
        package=built.package, choreography=choreography,
    )
    (workspace / "render").mkdir(parents=True)
    plan, path = RenderPlanner().compile(
        built.transcript, built.assets, story, composition, motion, workspace / "render", text=text,
    )
    return outcome, story, motion, plan, path


def fingerprint(resolution: SceneCarrierResolution) -> str:
    payload = json.dumps(resolution.to_payload(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
