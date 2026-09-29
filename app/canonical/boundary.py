from __future__ import annotations

from typing import Any

from app.shared.errors import InvalidPackageError

from .models import CanonicalPackage


def ensure_canonical_package(package: Any) -> CanonicalPackage:
    """Require the runtime package boundary to already be canonical.

    Unified Final Package 2.0 is converted exactly once by FinalPackageLoader.
    Downstream layers may not normalize legacy dictionaries or file-shaped data.
    """

    if not isinstance(package, CanonicalPackage):
        raise InvalidPackageError(
            "runtime package must be CanonicalPackage produced by Unified Final Package 2.0 loader"
        )
    return package
