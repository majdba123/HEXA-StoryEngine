"""Provision and verify the real Unified Final Package 2.0 certification corpus.

The six certified ZIPs are not committed; ``Bayer_Packages/unified_2_0_certified_corpus.json``
pins their exact bytes. Certification must never run on a missing, partial or
different corpus, so both commands exit non-zero unless every package matches.

    python -m tests.support.real_corpus fetch <base-url> <directory>
    python -m tests.support.real_corpus verify <directory>
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[2] / "Bayer_Packages" / "unified_2_0_certified_corpus.json"


def certified_packages() -> dict[str, str]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {row["filename"]: row["sha256"] for row in payload["packages"]}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(directory: Path) -> list[str]:
    """Return one problem line per missing or mismatched package."""
    problems = []
    for filename, expected in certified_packages().items():
        path = directory / filename
        if not path.is_file():
            problems.append(f"MISSING  {filename}")
        elif (actual := _sha256(path)) != expected:
            problems.append(f"SHA256 MISMATCH  {filename}: expected {expected}, got {actual}")
    return problems


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Release assets redirect to signed storage URLs that reject a Bearer token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


_OPENER = urllib.request.build_opener(_DropAuthOnRedirect)
_GITHUB_RELEASE_API = re.compile(
    r"^https://api\.github\.com/repos/[^/]+/[^/]+/releases/tags/[^/]+$"
)


def _request(url: str, token: str | None, accept: str | None = None) -> urllib.request.Request:
    request = urllib.request.Request(url, headers={"User-Agent": "hexa-real-corpus"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if accept:
        request.add_header("Accept", accept)
    return request


def asset_urls(base_url: str, token: str | None) -> dict[str, tuple[str, str | None]]:
    """Map each manifest filename to ``(download url, Accept header)``.

    A plain base URL serves ``<base>/<filename>``. A GitHub release API URL
    (``.../releases/tags/<tag>``, required for private repositories) resolves each
    asset through the API and downloads it as ``application/octet-stream``.
    """
    base = base_url.rstrip("/")
    if not _GITHUB_RELEASE_API.match(base):
        return {name: (f"{base}/{name}", None) for name in certified_packages()}
    with _OPENER.open(_request(base, token, "application/vnd.github+json"), timeout=60) as response:
        assets = {row["name"]: row["url"] for row in json.load(response)["assets"]}
    return {
        name: (assets[name], "application/octet-stream")
        for name in certified_packages()
        if name in assets
    }


def fetch(base_url: str, directory: Path) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    token = os.getenv("HEXA_REAL_PACKAGE_CORPUS_TOKEN") or None
    try:
        urls = asset_urls(base_url, token)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        return [f"RELEASE LOOKUP FAILED  {exc}"]
    problems = []
    for filename in certified_packages():
        if filename not in urls:
            problems.append(f"MISSING RELEASE ASSET  {filename}")
            continue
        url, accept = urls[filename]
        try:
            with _OPENER.open(_request(url, token, accept), timeout=600) as response:
                with (directory / filename).open("wb") as handle:
                    shutil.copyfileobj(response, handle)
        except (urllib.error.URLError, OSError) as exc:
            problems.append(f"DOWNLOAD FAILED  {filename}: {exc}")
    return problems


def require_executed(junit_xml: Path) -> list[str]:
    """A certification level only counts if tests ran and none skipped or failed."""
    import xml.etree.ElementTree as ElementTree

    root = ElementTree.parse(junit_xml).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(suite.get("tests", 0)) for suite in suites)
    problems = []
    if total == 0:
        problems.append(f"NO TESTS EXECUTED  {junit_xml.name}")
    for key in ("skipped", "failures", "errors"):
        count = sum(int(suite.get(key, 0)) for suite in suites)
        if count:
            problems.append(f"{count} {key.upper()}  {junit_xml.name}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "require-executed":
        problems = require_executed(Path(argv[1]))
        for line in problems:
            print(f"REAL PACKAGE CERTIFICATION BLOCKED: {line}")
        return 1 if problems else 0
    if len(argv) == 3 and argv[0] == "fetch":
        problems = fetch(argv[1], Path(argv[2])) or verify(Path(argv[2]))
    elif len(argv) == 2 and argv[0] == "verify":
        problems = verify(Path(argv[1]))
    else:
        print(__doc__)
        return 2
    for line in problems:
        print(f"REAL PACKAGE CORPUS BLOCKED: {line}")
    if not problems:
        print(f"real package corpus verified: {len(certified_packages())} packages match the manifest")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
