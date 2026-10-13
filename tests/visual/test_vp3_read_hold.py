"""VP3: every beat motion segment finishes before Rhythm's read hold when it legally can."""
from __future__ import annotations


from app.models import (
    LayoutItem,
    MotionCue,
    MotionSegment,
    StoryBeat,
)
from app.motion.read_hold import reserve_scene_read_hold
from app.motion.timing import motion_comfort, semantic_readability_floor

ITEM = LayoutItem(asset_id="a", x=0.5, y=0.5, width=0.2, height=0.3)
BEAT = StoryBeat(id="b", scene_id="s", start=0.0, end=2.0, narration="x", action="REVEAL")
_STATIC = {"name": "static_reveal_x", "settle_progress": 1.0, "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}


def _accent(phase: str, start: float, end: float, dx: float = 0.03) -> MotionCue:
    program = {"name": "accent", "keyframes": [
        {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
        {"progress": 0.45, "dx": dx, "dy": 0.0, "scale": 1.0},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}
    return MotionCue(beat_id="b", asset_id="a", kind="program_v3", start=0.5, end=0.8,
                     params={"program": _STATIC},
                     segments=[MotionSegment(phase=phase, start=start, end=end, program=program,
                                             handoff_deadline=end)])


# M1: segment read hold ----------------------------------------------------------------------
def test_accent_running_into_the_cut_finishes_before_the_read_hold() -> None:
    cue = _accent("INTERACT", 1.30, 1.95)
    out = reserve_scene_read_hold([cue], beat=BEAT, hold=0.30, items={"a": ITEM})[0]
    segment = out.segments[0]
    assert segment.start == 1.30 and abs(segment.end - 1.70) < 1e-9          # onset kept, end at deadline
    assert segment.handoff_deadline == segment.end
    assert segment.program["keyframes"][-1] == {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}
    peak = max(abs(f["dx"]) for f in segment.program["keyframes"])
    assert peak <= 0.03 + 1e-12                                               # never amplified
    assert peak >= semantic_readability_floor("INTERACT", item_width=0.2, item_height=0.3, duration=0.40)
    assert (out.start, out.end) == (cue.start, cue.end)                       # cue window unchanged
    assert out.params["read_hold"][0]["decision"] == "finished_before_read_hold"


def test_segment_starting_inside_the_hold_is_reported_not_moved() -> None:
    cue = _accent("PAYOFF", 1.80, 1.98)
    out = reserve_scene_read_hold([cue], beat=BEAT, hold=0.30, items={"a": ITEM})[0]
    assert out.segments == cue.segments
    assert out.params["read_hold"][0]["decision"] == "starts_inside_read_hold"


def test_comfort_minimum_is_never_violated() -> None:
    minimum = motion_comfort("REACT").minimum_seconds
    cue = _accent("REACT", 1.55, 1.95)                                         # deadline 1.70 < start + minimum
    out = reserve_scene_read_hold([cue], beat=BEAT, hold=0.30, items={"a": ITEM})[0]
    assert 1.55 + minimum > 1.70
    assert abs(out.segments[0].end - (1.55 + minimum)) < 1e-9                 # as early as comfort allows
    note = out.params["read_hold"][0]
    assert note["decision"] == "shortened_to_comfort_minimum"
    assert note["shortfall_ms"] == round((1.55 + minimum - 1.70) * 1000)
    at_minimum = _accent("REACT", 1.60, 1.60 + minimum)
    same = reserve_scene_read_hold([at_minimum], beat=BEAT, hold=0.30, items={"a": ITEM})[0]
    assert same.segments == at_minimum.segments
    assert same.params["read_hold"][0]["decision"] == "comfort_minimum_reaches_hold"


def test_finished_motion_and_locked_families_are_untouched() -> None:
    done = _accent("INTERACT", 0.9, 1.4)
    locked = _accent("INTERACT", 1.3, 1.95)
    locked.params["render_constraints"] = {"geometry_lock": "authored_footprint"}
    for cue in (done, locked):
        assert reserve_scene_read_hold([cue], beat=BEAT, hold=0.30, items={"a": ITEM})[0] is cue



def test_shortened_segment_stays_inside_the_encoded_qa_speed_limit() -> None:
    from app.render.verification import EncodedMotionVerifier

    for phase in ("INTERACT", "REACT", "PAYOFF", "ESTABLISH"):
        cue = _accent(phase, 1.20, 1.95, dx=0.06)
        segment = reserve_scene_read_hold([cue], beat=BEAT, hold=0.30, items={"a": ITEM})[0].segments[0]
        if segment.end == 1.95:
            continue  # left as authored (floor conflict)
        speed = EncodedMotionVerifier._max_normalized_keyframe_speed(
            segment, duration=segment.end - segment.start, item_width=0.2, item_height=0.3)
        assert speed <= motion_comfort(phase).max_normalized_speed + 1e-9


def test_story_semantic_proxy_window_is_never_retimed() -> None:
    from app.models import SemanticEventProxy

    cue = _accent("ESTABLISH", 1.30, 1.95)
    cue.segments[0] = cue.segments[0].model_copy(update={"semantic_event_id": "E2"})
    proxy = SemanticEventProxy(asset_id="a", semantic_unit_id="u", semantic_event_id="E2",
                               trigger_text="x", trigger_char_start=0, trigger_char_end=1,
                               spoken_start=1.30, spoken_end=1.95,
                               reveal_start=1.30, semantic_peak=1.6, settle_at=1.95)
    beat = BEAT.model_copy(update={"semantic_event_proxies": [proxy]})
    out = reserve_scene_read_hold([cue], beat=beat, hold=0.30, items={"a": ITEM})[0]
    assert out.segments == cue.segments
    assert out.params["read_hold"][0]["decision"] == "story_proxy_window"
