from __future__ import annotations

from pathlib import Path

from app.recovery.builtins import BUILTIN_ISSUES
from app.recovery.handlers import HANDLERS, HandlerResult
from app.recovery.history import RecoveryHistory
from app.recovery.models import RecoveryEvent
from app.recovery.registry import RecoveryRegistry


class RecoveryManager:
    def __init__(self, state_root: Path) -> None:
        self.registry = RecoveryRegistry(state_root / "known-issues.json")
        self.history = RecoveryHistory(state_root / "recovery-history.jsonl")
        self._seed()

    def _seed(self) -> None:
        for issue in BUILTIN_ISSUES:
            if self.registry.get(issue.code) is None:
                self.registry.upsert(issue)

    def handle(self, *, code: str, job_id: str, package_id: str, context: dict, attempt: int) -> HandlerResult | None:
        issue = self.registry.get(code)
        if issue is None or issue.status.value != "proven" or attempt > issue.max_attempts:
            return None
        handler = HANDLERS.get(issue.handler)
        if handler is None:
            return None
        result = handler(context)
        self.history.append(RecoveryEvent(
            issue_code=issue.code,
            job_id=job_id,
            package_id=package_id,
            handler=issue.handler,
            handler_version=issue.handler_version,
            attempt=attempt,
            success=result.success,
            details={"message": result.message, "invalidate_from_stage": result.invalidate_from_stage},
        ))
        return result
