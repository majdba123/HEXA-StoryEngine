"""VP3: an opacity-only entry settles before Rhythm's read hold."""
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
    VisualAsset,
)
from app.motion import EntryMotionGrammar
from app.shared.handoff import LayerHandoffValidator

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


# M2: opacity-only entry settles before the hold ---------------------------------------------
def test_opacity_only_entry_settles_before_the_read_hold() -> None:
    cues = [_entry("opener", 0.0, 0.3), _entry("late", 1.50, 1.90)]
    late = _grammar(cues, story=BEAT)["late"]
    assert late.start == 1.50 and abs(late.end - 1.70) < 1e-9
    assert late.params["entry_opacity"]["start"] == late.start
    assert late.params["entry_opacity"]["settle"] == late.end
    assert LayerHandoffValidator._entry_opacity_inside_story_window(late.params["entry_opacity"], late)
    assert late.params["semantic_settle_time"] == 1.90                       # Text's sync anchor unchanged


def test_opacity_settle_abstains_without_three_frames() -> None:
    cues = [_entry("opener", 0.0, 0.3), _entry("late", 1.65, 1.95)]         # deadline 1.70: 0.05 s left
    late = _grammar(cues, story=BEAT)["late"]
    assert (late.start, late.end) == (1.65, 1.95)
    assert "read_hold_settle" not in late.params["entry_grammar"]
