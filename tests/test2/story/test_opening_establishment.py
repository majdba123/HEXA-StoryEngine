"""Opening visual establishment: semantic coverage without premature disclosure.

Regression for production diagnostic 570a01cb (VISUAL_WHITE_FLASH, 33 frames 6-38 at
30 fps). Narration began at 0.18 s, but the first exact Unified 2.0 visual phrase was
spoken at 1.30 s. The 1.12 s lead exceeded Story's bounded 0.42 s visual lead, so no
carrier was established. The words before the first authored event ("prelude") were
bound to no authored unit, event or relation. Story may now establish the first safe
reveal cohort when forced-aligned Final Package evidence (OpeningEventEvidence) proves
the carrier's own event may be established from the first spoken instant.
"""
from __future__ import annotations

import itertools
import math

import pytest

from app.final.verification import opening_blank_seconds
from app.models import AssetActivation, StoryBeat
from app.story.windows import OpeningEventEvidence, StoryAssetActivation, schedule_windows

FPS = 30


def _beat(audio_start: float = 0.18, end: float = 3.18) -> StoryBeat:
    return StoryBeat(
        id="beat-001", scene_id="S1", start=0.0, end=end,
        audio_start=audio_start, audio_end=end,
        narration="w1 w2 w3 w4 w5 w6", action="INTRODUCE",
    )


def _row(
    asset_id: str,
    start: float,
    end: float,
    *,
    roles: list[str] | None = None,
    focus: str | None = None,
    event_id: str | None = "E1",
    event_order: int | None = 1,
    sequence_order: int | None = None,
    dependencies: list[str] | None = None,
) -> AssetActivation:
    return AssetActivation(
        asset_id=asset_id, semantic_unit_id=f"unit-{asset_id}",
        spoken_start=start, spoken_end=end,
        policy="EXPLICIT", source="unified_final_package",
        semantic_event_id=event_id, semantic_event_order=event_order,
        semantic_event_roles=list(roles or []), visual_focus=focus,
        sequence_order=sequence_order,
        semantic_event_dependency_ids=list(dependencies or []),
    )


def _diagnostic_rows() -> list[AssetActivation]:
    """Exact Story inputs of diagnostic 570a01cb beat-001 (asset ids anonymized)."""
    return [
        _row("participant", 1.30, 1.56, roles=["PARTICIPANT"], focus="SUPPORT", sequence_order=2),
        _row("leader", 1.80, 3.18, roles=["LEADER", "TEXT_ANCHOR"], focus="PRIMARY", sequence_order=1),
        _row("support", 2.30, 3.18, roles=["PARTICIPANT"], focus="SUPPORT", sequence_order=3),
    ]


def _schedule(
    rows, beat=None, *, events=None, opening=True, authority="SCENE_PRELUDE",
) -> dict[str, StoryAssetActivation]:
    """``events`` maps event id -> forced-aligned establish_from seconds."""
    beat = beat or _beat()
    evidence = None if events is None else {
        key: OpeningEventEvidence(establish_from=value, authority=authority)
        for key, value in events.items()
    }
    return {
        row.asset_id: row
        for row in schedule_windows(
            rows, beat, beat.end, set(), opening=opening,
            opening_event_evidence=evidence,
        )
    }


def _flagged_opening_frames(windows: dict[str, StoryAssetActivation], audio_start: float) -> list[int]:
    """Frames FinalMediaVerifier would scan that precede every Story reveal."""
    first_reveal = min(float(row.reveal_start) for row in windows.values() if row.reveal_start is not None)
    guard = opening_blank_seconds(audio_start)
    return [
        frame for frame in range(int(math.ceil(first_reveal * FPS)) + 1)
        if guard < frame / FPS < first_reveal - 1e-9
    ]


# 11. Exact production regression at 30 fps -------------------------------------------
def test_diagnostic_570a01cb_reproduces_33_white_frames_without_event_authority() -> None:
    windows = _schedule(_diagnostic_rows(), events=None)
    frames = _flagged_opening_frames(windows, 0.18)
    assert frames == list(range(6, 39))
    assert len(frames) == 33
    assert all("opening_spoken_coverage" not in row.evidence for row in windows.values())


def test_diagnostic_570a01cb_opening_event_in_progress_leaves_no_white_frame() -> None:
    windows = _schedule(_diagnostic_rows(), events={"E1": 0.18})
    assert _flagged_opening_frames(windows, 0.18) == []
    carrier = windows["participant"]
    assert carrier.reveal_start == pytest.approx(0.18)
    assert "opening_establish_authority=SCENE_PRELUDE" in carrier.evidence


