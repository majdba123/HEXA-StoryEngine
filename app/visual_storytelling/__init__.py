"""Optional Visual Storytelling 1.0 processing for authored sidecars.

This package never edits input Final Packages, canonical semantics, or legacy
motion. It operates on a defensive copy of the already-compiled reference plan.
"""
from .extension import enhance_reference_plan, load_sidecar

__all__ = ["enhance_reference_plan", "load_sidecar"]
