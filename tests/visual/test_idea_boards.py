"""Idea boards and keyword hold (2026-10-21 frame review of both references).

Inside one sentence the references never clear the screen: an old element stays until a
new element or word lands on its spot and fades just before it; the rest of the idea
stays. A spoken keyword stays as part of the idea until the next keyword or the scene end.
Positions and every Story / narration instant are unchanged.
"""
from __future__ import annotations

import pytest

import app.boundary.release as release
from app.boundary.release import (
    BOARD_LEAD_FRAMES,
    BOARD_MAX_UNITS,
    FADE_FRAMES,
    SceneBoundaryPlanner,
    continues_sentence,
)
from app.models import StoryBeat, TextCue
from app.text.timing.visibility import KEYWORD_HOLD_SECONDS, TextVisibilityPolicy
from tests.visual.test_sprint_4_5_scene_handoffs import (
    FPS,
    NEW_ON_OLD,
    Scene,
    _asset,
    _cue,
    _layout,
)


def _board(scene: Scene, narration: str = "أوصل لغير مكان!!,") -> Scene:
    scene.story[0] = scene.story[0].model_copy(update={"narration": narration})
    return scene


@pytest.mark.parametrize("narration,continues", [
    ("أوصل لغير مكان!!,", True), ("النظام انكسر", True), ("أولًا،", True), ("قال:", True),
    ("هنا تبدأ الفكرة .", False), ("ليش؟", False), ("خلص!", False), ('قال: "خلص!"', False),
    ("وبعدين…", False), ("", False), ("123", False),
])
def test_a_board_is_one_sentence_spread_over_several_pictures(narration, continues) -> None:
    assert continues_sentence(narration) is continues


def test_inside_one_sentence_the_old_picture_is_replaced_in_place_not_cleared() -> None:
    scene = _board(Scene(lead=3, opener=NEW_ON_OLD))
    row = scene.plan()
    assert row.audit["hero_exit"] == "idea_board"
    old_a, old_b = row.overlap_exits["old_a"], row.overlap_exits["old_b"]
    # old_a sits where the opener lands: it starts fading BOARD_LEAD_FRAMES before it ...
    assert scene.frame(old_a["start"]) == 3 - BOARD_LEAD_FRAMES
    # ... while old_b, which nothing new touches, stays until the new picture is complete
    # and has faded before its scene ends.
    assert scene.frame(old_b["start"]) > scene.frame(old_a["start"]) + 30
    assert old_b["end"] <= scene.story[1].end - 1 / FPS + 1e-6
    for spec in (old_a, old_b):
        assert spec["fade"] == 1.0 and spec["end"] - spec["start"] == pytest.approx(FADE_FRAMES / FPS, abs=1e-5)
    assert row.exit_motion_blur == {}                                   # in place: nothing travels
    board = row.audit["idea_board"]
    assert (board["left_at_opener"], board["replaced_in_place"], board["held_to_picture_end"]) == (1, 0, 1)


def test_a_later_new_element_replaces_the_old_one_it_lands_on() -> None:
    scene = _board(Scene(lead=3, opener=NEW_ON_OLD, later=None))
    late = (0.8, 0.3, 0.2, 0.3)                                         # exactly where old_b is
    scene.composition[1] = _layout("b2", {"new_a": NEW_ON_OLD, "new_c": late})
    scene.assets.append(_asset("new_c", None))
    scene.motion.append(_cue("b2", "new_c", scene.boundary + 40 / FPS, opacity=True))
    row = scene.plan()
    assert scene.frame(row.overlap_exits["old_b"]["start"]) == 40 - BOARD_LEAD_FRAMES


def test_a_keyword_that_appears_over_a_held_element_makes_it_fade_first() -> None:
    scene = _board(Scene(lead=3, opener=NEW_ON_OLD))
    scene.add_text(20, 50, 0.8, 0.3)                                    # the word lands on old_b
    row = scene.plan()
    # it has fully faded before the word's first frame: they never share the spot
    assert scene.frame(row.overlap_exits["old_b"]["end"]) == 20


def test_no_more_than_the_board_capacity_share_the_screen() -> None:
    # Five old units in the top row; the opener lands on the first, a later arrival lands
    # on nothing. With four held units the later arrival would make six: the smallest held
    # unit (old_4) gives way to it, the others stay.
    old = {f"old_{n}": (0.1 + 0.16 * n, 0.12, 0.1, 0.1) for n in range(BOARD_MAX_UNITS)}
    old["old_4"] = (0.1 + 0.16 * 4, 0.12, 0.06, 0.06)
    scene = _board(Scene(lead=3, opener=(0.1, 0.12, 0.1, 0.1), later=30, old=old))
    row = scene.plan()
    frames = {asset: scene.frame(spec["start"]) for asset, spec in row.overlap_exits.items()}
    assert frames["old_0"] == 3 - BOARD_LEAD_FRAMES
    assert frames["old_4"] == 30 - BOARD_LEAD_FRAMES
    assert all(frames[f"old_{n}"] > 30 for n in (1, 2, 3))