@pytest.mark.parametrize("authority", ["AUTHORED_EVENT_SPOKEN", "SCENE_PRELUDE"])
def test_both_authored_authorities_establish(authority) -> None:
    windows = _schedule(_diagnostic_rows(), events={"E1": 0.18}, authority=authority)
    assert windows["participant"].reveal_start == pytest.approx(0.18)
    assert f"opening_establish_authority={authority}" in windows["participant"].evidence


@pytest.mark.parametrize("authority", ["", "GUESS", "BOUNDED_STORY_LEAD"])
def test_unknown_evidence_authority_is_not_trusted(authority) -> None:
    windows = _schedule(_diagnostic_rows(), events={"E1": 0.18}, authority=authority)
    assert windows["participant"].reveal_start == pytest.approx(1.30)


# 1/12/13. Narration before first phrase; no early payoff; no new internal gap -------
def test_establishment_moves_only_the_carrier_reveal_and_preserves_semantic_timing() -> None:
    before = _schedule(_diagnostic_rows(), events=None)
    after = _schedule(_diagnostic_rows(), events={"E1": 0.18})
    for asset_id, row in after.items():
        reference = before[asset_id]
        assert row.phrase_start == pytest.approx(reference.phrase_start)
        assert row.phrase_end == pytest.approx(reference.phrase_end)
        assert row.semantic_peak == pytest.approx(reference.semantic_peak)
        assert row.settle_at == pytest.approx(reference.settle_at)
        if asset_id != "participant":
            assert row.reveal_start == pytest.approx(reference.reveal_start)
            assert "opening_spoken_coverage" not in row.evidence
    # The carrier remains the first reveal and settles before the next meaning starts.
    carrier = after["participant"]
    later = [row.reveal_start for key, row in after.items() if key != "participant"]
    assert carrier.reveal_start < min(later)
    assert carrier.settle_at <= min(later) + 1e-9


# 2/3/4/15. Safe carriers and deterministic authority ranking ------------------------
@pytest.mark.parametrize(
    ("roles", "focus"),
    [(["CONTEXT"], "CONTEXT"), (["LEADER"], "PRIMARY"), ([], "PRIMARY"), (["PARTICIPANT"], "SUPPORT")],
)
def test_safe_first_cohort_establishes_with_event_authority(roles, focus) -> None:
    windows = _schedule([_row("carrier", 1.30, 1.70, roles=roles, focus=focus)], events={"E1": 0.18})
    assert windows["carrier"].reveal_start == pytest.approx(0.18)
    assert windows["carrier"].phrase_start == pytest.approx(1.30)


def test_multiple_opening_carriers_select_by_semantic_authority() -> None:
    # One simultaneous reveal cohort (no authored sequence split inside the phrase).
    rows = [
        _row("participant", 1.30, 1.70, roles=["PARTICIPANT"]),
        _row("leader", 1.30, 1.70, roles=["LEADER"], focus="PRIMARY"),
        _row("context", 1.30, 1.70, roles=["CONTEXT"]),
    ]
    windows = _schedule(rows, events={"E1": 0.18})
    established = [key for key, row in windows.items() if "opening_spoken_coverage" in row.evidence]
    assert established == ["context"]

    without_context = _schedule(rows[:2], events={"E1": 0.18})
    established = [key for key, row in without_context.items() if "opening_spoken_coverage" in row.evidence]
    assert established == ["leader"]


# 14. Determinism across input ordering ----------------------------------------------
def test_establishment_is_independent_of_input_order() -> None:
    rows = _diagnostic_rows() + [_row("tie", 1.30, 1.56, roles=["PARTICIPANT"], sequence_order=2)]
    reference = None
    for permutation in itertools.permutations(rows):
        windows = _schedule(list(permutation), events={"E1": 0.18})
        snapshot = sorted(
            (key, row.reveal_start, row.semantic_peak, row.settle_at,
             "opening_spoken_coverage" in row.evidence)
            for key, row in windows.items()
        )
        if reference is None:
            reference = snapshot
        assert snapshot == reference
    assert [row[0] for row in reference if row[4]] == ["participant"]


# 5/6/7/8. Fail-closed vetoes even with event authority ------------------------------
@pytest.mark.parametrize(
    "row",
    [
        _row("result", 1.30, 1.70, roles=["RESULT"]),
        _row("result_focus", 1.30, 1.70, roles=["PARTICIPANT"], focus="RESULT"),
        _row("leader_result", 1.30, 1.70, roles=["LEADER", "RESULT"], focus="PRIMARY"),
        _row("dependent", 1.30, 1.70, roles=["LEADER"], focus="PRIMARY", dependencies=["E0"]),
        _row("second_event", 1.30, 1.70, roles=["LEADER"], focus="PRIMARY", event_order=2),
        _row("unclassified", 1.30, 1.70),
    ],
    ids=lambda row: row.asset_id,
)
def test_unsafe_opening_visual_is_never_revealed_early(row) -> None:
    windows = _schedule([row], events={"E1": 0.18})
    assert windows[row.asset_id].reveal_start == pytest.approx(1.30)
    assert "opening_spoken_coverage" not in windows[row.asset_id].evidence


