from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.models import Transcript


class ForcedAligner(Protocol):
    def align(self, audio: Path, script: str, duration: float) -> Transcript: ...
