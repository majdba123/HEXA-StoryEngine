"""Corpus provisioning is fail-closed: no missing, partial, wrong or skipped corpus."""

from __future__ import annotations

import hashlib
import io
import json
import urllib.request
from pathlib import Path

import pytest

from tests.support import real_corpus

RELEASE = "https://api.github.com/repos/owner/corpus/releases/tags/tag-1"


@pytest.fixture
def two_packages(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    payload = {"A.zip": b"alpha-bytes", "B.zip": b"beta-bytes"}
    monkeypatch.setattr(real_corpus, "certified_packages", lambda: {
        name: hashlib.sha256(data).hexdigest() for name, data in payload.items()
    })
    return payload


def test_verify_accepts_only_the_exact_manifest_bytes(tmp_path: Path, two_packages) -> None:
    assert [line.split()[0] for line in real_corpus.verify(tmp_path)] == ["MISSING", "MISSING"]
    (tmp_path / "A.zip").write_bytes(two_packages["A.zip"])
    (tmp_path / "B.zip").write_bytes(b"tampered")
    problems = real_corpus.verify(tmp_path)
    assert len(problems) == 1 and problems[0].startswith("SHA256 MISMATCH  B.zip")
    (tmp_path / "B.zip").write_bytes(two_packages["B.zip"])
    assert real_corpus.verify(tmp_path) == []
    assert real_corpus.main(["verify", str(tmp_path)]) == 0


def test_plain_base_url_maps_filenames_directly(two_packages) -> None:
    urls = real_corpus.asset_urls("https://host/corpus/", None)
    assert urls == {"A.zip": ("https://host/corpus/A.zip", None),
                    "B.zip": ("https://host/corpus/B.zip", None)}


class _FakeOpener:
    def __init__(self, release_assets: dict[str, str], blobs: dict[str, bytes]) -> None:
        self.release_assets, self.blobs, self.requests = release_assets, blobs, []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if request.full_url == RELEASE:
            body = json.dumps({"assets": [
                {"name": name, "url": url} for name, url in self.release_assets.items()
            ]}).encode()
        else:
            body = self.blobs[request.full_url]
        return io.BytesIO(body)


def test_private_release_assets_download_through_the_api_with_token(
    tmp_path: Path, two_packages, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = {name: f"https://api.github.com/repos/owner/corpus/releases/assets/{i}"
           for i, name in enumerate(two_packages)}
    opener = _FakeOpener(api, {api[name]: data for name, data in two_packages.items()})
    monkeypatch.setattr(real_corpus, "_OPENER", opener)
    monkeypatch.setenv("HEXA_REAL_PACKAGE_CORPUS_TOKEN", "secret-token")

    assert real_corpus.main(["fetch", RELEASE, str(tmp_path)]) == 0
    assert real_corpus.verify(tmp_path) == []
    assert all(req.get_header("Authorization") == "Bearer secret-token" for req in opener.requests)
    downloads = [req for req in opener.requests if req.full_url != RELEASE]
    assert all(req.get_header("Accept") == "application/octet-stream" for req in downloads)


def test_release_missing_an_asset_or_serving_wrong_bytes_fails(
    tmp_path: Path, two_packages, monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://api.github.com/repos/owner/corpus/releases/assets/1"
    monkeypatch.setattr(real_corpus, "_OPENER", _FakeOpener({"A.zip": url}, {url: b"wrong"}))
    assert real_corpus.fetch(RELEASE, tmp_path) == ["MISSING RELEASE ASSET  B.zip"]
    assert real_corpus.main(["fetch", RELEASE, str(tmp_path)]) == 1
    (tmp_path / "B.zip").write_bytes(two_packages["B.zip"])
    assert any(line.startswith("SHA256 MISMATCH  A.zip") for line in real_corpus.verify(tmp_path))


def test_token_is_not_forwarded_to_the_storage_redirect() -> None:
    request = urllib.request.Request(RELEASE, headers={"Authorization": "Bearer secret-token"})
    redirected = real_corpus._DropAuthOnRedirect().redirect_request(
        request, io.BytesIO(), 302, "Found", {}, "https://objects.example/signed?sig=1",
    )
    assert redirected is not None and redirected.get_header("Authorization") is None


@pytest.mark.parametrize(
    "attributes,blocked",
    [('tests="6" skipped="0" failures="0" errors="0"', False),
     ('tests="6" skipped="1" failures="0" errors="0"', True),
     ('tests="0" skipped="0" failures="0" errors="0"', True),
     ('tests="6" skipped="0" failures="2" errors="0"', True)],
    ids=["executed", "skipped", "nothing-ran", "failed"],
)
def test_certification_level_requires_executed_unskipped_tests(
    tmp_path: Path, attributes: str, blocked: bool,
) -> None:
    report = tmp_path / "level.xml"
    report.write_text(f"<testsuites><testsuite {attributes}/></testsuites>", encoding="utf-8")
    assert bool(real_corpus.require_executed(report)) is blocked
    assert real_corpus.main(["require-executed", str(report)]) == int(blocked)
