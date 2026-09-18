from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path


CHECKPOINT = Path(__file__).parents[1] / "checkpoints" / "v7_audio_sync"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_v7_runtime_source_is_byte_frozen() -> None:
    manifest = json.loads((CHECKPOINT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["checkpoint"] == "HEXA V7 Audio-Synced Object Storytelling"
    assert manifest["status"] == "USER_APPROVED_STRONG_BASELINE"
    assert manifest["behavior"]["aligned_words"] == 227
    assert manifest["behavior"]["object_layers"] == 96
    assert manifest["behavior"]["story_beats"] == 49
    assert manifest["behavior"]["text_cues"] == 21

    source = manifest["runtime_source_archive"]
    payload = base64.b64decode((CHECKPOINT / source["file"]).read_text(encoding="ascii"))
    assert len(payload) == source["decoded_size_bytes"]
    assert _sha256(payload) == source["decoded_sha256"]

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = {m.name: m for m in archive.getmembers() if m.isfile()}
        assert set(members) == set(source["files"])
        for name, expected_sha256 in source["files"].items():
            extracted = archive.extractfile(members[name])
            assert extracted is not None
            assert _sha256(extracted.read()) == expected_sha256


def test_v7_review_artifact_identity_is_frozen() -> None:
    manifest = json.loads((CHECKPOINT / "manifest.json").read_text(encoding="utf-8"))
    render = manifest["render"]
    assert render["sha256"] == "b1964762ed826b2442cd76085b2f31bd067e8595fe71424600eabd1a5e0329cd"
    assert render["duration_seconds"] == 102.4
    assert render["strict_proven"] is False
    assert manifest["bundle"]["sha256"] == "862bbfaaecd24b1bee4e57afc3e532d1494520789624a82767854193df3ebebd"
