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
    assert scene.frame(row.overlap_exits["old_b"]["start"]) == 20 - BOARD_LEAD_FRAMES


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


def test_a_finished_sentence_keeps_the_plain_fade_to_white() -> None:
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
