from __future__ import annotations


class HexaError(RuntimeError):
    code = "HEXA_ERROR"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}

    @property
    def effective_code(self) -> str:
        detail_code = self.details.get("code")
        if detail_code is None:
            return self.code
        value = str(detail_code).strip()
        return value or self.code


class InvalidPackageError(HexaError):
    code = "INVALID_PACKAGE"


class DependencyUnavailableError(HexaError):
    code = "DEPENDENCY_UNAVAILABLE"


class StageFailedError(HexaError):
    code = "STAGE_FAILED"


class GenerationCancelledError(HexaError):
    code = "GENERATION_CANCELLED"
