"""Authoring audit: non-blocking findings for Builder-owned visual limits (B1-B5)."""
from __future__ import annotations

from pathlib import Path

from app.final_package.authoring_audit import audit_package
from app.models import SceneSource
from tests.support.canonical_package import canonical_package

SCRIPT = "إذا وصل إلى حساب موظف، ثم السيطرة على أجهزة"


def _span(phrase: str) -> dict:
    start = SCRIPT.index(phrase)
    return {"char_start": start, "char_end": start + len(phrase)}


def _asset(asset_id: str, phrase: str, order: int, *, focus: str = "PRIMARY", event: str = "E1") -> dict:
    return {"asset_id": asset_id, "scene_id": "scene-001", "semantic_group_id": "g1", "sequence_order": order,
            "binding_type": "EXPLICIT", "confidence": 1.0, "visual_focus": focus, "semantic_event_id": event,
            "script_text": phrase, "script_span": _span(phrase), "semantic_meaning": "x", "visual_concept": "x"}


def _package():
    scene = SceneSource(id="scene-001", image_path=Path("scene.png"), order=1,
                        script_char_start=0, script_char_end=len(SCRIPT))
    assets = [
        _asset("gateway", "وصل", 1, event="E2"),
        _asset("badge", "حساب موظف", 2),
        _asset("key", "وصل إلى حساب موظف", 3, focus="RESULT"),
        _asset("phone", "أجهزة", 4, event="E3"),
        _asset("camera", "أجهزة", 5, event="E3"),
    ]
    events = [
        {"semantic_event_id": "E1", "script_text": "حساب موظف", "script_span": _span("حساب موظف"), "sequence_order": 1,
         "visual_leader_asset_id": "badge", "result_asset_ids": ["key"]},
        {"semantic_event_id": "E2", "script_text": "وصل", "script_span": _span("وصل"), "sequence_order": 2,
         "visual_leader_asset_id": "gateway", "depends_on_event_ids": ["E1"]},
        {"semantic_event_id": "E3", "script_text": "أجهزة", "script_span": _span("أجهزة"), "sequence_order": 3,
         "visual_leader_asset_id": "camera", "text_anchor_asset_id": "camera"},
    ]
    return canonical_package(
        root=Path("/tmp"), package_id="audit", scenes=[scene], script=SCRIPT, authoritative_semantics=True,
        semantics={"scenes": [{
            "scene_id": scene.id,
            "semantic_groups": [{"semantic_group_id": "g1", "script_text": SCRIPT,
                                 "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                                 "asset_ids": [row["asset_id"] for row in assets]}],
            "semantic_events": events,
            "assets": assets,
        }]},
    )


def test_audit_names_each_builder_owned_limit_with_its_rule() -> None:
    codes = {finding.code: finding for finding in audit_package(_package())}
    assert codes["SEQUENTIAL_GROUP_ON_FINAL_WORD"].asset_ids == ("phone", "camera")
    assert "(event leader)" in codes["SEQUENTIAL_GROUP_ON_FINAL_WORD"].detail
    assert codes["RESULT_BEFORE_LEADER_CONTAINED"].asset_ids == ("key", "badge")
    assert codes["DEPENDENT_EVENT_SPOKEN_FIRST"].event_ids == ("E2", "E1")
    assert codes["TEXT_ANCHOR_LATE_IN_SEQUENCE"].asset_ids == ("camera", "phone")
    assert codes["OPENING_WITHOUT_SAFE_CARRIER"].builder_rule == "B4"   # gateway: dependent; key: RESULT
    assert all(finding.builder_rule in {"B1", "B2", "B3", "B4", "B5"} for finding in codes.values())


def test_audit_is_read_only_and_serializable() -> None:
    package = _package()
    before = package.model_dump()
    payload = [finding.to_payload() for finding in audit_package(package)]
    assert package.model_dump() == before
    assert all(isinstance(row["asset_ids"], list) for row in payload)
