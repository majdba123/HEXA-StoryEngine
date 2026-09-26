from typing import get_type_hints

from app.canonical import CanonicalPackage
from app.choreography import ChoreographyDirector
from app.cutout.pass1 import CutoutService
from app.director import VisualDirector
from app.story import StoryPlanner
from app.text import TextPlanner
from app.vision import VisionService


def test_public_package_consumers_declare_canonical_runtime_contract() -> None:
    consumers = (
        StoryPlanner.plan,
        ChoreographyDirector.plan,
        TextPlanner.plan,
        VisionService.analyze,
        CutoutService.extract,
        VisualDirector.plan,
    )
    for consumer in consumers:
        package_hint = get_type_hints(consumer).get("package")
        assert package_hint in {CanonicalPackage, CanonicalPackage | None}
