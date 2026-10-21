"""Idea spread: two pictures of one idea share the screen (pacing review 2026-10-21).

When the next scene continues the same idea (the idea-board rule), the current picture
glides as one block into the right half and stays complete there while the next one is
built in the left half; along a chain the halves alternate. Narration, Story and every
reveal instant are unchanged: nothing appears earlier or later.
"""
from __future__ import annotations

import shutil

import pytest

import app.boundary.release as release
import app.composition.idea_spread as spread_module
from app.boundary.release import FADE_FRAMES, SceneBoundaryPlanner
from app.composition import TextCompositionPlanner
from app.composition.idea_spread import (
    GLIDE_FRAMES,
    SPREAD_GAP,
    SPREAD_PLACEMENT_SOURCE,
    IdeaSpreadPlanner,
)
from app.models import LayoutItem, StoryBeat, TextCue
from app.shared import safe_mode
from app.shared.narration import idea_links
from app.targets import active_target
from tests.visual.test_sprint_4_5_scene_handoffs import (
    FPS,
    NEW_CLEAR,
    NEW_ON_OLD,
    OLD_LEFT,
    OLD_RIGHT,
    Scene,
    _asset,
    _darkness,
    _encode,
)


def _story(*rows: tuple[str, float, float, str]) -> list[StoryBeat]:
    """(scene id, start, end, narration) per beat, one beat per row."""
    return [StoryBeat(id=f"b{n}", scene_id=scene, start=start, end=end, narration=text, action="REVEAL")
            for n, (scene, start, end, text) in enumerate(rows, 1)]


# -- which pictures belong to one idea ------------------------------------------------------
def test_a_sentence_split_over_pictures_and_a_young_connective_continue_the_idea() -> None:
    story = _story(("s1", 0.0, 2.0, "الهاكر يدخل الأنظمة"),       # no end punctuation: continues
                   ("s2", 2.0, 3.0, "بدون إذن."),                     # finished sentence ...
                   ("s3", 3.0, 5.0, "وهذا مخالف للقانون."),           # ... a connective, idea 3 s old
                   ("s4", 5.0, 7.0, "وكمان ممكن يسرق بيانات."),       # connective, idea now 5 s old
                   ("s5", 7.0, 9.0, "موضوع جديد تمامًا"))             # no connective: a new idea
    assert idea_links(story, min_seconds=3.5) == {"b2", "b3"}


def test_beats_of_one_scene_never_link_and_restart_the_clock() -> None:
    # b2 shares b1's picture (no link); the clock restarts there, so at 5 s the idea is 3 s old.
    story = _story(("s1", 0.0, 2.0, "جملة"), ("s1", 2.0, 5.0, "تكملة."), ("s2", 5.0, 6.0, "ثم شيء."))
    assert idea_links(story, min_seconds=3.5) == {"b3"}


# -- Composition: halves --------------------------------------------------------------------
def _staged(scene: str, boxes: dict[str, tuple[float, float, float, float]], source="authored_scene_geometry"):
    return [LayoutItem(asset_id=f"{scene}:{name}", x=x, y=y, width=w, height=h, z=n, placement_source=source)
            for n, (name, (x, y, w, h)) in enumerate(boxes.items())]


def _chain(count: int = 3):
    texts = ["الهاكر يدخل", "ويفحص الموقع", "ويكتب تقرير", "وبعدين يرسله."][:count]
    story = _story(*[(f"s{n}", 2.0 * (n - 1), 2.0 * n, text) for n, text in enumerate(texts, 1)])
    staged = {f"s{n}": _staged(f"s{n}", {"hero": (0.25, 0.5, 0.3, 0.8), "prop": (0.75, 0.6, 0.3, 0.5)})
              for n in range(1, count + 1)}
    assets = [_asset(item.asset_id).model_copy(update={"scene_id": scene})
              for scene, items in staged.items() for item in items]
    return story, staged, assets


def _extent(items: list[LayoutItem]) -> tuple[float, float, float, float]:
    return (min(i.x - i.width / 2 for i in items), min(i.y - i.height / 2 for i in items),
            max(i.x + i.width / 2 for i in items), max(i.y + i.height / 2 for i in items))


