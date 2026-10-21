"""Focus staging and the idea-climax wash (2026-10-21 reference measurement).

References: one dominant object per picture (largest object ~51-53 % of the height, the only
coloured object in most frames) and a grey/blur wash on the backdrop at the end of an idea
(3-5 per minute and a quarter, 1.8-2.8 s each, 11.6-18.5 s apart). Timing never changes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import app.composition.focus_staging as staging
from app.composition.focus_staging import (
    ANCHOR_MAX_HEIGHT,
    FOCUS_PLACEMENT_SOURCE,
    GAP,
    SATELLITE_RATIO,
    FocusStagingPlanner,
)
from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    MotionCue,
    StoryBeat,
    StoryEntity,
    StorySemanticContext,
    VisualAsset,
)
from app.motion import resolution
from app.motion.resolution import IDEA_WASH_MIN_GAP, PayoffResolutionDirector
from app.motion.spoken_pulse import pulse_at

ASPECT = 16 / 9


def _asset(asset_id: str, family: str | None = None) -> VisualAsset:
    return VisualAsset(id=asset_id, scene_id="s1", role="visual", image_path=Path(f"/missing/{asset_id}.png"),
                       extraction_method="test", asset_family_id=family)


def _item(asset_id: str, x: float, y: float, w: float, h: float, z: int = 10) -> LayoutItem:
    return LayoutItem(asset_id=asset_id, x=x, y=y, width=w, height=h, z=z, placement_source="authored_scene_geometry")


def _beat(roles: dict[str, str], *, narration: str = "انتهت الفكرة.", names: dict[str, str] | None = None,
          beat_id: str = "b1", start: float = 0.0, end: float = 4.0) -> StoryBeat:
    names = names or {}
    entities = [StoryEntity(unit_id=f"u_{a}", role=r, semantic_name=names.get(a)) for a, r in roles.items()]
    return StoryBeat(id=beat_id, scene_id="s1", start=start, end=end, narration=narration, action="REVEAL",
                     semantic_context=StorySemanticContext(entities=entities),
                     asset_activations=[AssetActivation(asset_id=a, semantic_unit_id=f"u_{a}") for a in roles])


def _side(item: LayoutItem) -> float:
    return max(item.height, item.width * ASPECT)


def _gap(a: LayoutItem, b: LayoutItem) -> float:
    gx = max(a.x - a.width / 2, b.x - b.width / 2) - min(a.x + a.width / 2, b.x + b.width / 2)
    gy = max(a.y - a.height / 2, b.y - b.height / 2) - min(a.y + a.height / 2, b.y + b.height / 2)
    return max(gx, gy)


def _stage(items, roles, *, spoken=(), focus=None, names=None):
    assets = [_asset(item.asset_id) for item in items]
    result = FocusStagingPlanner().stage(items, assets, [_beat(roles, names=names)], focus, set(spoken))
    return result, {item.asset_id: item for item in result.items}


# -- focus staging --------------------------------------------------------------------
def test_competing_objects_get_one_dominant_anchor_the_narration_names() -> None:
    items = [_item("phone", 0.30, 0.50, 0.16, 0.30), _item("lock", 0.70, 0.50, 0.16, 0.30)]
    result, out = _stage(items, {"phone": "OBJECT", "lock": "OBJECT"}, spoken={"lock"})
    assert result.anchor_id == "lock" and result.evidence.startswith("focus_staging:applied")
    assert out["lock"].height > 0.30 and out["lock"].height <= ANCHOR_MAX_HEIGHT + 1e-9
    assert _side(out["phone"]) <= SATELLITE_RATIO * _side(out["lock"]) + 1e-6
    assert out["phone"].x < out["lock"].x                               # keeps its side
    assert _gap(out["phone"], out["lock"]) >= GAP - 1e-6                # never overlaps
    assert all(item.placement_source == FOCUS_PLACEMENT_SOURCE for item in out.values())


def test_a_clearly_larger_drawing_is_never_shrunk_for_a_smaller_named_one() -> None:
    items = [_item("window", 0.40, 0.50, 0.30, 0.45), _item("button", 0.75, 0.30, 0.08, 0.14)]
    result, out = _stage(items, {"window": "OBJECT", "button": "PRIMARY"}, spoken={"button"})
    assert result.anchor_id == "window"
    assert out["window"].height >= items[0].height - 1e-9


def test_characters_and_what_they_hold_never_move() -> None:
    items = [_item("hero", 0.25, 0.55, 0.20, 0.80), _item("card", 0.37, 0.45, 0.06, 0.08),
             _item("lock", 0.62, 0.45, 0.14, 0.26), _item("phone", 0.85, 0.45, 0.14, 0.26)]
    roles = {"hero": "CHARACTER", "card": "OBJECT", "lock": "OBJECT", "phone": "OBJECT"}
    result, out = _stage(items, roles, spoken={"lock"})
    assert result.evidence.startswith("focus_staging:applied")
    for asset_id in ("hero", "card"):                                   # the card touches the hero
        assert (out[asset_id].x, out[asset_id].y, out[asset_id].width) == pytest.approx(
            next((i.x, i.y, i.width) for i in items if i.asset_id == asset_id))


def test_a_pass2_family_scales_rigidly() -> None:
    items = [_item("box", 0.30, 0.50, 0.16, 0.30), _item("box:secondary-1", 0.33, 0.52, 0.06, 0.08),
             _item("lock", 0.70, 0.50, 0.16, 0.30)]
    assets = [_asset("box", "box"), _asset("box:secondary-1", "box"), _asset("lock")]
    roles = {"box": "OBJECT", "box:secondary-1": "OBJECT", "lock": "OBJECT"}
    result = FocusStagingPlanner().stage(items, assets, [_beat(roles)], None, {"lock"})
    out = {item.asset_id: item for item in result.items}
    ratio = out["box"].width / items[0].width
    assert out["box:secondary-1"].width / items[1].width == pytest.approx(ratio)
    assert (out["box:secondary-1"].x - out["box"].x) == pytest.approx((0.33 - 0.30) * ratio)


@pytest.mark.parametrize("roles,names,reason", [
    ({"a": "OBJECT", "b": "OBJECT"}, {"b": "curved arrow"}, "authored_path_art"),
    ({"a": "CHARACTER", "b": "CHARACTER"}, None, "no_objects"),
])
def test_scenes_whose_meaning_is_in_the_drawing_stay_as_authored(roles, names, reason) -> None:
    items = [_item("a", 0.30, 0.50, 0.16, 0.30), _item("b", 0.70, 0.50, 0.16, 0.30)]
    result, out = _stage(items, roles, names=names)
    assert result.evidence == f"focus_staging:abstained:{reason}" and result.items == items


def test_an_already_dominant_anchor_is_left_alone() -> None:
    items = [_item("big", 0.45, 0.50, 0.30, 0.52), _item("tick", 0.80, 0.30, 0.06, 0.12)]
    result, _ = _stage(items, {"big": "OBJECT", "tick": "OBJECT"})
    assert result.evidence == "focus_staging:abstained:already_dominant"
    assert result.anchor_id == "big" and result.items == items


def test_the_switch_restores_the_authored_picture(monkeypatch) -> None:
    monkeypatch.setattr(staging, "FOCUS_STAGING", False)
    items = [_item("phone", 0.30, 0.50, 0.16, 0.30), _item("lock", 0.70, 0.50, 0.16, 0.30)]
    result, _ = _stage(items, {"phone": "OBJECT", "lock": "OBJECT"}, spoken={"lock"})
    assert result.items == items


# -- idea climax ------------------------------------------------------------------------
def _cue(beat_id: str, asset_id: str, start: float) -> MotionCue:
    return MotionCue(beat_id=beat_id, asset_id=asset_id, kind="program_v3", start=start, end=start + 0.3, params={})


def _climax_plan(narration: str = "انتهت الفكرة.", *, backdrop_start: float = 0.6, beat_id: str = "b1",
                 start: float = 0.0, end: float = 4.0):
    beat = _beat({"lock": "OBJECT", "phone": "OBJECT"}, narration=narration, beat_id=beat_id, start=start, end=end)
    layout = CompositionBeat(beat_id=beat_id, items=[_item("lock", 0.65, 0.5, 0.2, 0.4, z=12),
                                                     _item("phone", 0.25, 0.5, 0.1, 0.2, z=11)],
                             visual_anchor_asset_id="lock")
    cues = [_cue(beat_id, "lock", start + 0.4), _cue(beat_id, "phone", start + backdrop_start)]
    return beat, layout, cues


def test_an_idea_ends_on_its_anchor_with_the_backdrop_washed() -> None:
    beat, layout, cues = _climax_plan()
    out = PayoffResolutionDirector().plan(story=[beat], composition=[layout], motion=cues,
                                          assets=[_asset("lock"), _asset("phone")])
    wash = next(cue for cue in out if cue.asset_id == "lock").params["focus_wash"]
    assert wash["case"] == "IDEA_CLIMAX" and wash["focus_asset_ids"] == ["lock"]
    assert wash["end"] == pytest.approx(beat.end)
    assert wash["start"] >= 0.6 + resolution.IDEA_WASH_SETTLE - 1e-6     # after the backdrop landed
    assert [(c.asset_id, c.start, c.end) for c in out] == [(c.asset_id, c.start, c.end) for c in cues]


def test_no_climax_inside_a_sentence_or_without_a_readable_hold() -> None:
    beat, layout, cues = _climax_plan(narration="والفكرة مستمرة،")
    out = PayoffResolutionDirector().plan(story=[beat], composition=[layout], motion=cues,
                                          assets=[_asset("lock"), _asset("phone")])
    assert not any("focus_wash" in cue.params for cue in out)
    beat, layout, cues = _climax_plan(backdrop_start=3.2)                # lands too late to read a wash
    out = PayoffResolutionDirector().plan(story=[beat], composition=[layout], motion=cues,
                                          assets=[_asset("lock"), _asset("phone")])
    assert not any("focus_wash" in cue.params for cue in out)


def test_idea_climaxes_keep_the_reference_spacing() -> None:
    first = _climax_plan(beat_id="b1", start=0.0, end=4.0)
    second = _climax_plan(beat_id="b2", start=4.0, end=8.0)
    third = _climax_plan(beat_id="b3", start=4.0 + IDEA_WASH_MIN_GAP + 1.0, end=8.0 + IDEA_WASH_MIN_GAP + 1.0)
    rows = [first, second, third]
    out = PayoffResolutionDirector().plan(story=[r[0] for r in rows], composition=[r[1] for r in rows],
                                          motion=[c for r in rows for c in r[2]],
                                          assets=[_asset("lock"), _asset("phone")])
    washed = sorted(cue.beat_id for cue in out if "focus_wash" in cue.params)
    assert len(washed) == 2 and "b3" in washed                           # one of b1/b2, and b3


def test_the_climax_switch_restores_the_event_washes_only(monkeypatch) -> None:
    monkeypatch.setattr(resolution, "IDEA_CLIMAX_WASH", False)
    beat, layout, cues = _climax_plan()
    out = PayoffResolutionDirector().plan(story=[beat], composition=[layout], motion=cues,
                                          assets=[_asset("lock"), _asset("phone")])
    assert not any("focus_wash" in cue.params for cue in out)


def test_nothing_pulses_behind_a_wash() -> None:
    beat, layout, cues = _climax_plan()
    washed = PayoffResolutionDirector().plan(story=[beat], composition=[layout], motion=cues,
                                             assets=[_asset("lock"), _asset("phone")])
    phone = next(cue for cue in washed if cue.asset_id == "phone")
    wash_start = next(cue for cue in washed if cue.asset_id == "lock").params["focus_wash"]["start"]
    pulsed, reason = pulse_at(phone, at=wash_start + 0.1, beat=beat, item=layout.items[1], beat_cues=washed,
                              assets_by_id={"phone": _asset("phone"), "lock": _asset("lock")})
    assert pulsed is None and reason == "receded_behind_wash"


def test_a_late_arrival_lands_crisp_over_the_receding_scene() -> None:
    beat, layout, cues = _climax_plan()
    beat = beat.model_copy(update={"asset_activations": [*beat.asset_activations,
                                                         AssetActivation(asset_id="key", semantic_unit_id="u_key")]})
    layout = layout.model_copy(update={"items": [*layout.items, _item("key", 0.45, 0.2, 0.08, 0.12, z=13)]})
    cues = [*cues, _cue("b1", "key", 2.6)]                                # lands too late for a full settle
    out = PayoffResolutionDirector().plan(story=[beat], composition=[layout], motion=cues,
                                          assets=[_asset("lock"), _asset("phone"), _asset("key")])
    wash = next(cue for cue in out if cue.asset_id == "lock").params["focus_wash"]
    assert wash["start"] == pytest.approx(2.6)                           # with the last arrival
    assert wash["focus_asset_ids"] == ["key", "lock"]                    # the arrival stays crisp


# -- opening hook (retention review 2026-10-21) ------------------------------------------------
def _sized_asset(tmp_path: Path, asset_id: str, px: tuple[int, int]) -> VisualAsset:
    from PIL import Image

    path = tmp_path / f"{asset_id}.png"
    Image.new("RGBA", px, (40, 90, 200, 255)).save(path)
    return VisualAsset(id=asset_id, scene_id="s1", role="visual", image_path=path, extraction_method="test")


def test_the_first_element_spoken_leads_the_opening_large_central_and_sharp(tmp_path: Path) -> None:
    """Cybercrime Gangs v1: a small building alone in a corner opened the video."""
    items = [_item("building", 0.79, 0.21, 0.13, 0.17), _item("monitor", 0.40, 0.60, 0.35, 0.60)]
    assets = [_sized_asset(tmp_path, "building", (380, 300)), _sized_asset(tmp_path, "monitor", (590, 567))]
    result = FocusStagingPlanner().stage(items, assets, [_beat({"building": "OBJECT", "monitor": "OBJECT"})],
                                         None, set(), hook_asset_id="building")
    out = {item.asset_id: item for item in result.items}
    assert result.anchor_id == "building" and ":opening_hook:" in result.evidence
    assert out["building"].height > 0.17 * 1.3                       # it grows ...
    native_upscale = out["building"].height * 1080 / 300
    assert native_upscale <= staging.OPENING_MAX_UPSCALE + 1e-6       # ... but stays sharp
    assert abs(out["building"].x - 0.5) < abs(0.79 - 0.5)             # toward the centre
    assert _side(out["monitor"]) <= SATELLITE_RATIO * _side(out["building"]) + 1e-6


def test_a_hook_that_cannot_become_large_and_sharp_does_not_lead(tmp_path: Path) -> None:
    items = [_item("dot", 0.80, 0.20, 0.05, 0.06), _item("monitor", 0.40, 0.60, 0.35, 0.60)]
    assets = [_sized_asset(tmp_path, "dot", (100, 70)), _sized_asset(tmp_path, "monitor", (590, 567))]
    result = FocusStagingPlanner().stage(items, assets, [_beat({"dot": "OBJECT", "monitor": "OBJECT"})],
                                         None, set(), hook_asset_id="dot")
    assert result.anchor_id == "monitor" and ":opening_hook:" not in result.evidence


def test_the_opening_hook_switch_restores_the_usual_anchor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(staging, "OPENING_HOOK", False)
    items = [_item("building", 0.79, 0.21, 0.13, 0.17), _item("monitor", 0.40, 0.60, 0.35, 0.60)]
    assets = [_sized_asset(tmp_path, "building", (380, 300)), _sized_asset(tmp_path, "monitor", (590, 567))]
    result = FocusStagingPlanner().stage(items, assets, [_beat({"building": "OBJECT", "monitor": "OBJECT"})],
                                         None, set(), hook_asset_id="building")
    assert result.anchor_id != "building" or ":opening_hook:" not in result.evidence
