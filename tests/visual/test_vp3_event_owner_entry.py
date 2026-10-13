"""VP3: unique authored event owners get the restrained entry; supports do not."""
from __future__ import annotations

import json
from pathlib import Path

from app.choreography import ChoreographyDirective, ChoreographyPlan, SequencePhase
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    MotionSegment,
    StoryBeat,
    StoryEventAuthority,
    VisualAsset,
)
from app.motion import EntryMotionGrammar

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


def _grammar(cues, *, story, leader=None, owners=()):
    ids = [c.asset_id for c in cues]
    layout = CompositionBeat(beat_id="b", items=[
        LayoutItem(asset_id=a, x=0.12 + 0.25 * n, y=0.5, width=0.2, height=0.3) for n, a in enumerate(ids)])
    directive = ChoreographyDirective(beat_id="b", sequence_id="q", phase=SequencePhase.SETUP,
                                      action="REVEAL", primary_asset_id=leader)
    assets = [VisualAsset(id=a, scene_id="s", role="supporting", image_path=Path(f"{a}.png"),
                          extraction_method="test") for a in ids]
    beat = story.model_copy(update={"event_authorities": list(owners)})
    out = EntryMotionGrammar().apply(cues, composition=[layout], choreography=ChoreographyPlan(
        directives=(directive,)), assets=assets, story=[beat])
    return {c.asset_id: c for c in out}


def _entry(asset: str, start: float, end: float, hold_ms: int = 300) -> MotionCue:
    return MotionCue(beat_id="b", asset_id=asset, kind="program_v3", start=start, end=end,
                     params={"program": json.loads(json.dumps(_STATIC)),
                             "semantic_continuity": {"mode": "ENTER"},
                             "semantic_settle_time": end, "semantic_peak_time": start,
                             "semantic_focus": {"rhythm": {"minimum_read_hold_ms": hold_ms}}})


# M4: unique event owners ----------------------------------------------------------------------
def test_unique_event_result_gets_the_restrained_entry_support_does_not() -> None:
    owners = [StoryEventAuthority(event_id="e1", leader_asset_ids=["lead"], result_asset_ids=["res"],
                                  participant_asset_ids=["sup"])]
    cues = [_entry("opener", 0.0, 0.3), _entry("sup", 0.4, 0.8), _entry("res", 0.9, 1.3)]
    out = _grammar(cues, story=BEAT, owners=owners)
    assert out["res"].params["entry_grammar"]["scale_in"] is True
    assert out["sup"].params["entry_grammar"]["scale_in"] is False
    assert out["res"].params["program"]["keyframes"][-1]["scale"] == 1.0


def test_overlapping_owners_keep_one_accent_by_authority() -> None:
    owners = [StoryEventAuthority(event_id="e1", leader_asset_ids=["lead"]),
              StoryEventAuthority(event_id="e2", leader_asset_ids=["x"], result_asset_ids=["res"])]
    cues = [_entry("opener", 0.0, 0.3), _entry("lead", 0.9, 1.3), _entry("res", 1.0, 1.4)]
    out = _grammar(cues, story=BEAT, owners=owners)
    assert out["res"].params["entry_grammar"]["scale_in"] is True             # RESULT outranks LEADER
    assert out["lead"].params["entry_grammar"]["scale_in"] is False


def test_ambiguous_or_review_events_have_no_owner() -> None:
    owners = [StoryEventAuthority(event_id="e1", leader_asset_ids=["a1", "a2"]),
              StoryEventAuthority(event_id="e2", result_asset_ids=["r"], needs_review=True)]
    cues = [_entry("opener", 0.0, 0.3), _entry("a1", 0.4, 0.8), _entry("a2", 0.9, 1.3), _entry("r", 1.4, 1.6)]
    out = _grammar(cues, story=BEAT, owners=owners)
    assert not any(out[a].params["entry_grammar"]["scale_in"] for a in ("a1", "a2", "r"))
