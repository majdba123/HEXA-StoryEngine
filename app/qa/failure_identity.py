from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class _ViolationWithCode(Protocol):
    code: str


def violation_failure_details(
    violations: Iterable[_ViolationWithCode],
    *,
    aggregate_code: str,
) -> dict[str, object]:
    """Return deterministic top-level identity for strict QA failures.

    A single failure class is surfaced unchanged so diagnostics and API callers can
    route it directly. Mixed failure classes keep their individual identities while
    using a stable aggregate code for the failed QA boundary.
    """
    rows = tuple(violations)
    codes = sorted(
        {
            str(row.code).strip()
            for row in rows
            if str(getattr(row, "code", "")).strip()
        }
    )
    normalized_aggregate = str(aggregate_code).strip() or "QA_CONTRACT_VIOLATIONS"
    effective_code = codes[0] if len(codes) == 1 else normalized_aggregate
    return {
        "code": effective_code,
        "violation_codes": codes,
        "violation_count": len(rows),
    }