def test_a_finished_sentence_keeps_the_plain_fade_to_white(monkeypatch) -> None:
    monkeypatch.setattr(release, "IDEA_MIN_SECONDS", 1.5)  # the idea has been on screen 2 s
    scene = _board(Scene(lead=3, opener=NEW_ON_OLD), narration="end of the idea.")
    row = scene.plan()
    assert row.audit["hero_exit"] == "scene_fade"
    assert len({spec["start"] for spec in row.overlap_exits.values()}) == 1


def test_the_board_switch_restores_the_plain_fade(monkeypatch) -> None:
    monkeypatch.setattr(release, "IDEA_BOARD", False)
    assert _board(Scene(lead=3, opener=NEW_ON_OLD)).plan().audit["hero_exit"] == "scene_fade"


def test_boards_never_touch_story_or_narration_instants() -> None:
    scene = _board(Scene(lead=3, opener=NEW_ON_OLD))
    before = [(cue.asset_id, cue.start, cue.end) for cue in scene.motion]
    scene.plan(SceneBoundaryPlanner())
    assert [(cue.asset_id, cue.start, cue.end) for cue in scene.motion] == before


# -- keyword hold -------------------------------------------------------------------------
def _beat(end: float = 6.0) -> StoryBeat:
    return StoryBeat(id="b1", scene_id="s1", start=0.0, end=end, narration="x", action="REVEAL")


def _word(cue_id: str, start: float, end: float, text: str = "كلمة") -> TextCue:
    return TextCue(id=cue_id, beat_id="b1", text=text, semantic_type="keyword", source_char_start=0,
                   source_char_end=len(text), spoken_start=start, spoken_end=end, emphasis_time=start,
                   style_id="keyword")


def test_a_keyword_stays_until_the_next_keyword_replaces_it() -> None:
    first, second = _word("a", 0.5, 0.9), _word("b", 3.0, 3.4)
    end = TextVisibilityPolicy.visible_end(first, _beat(), [first, second])
    assert end == pytest.approx(3.0 - 0.08)                             # 2.4 s on screen, not ~1 s


def test_a_keyword_stays_until_the_scene_ends_and_never_beyond_it() -> None:
    word = _word("a", 0.5, 0.9)
    assert TextVisibilityPolicy.visible_end(word, _beat(end=2.5), [word]) == pytest.approx(2.5)
    long_scene = TextVisibilityPolicy.visible_end(word, _beat(end=20.0), [word])
    assert long_scene == pytest.approx(0.5 + KEYWORD_HOLD_SECONDS)


def test_the_hold_switch_restores_the_reading_time_window(monkeypatch) -> None:
    monkeypatch.setattr("app.text.timing.visibility.KEYWORD_HOLD_SECONDS", 0.0)
    word = _word("a", 0.5, 0.9)
    assert TextVisibilityPolicy.visible_end(word, _beat(), [word]) < 0.5 + 1.95


# -- the keyword is part of the idea: it crosses the board boundary --------------------
def _outgoing_word(scene: Scene, x: float = 0.5, y: float = 0.75, spoken: float = 1.2) -> None:
    from app.models import TextCompositionBeat, TextLayoutItem, TextMotionCue, TextPlan

    cue = TextCue(id="w1", beat_id="b1", text="label", semantic_type="emphasis", source_char_start=0,
                  source_char_end=5, spoken_start=spoken, spoken_end=spoken + 0.3, emphasis_time=spoken,
                  style_id="emphasis")
    scene.text = TextPlan(cues=[*scene.text.cues, cue])
    scene.text_composition = [*scene.text_composition, TextCompositionBeat(
        beat_id="b1", items=[TextLayoutItem(text_cue_id="w1", x=x, y=y, max_width=0.2)])]
    scene.text_motion = [*scene.text_motion, TextMotionCue(
        beat_id="b1", text_cue_id="w1", kind="text", start=spoken, end=spoken + 0.3,
        params={"visible_end": scene.boundary})]


def test_a_keyword_on_screen_at_the_cut_stays_into_the_next_picture() -> None:
    scene = _board(Scene(lead=3, opener=NEW_ON_OLD))
    _outgoing_word(scene)
    row = scene.plan()
    assert row.audit["idea_board"]["carried_words"] == 1
    # nothing replaces it: it stays until the new picture is complete
    assert scene.frame(row.text_carry["w1"]) == scene.frame(scene.story[1].end) - FADE_FRAMES - 1


def test_the_next_keyword_replaces_the_carried_one() -> None:
    scene = _board(Scene(lead=3, opener=NEW_ON_OLD))
    scene.add_text(20, 50, 0.2, 0.85)                                   # the next word, elsewhere
    _outgoing_word(scene)                                               # (add_text replaces the plan)
    row = scene.plan()
    assert scene.frame(row.text_carry["w1"]) == 20 - FADE_FRAMES     # gone before the next word


def test_an_arrival_on_the_carried_word_ends_it_first() -> None:
    scene = _board(Scene(lead=3, opener=NEW_ON_OLD))
    _outgoing_word(scene, x=0.8, y=0.8)                                 # where new_b lands at frame 30
    row = scene.plan()
    assert scene.frame(row.text_carry["w1"]) == 30 - BOARD_LEAD_FRAMES


