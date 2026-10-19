"""VNext: reference-strength hero emphasis, RESULT after its cause, text after its subject."""
from __future__ import annotations

import pytest

from app.models import AssetActivation, LayoutItem, MotionCue, StoryBeat, TextCue
from app.motion.hero_travel import EMPHASIS_CANDIDATES, EMPHASIS_RANGE
from app.story.windows import schedule_windows
from app.text.timing import TextVisibilityPolicy
from tests.visual.test_vp4_hero_travel import HERO, SUPPORT, _cue, _plan


# -- emphasis ---------------------------------------------------------------------------------
def _pulse_scale(cue: MotionCue) -> float:
    pulse = next(s for s in cue.segments if s.semantic_action == "HERO_EMPHASIS")
    return max(f["scale"] for f in pulse.program["keyframes"])


BIG_HERO = LayoutItem(asset_id="hero", x=0.75, y=0.62, width=0.3, height=0.45)   # 486 px: floor < 3.5 %


def test_emphasis_takes_the_strongest_restrained_amplitude_that_is_safe() -> None:
    _planner, out = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)], [SUPPORT, BIG_HERO])
    assert _pulse_scale(out[("b", "hero")]) == pytest.approx(1 + EMPHASIS_CANDIDATES[0]) == pytest.approx(1.05)
    # A 270 px subject needs ~6 % to be readable: it gets exactly that floor, never more.
    _planner, out = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)], [SUPPORT, HERO])
    assert 1 + EMPHASIS_CANDIDATES[0] < _pulse_scale(out[("b", "hero")]) <= 1 + EMPHASIS_RANGE[1] + 1e-9


def test_a_neighbour_steps_the_emphasis_down_instead_of_colliding() -> None:
    def neighbour(gap: float) -> LayoutItem:          # its right edge sits ``gap`` left of the hero
        return LayoutItem(asset_id="support", x=0.6 - 0.1 - gap, y=0.70, width=0.2, height=0.25)

    _planner, out = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)], [neighbour(0.0015), BIG_HERO])
    assert 1 + EMPHASIS_CANDIDATES[-1] - 1e-9 <= _pulse_scale(out[("b", "hero")]) < 1 + EMPHASIS_CANDIDATES[0]
    planner, out = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)], [neighbour(0.0), BIG_HERO])
    assert planner.decisions[0].emphasis == "abstain:scaled_hero_would_collide"
    assert "hero_emphasis" not in out[("b", "hero")].params


def test_composed_text_beside_the_hero_trims_or_revokes_the_pulse() -> None:
    planner, out = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)], [SUPPORT, HERO])
    motion = list(out.values())
    hero = out[("b", "hero")]
    pulse = hero.params["hero_emphasis"]
    # A text box touching the hero's right edge, visible during the pulse.
    right = HERO.x + HERO.width / 2
    text = {"b": [(pulse["start"] - 0.1, pulse["end"] + 0.1, (right + 0.001, 0.6, right + 0.2, 0.8))]}
    fitted = {c.asset_id: c for c in planner.fit_emphasis_to_text(motion, text)}["hero"]
    after = fitted.params.get("hero_emphasis")
    decision = next(d for d in planner.decisions if d.asset_id == "hero").emphasis
    if after is None:
        assert decision == "revoked:pulse_would_grow_into_composed_text"
        assert not any(s.semantic_action == "HERO_EMPHASIS" for s in fitted.segments)
    else:
        assert after["scale"] < pulse["scale"] and decision.startswith("applied:trimmed_for_text")


# -- RESULT after its cause -------------------------------------------------------------------
def _row(asset: str, start: float, end: float, roles: list[str], *, event: str = "E1") -> AssetActivation:
    return AssetActivation(asset_id=asset, semantic_unit_id=asset, spoken_start=start, spoken_end=end,
                           policy="EXPLICIT", source="unified_final_package", semantic_event_id=event,
                           semantic_event_order=1, semantic_event_roles=roles, visual_focus="PRIMARY")


BEAT = StoryBeat(id="b", scene_id="s", start=10.0, end=12.5, audio_start=10.0, audio_end=12.5,
                 narration="reached employee account", action="REVEAL")


def _windows(rows) -> dict:
    return {row.asset_id: row for row in schedule_windows(rows, BEAT, BEAT.end, set())}


