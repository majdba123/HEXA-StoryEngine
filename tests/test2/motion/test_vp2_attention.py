"""Visual Polish VP2-B: one emphasis owner per instant."""
from __future__ import annotations

from app.models import LayoutItem, MotionCue, MotionSegment
from app.motion.attention import SUBORDINATE_GAIN, arbitrate_simultaneous_peaks
from app.motion.timing import semantic_readability_floor


# VP2-B -----------------------------------------------------------------------------------------
def _cue(asset: str, *, start: float, focus: dict, dx: float = 0.04, unit: str | None = None,
         phase: str = "ENTRY", lock: bool = False) -> MotionCue:
    frames = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
              {"progress": 0.6, "dx": dx, "dy": 0.0, "scale": 1.0},
              {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]
    params = {"semantic_focus": {"rhythm": {"accent_gap_ms": 100}, **focus},
              "semantic_continuity": {"semantic_unit_id": unit or asset}}
    if lock:
        params["render_constraints"] = {"geometry_lock": "authored_footprint"}
    return MotionCue(beat_id="b", asset_id=asset, kind="program_v3", start=start, end=start + 0.4,
                     params=params, segments=[MotionSegment(phase=phase, start=start, end=start + 0.4,
                                                            program={"name": "p", "keyframes": frames})])


ITEMS = {a: LayoutItem(asset_id=a, x=0.5, y=0.5, width=0.2, height=0.3) for a in ("lead", "support", "peer")}
RESULT = {"visual_focus": "RESULT", "role": "RESULT"}
SUPPORT = {"visual_focus": "SUPPORT", "role": "ACTION"}


def _peak(cue: MotionCue) -> float:
    return max(abs(f["dx"]) for f in cue.segments[0].program["keyframes"])


def test_subordinate_peak_yields_to_the_result_with_unchanged_timing() -> None:
    cues = [_cue("lead", start=1.0, focus=RESULT), _cue("support", start=1.02, focus=SUPPORT)]
    out = arbitrate_simultaneous_peaks(cues, items=ITEMS)
    assert out[0] == cues[0]
    soft = out[1]
    assert (soft.start, soft.end, soft.segments[0].start, soft.segments[0].end) == (1.02, 1.42, 1.02, 1.42)
    assert abs(_peak(soft) - 0.04 * SUBORDINATE_GAIN) < 1e-9
    assert soft.segments[0].program["keyframes"][-1] == {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}
    assert soft.params["attention_arbitration"][0]["yielded_to"] == "lead"


def test_softening_never_goes_below_the_readability_floor() -> None:
    floor = semantic_readability_floor("ENTRY", item_width=0.2, item_height=0.3, duration=0.4)
    cues = [_cue("lead", start=1.0, focus=RESULT), _cue("support", start=1.0, focus=SUPPORT, dx=floor * 1.1)]
    out = arbitrate_simultaneous_peaks(cues, items=ITEMS)
    assert _peak(out[1]) >= floor


def test_no_authority_or_no_coincidence_means_no_change() -> None:
    equal = [_cue("lead", start=1.0, focus=SUPPORT), _cue("peer", start=1.0, focus=SUPPORT)]
    apart = [_cue("lead", start=1.0, focus=RESULT), _cue("support", start=1.5, focus=SUPPORT)]
    one_unit = [_cue("lead", start=1.0, focus=RESULT, unit="u"), _cue("support", start=1.0, focus=SUPPORT, unit="u")]
    arbitrated = [_cue("lead", start=1.0, focus=RESULT),
                  _cue("support", start=1.0, focus={**SUPPORT, "cohort_role": "participant"})]
    locked = [_cue("lead", start=1.0, focus=RESULT), _cue("support", start=1.0, focus=SUPPORT, lock=True)]
    for cues in (equal, apart, one_unit, arbitrated, locked):
        assert arbitrate_simultaneous_peaks(cues, items=ITEMS) is cues


def test_scale_led_establish_is_floored_in_the_encoded_pixel_measure() -> None:
    from app.motion.timing import projected_motion_activity_px, semantic_readability_floor_px

    wide = {"wide": LayoutItem(asset_id="wide", x=0.5, y=0.5, width=0.4, height=0.2), "lead": ITEMS["lead"]}
    frames = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
              {"progress": 0.45, "dx": 0.0037, "dy": -0.0051, "scale": 0.90},
              {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]
    cue = _cue("wide", start=1.0, focus=SUPPORT, phase="ESTABLISH")
    cue = cue.model_copy(update={"segments": [cue.segments[0].model_copy(
        update={"program": {"name": "p", "keyframes": frames}})]})
    out = arbitrate_simultaneous_peaks([_cue("lead", start=1.0, focus=RESULT), cue], items=wide)
    kept = max(projected_motion_activity_px(dx=f["dx"], dy=f["dy"], scale=f["scale"], item_width=0.4,
                                            item_height=0.2)
               for f in out[1].segments[0].program["keyframes"])
    assert out[1].params["attention_arbitration"]  # it did yield, but only down to the QA floor
    assert kept >= semantic_readability_floor_px("ESTABLISH", item_width=0.4, item_height=0.2, duration=0.4)


def test_unique_result_quiets_different_event_entry_across_payoff_window() -> None:
    def event(cue: MotionCue, event_id: str) -> MotionCue:
        segment = cue.segments[0].model_copy(update={"semantic_event_id": event_id})
        return cue.model_copy(update={"segments": [segment]})

    result = event(_cue("lead", start=1.0, focus=RESULT, phase="PAYOFF"), "result_event")
    entry = event(_cue("support", start=0.82, focus=SUPPORT), "next_event")
    # Motion peaks are 180 ms apart, beyond the 100 ms accent gap, but the
    # different event's ENTRY remains active for 220 ms of the PAYOFF.
    out = arbitrate_simultaneous_peaks([result, entry], items=ITEMS)
    assert out[0] == result
    assert _peak(out[1]) < _peak(entry)
    assert out[1].params["attention_arbitration"][0]["yielded_to"] == "lead"
    assert (out[1].start, out[1].end) == (entry.start, entry.end)

    same_event = event(entry, "result_event")
    assert arbitrate_simultaneous_peaks([result, same_event], items=ITEMS) == [result, same_event]
    peer = event(_cue("peer", start=1.1, focus=RESULT, phase="PAYOFF"), "peer_event")
    assert arbitrate_simultaneous_peaks([result, entry, peer], items=ITEMS) == [result, entry, peer]
