from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class ProposalSource(StrEnum):
    cv = "cv"
    semantic = "semantic"
    hybrid = "hybrid"


@dataclass(frozen=True, slots=True)
class CandidateProposal:
    id: str
    bbox: tuple[int, int, int, int]
    center: tuple[float, float]
    area_share: float
    stability: float
    source: ProposalSource
    core_mask: np.ndarray


@dataclass(frozen=True, slots=True)
class DetachedDecision:
    accepted: bool
    gutter_score: float
    touch_score: float
    stability_score: float
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    mask: np.ndarray
    seed_coverage: float
    foreign_core_leak: float
    alpha_share: float