def test_a_result_whose_phrase_contains_its_leader_waits_for_the_leader() -> None:
    windows = _windows([_row("key", 10.2, 12.0, ["PARTICIPANT", "RESULT"]),
                        _row("badge", 10.8, 12.0, ["LEADER"])])
    key, badge = windows["key"], windows["badge"]
    assert key.reveal_start == pytest.approx(badge.settle_at)            # cause first, then the result
    assert key.reveal_start <= key.phrase_start <= key.semantic_peak <= key.settle_at <= key.phrase_end
    assert "result_follows_cause" in key.evidence
    assert key.settle_at - key.reveal_start == pytest.approx(0.32, abs=0.08)  # gesture length kept


def test_a_result_stated_before_its_leader_or_on_the_same_words_is_unchanged() -> None:
    first = _windows([_row("key", 10.2, 10.6, ["RESULT"]), _row("badge", 10.8, 12.0, ["LEADER"])])
    assert first["key"].reveal_start == pytest.approx(10.2)              # narration states the outcome first
    same = _windows([_row("key", 10.8, 12.0, ["RESULT"]), _row("badge", 10.8, 12.0, ["LEADER"])])
    assert "result_follows_cause" not in same["key"].evidence


def test_a_result_with_no_read_time_left_keeps_its_own_timing() -> None:
    late = StoryBeat(id="b", scene_id="s", start=10.0, end=11.1, audio_start=10.0, audio_end=11.1,
                     narration="x", action="REVEAL")
    rows = [_row("key", 10.2, 11.1, ["RESULT"]), _row("badge", 10.8, 11.1, ["LEADER"])]
    windows = {row.asset_id: row for row in schedule_windows(rows, late, late.end, set())}
    assert windows["key"].reveal_start == pytest.approx(10.2)


# -- text never before its subject -----------------------------------------------------------
def _text(start: float, end: float) -> TextCue:
    return TextCue(id="t", beat_id="b", text="حساب موظف", semantic_type="emphasis", source_char_start=0,
                   source_char_end=9, spoken_start=start, spoken_end=end, emphasis_time=start,
                   style_id="emphasis", priority=75, anchor_asset_id="badge")


def test_text_waits_until_its_story_subject_is_recognizable() -> None:
    windows = list(schedule_windows([_row("key", 10.2, 12.0, ["PARTICIPANT", "RESULT"]),
                                     _row("badge", 10.8, 12.0, ["LEADER"])], BEAT, BEAT.end, set()))
    beat = BEAT.model_copy(update={"asset_activations": [row.to_legacy() if hasattr(row, "to_legacy") else row
                                                         for row in windows]})
    badge = next(row for row in windows if row.asset_id == "badge")
    ready = float(badge.reveal_start) + 3 / 30
    assert TextVisibilityPolicy.anchor_ready(_text(10.2, 11.0), beat) == pytest.approx(ready)
    assert TextVisibilityPolicy.display_start(_text(10.2, 11.0), beat) == pytest.approx(ready)
    assert TextVisibilityPolicy.display_start(_text(11.3, 11.6), beat) == pytest.approx(11.3)
    unanchored = _text(10.2, 11.0).model_copy(update={"anchor_asset_id": None})
    assert TextVisibilityPolicy.display_start(unanchored, beat) == pytest.approx(10.2)


def test_text_and_a_subject_revealed_on_the_same_words_enter_together() -> None:
    windows = list(schedule_windows([_row("badge", 10.8, 12.0, ["LEADER"])], BEAT, BEAT.end, set()))
    beat = BEAT.model_copy(update={"asset_activations": windows})
    assert TextVisibilityPolicy.display_start(_text(10.8, 11.4), beat) == pytest.approx(10.8)


def test_emphasis_keeps_the_exact_readable_amplitude_when_stronger_ones_clip() -> None:
    from app.motion.hero_travel import _amplitudes
    assert _amplitudes(0.045) == [0.05, 0.045]
    assert _amplitudes(0.042) == [0.05, 0.045, 0.042]
    assert _amplitudes(0.01)[-1] == 0.03 and _amplitudes(0.01)[0] == 0.05


@pytest.fixture(autouse=True)
def _pulse_machinery(monkeypatch):
    """These tests pin the post-settle pulse rules; production keeps pulses off (reference)."""
    import app.motion.hero_travel as hero_travel

    monkeypatch.setattr(hero_travel, "POST_SETTLE_PULSES", True)
