from __future__ import annotations

from dataclasses import dataclass

from app.reference.profile import HexaVisualProfile


@dataclass(frozen=True, slots=True)
class ReferenceAnalysis:
    profile: HexaVisualProfile
    source: str = "hexa_reference_rules"


class ReferenceAnalyzer:
    """Expose the approved reference grammar as a first-class pipeline dependency.

    Video-model extraction can enrich this later, but production hard rules never depend
    on an external model being available at render time.
    """

    def analyze(self) -> ReferenceAnalysis:
        return ReferenceAnalysis(profile=HexaVisualProfile.production())
