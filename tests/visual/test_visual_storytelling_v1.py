"""Sidecar contract and legacy/isolation regression checks."""
import json
import zipfile
from pathlib import Path

import pytest

from app.models import MotionCue, RenderPlan, StoryBeat, StoryEventAuthority
from app.shared.errors import InvalidPackageError
from app.visual_storytelling import enhance_reference_plan, load_sidecar


def package_data():
    return {"package_id": "TEST",
            "scenes": [{
                "scene_id": "SCENE_001",
                "objects": [{"asset_id": "A1"}, {"asset_id": "A2"}],
                "semantic_events": [{
                    "semantic_event_id": "E1", "visual_leader_asset_id": "A1",
                    "result_asset_ids": ["A2"],
                }],
            }]}


def sidecar_data():
    return {"contract": "HEXA_VISUAL_STORYTELLING_SIDECAR",
            "version": "1.0", "package_id": "TEST",
            "scenes": [{"scene_id": "SCENE_001",
                        "directives": [{
                            "directive_id": "VS_001", "semantic_event_id": "E1",
                            "action": "RESULT_FOCUS", "leader_asset_id": "A1",
                            "target_asset_id": "A2", "evidence": "EVENT_RESULT",
                            "priority": "NORMAL",
                        }]}]}


def make_zip(tmp_path: Path, *, manifest=None, sidecar=None):
    path = tmp_path / "package.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("package.json", json.dumps(manifest or package_data()))
        if sidecar is not False:
            archive.writestr("visual_storytelling_v1.json",
                             json.dumps(sidecar if sidecar is not None else sidecar_data()))
    return path


def test_accepts_genuine_result_focus(tmp_path):
    sidecar = load_sidecar(make_zip(tmp_path))
    assert sidecar is not None
    assert len(sidecar.directives) == 1
    assert sidecar.directives[0].target_asset_id == "A2"


def test_legacy_without_sidecar_is_supported(tmp_path):
    assert load_sidecar(make_zip(tmp_path, sidecar=False)) is None


def test_rejects_package_id_mismatch(tmp_path):
    sidecar = sidecar_data()
    sidecar["package_id"] = "OTHER"
    with pytest.raises(InvalidPackageError, match="package_id"):
        load_sidecar(make_zip(tmp_path, sidecar=sidecar))


def test_rejects_wrong_event_result(tmp_path):
    sidecar = sidecar_data()
    sidecar["scenes"][0]["directives"][0]["target_asset_id"] = "A1"
    with pytest.raises(InvalidPackageError):
        load_sidecar(make_zip(tmp_path, sidecar=sidecar))


def test_rejects_unknown_fields(tmp_path):
    sidecar = sidecar_data()
    sidecar["scenes"][0]["directives"][0]["inject_renderer_command"] = "bad"
    with pytest.raises(InvalidPackageError, match="wrong keys"):
        load_sidecar(make_zip(tmp_path, sidecar=sidecar))


def test_rejects_duplicate_directives(tmp_path):
    sidecar = sidecar_data()
    sidecar["scenes"][0]["directives"].append(dict(sidecar["scenes"][0]["directives"][0]))
    with pytest.raises(InvalidPackageError, match="duplicate directive_id"):
        load_sidecar(make_zip(tmp_path, sidecar=sidecar))


def plan(with_wash=True):
    spec = {"event_id": "E1", "style": "reference_wash",
            "focus_asset_ids": ["A2"], "tint_alpha": 0.42} if with_wash else None
    motion = MotionCue(beat_id="B1", asset_id="A2", kind="reveal_in", start=0, end=0.5,
                       params={"focus_wash": spec} if spec else {})
    beat = StoryBeat(id="B1", scene_id="SCENE_001", start=0, end=2,
                     narration="demo", action="BUILD",
                     event_authorities=[StoryEventAuthority(
                         event_id="E1", leader_asset_ids=["A1"], result_asset_ids=["A2"]
                     )])
    return RenderPlan(duration=2, story=[beat], composition=[], motion=[motion], assets=[])


def test_focus_only_changes_preverified_wash_and_not_input(tmp_path):
    source = make_zip(tmp_path)
    original = plan()
    enhanced = enhance_reference_plan(source, original, tmp_path / "run")
    assert original.motion[0].params["focus_wash"]["tint_alpha"] == 0.42
    assert enhanced.motion[0].params["focus_wash"]["tint_alpha"] == 0.46
    report = json.loads((tmp_path / "run/diagnostics/visual-storytelling-v1.json").read_text())
    assert report["applied"] == 1 and report["abstained"] == 0


def test_missing_safe_wash_abstains_without_plan_change(tmp_path):
    source = make_zip(tmp_path)
    original = plan(with_wash=False)
    enhanced = enhance_reference_plan(source, original, tmp_path / "run")
    assert enhanced.model_dump() == original.model_dump()
    report = json.loads((tmp_path / "run/diagnostics/visual-storytelling-v1.json").read_text())
    assert report["applied"] == 0 and report["abstained"] == 1


def test_missing_sidecar_is_byte_equivalent_in_plan(tmp_path):
    source = make_zip(tmp_path, sidecar=False)
    original = plan()
    result = enhance_reference_plan(source, original, tmp_path / "run")
    assert result is original
    assert result.model_dump_json() == original.model_dump_json()
