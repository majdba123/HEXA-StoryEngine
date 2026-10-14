"""Scene-opening establishment for every scene (authorized 2026-10-15).

The certified opening rule (bounded 0.42 s lead, SCENE_PRELUDE, AUTHORED_EVENT_SPOKEN)
previously ran only for the video's first beat. Every later scene whose narration starts
before its first authored trigger kept the previous scene's artwork on screen under the
new sentence. The same authorities and fail-closed checks now apply to the first beat of
every scene; a scene's later beats stay phrase locked.
"""
from __future__ import annotations

import pytest

from app.models import AssetActivation, StoryBeat
from app.motion.timing import MotionTimingPolicy, MotionWindow
from app.story.windows import OpeningEventEvidence, StoryAssetActivation, schedule_windows


def _span(script: str, text: str) -> dict:
    start = script.index(text)
    return {"global_char_start": start, "global_char_end": start + len(text), "text": text}


def _story(tmp_path, *, second_event_roles: str = "leader"):
    from app.final_package import FinalPackageLoader
    from app.story import StoryPlanner
    from tests.support.unified_package import write_unified_package
    from tests.test1.factory import controlled_visual_assets, deterministic_transcript

    script = "alpha beta. so then person acts result."
    s1, s2 = "alpha beta.", "so then person acts result."
    second = {
        "scene_id": "S2", "order": 1, "script_span": _span(script, s2),
        "objects": [
            {"asset_id": "S2_A0", "role": "primary", "script_text": "acts",
             "script_span": _span(script, "acts"), "semantic_event_id": "S2_E1", "sequence_order": 2},
            {"asset_id": "S2_A1", "role": "supporting", "script_text": "person",
             "script_span": _span(script, "person"), "semantic_event_id": "S2_E1", "sequence_order": 1},
        ],
        "semantic_events": [{
            "semantic_event_id": "S2_E1", "script_text": "person acts", "script_span": _span(script, "person acts"),
            "sequence_order": 1, "visual_leader_asset_id": "S2_A0",
            **({"participant_asset_ids": ["S2_A1"]} if second_event_roles == "leader"
               else {"result_asset_ids": ["S2_A1", "S2_A0"]}),
        }],
    }
    first = {
        "scene_id": "S1", "order": 0, "script_span": _span(script, s1),
        "objects": [{"asset_id": "S1_A0", "role": "primary", "script_text": "alpha",
                     "script_span": _span(script, "alpha"), "semantic_event_id": "S1_E1", "sequence_order": 1}],
        "semantic_events": [{"semantic_event_id": "S1_E1", "script_text": "alpha", "script_span": _span(script, "alpha"),
                             "sequence_order": 1, "visual_leader_asset_id": "S1_A0"}],
    }
    root = write_unified_package(tmp_path / "pkg", script=script, scenes=[first, second])
    package = FinalPackageLoader().load(root, tmp_path / "load")
    transcript = deterministic_transcript(package)
    story = StoryPlanner().plan(package, transcript, controlled_visual_assets(package))
    words = {w.text.strip(".,"): w for w in transcript.words}
    return story, words


def _windows(beat: StoryBeat) -> dict[str, StoryAssetActivation]:
    return {row.asset_id: StoryAssetActivation.from_legacy(row) for row in beat.asset_activations
            if row.source == "unified_final_package"}


def test_a_later_scene_opening_establishes_its_first_carrier_from_its_first_word(tmp_path) -> None:
    story, words = _story(tmp_path)
    scene_two = next(beat for beat in story if beat.scene_id == "S2")
    windows = _windows(scene_two)
    established = [row for row in windows.values() if "opening_spoken_coverage" in row.evidence]
    assert len(established) == 1
    carrier = established[0]
    assert carrier.reveal_start == pytest.approx(words["so"].start)          # first spoken word of the scene
    assert carrier.phrase_start == pytest.approx(words["person"].start)      # authored phrase anchor kept
    assert carrier.semantic_peak >= carrier.phrase_start
    assert "opening_establish_authority=SCENE_PRELUDE" in carrier.evidence
    other = next(row for row in windows.values() if row is not carrier)
    assert other.reveal_start == pytest.approx(other.phrase_start)           # nothing else pulled forward


def test_a_result_first_scene_opening_still_fails_closed(tmp_path) -> None:
    story, _words = _story(tmp_path, second_event_roles="result")
    scene_two = next(beat for beat in story if beat.scene_id == "S2")
    assert not any("opening_spoken_coverage" in row.evidence for row in _windows(scene_two).values())


def _row(asset_id: str, start: float, end: float, *, unit: str, roles=("PARTICIPANT",)) -> AssetActivation:
    return AssetActivation(asset_id=asset_id, semantic_unit_id=unit, spoken_start=start, spoken_end=end,
                           policy="EXPLICIT", source="unified_final_package", semantic_event_id="E1",
                           semantic_event_order=1, semantic_event_roles=list(roles), visual_focus="SUPPORT")


BEAT = StoryBeat(id="b9", scene_id="S9", start=10.0, end=13.0, audio_start=10.1, audio_end=13.0,
                 narration="w1 w2 w3 w4 w5", action="INTRODUCE")
PRELUDE = {"E1": OpeningEventEvidence(establish_from=10.1, authority="SCENE_PRELUDE")}


def test_a_split_visual_unit_is_established_whole_and_nothing_else() -> None:
    rows = [_row("piece-a", 11.2, 11.6, unit="lock"), _row("piece-b", 11.2, 11.6, unit="lock"),
            _row("zz-other", 11.2, 11.6, unit="key")]                     # sorts after the pieces
    windows = {row.asset_id: row for row in schedule_windows(
        rows, BEAT, BEAT.end, set(), opening=True, opening_event_evidence=PRELUDE)}
    established = {key for key, row in windows.items() if "opening_spoken_coverage" in row.evidence}
    assert established == {"piece-a", "piece-b"}                             # the whole unit, nothing else
    for key in established:
        assert windows[key].reveal_start == pytest.approx(10.1)
        assert windows[key].phrase_start == pytest.approx(11.2)


def test_a_later_reveal_cannot_cut_an_established_carrier_before_its_own_phrase() -> None:
    # The carrier's phrase starts at 11.2; another meaning reveals at 11.2 with a different
    # span. Capping from the early reveal would put settle before the phrase (invalid).
    rows = [_row("carrier", 11.2, 11.6, unit="c"), _row("next", 11.2, 12.4, unit="n", roles=("PARTICIPANT",))]
    windows = {row.asset_id: row for row in schedule_windows(
        rows, BEAT, BEAT.end, set(), opening=True, opening_event_evidence=PRELUDE)}
    for row in windows.values():
        assert row.reveal_start <= row.phrase_start <= row.semantic_peak <= row.settle_at <= row.phrase_end


def test_established_unit_members_build_quickly_and_keep_the_story_peak() -> None:
    window = MotionWindow(start=10.1, end=11.6, semantic_settle=11.6, pace_tier="balanced",
                          semantic_peak=11.4, story_v2=True)
    members = [MotionTimingPolicy._stagger_visual_unit_window(window, index=i, count=3, build_span=0.4)
               for i in range(3)]
    starts = [m.start for m in members]
    assert starts == sorted(starts) and starts[0] == 10.1 and starts[-1] <= 10.1 + 0.4 + 1e-9
    assert all(m.end == 11.6 and m.semantic_peak == 11.4 for m in members)
