"""Compatibility import for the pre-boundary Final Package loader path.

Production code must import from :mod:`app.final_package`. This module remains only so
existing external callers/tests do not break during the architecture migration.
"""

from app.final_package.loader import FinalPackageLoader

__all__ = ["FinalPackageLoader"]