def test_unsafe_first_cohort_does_not_promote_a_later_safe_visual() -> None:
    rows = [
        _row("result", 1.30, 1.70, roles=["RESULT"]),
        _row("leader", 1.90, 2.40, roles=["LEADER"], focus="PRIMARY"),
    ]
    windows = _schedule(rows, events={"E1": 0.18})
    assert windows["result"].reveal_start == pytest.approx(1.30)
    assert windows["leader"].reveal_start == pytest.approx(1.90)


# 9/10. Long lead without event evidence fails closed deterministically --------------
@pytest.mark.parametrize(
    ("events", "event_id", "event_order"),
    [
        (None, "E1", 1),                 # no aligned event evidence
        ({}, "E1", 1),                   # event span did not resolve
        ({"E1": 0.90}, "E1", 1),         # event begins after narration: future meaning
        ({"E1": 0.18 + 0.05}, "E1", 1),  # beyond alignment tolerance
        ({"E1": 0.18}, None, None),      # no authored event at all
        ({"E1": 0.18}, "E1", None),      # unordered event cannot claim order 1
        ({"OTHER": 0.18}, "E1", 1),      # another event's coverage is not authority
        ({"E1": float("nan")}, "E1", 1),
    ],
)
def test_long_lead_without_event_authority_fails_closed(events, event_id, event_order) -> None:
    row = _row("leader", 1.30, 1.70, roles=["LEADER"], focus="PRIMARY",
               event_id=event_id, event_order=event_order)
    first = _schedule([row], events=events)
    second = _schedule([row], events=events)
    assert first["leader"].reveal_start == pytest.approx(1.30)
    assert first["leader"].model_dump() == second["leader"].model_dump()
    assert _flagged_opening_frames(first, 0.18) == list(range(6, 39))


def test_event_start_within_alignment_tolerance_is_authority() -> None:
    row = _row("leader", 1.30, 1.70, roles=["LEADER"], focus="PRIMARY")
    windows = _schedule([row], events={"E1": 0.18 + 0.02})
    assert windows["leader"].reveal_start == pytest.approx(0.18)


def test_bounded_lead_keeps_existing_authority_without_event_evidence() -> None:
    row = _row("leader", 0.50, 1.00, roles=["LEADER"], focus="PRIMARY")
    windows = _schedule([row], events=None)
    assert windows["leader"].reveal_start == pytest.approx(0.18)
    assert "opening_establish_authority=BOUNDED_STORY_LEAD" in windows["leader"].evidence


def test_nonopening_beat_never_uses_event_authority() -> None:
    windows = _schedule(_diagnostic_rows(), events={"E1": 0.18}, opening=False)
    assert windows["participant"].reveal_start == pytest.approx(1.30)
    assert all("opening_spoken_coverage" not in row.evidence for row in windows.values())


def test_established_window_survives_legacy_serialization() -> None:
    windows = _schedule(_diagnostic_rows(), events={"E1": 0.18})
    restored = StoryAssetActivation.from_legacy(
        AssetActivation.model_validate(windows["participant"].model_dump())
    )
    assert restored.reveal_start == pytest.approx(0.18)
    assert restored.phrase_start == pytest.approx(1.30)


# Planner evidence: SCENE_PRELUDE must be proven from authored spans, never assumed. ---
_LOADED: list = []


def _span(script: str, text: str) -> dict:
    start = script.index(text)
    return {"global_char_start": start, "global_char_end": start + len(text), "text": text}


