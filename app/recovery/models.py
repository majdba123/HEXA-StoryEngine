from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RecoveryStatus(StrEnum):
    candidate = "candidate"
    proven = "proven"
    disabled = "disabled"


class KnownIssue(BaseModel):
    code: str
    description: str
    affected_stage: str
    handler: str
    status: RecoveryStatus = RecoveryStatus.candidate
    handler_version: int = 1
    max_attempts: int = Field(default=2, ge=1, le=5)


class RecoveryEvent(BaseModel):
    issue_code: str
    job_id: str
    package_id: str
    handler: str
    handler_version: int
    attempt: int
    success: bool
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
