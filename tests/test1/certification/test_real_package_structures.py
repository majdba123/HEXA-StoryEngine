from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.canonical import CanonicalNormalizer
from app.final_package import FinalPackageLoader

_EXPECTED = {
    "HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip": (40, 129, 55),
    "HEXA_WHITE_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip": (35, 145, 51),
    "HEXA_GRAY_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip": (35, 135, 75),
    "HEXA_SCRIPT_KIDDIE_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip": (35, 80, 80),
}


@pytest.mark.parametrize("filename,expected", _EXPECTED.items())
def test_real_corrected_package_corpus(tmp_path: Path, filename: str, expected: tuple[int, int, int]) -> None:
    corpus = os.getenv("HEXA_REAL_PACKAGE_CORPUS")
    if not corpus:
        if os.getenv("HEXA_REQUIRE_REAL_PACKAGE_CORPUS") == "1":
            pytest.fail("REAL PACKAGE CERTIFICATION BLOCKED: HEXA_REAL_PACKAGE_CORPUS is unset")
        pytest.skip("real Final Package corpus is not installed in this CI environment")
    source = Path(corpus) / filename
    if not source.is_file():
        pytest.fail(f"missing certified Final Package fixture: {source}")
    raw = FinalPackageLoader().load(source, tmp_path / filename.removesuffix(".zip"))
    canonical = CanonicalNormalizer().normalize(raw)
    assert (len(canonical.scenes), len(canonical.asset_by_id), len(canonical.event_by_id)) == expected