def _opening_evidence(tmp_path, *, event_text: str, extra_objects=(), relations=(), events=(), progression=()):
    from app.final_package import FinalPackageLoader
    from app.story.activation import SemanticActivationPlanner
    from tests.support.unified_package import write_unified_package
    from tests.test1.factory import deterministic_transcript

    script = "opening words person acts result"
    objects = [
        {"asset_id": "S1_A0", "role": "primary", "script_text": "acts",
         "script_span": _span(script, "acts"), "semantic_event_id": "S1_E1", "sequence_order": 1},
        {"asset_id": "S1_A1", "role": "supporting", "script_text": "person",
         "script_span": _span(script, "person"), "semantic_event_id": "S1_E1", "sequence_order": 2},
        *extra_objects,
    ]
    scene = {
        "scene_id": "S1", "order": 0, "script_span": _span(script, script),
        "objects": objects,
        "semantic_events": [{
            "semantic_event_id": "S1_E1", "script_text": event_text,
            "script_span": _span(script, event_text), "sequence_order": 1,
            "visual_leader_asset_id": "S1_A0", "participant_asset_ids": ["S1_A1"],
        }, *events],
        "relations": list(relations),
        **({"visual_progression": list(progression)} if progression else {}),
    }
    root = write_unified_package(tmp_path / "pkg", script=script, scenes=[scene])
    package = FinalPackageLoader().load(root, tmp_path / "load")
    transcript = deterministic_transcript(package)
    _LOADED.append((package, transcript))
    return SemanticActivationPlanner._opening_event_evidence(
        package=package, transcript=transcript, scene=package.scenes[0],
    ), transcript


def test_event_spoken_from_first_word_is_authored_event_authority(tmp_path) -> None:
    evidence, transcript = _opening_evidence(tmp_path, event_text="opening words person acts result")
    assert evidence["S1_E1"] == OpeningEventEvidence(transcript.words[0].start, "AUTHORED_EVENT_SPOKEN")


def test_unbound_prelude_before_first_event_is_scene_prelude_authority(tmp_path) -> None:
    evidence, transcript = _opening_evidence(tmp_path, event_text="person acts")
    assert evidence["S1_E1"] == OpeningEventEvidence(transcript.words[0].start, "SCENE_PRELUDE")


def test_prelude_with_another_authored_unit_is_not_authority(tmp_path) -> None:
    script = "opening words person acts result"
    evidence, transcript = _opening_evidence(
        tmp_path, event_text="person acts",
        extra_objects=[{"asset_id": "S1_A2", "role": "supporting", "script_text": "words",
                        "script_span": _span(script, "words"), "semantic_event_id": "S1_E2",
                        "sequence_order": 1}],
        events=[{"semantic_event_id": "S1_E2", "script_text": "result",
                 "script_span": _span(script, "result"), "sequence_order": 2,
                 "visual_leader_asset_id": "S1_A2"}],
    )
    # E1 keeps only its own aligned span: the prelude carries other authored meaning.
    assert evidence["S1_E1"].authority == "AUTHORED_EVENT_SPOKEN"
    assert evidence["S1_E1"].establish_from == pytest.approx(transcript.words[2].start)


def test_prelude_with_authored_relation_is_not_authority(tmp_path) -> None:
    script = "opening words person acts result"
    evidence, transcript = _opening_evidence(
        tmp_path, event_text="person acts",
        relations=[{"relation_id": "S1_R1", "subject_asset_id": "S1_A0", "relation_type": "CAUSES",
                    "object_asset_id": "S1_A1", "script_text": "opening",
                    "script_span": _span(script, "opening")}],
    )
    assert evidence["S1_E1"].authority == "AUTHORED_EVENT_SPOKEN"
    assert evidence["S1_E1"].establish_from == pytest.approx(transcript.words[2].start)


def test_visual_progression_trigger_before_event_prevents_scene_prelude(tmp_path) -> None:
    script = "opening words person acts result"
    evidence, transcript = _opening_evidence(
        tmp_path, event_text="person acts",
        progression=[{"action": "EXPLAIN", "event_id": "S1_E1", "order": 1,
                      "targets": ["S1_A0"], "trigger": _span(script, "opening")}],
    )
    assert evidence["S1_E1"].authority == "AUTHORED_EVENT_SPOKEN"
    assert evidence["S1_E1"].establish_from == pytest.approx(transcript.words[2].start)


def test_unresolved_visual_progression_trigger_fails_closed(tmp_path) -> None:
    from app.canonical import CanonicalScriptSpan, CanonicalVisualProgression
    from app.story.activation import SemanticActivationPlanner

    # The loader rejects mismatched spans, so corrupt the loaded canonical scene.
    evidence, _ = _opening_evidence(tmp_path, event_text="person acts")
    assert evidence["S1_E1"].authority == "SCENE_PRELUDE"
    package, transcript = _LOADED[-1]
    scene = package.scenes[0].model_copy(update={"visual_progression": (CanonicalVisualProgression(
        event_id="S1_E1", order=1,
        trigger=CanonicalScriptSpan(text="absent", global_char_start=0, global_char_end=6),
    ),)})
    package = package.model_copy(update={"scenes": (scene,)})
    result = SemanticActivationPlanner._opening_event_evidence(
        package=package, transcript=transcript, scene=scene,
    )
    assert result["S1_E1"].authority == "AUTHORED_EVENT_SPOKEN"
