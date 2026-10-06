"""Reference-led Motion decisions for non-reference output formats (Roadmap V2 Sprint 1)."""
from __future__ import annotations

from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment
from app.motion.emphasis import (
    SUPPORT_DIP_MAX_DELTA,
    _PEAK_PROGRESS,
    _SAFETY,
    apply_character_emphasis,
    comfort_bounded_delta,
    reference_dip_delta,
)
from app.motion.semantic_reference import MotionSemanticReference
from app.motion.timing import motion_comfort

STATIC = {"name": "static", "settle_progress": 1.0, "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
]}


def _item(asset_id: str, x: float, y: float, w: float, h: float) -> LayoutItem:
    return LayoutItem(asset_id=asset_id, x=x, y=y, width=w, height=h)


def _cue(asset_id: str, start: float = 1.0, end: float = 1.2, **params) -> MotionCue:
    return MotionCue(beat_id="b1", asset_id=asset_id, kind="program_v3", start=start, end=end,
                     params={"program": STATIC, **params},
                     segments=[MotionSegment(phase="ENTRY", start=start, end=end, program=STATIC)])


def _speed(delta: float, item: LayoutItem, duration: float) -> float:
    leg = min(_PEAK_PROGRESS, 1.0 - _PEAK_PROGRESS) * duration
    return delta * min(item.width, item.height) / leg


def test_reference_reproduces_order_items_on_reference_geometry() -> None:
    ref_items = [_item("a", 0.2, 0.5, 0.2, 0.4), _item("b", 0.7, 0.5, 0.2, 0.4)]
    reference = MotionSemanticReference.of([CompositionBeat(beat_id="b1", items=ref_items)], [])
    target = [_item("b", 0.5, 0.7, 0.4, 0.2), _item("a", 0.5, 0.3, 0.4, 0.2)]
    assert reference.order_items("b1", target) == [ref_items[1], ref_items[0]]
    assert reference.order_items("b1", target[:1]) is None  # different item set: no override
    assert reference.order_items("missing", target) is None


def test_reference_abstention_is_reproduced_exactly() -> None:
    item = _item("a", 0.5, 0.5, 0.2, 0.2)
    audit = {"applied": False, "reason": "no_safe_headroom", "window": [1.2, 1.7]}
    cue = apply_character_emphasis(_cue("a"), item=item, layout_items=[item], bound=3.0,
                                   semantic_event_id="e1", reference=audit)
    assert cue.params["character_emphasis"]["applied"] is False
    assert cue.params["character_emphasis"]["window"] == [1.2, 1.7]
    assert not any(s.semantic_action == "EMPHASIZE" for s in cue.segments)


def test_reference_application_is_reproduced_even_without_headroom() -> None:
    item = _item("a", 0.5, 0.5, 0.9, 0.9)  # no safe headroom on this geometry
    without = apply_character_emphasis(_cue("a"), item=item, layout_items=[item], bound=3.0,
                                       semantic_event_id="e1")
    assert without.params["character_emphasis"]["applied"] is False
    forced = apply_character_emphasis(_cue("a"), item=item, layout_items=[item], bound=3.0,
                                      semantic_event_id="e1", reference={"applied": True})
    segment = next(s for s in forced.segments if s.semantic_action == "EMPHASIZE")
    peak = segment.program["keyframes"][1]
    assert peak["dx"] == 0.0 and peak["dy"] == 0.0
    duration = segment.end - segment.start
    limit = motion_comfort("ESTABLISH").max_normalized_speed * _SAFETY
    assert _speed(peak["scale"] - 1.0, item, duration) <= limit + 1e-9
    final = segment.program["keyframes"][-1]
    assert (final["dx"], final["dy"], final["scale"]) == (0.0, 0.0, 1.0)


def test_forced_dip_never_exceeds_comfort_speed() -> None:
    limit = motion_comfort("ESTABLISH").max_normalized_speed * _SAFETY
    for w, h, duration in ((0.32, 0.35, 0.40), (0.6, 0.8, 0.30), (0.05, 0.05, 0.6)):
        item = _item("a", 0.5, 0.5, w, h)
        delta = reference_dip_delta(item, duration)
        assert 0.0 < delta <= SUPPORT_DIP_MAX_DELTA
        assert _speed(delta, item, duration) <= limit + 1e-9
        assert comfort_bounded_delta(item, duration, 1.0) >= delta - 1e-12


def test_handoff_reference_reads_executed_segments() -> None:
    cue = _cue("src")
    cue = cue.model_copy(update={"segments": [*cue.segments, MotionSegment(
        phase="ESTABLISH", start=1.3, end=1.7, semantic_action="FOCUS_HANDOFF",
        source_asset_id="src", target_asset_id="dst", program=STATIC)]})
    reference = MotionSemanticReference.of([], [cue, _cue("other")])
    assert reference.handoff_applied("b1", "src", "dst") is True
    assert reference.handoff_applied("b1", "other", "dst") is False
    assert reference.handoff_applied("b1", "unknown", "dst") is None
