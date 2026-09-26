from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SemanticDetection:
    label: str
    bbox: tuple[int, int, int, int]
    confidence: float


class SemanticProposalBackend(Protocol):
    def detect(self, image_path: Path) -> list[SemanticDetection]: ...
