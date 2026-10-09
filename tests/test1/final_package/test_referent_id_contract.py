"""Roadmap V2 Sprint 7A - authored cross-scene referent identity (``referent_id``).

``referent_id`` is an optional, additive Final Package 2.0 field. It asserts authored
identity only (WHO/WHAT), never a motion or persistence policy, and nothing infers it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.final_package import FinalPackageLoader
from app.shared.errors import InvalidPackageError
from tests.support.unified_package import write_unified_package

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = "the attacker enters the account then he steals the data and the hackers leave"


def _span(phrase: str) -> dict:
    start = SCRIPT.index(phrase)
    return {"text": phrase, "global_char_start": start, "global_char_end": start + len(phrase)}


def _asset(asset_id: str, phrase: str, **extra) -> dict:
    return {"unit_id": extra.pop("unit_id", asset_id), "asset_id": asset_id, "script_text": phrase,
            "script_span": _span(phrase), "semantic_role": "CHARACTER", **extra}


def _scenes(*rows: list[dict]) -> list[dict]:
    phrases = ["the attacker enters the account", "then he steals the data", "and the hackers leave"]
    return [{"scene_id": f"SCENE_{i + 1:03d}", "order": i, "script_span": _span(phrases[i % 3]),
             "assets": assets} for i, assets in enumerate(rows)]


def _load(tmp_path: Path, scenes: list[dict]):
    source = write_unified_package(tmp_path / "pkg", script=SCRIPT, scenes=scenes)
    return FinalPackageLoader().load(source, tmp_path / "work")


def _referents(package) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for scene in package.scenes:
        for unit in scene.units:
            if unit.referent_id is not None:
                out.setdefault(unit.referent_id, []).append((scene.id, unit.asset_id))
    return out


# 1-4, 13: valid authoring -------------------------------------------------------------
def test_package_without_referent_id_loads_and_means_not_authored(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes([_asset("A01", "the attacker")], [_asset("B01", "he steals")]))
    raw = json.loads((tmp_path / "pkg" / "package.json").read_text(encoding="utf-8"))
    assert all("referent_id" not in obj for scene in raw["scenes"] for obj in scene["objects"])
    assert all(unit.referent_id is None for scene in package.scenes for unit in scene.units)


def test_explicit_null_referent_id_is_valid(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes([_asset("A01", "the attacker", referent_id=None)]))
    assert package.scenes[0].units[0].referent_id is None


def test_same_referent_with_different_asset_ids_across_scenes(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes(
        [_asset("ASSET_031", "the attacker", referent_id="REF_HACKER_01")],
        [_asset("ASSET_047", "he steals", referent_id="REF_HACKER_01")],
    ))
    assert _referents(package) == {"REF_HACKER_01": [("SCENE_001", "ASSET_031"), ("SCENE_002", "ASSET_047")]}


@pytest.mark.parametrize("value", ["REF_HACKER_01", "PERSON:ALICE", "DEVICE_LAPTOP_03", "ORG.COMPANY.A",
                                   "a", "X" * 128, "ref-01"])
def test_valid_referent_id_forms_are_preserved_exactly(tmp_path: Path, value: str) -> None:
    package = _load(tmp_path, _scenes([_asset("A01", "the attacker", referent_id=value)]))
    assert package.scenes[0].units[0].referent_id == value  # never normalized


def test_same_referent_in_non_adjacent_scenes_is_allowed(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes(
        [_asset("A01", "the attacker", referent_id="REF_PERSON_01")],
        [_asset("B01", "he steals")],
        [_asset("C01", "the hackers", referent_id="REF_PERSON_01")],
    ))
    assert [scene for scene, _ in _referents(package)["REF_PERSON_01"]] == ["SCENE_001", "SCENE_003"]


def test_case_is_significant_two_strings_are_two_referents(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes(
        [_asset("A01", "the attacker", referent_id="REF_A")],
        [_asset("B01", "he steals", referent_id="ref_a")],
    ))
    assert set(_referents(package)) == {"REF_A", "ref_a"}


# 5-7, 14-16: nothing else creates identity ------------------------------------------------
def test_same_semantic_name_with_different_referents_stays_different(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes(
        [_asset("A01", "the attacker", semantic_name="hacker", referent_id="REF_WHITE_HAT")],
        [_asset("B01", "he steals", semantic_name="hacker", referent_id="REF_BLACK_HAT")],
    ))
    assert set(_referents(package)) == {"REF_WHITE_HAT", "REF_BLACK_HAT"}


def test_same_source_asset_id_without_referent_gives_no_identity(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes(
        [_asset("A01", "the attacker", source_asset_id="security_researcher")],
        [_asset("B01", "he steals", source_asset_id="security_researcher")],
    ))
    assert _referents(package) == {}
    assert [u.source_asset_id for s in package.scenes for u in s.units] == ["security_researcher"] * 2
    assert all(u.extension_metadata == {"source_asset_id": "security_researcher"}
               for s in package.scenes for u in s.units)


def test_same_unit_id_across_scenes_gives_no_identity(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes(
        [_asset("A01", "the attacker", unit_id="UNIT_001")],
        [_asset("B01", "he steals", unit_id="UNIT_001")],
    ))
    assert _referents(package) == {}


def test_generic_singular_plural_and_compared_entities_keep_their_authored_ids(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes(
        [_asset("A01", "the attacker", referent_id="REF_ATTACKER_01"),
         _asset("A02", "enters the account", referent_id="REF_VICTIM_ACCOUNT")],
        [_asset("B01", "he steals", referent_id="REF_ATTACKER_01")],
        [_asset("C01", "the hackers", referent_id="REF_ATTACKER_GROUP")],
    ))
    refs = _referents(package)
    assert refs["REF_ATTACKER_01"] == [("SCENE_001", "A01"), ("SCENE_002", "B01")]
    assert refs["REF_ATTACKER_GROUP"] == [("SCENE_003", "C01")]  # group != individual


# 8-12: invalid authoring fails closed -------------------------------------------------------
@pytest.mark.parametrize("value", ["", " ", "REF 01", " REF_01", "REF_01 ", "REF\t01", "-REF", ".REF",
                                   "X" * 129, "REF/01", "مرجع_01", "REF#1", "REF\n"])
def test_malformed_referent_id_is_rejected_without_normalization(tmp_path: Path, value: str) -> None:
    with pytest.raises(InvalidPackageError, match="invalid referent_id: SCENE_001:A01"):
        _load(tmp_path, _scenes([_asset("A01", "the attacker", referent_id=value)]))


def test_two_independent_carriers_of_one_referent_in_a_scene_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(InvalidPackageError,
                       match="ambiguous referent carriers in scene: SCENE_001:REF_HACKER_01:A01,A02"):
        _load(tmp_path, _scenes([
            _asset("A01", "the attacker", referent_id="REF_HACKER_01"),
            _asset("A02", "enters the account", referent_id="REF_HACKER_01"),
        ]))


def test_compound_root_with_its_child_may_share_one_referent(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes([
        _asset("A01", "the attacker", referent_id="REF_HACKER_01"),
        _asset("A01_ARM", "enters the account", referent_id="REF_HACKER_01", parent_asset_id="A01"),
    ]))
    assert _referents(package)["REF_HACKER_01"] == [("SCENE_001", "A01"), ("SCENE_001", "A01_ARM")]


def test_siblings_under_an_unshared_parent_are_still_ambiguous(tmp_path: Path) -> None:
    with pytest.raises(InvalidPackageError, match="ambiguous referent carriers"):
        _load(tmp_path, _scenes([
            _asset("A00", "the attacker"),
            _asset("A01", "enters the account", referent_id="REF_X", parent_asset_id="A00"),
            _asset("A02", "the account", referent_id="REF_X", parent_asset_id="A00"),
        ]))


# 18-21: existing field contracts unchanged --------------------------------------------------
def test_continuity_target_stays_scene_local(tmp_path: Path) -> None:
    with pytest.raises(InvalidPackageError, match="continuity target is missing"):
        _load(tmp_path, _scenes(
            [_asset("A01", "the attacker", referent_id="REF_1")],
            [_asset("B01", "he steals", referent_id="REF_1",
                    continuity={"mode": "TRANSFORM_TO", "target_asset_id": "A01"})],
        ))


def test_persist_and_transform_to_validation_unchanged(tmp_path: Path) -> None:
    package = _load(tmp_path, _scenes([
        _asset("A01", "the attacker", continuity={"mode": "PERSIST"}),
        _asset("A02", "enters the account", continuity={"mode": "TRANSFORM_TO", "target_asset_id": "A01"}),
    ]))
    modes = [str(u.continuity.mode) for u in package.scenes[0].units]
    assert modes == ["PERSIST", "TRANSFORM_TO"]
    with pytest.raises(InvalidPackageError, match="TRANSFORM_TO requires target_asset_id"):
        _load(tmp_path / "bad", _scenes([_asset("A01", "the attacker", continuity={"mode": "TRANSFORM_TO"})]))


# Ownership: identity is consumed by exactly one runtime layer -------------------------------
def test_referent_id_consumers_are_exactly_the_contract_owners() -> None:
    hits = subprocess.run(["git", "grep", "-n", "referent_id", "--", "app"], cwd=ROOT,
                          capture_output=True, text=True).stdout.splitlines()
    owners = {line.split(":", 1)[0] for line in hits}
    # semantic.py only lists it as a canonical field that Story must NOT copy (Story stays
    # unchanged). Sprint 7: the cross-scene continuity planner (Motion owner) is the single
    # runtime consumer; Choreography, Composition, Text, Boundary and Render never read it.
    assert owners <= {"app/final_package/models.py", "app/final_package/loader.py",
                      "app/canonical/models.py", "app/story/semantic.py",
                      "app/motion/cross_scene.py"}
    assert not any(owner.startswith(("app/render/", "app/targets/", "app/text/", "app/boundary/",
                                     "app/composition/", "app/choreography/")) for owner in owners)


def test_story_metadata_is_identical_with_and_without_authored_referent_ids(tmp_path: Path) -> None:
    from app.story.semantic import PackageStoryInterpreter

    def story_metadata(root: Path, authored: bool) -> list[dict]:
        extra = {"referent_id": "REF_ATTACKER_01"} if authored else {}
        package = _load(root, _scenes([_asset("A01", "the attacker", **extra)],
                                      [_asset("B01", "he steals", **extra)]))
        assets = [asset for scene in package.scenes for asset in scene.assets]
        assert [asset.referent_id for asset in assets] == (["REF_ATTACKER_01"] * 2 if authored else [None, None])
        return [PackageStoryInterpreter._record_metadata(asset) for asset in assets]

    plain = story_metadata(tmp_path / "plain", False)
    assert plain == story_metadata(tmp_path / "authored", True)
    assert all("referent_id" not in row for row in plain)


def test_audit_tool_reports_authored_evidence_only(tmp_path: Path) -> None:
    write_unified_package(tmp_path / "pkg", script=SCRIPT, scenes=_scenes(
        [_asset("A01", "the attacker", referent_id="REF_P", semantic_name="hacker", source_asset_id="k")],
        [_asset("B01", "he steals", semantic_name="hacker", source_asset_id="k")],
        [_asset("C01", "the hackers", referent_id="REF_P")],
    ))
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "audit_referents.py"), str(tmp_path / "pkg")],
                            capture_output=True, text=True, encoding="utf-8")
    report = json.loads(result.stdout)[0]
    assert result.returncode == 0 and report["valid"]
    assert report["objects_with_referent_id"] == 2
    assert report["adjacent_scene_candidates"] == []  # B01 shares name/source only: no identity
    assert [r["to_scene"] for r in report["non_adjacent_recurrences"]] == ["SCENE_003"]