def test_a_chain_alternates_halves_and_only_its_first_picture_glides() -> None:
    story, staged, assets = _chain(3)
    result = IdeaSpreadPlanner().plan(story, staged, assets)
    safe = active_target().safe_zones.content
    middle = (safe.left + safe.right) / 2
    # The first picture keeps its full-frame layout until the glide ...
    assert result.items["s1"] == staged["s1"]
    head = result.info["s1"]
    assert head["slot"] == "right" and 0.4 <= head["hold_scale"] < 1.0
    # ... the second is built in the left half, the third in the right half the first left.
    left, right = _extent(result.items["s2"]), _extent(result.items["s3"])
    assert left[2] <= middle - SPREAD_GAP / 2 + 1e-9 and left[0] >= safe.left - 1e-9
    assert right[0] >= middle + SPREAD_GAP / 2 - 1e-9 and right[2] <= safe.right + 1e-9
    assert result.info["s2"] == {"slot": "left", "scale": pytest.approx(head["hold_scale"]), "joins": "s1",
                                 "hold_scale": 1.0}
    assert result.info["s3"]["slot"] == "right" and result.info["s3"]["joins"] == "s2"
    assert all(item.placement_source == SPREAD_PLACEMENT_SOURCE for item in result.items["s2"])
    # Each beat that joins knows the picture held beside it, at its held geometry.
    assert set(result.held_items) == {"b2", "b3"}
    assert result.held_items["b3"] == result.items["s2"]
    assert _extent(result.held_items["b2"])[0] >= middle + SPREAD_GAP / 2 - 1e-9


def test_a_half_is_a_rigid_uniform_scale_of_the_staged_picture() -> None:
    story, staged, assets = _chain(2)
    before, after = staged["s2"], IdeaSpreadPlanner().plan(story, staged, assets).items["s2"]
    scale = after[0].width / before[0].width
    for old, new in zip(before, after):
        assert (new.width / old.width, new.height / old.height) == pytest.approx((scale, scale))
        assert new.z == old.z and new.asset_id == old.asset_id
    # relations between the elements are kept: same offsets, scaled
    assert (after[1].x - after[0].x) == pytest.approx((before[1].x - before[0].x) * scale)
    assert (after[1].y - after[0].y) == pytest.approx((before[1].y - before[0].y) * scale)


def test_a_picture_that_would_be_too_small_stays_full_frame(monkeypatch) -> None:
    story, staged, assets = _chain(2)
    monkeypatch.setattr(spread_module, "SPREAD_MIN_SCALE", 0.95)
    result = IdeaSpreadPlanner().plan(story, staged, assets)
    assert result.items == staged and result.info == {} and result.held_items == {}
    assert result.evidence["s2"] == "idea_spread:abstained:no_room"


def test_fallback_geometry_and_a_new_idea_are_never_spread() -> None:
    story, staged, assets = _chain(2)
    staged["s2"] = _staged("s2", {"hero": (0.5, 0.5, 0.3, 0.3)}, source="fallback_missing_source_geometry")
    assert IdeaSpreadPlanner().plan(story, staged, assets).info == {}
    story, staged, assets = _chain(2)
    story[0] = story[0].model_copy(update={"narration": "جملة كاملة."})
    story[1] = story[1].model_copy(update={"narration": "موضوع آخر"})
    assert IdeaSpreadPlanner().plan(story, staged, assets).info == {}


@pytest.mark.parametrize("module,flag", [(spread_module, "IDEA_SPREAD"), (release, "IDEA_BOARD"),
                                         (release, "SCENE_WHIP")])
def test_the_spread_switches_off_with_its_own_switch_and_with_the_board(monkeypatch, module, flag) -> None:
    story, staged, assets = _chain(2)
    monkeypatch.setattr(module, flag, False)
    assert IdeaSpreadPlanner().plan(story, staged, assets).items == staged


def test_the_first_safe_level_removes_the_spread() -> None:
    for level in (1, 2):
        assert safe_mode.LEVELS[level]["app.composition.idea_spread"] == {"IDEA_SPREAD": False}


# -- Boundary: the held picture -------------------------------------------------------------
HOLD = {"slot": "right", "hold_scale": 0.5, "hold_pivot_x": 0.5, "hold_pivot_y": 0.5,
        "hold_to_x": 0.75, "hold_to_y": 0.5}


