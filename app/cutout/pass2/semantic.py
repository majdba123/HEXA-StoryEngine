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


class FlorenceSemanticBackend:
    """Lazy Florence-2 object proposals. Missing runtime deps fail closed."""

    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path
        self._detector = None
        self._failed = False

    def detect(self, image_path: Path) -> list[SemanticDetection]:
        if self._failed or not self.model_path.exists():
            return []
        if self._detector is None:
            try:
                from app.vision.florence import FlorenceDetector

                self._detector = FlorenceDetector(self.model_path)
            except Exception:
                self._failed = True
                return []
        try:
            rows = self._detector.detect(image_path)
        except Exception:
            return []
        return [
            SemanticDetection(label=str(label), bbox=bbox, confidence=float(confidence))
            for label, bbox, confidence in rows
        ]
