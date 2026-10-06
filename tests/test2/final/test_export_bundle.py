"""Export root + versioned bundle writer (Roadmap V2 Sprint 1)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.config import Settings
from app.final.bundle import (
    FAILED_MARKER,
    INCOMPLETE_MARKER,
    ExportBundleWriter,
    ExportRoot,
    export_slug,
)
from app.shared.errors import StageFailedError


def _manifest(bundle) -> dict:
    return {"completed": True, "outputs": {
        "YOUTUBE_16_9": {"filename": bundle.output_path("YOUTUBE").name},
        "REELS_9_16": {"filename": bundle.output_path("REELS").name},
    }}


def _complete(writer: ExportBundleWriter, slug: str, payload: bytes = b"video"):
    bundle = writer.reserve(slug)
    for suffix in ("YOUTUBE", "REELS"):
        bundle.output_path(suffix).write_bytes(payload)
    writer.publish(bundle, _manifest(bundle))
    return bundle


@pytest.mark.parametrize(("raw", "expected"), [
    ("hexa_black_hat_hacker_ar", "HEXA_BLACK_HAT_HACKER_AR"),
    ("Black Hat / Hacker", "BLACK_HAT_HACKER"),
    ("../../etc/passwd", "ETC_PASSWD"),
    ("C:\\Windows\\System32", "C_WINDOWS_SYSTEM32"),
    ("  ..__weird..name__  ", "WEIRD_NAME"),
])
def test_slug_is_sanitized(raw: str, expected: str) -> None:
    assert export_slug(raw) == expected


@pytest.mark.parametrize("raw", ["", "..", "///", "con", "NUL", None])
def test_unsafe_identity_is_rejected(raw) -> None:
    with pytest.raises(StageFailedError) as error:
        export_slug(raw)
    assert error.value.details["code"] == "EXPORT_IDENTITY_INVALID"


def test_v1_then_v2_and_v1_is_never_touched(tmp_path: Path) -> None:
    writer = ExportBundleWriter(tmp_path)
    first = _complete(writer, "BLACK_HAT", b"first")
    before = {p.name: p.read_bytes() for p in first.directory.iterdir()}
    stamps = {p.name: p.stat().st_mtime_ns for p in first.directory.iterdir()}
    second = _complete(writer, "BLACK_HAT", b"second")
    assert (first.version, second.version) == (1, 2)
    assert first.directory == tmp_path / "BLACK_HAT" / "v1"
    assert second.directory == tmp_path / "BLACK_HAT" / "v2"
    assert {p.name: p.read_bytes() for p in first.directory.iterdir()} == before
    assert {p.name: p.stat().st_mtime_ns for p in first.directory.iterdir()} == stamps
    assert sorted(p.name for p in second.directory.iterdir()) == [
        "BLACK_HAT_REELS.mp4", "BLACK_HAT_YOUTUBE.mp4", "export.json",
    ]
    assert ExportBundleWriter.is_complete(first.directory)
    assert ExportBundleWriter.is_complete(second.directory)


def test_existing_versions_are_skipped_not_overwritten(tmp_path: Path) -> None:
    for name in ("v1", "v2", "v7.failed-abc"):
        (tmp_path / "PKG" / name).mkdir(parents=True)
    (tmp_path / "PKG" / "v2" / "keep.txt").write_text("user data")
    bundle = ExportBundleWriter(tmp_path).reserve("PKG")
    assert bundle.version == 8
    assert (tmp_path / "PKG" / "v2" / "keep.txt").read_text() == "user data"


def test_concurrent_reservations_never_collide(tmp_path: Path) -> None:
    writer = ExportBundleWriter(tmp_path)
    barrier = threading.Barrier(12)
    results: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        bundle = writer.reserve("RACE")
        with lock:
            results.append(bundle.version)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == list(range(1, 13))


def test_reserved_bundle_is_invalid_until_published(tmp_path: Path) -> None:
    writer = ExportBundleWriter(tmp_path)
    bundle = writer.reserve("PKG")
    assert (bundle.directory / INCOMPLETE_MARKER).is_file()
    assert not ExportBundleWriter.is_complete(bundle.directory)
    bundle.output_path("YOUTUBE").write_bytes(b"x")
    with pytest.raises(StageFailedError) as error:  # Reels missing -> cannot publish
        writer.publish(bundle, _manifest(bundle))
    assert error.value.details["code"] == "EXPORT_BUNDLE_INCOMPLETE"
    assert not ExportBundleWriter.is_complete(bundle.directory)


def test_failure_marks_bundle_and_consumes_number(tmp_path: Path) -> None:
    writer = ExportBundleWriter(tmp_path)
    bundle = writer.reserve("PKG")
    bundle.output_path("YOUTUBE").write_bytes(b"partial")
    failed = writer.fail(bundle, StageFailedError("reels failed", details={"code": "X"}),
                         diagnostics={"rendered_targets": ["YOUTUBE_16_9"]})
    assert failed.name.startswith("v1.failed-")
    assert not (tmp_path / "PKG" / "v1").exists()
    payload = json.loads((failed / FAILED_MARKER).read_text(encoding="utf-8"))
    assert payload["state"] == "FAILED" and payload["rendered_targets"] == ["YOUTUBE_16_9"]
    assert not ExportBundleWriter.is_complete(failed)
    assert (failed / "PKG_YOUTUBE.mp4").read_bytes() == b"partial"  # diagnostics kept
    assert writer.reserve("PKG").version == 2


def test_unsanitized_or_escaping_slug_is_refused(tmp_path: Path) -> None:
    writer = ExportBundleWriter(tmp_path)
    for slug in ("../escape", "a/b", "lower"):
        with pytest.raises(StageFailedError) as error:
            writer.reserve(slug)
        assert error.value.details["code"] in {"EXPORT_PATH_UNSAFE", "EXPORT_IDENTITY_INVALID"}
    assert list(tmp_path.iterdir()) == []


def test_unavailable_drive_fails_closed(tmp_path: Path) -> None:
    missing_drive = Path("Q:\\" if Path("Q:\\").anchor else "/nonexistent-drive") / "HEXA" / "Exports"
    if Path(missing_drive.anchor).exists():
        pytest.skip("drive unexpectedly exists")
    with pytest.raises(StageFailedError) as error:
        ExportRoot(missing_drive, min_free_bytes=0).validate()
    assert error.value.details["code"] == "EXPORT_ROOT_UNAVAILABLE"


def test_relative_root_and_file_root_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(StageFailedError) as error:
        ExportRoot(Path("relative/exports"), min_free_bytes=0).validate()
    assert error.value.details["code"] == "EXPORT_ROOT_UNAVAILABLE"
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(StageFailedError) as error:
        ExportRoot(blocker / "exports", min_free_bytes=0).validate()
    assert error.value.details["code"] == "EXPORT_ROOT_UNAVAILABLE"


def test_insufficient_space_fails_before_work(tmp_path: Path) -> None:
    with pytest.raises(StageFailedError) as error:
        ExportRoot(tmp_path, min_free_bytes=1 << 62).validate()
    assert error.value.details["code"] == "EXPORT_ROOT_INSUFFICIENT_SPACE"


def test_valid_root_is_created_and_writable(tmp_path: Path) -> None:
    status = ExportRoot(tmp_path / "HEXA" / "Exports", min_free_bytes=0).validate()
    assert status.root.is_dir() and status.free_bytes > 0
    assert list(status.root.iterdir()) == []


def test_settings_resolve_export_root(tmp_path: Path, monkeypatch) -> None:
    settings_file = tmp_path / "hexa.settings.json"
    settings_file.write_text(json.dumps({"export_root": str(tmp_path / "from-file")}), encoding="utf-8")
    monkeypatch.setenv("HEXA_SETTINGS_FILE", str(settings_file))
    monkeypatch.setenv("HEXA_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setenv("HEXA_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.delenv("HEXA_EXPORT_ROOT", raising=False)
    assert Settings.from_env().resolved_export_root == tmp_path / "from-file"
    monkeypatch.setenv("HEXA_EXPORT_ROOT", str(tmp_path / "from-env"))
    assert Settings.from_env().resolved_export_root == tmp_path / "from-env"
    monkeypatch.setenv("HEXA_SETTINGS_FILE", str(tmp_path / "absent.json"))
    monkeypatch.delenv("HEXA_EXPORT_ROOT")
    assert Settings.from_env().resolved_export_root is None
    assert not ((tmp_path / "out").resolve() / "exports").exists()