def _spread_scene(*, opener=NEW_ON_OLD, lead: int = 3, root=None, hold=HOLD) -> Scene:
    """b1 (old_a left, old_b right, full frame) is held beside b2, built in the left half."""
    scene = Scene(lead=lead, opener=opener, later=30, root=root)
    scene.story = [beat.model_copy(update={"narration": "جملة كاملة."}) for beat in scene.story]
    scene.composition[0] = scene.composition[0].model_copy(update={"idea_spread": dict(hold)})
    scene.composition[1] = scene.composition[1].model_copy(update={
        "idea_spread": {"slot": "left", "scale": 0.5, "joins": "s1"}})
    return scene


def test_the_held_picture_stays_complete_until_the_new_picture_ends() -> None:
    # The opener lands on old_a's full-frame spot, but old_a has glided out of its way.
    scene = _spread_scene()
    row = scene.plan()
    assert row.audit["hero_exit"] == "idea_board"
    assert row.audit["idea_spread"] == {"slot": "left", "scale": 0.5, "glide": True}  # the new picture's half
    board = row.audit["idea_board"]
    assert (board["left_at_opener"], board["replaced_in_place"], board["held_to_picture_end"]) == (0, 0, 2)
    last = round((scene.story[1].end - scene.boundary) * FPS) - FADE_FRAMES - 1
    for spec in row.overlap_exits.values():
        assert scene.frame(spec["start"]) == last and spec["fade"] == 1.0
    assert row.text_carry == {}                         # a gliding picture leaves its words behind


def test_the_glide_moves_every_member_to_its_place_in_the_half() -> None:
    row = _spread_scene().plan()
    a, b = row.overlap_exits["old_a"], row.overlap_exits["old_b"]
    assert (a["glide_x"], a["glide_y"]) == pytest.approx((0.75 + (OLD_LEFT[0] - 0.5) * 0.5,
                                                          0.5 + (OLD_LEFT[1] - 0.5) * 0.5))
    assert (b["glide_x"], b["glide_y"]) == pytest.approx((0.75 + (OLD_RIGHT[0] - 0.5) * 0.5,
                                                          0.5 + (OLD_RIGHT[1] - 0.5) * 0.5))
    for spec in (a, b):
        assert spec["glide_scale"] == 0.5
        assert spec["glide_start"] == pytest.approx(2.0)
        assert spec["glide_end"] == pytest.approx(2.0 + GLIDE_FRAMES / FPS, abs=1e-5)


def test_a_picture_already_in_its_half_is_held_without_moving() -> None:
    row = _spread_scene(opener=NEW_CLEAR, hold={"slot": "left", "scale": 0.5, "hold_scale": 1.0}).plan()
    assert row.audit["idea_spread"]["glide"] is False
    assert all("glide_x" not in spec for spec in row.overlap_exits.values())
    assert row.audit["idea_board"]["held_to_picture_end"] == 2


def test_a_free_overlap_release_becomes_the_board_when_the_picture_joins() -> None:
    assert Scene(lead=10).plan().mode == "OVERLAP"                   # without the spread
    row = _spread_scene(opener=NEW_CLEAR, lead=10).plan()
    assert (row.mode, row.audit["hero_exit"]) == ("HARD_CUT", "idea_board")
    assert row.release_start is row.release_end is row.opener_at is None
    assert row.downgrade_reason == "idea_spread:overlap"


def test_a_spread_never_touches_story_or_narration_instants() -> None:
    scene = _spread_scene()
    before = ([(c.asset_id, c.start, c.end) for c in scene.motion],
              [(b.id, b.start, b.end, b.narration) for b in scene.story])
    scene.plan(SceneBoundaryPlanner())
    assert ([(c.asset_id, c.start, c.end) for c in scene.motion],
            [(b.id, b.start, b.end, b.narration) for b in scene.story]) == before


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_the_old_picture_glides_into_its_half_and_stays(tmp_path) -> None:
    scene = _spread_scene(root=tmp_path)
    row = scene.plan()
    frames = _encode(scene, [row], tmp_path / "spread")
    b = 60                                                               # first frame of the new beat
    held_b = (row.overlap_exits["old_b"]["glide_x"], row.overlap_exits["old_b"]["glide_y"],
              OLD_RIGHT[2] * 0.5, OLD_RIGHT[3] * 0.5)
    assert _darkness(frames, OLD_RIGHT)[b] > 0.9                         # starts where it was
    assert _darkness(frames, OLD_RIGHT)[b + GLIDE_FRAMES + 2] < 0.05     # has left its full-frame spot
    held = _darkness(frames, held_b, pad=0.02)
    end = scene.frame(row.overlap_exits["old_b"]["start"])
    assert held[b + GLIDE_FRAMES + 2] > 0.9 and held[b + end - 1] > 0.9  # complete in its half until its fade
    assert held[-1] < 0.05                                               # faded with its scene's end


