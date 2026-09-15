from __future__ import annotations

import json
from pathlib import Path

from app.recovery.models import KnownIssue


class RecoveryRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n", encoding="utf-8")

    def all(self) -> list[KnownIssue]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [KnownIssue.model_validate(item) for item in raw]

    def get(self, code: str) -> KnownIssue | None:
        return next((item for item in self.all() if item.code == code), None)

    def upsert(self, issue: KnownIssue) -> None:
        items = {item.code: item for item in self.all()}
        items[issue.code] = issue
        payload = [item.model_dump(mode="json") for item in sorted(items.values(), key=lambda x: x.code)]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
