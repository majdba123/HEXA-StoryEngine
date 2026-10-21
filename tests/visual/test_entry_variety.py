"""Entry variety 2026-10-21: objects and keywords never all enter alike.

Half of all entries were the same high-scale landing and every keyword the same diagonal
slide, so the eye stopped reading them. Landings now rotate between four in-place styles and
keywords between three directions; both are seeded from the story (a re-render is
identical), never repeat back to back, keep together what appears together, and stay inside
the space the layout already reserves.
"""
from __future__ import annotations

import pytest

import app.motion.landing as landing
import app.motion.text as text_motion
from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    MotionCue,
    StoryBeat,
    StoryEntity,
    StorySemanticContext,
    TextMotionCue,
    VisualAsset,
)
from app.motion.contract import segment_contract_violations
from app.motion.landing import ReferenceLandingPolicy
from app.render.text import TextRenderer

_STATIC = {"name": "reference_entry", "settle_progress": 1.0, "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}, {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}


def _scene(count: int = 24, *, together: bool = False, text: str = "مشهد"):
    story, composition, motion, assets = [], [], [], []
    for k in range(count):
        ids = [f"o{k}", f"p{k}"] if together else [f"o{k}"]
        story.append(StoryBeat(
            id=f"b{k}", scene_id=f"s{k}", start=2.0 * k, end=2.0 * k + 2.0, narration=f"{text} {k}",
            action="REVEAL", primary_asset_ids=ids,
            semantic_context=StorySemanticContext(entities=[StoryEntity(unit_id=f"u_{a}", role="OBJECT") for a in ids]),
            asset_activations=[AssetActivation(asset_id=a, semantic_unit_id=f"u_{a}") for a in ids]))
        composition.append(CompositionBeat(beat_id=f"b{k}", items=[
            LayoutItem(asset_id=a, x=0.3 + 0.4 * n, y=0.5, width=0.2, height=0.3) for n, a in enumerate(ids)]))
        for a in ids:
            motion.append(MotionCue(beat_id=f"b{k}", asset_id=a, kind="program_v3", start=2.0 * k + 0.3,
                                    end=2.0 * k + 0.7, params={"program": dict(_STATIC),
                                                               "semantic_continuity": {"mode": "ENTER"}}))
            assets.append(VisualAsset(id=a, scene_id=f"s{k}", role="supporting", image_path=f"{a}.png",
                                      extraction_method="t"))
    return story, composition, motion, assets


def _land(story, composition, motion, assets):
    out = ReferenceLandingPolicy().apply(story=story, composition=composition, motion=motion, assets=assets)
    return sorted(out, key=lambda cue: (cue.start, cue.asset_id))


def test_landings_rotate_four_styles_starting_with_the_reference_and_never_back_to_back() -> None:
    out = _land(*_scene())
    styles = [cue.params["reference_landing"]["style"] for cue in out]
    assert styles[0] == "high"  # the reference G19 landing opens every video
    assert all(a != b for a, b in zip(styles, styles[1:]))
    assert set(styles) == set(landing.LANDING_STYLES)
    assert styles.count("high") >= max(styles.count(name) for name in ("grow", "soft", "bloom")) - 2


def test_every_landing_style_is_in_place_inside_the_reserved_footprint_and_contract_clean() -> None:
    story, composition, motion, assets = _scene()
    items = {(row.beat_id, item.asset_id): item for row in composition for item in row.items}
    for cue in _land(story, composition, motion, assets):
        frames = cue.params["program"]["keyframes"]
        assert all(f["dx"] == 0.0 and f["dy"] == 0.0 for f in frames)  # in place: no path to collide
        assert all(0.7 <= f["scale"] <= 1.28 + 1e-9 for f in frames)  # inside the 1.28x board footprint
        assert frames[-1]["scale"] == 1.0  # rests at its authored size
        item = items[(cue.beat_id, cue.asset_id)]
        assert not segment_contract_violations(
            phase="ENTRY", program=cue.params["program"], params=cue.params, segment_duration=cue.end - cue.start,
            item_width=item.width, item_height=item.height, base_entry=True)
    original = {(cue.beat_id, cue.asset_id): (cue.start, cue.end) for cue in motion}
    assert all((cue.start, cue.end) == original[(cue.beat_id, cue.asset_id)]
               for cue in _land(story, composition, motion, assets))  # Story instants kept


def test_elements_revealed_together_land_in_one_style() -> None:
    out = _land(*_scene(together=True))
    by_beat: dict[str, set[str]] = {}
    for cue in out:
        by_beat.setdefault(cue.beat_id, set()).add(cue.params["reference_landing"]["style"])
    assert all(len(styles) == 1 for styles in by_beat.values())
    sequence = [next(iter(by_beat[f"b{k}"])) for k in range(len(by_beat))]
    assert all(a != b for a, b in zip(sequence, sequence[1:]))


def test_landing_styles_follow_the_story_and_are_reproducible() -> None:
    first = [cue.params["reference_landing"]["style"] for cue in _land(*_scene())]
    again = [cue.params["reference_landing"]["style"] for cue in _land(*_scene())]
    other = [cue.params["reference_landing"]["style"] for cue in _land(*_scene(text="قصة أخرى"))]
    assert first == again and first != other


def test_landing_variety_switch_off_keeps_the_single_reference_landing(monkeypatch) -> None:
    monkeypatch.setattr(landing, "LANDING_VARIETY", False)
    assert {cue.params["reference_landing"]["style"] for cue in _land(*_scene())} == {"high"}


# -- keywords -------------------------------------------------------------------------------
def _keywords(count: int = 30, *, pairs: bool = False) -> list[TextMotionCue]:
    cues = []
    for k in range(count):
        cues.append(TextMotionCue(beat_id=f"b{k}", text_cue_id=f"t{k}", kind="text", start=1.5 * k, end=1.5 * k + 0.2))
        if pairs:
            cues.append(TextMotionCue(beat_id=f"b{k}", text_cue_id=f"u{k}", kind="text", start=1.5 * k + 0.05,
                                      end=1.5 * k + 0.25))
    return cues


def _beats(count: int = 30, text: str = "كلمة") -> list[StoryBeat]:
    return [StoryBeat(id=f"b{k}", scene_id="s", start=1.5 * k, end=1.5 * k + 1.5, narration=f"{text} {k}",
                      action="REVEAL") for k in range(count)]


def test_keywords_rotate_entry_directions_never_twice_in_a_row() -> None:
    out = text_motion.assign_entry_styles(_keywords(), _beats())
    styles = [cue.params["entry_style"] for cue in out]
    assert styles[0] == "slide" and set(styles) == set(text_motion.TEXT_ENTRY_STYLES)
    assert all(a != b for a, b in zip(styles, styles[1:]))
    assert styles == [cue.params["entry_style"] for cue in text_motion.assign_entry_styles(_keywords(), _beats())]
    pairs = text_motion.assign_entry_styles(_keywords(pairs=True), _beats())
    by_beat: dict[str, set[str]] = {}
    for cue in pairs:
        by_beat.setdefault(cue.beat_id, set()).add(cue.params["entry_style"])
    assert all(len(row) == 1 for row in by_beat.values())  # words appearing together enter together


def test_keyword_variety_switch_off_leaves_the_plan_untouched(monkeypatch) -> None:
    monkeypatch.setattr(text_motion, "TEXT_ENTRY_VARIETY", False)
    assert all("entry_style" not in cue.params for cue in text_motion.assign_entry_styles(_keywords(), _beats()))


@pytest.mark.parametrize("rtl", [True, False])
@pytest.mark.parametrize("strength", [0.0, 1.0])
def test_every_keyword_direction_stays_inside_the_reserved_entry_excursion(rtl, strength) -> None:
    slide = TextRenderer._entry_gesture(rtl=rtl, pixel_scale=1.0, entry_strength=strength, entry_duration_ms=165)
    seen = {slide[:2]}
    for style in text_motion.TEXT_ENTRY_STYLES:
        dx, dy, duration = TextRenderer._entry_gesture(rtl=rtl, pixel_scale=1.0, entry_strength=strength,
                                                       entry_duration_ms=165, entry_style=style)
        assert duration == slide[2]
        assert 0 <= dy <= slide[1]  # never above the ink, never further below than reserved
        assert (0 <= dx <= slide[0]) if rtl else (slide[0] <= dx <= 0)  # only outward of the reading edge
        seen.add((dx, dy))
    assert len(seen) == len(text_motion.TEXT_ENTRY_STYLES)


def test_the_entry_direction_reaches_the_rendered_move_tag() -> None:
    def tags(style: str) -> str:
        return TextRenderer._line_tags(x=500, y=300, rtl=True, first=True, entry_duration_ms=165, entry_style=style)

    assert "\\move(514,310,500,300" in tags("slide")
    assert "\\move(500,310,500,300" in tags("rise")
    assert "\\move(514,300,500,300" in tags("side")