# -- Text: words stay off the held picture --------------------------------------------------
def test_text_places_words_against_the_held_picture_too(monkeypatch) -> None:
    scene = _spread_scene()
    held = [LayoutItem(asset_id="old_a", x=0.6, y=0.4, width=0.1, height=0.15)]
    seen: list[set[str]] = []
    planner = TextCompositionPlanner()

    def place(**kwargs):
        seen.append({item.asset_id for item in kwargs["visual"].items})
        return None

    monkeypatch.setattr(planner.director, "place", place)
    cue = TextCue(id="t1", beat_id="b2", text="كلمة", semantic_type="keyword", source_char_start=0,
                  source_char_end=4, spoken_start=2.5, spoken_end=2.9, emphasis_time=2.5, style_id="keyword")
    planner.plan(scene.story, scene.composition, [cue], scene.assets, held_items={"b2": held})
    assert seen and all("old_a" in visible for visible in seen)


# -- Reels: the glide is projected with the picture -----------------------------------------
def test_the_projection_moves_the_glide_with_the_picture(tmp_path, monkeypatch) -> None:
    from app.render.planner import RenderPlanner
    from app.targets.projection import ReferencePlanProjector
    from app.targets.registry import REELS_9_16

    # The two-beat fixture is not a whole Final Package: only the projection itself is tested.
    monkeypatch.setattr(RenderPlanner, "_require_executable", staticmethod(lambda plan: None))
    scene = _spread_scene()
    plan = scene.render_plan()
    reels = ReferencePlanProjector().project(plan, REELS_9_16, tmp_path)
    p = reels.projection
    x = lambda v: (p.offset_x + v * 1920 * p.scale) / reels.width  # noqa: E731
    y = lambda v: (p.offset_y + v * 1080 * p.scale) / reels.height  # noqa: E731
    before, after = plan.scene_boundaries[0].overlap_exits["old_a"], reels.scene_boundaries[0].overlap_exits["old_a"]
    assert (after["glide_x"], after["glide_y"]) == pytest.approx((x(before["glide_x"]), y(before["glide_y"])))
    assert after["glide_scale"] == before["glide_scale"]
    spread = reels.composition[0].idea_spread
    assert (spread["hold_to_x"], spread["hold_pivot_y"]) == pytest.approx((x(0.75), y(0.5)))


# -- Motion: a held picture has not ended its idea ------------------------------------------
def test_a_picture_held_beside_the_next_one_gets_no_idea_climax_wash() -> None:
    from app.motion.resolution import PayoffResolutionDirector
    from tests.visual.test_focus_staging import _asset as _plain_asset
    from tests.visual.test_focus_staging import _climax_plan

    beat, layout, cues = _climax_plan()
    assets = [_plain_asset("lock"), _plain_asset("phone")]
    washed = PayoffResolutionDirector().plan(story=[beat], composition=[layout], motion=cues, assets=assets)
    assert any("focus_wash" in cue.params for cue in washed)              # the plain case washes
    nxt = StoryBeat(id="b2", scene_id="s-next", start=beat.end, end=beat.end + 2, narration="x", action="REVEAL")
    joined = layout.model_copy(update={"beat_id": "b2", "idea_spread": {"slot": "left", "scale": 0.5,
                                                                        "joins": beat.scene_id}})
    out = PayoffResolutionDirector().plan(story=[beat, nxt], composition=[layout, joined], motion=cues,
                                          assets=assets)
    assert not any("focus_wash" in cue.params for cue in out if cue.beat_id == beat.id)
