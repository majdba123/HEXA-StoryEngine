from __future__ import annotations


class HexaError(RuntimeError):
    code = "HEXA_ERROR"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class InvalidPackageError(HexaError):
    code = "INVALID_PACKAGE"


class DependencyUnavailableError(HexaError):
    code = "DEPENDENCY_UNAVAILABLE"


class StageFailedError(HexaError):
    code = "STAGE_FAILED"