def test_no_carry_after_a_finished_sentence_or_for_a_word_already_gone(monkeypatch) -> None:
    monkeypatch.setattr(release, "IDEA_MIN_SECONDS", 1.5)  # a finished idea, not a young one
    finished = _board(Scene(lead=3, opener=NEW_ON_OLD), narration="end of the idea.")
    _outgoing_word(finished)
    assert finished.plan().text_carry == {}
    gone = _board(Scene(lead=3, opener=NEW_ON_OLD))
    _outgoing_word(gone)
    gone.text_motion[-1] = gone.text_motion[-1].model_copy(update={"params": {"visible_end": 1.6}})
    assert gone.plan().text_carry == {}


# -- holding a word never shrinks or drops it ---------------------------------------------
def _composed(late_reveal: float | None):
    from pathlib import Path

    from app.composition import TextCompositionPlanner
    from app.models import CompositionBeat, LayoutItem, MotionCue, VisualAsset
    from app.motion import TextMotionPlanner

    beat = _beat(end=6.0)
    word = _word("a", 0.5, 0.9, text="السيطرة")
    items = [LayoutItem(asset_id="hero", x=0.2, y=0.55, width=0.2, height=0.5, z=10)]
    motion = [MotionCue(beat_id="b1", asset_id="hero", kind="program_v3", start=0.0, end=0.3, params={})]
    assets = [VisualAsset(id="hero", scene_id="s1", role="visual", image_path=Path("/missing/hero.png"),
                          extraction_method="test")]
    if late_reveal is not None:  # a later element covers the whole frame from late_reveal on
        items.append(LayoutItem(asset_id="late", x=0.5, y=0.5, width=1.0, height=1.0, z=11))
        motion.append(MotionCue(beat_id="b1", asset_id="late", kind="program_v3", start=late_reveal,
                                end=late_reveal + 0.3, params={}))
        assets.append(VisualAsset(id="late", scene_id="s1", role="visual", image_path=Path("/missing/late.png"),
                                  extraction_method="test"))
    layout = TextCompositionPlanner().plan([beat], [CompositionBeat(beat_id="b1", items=items)], [word],
                                           assets=assets, visual_motion=motion)
    text_motion = TextMotionPlanner().plan([beat], [word], layout)
    return beat, word, layout, text_motion


def test_with_room_the_word_is_held_and_motion_follows_the_policy() -> None:
    beat, word, layout, text_motion = _composed(late_reveal=None)
    assert layout[0].items[0].visible_end is None
    assert text_motion[0].params["visible_end"] == pytest.approx(
        TextVisibilityPolicy.visible_end(word, beat, [word]))


def test_a_word_whose_spot_is_taken_later_keeps_its_reading_window_instead_of_vanishing() -> None:
    beat, word, layout, text_motion = _composed(late_reveal=2.0)
    item = layout[0].items[0]                                           # placed, not dropped
    assert item.visible_end == pytest.approx(TextVisibilityPolicy.reading_end(word, beat, [word]), abs=1e-6)
    assert item.visible_end < 2.0                                       # gone before the spot is taken
    assert text_motion[0].params["visible_end"] == pytest.approx(item.visible_end)


# -- idea clock (pacing review 2026-10-21) ---------------------------------------------------
def test_a_young_idea_continues_on_the_board_after_a_sentence_end() -> None:
    """Sentences last ~2.7 s; an idea 3-7 s: a sentence end clears only a finished idea."""
    row = _board(Scene(lead=3, opener=NEW_ON_OLD), narration="end of the idea.").plan()
    assert row.audit["hero_exit"] == "idea_board"  # the idea is 2 s old < IDEA_MIN_SECONDS


def test_the_idea_clock_switch_restores_the_sentence_rule(monkeypatch) -> None:
    monkeypatch.setattr(release, "IDEA_CLOCK", False)
    row = _board(Scene(lead=3, opener=NEW_ON_OLD), narration="end of the idea.").plan()
    assert row.audit["hero_exit"] == "scene_fade"


def test_a_clear_dims_the_old_idea_before_the_new_element_lands(monkeypatch) -> None:
    """Soft dip: the old scene starts fading SCENE_FADE_LEAD_FRAMES before the opener and
    is still partly visible when the new element lands (never a blank frame)."""
    monkeypatch.setattr(release, "IDEA_MIN_SECONDS", 1.5)
    scene = _board(Scene(lead=4, opener=NEW_ON_OLD), narration="end of the idea.")
    row = scene.plan()
    assert row.audit["hero_exit"] == "scene_fade"
    for spec in row.overlap_exits.values():
        assert scene.frame(spec["start"]) == 4 - release.SCENE_FADE_LEAD_FRAMES
        assert spec["end"] - spec["start"] == pytest.approx(release.SCENE_FADE_FRAMES / FPS, abs=1e-5)
        assert release.SCENE_FADE_LEAD_FRAMES < release.SCENE_FADE_FRAMES  # still visible at the opener
