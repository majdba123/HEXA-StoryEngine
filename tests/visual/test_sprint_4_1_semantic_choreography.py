"""Sprint 4.1 - semantic choreography / element interaction (permanent regression gate).

Contracts, not pixels: Choreography names WHO a semantic event is about, Motion expresses
it as a bounded temporary emphasis, Composition keeps every settled coordinate. Only the
final test inspects encoded frames, to prove the emphasis is actually visible.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from app.canonical import CanonicalRelation
from app.choreography import ChoreographyDirector
from app.choreography.emphasis import select_character_emphasis
from app.composition import CompositionPlanner
from app.models import LayoutItem, MotionCue, MotionSegment, Transcript, TranscriptSegment
from app.motion import MotionPlanner
from app.motion.collision import authored_overlap_ratio, box, overlap_ratio
from app.motion.emphasis import (
    CHARACTER_EMPHASIS_MAX_DELTA,
    CHARACTER_EMPHASIS_MIN_DELTA,
    apply_character_emphasis,
)
from app.motion.reference import ReferenceMotionEnforcer
from app.reference.profile import HexaVisualProfile
from app.story import StoryPlanner
from tests.support.carrier_scene import (
    Cutout,
    Event,
    SceneSpec,
    Unit,
    build_package,
    locator_for,
)

PHRASE = tuple(f"w{index}" for index in range(10))
# Slow narration: Story windows are wide enough for comfort-bounded emphasis.
SLOW = 3.0

HERO = (60, 300, 200, 420)
PARTNER = (740, 300, 200, 420)
BYSTANDER = (400, 300, 160, 380)
DOCUMENT = (330, 80, 200, 150)
RESULT = (600, 80, 200, 150)


@dataclass
class Planned:
    built: object
    story: list
    choreography: object
    composition: list
    composition_before: list
    motion: list
    package: object = None
    transcript: object = None
    assets: list = None

    def cue(self, beat_index: int, key: str) -> MotionCue:
        beat = self.story[beat_index]
        asset = self.built.runtime_id(beat_index, key)
        return next(c for c in self.motion if c.beat_id == beat.id and c.asset_id == asset)

    def emphasis(self, beat_index: int, key: str) -> dict:
        return self.cue(beat_index, key).params.get("character_emphasis") or {}

    def layout(self, beat_index: int):
        beat = self.story[beat_index]
        return next(c for c in self.composition if c.beat_id == beat.id).items


def _slow(transcript: Transcript, factor: float) -> Transcript:
    words = [
        word.model_copy(update={"start": word.start * factor, "end": word.end * factor})
        for word in transcript.words
    ]
    segments = []
    offset = 0
    for segment in transcript.segments:
        count = len(segment.words)
        scene_words = words[offset:offset + count]
        offset += count
        segments.append(TranscriptSegment(
            start=scene_words[0].start, end=scene_words[-1].end, text=segment.text,
            char_start=segment.char_start, char_end=segment.char_end, words=scene_words,
        ))
    return Transcript(
        language=transcript.language, duration=transcript.duration * factor,
        segments=segments, words=words, timing_source=transcript.timing_source,
    )


def _scene(
    *, characters=(("hero", HERO, (2, 2)),), objects=(("doc", DOCUMENT, (4, 4)),),
    results=(("result", RESULT, (7, 7)),), leader="hero", participants=None,
    relations=(), extra_units=(), extra_cutouts=(), depends_on=(),
) -> tuple[SceneSpec, tuple]:
    units, cutouts = [], []
    for name, rect, words in characters:
        units.append(Unit(name, words, role="CHARACTER", locator=locator_for(rect)))
        cutouts.append(Cutout(name, rect, role="CHARACTER"))
    for name, rect, words in objects:
        units.append(Unit(name, words, role="supporting", locator=locator_for(rect)))
        cutouts.append(Cutout(name, rect, role="supporting"))
    for name, rect, words in results:
        units.append(Unit(name, words, role="RESULT", locator=locator_for(rect)))
        cutouts.append(Cutout(name, rect, role="RESULT"))
    for unit, cutout in extra_units:
        units.append(unit)
        cutouts.append(cutout)
    names = [unit.name for unit in units]
    if participants is None:
        participants = tuple(
            name for name in names
            if name != leader and name not in {r[0] for r in results}
            and name not in {u.name for u, _ in extra_units}
        )
    event = Event(
        "E1", leader=leader, words=(2, 7), participants=tuple(participants),
        results=tuple(r[0] for r in results),
        context=tuple(unit.name for unit, _ in extra_units), depends_on=depends_on,
    )
    return SceneSpec(PHRASE, tuple(units), tuple(cutouts), (event,)), relations


def plan(scene_specs, *, tmp_path: Path, shuffle: bool = False) -> Planned:
    specs = [spec for spec, _ in scene_specs]
    built = build_package(
        specs, namespace="S41", image_root=tmp_path / "images", write_images=True,
    )
    scenes = []
    for index, (_spec, relations) in enumerate(scene_specs):
        scene = built.package.scenes[index]
        if relations:
            rows = tuple(
                CanonicalRelation(
                    relation_id=f"{scene.id}_R{n}",
                    subject_asset_id=f"{scene.id}_{subject}",
                    relation_type=kind,
                    object_asset_id=f"{scene.id}_{target}",
                    script_text=f"{PHRASE[3]} {PHRASE[4]}",
                    script_span=scene.units[0].script_span.model_copy(update={
                        "text": f"{PHRASE[3]} {PHRASE[4]}",
                        "global_char_start": scene.script_char_start + 9,
                        "global_char_end": scene.script_char_start + 14,
                    }),
                )
                for n, (subject, kind, target) in enumerate(relations)
            )
            scene = scene.model_copy(update={"relations": rows})
        scenes.append(scene)
    package = built.package.model_copy(update={"scenes": tuple(scenes)})
    assets = list(built.assets)
    if shuffle:
        assets = list(reversed(assets))
    transcript = _slow(built.transcript, SLOW)
    story = StoryPlanner().plan(package, transcript, assets)
    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)
    before = json.loads(json.dumps([c.model_dump(mode="json") for c in composition]))
    motion = ReferenceMotionEnforcer().enforce(
        MotionPlanner().plan(story, composition, choreography, assets)
    )
    return Planned(built, story, choreography, composition, before, motion,
                   package, transcript, assets)


@pytest.fixture(scope="module")
def two_characters(tmp_path_factory) -> Planned:
    spec = _scene(
        characters=(("hero", HERO, (2, 2)), ("partner", PARTNER, (4, 4))),
        objects=(("doc", DOCUMENT, (5, 5)),),
        participants=("partner", "doc"),
    )
    return plan([spec], tmp_path=tmp_path_factory.mktemp("two_characters"))


@pytest.fixture(scope="module")
def with_bystander(tmp_path_factory) -> Planned:
    bystander = (
        Unit("bystander", (3, 3), role="CHARACTER", locator=locator_for(BYSTANDER)),
        Cutout("bystander", BYSTANDER, role="CHARACTER"),
    )
    spec = _scene(
        characters=(("hero", HERO, (2, 2)),), extra_units=((bystander[0], bystander[1]),),
    )
    return plan([spec], tmp_path=tmp_path_factory.mktemp("bystander"))


@pytest.fixture(scope="module")
def no_relations(tmp_path_factory) -> Planned:
    return plan([_scene()], tmp_path=tmp_path_factory.mktemp("no_relations"))


@pytest.fixture(scope="module")
def related(tmp_path_factory) -> Planned:
    spec, relations = _scene(relations=(("hero", "ATTACKS", "doc"),))
    return plan([(spec, relations)], tmp_path=tmp_path_factory.mktemp("related"))


def _segments(cue: MotionCue, phase: str):
    return [segment for segment in cue.segments if segment.phase == phase]


# 1 + 2. Primary and secondary participating characters are emphasized --------------
def test_primary_character_becomes_visual_leader_when_focused(two_characters) -> None:
    audit = two_characters.emphasis(0, "hero")
    assert audit.get("applied") is True, audit
    assert 1.0 + CHARACTER_EMPHASIS_MIN_DELTA <= audit["peak_scale"] <= (
        1.0 + CHARACTER_EMPHASIS_MAX_DELTA + 1e-9
    )
    assert _segments(two_characters.cue(0, "hero"), "ESTABLISH")


def test_secondary_participating_character_is_emphasized(two_characters) -> None:
    directive = two_characters.choreography.directives[0]
    assert set(directive.emphasis_asset_ids) == {
        two_characters.built.runtime_id(0, "hero"),
        two_characters.built.runtime_id(0, "partner"),
    }
    for asset_id in directive.emphasis_asset_ids:
        cue = next(c for c in two_characters.motion if c.asset_id == asset_id)
        assert cue.params["character_emphasis"].get("applied") is True


# 3. Unrelated character is never emphasized ------------------------------------------
def test_unrelated_character_is_never_emphasized(with_bystander) -> None:
    directive = with_bystander.choreography.directives[0]
    bystander = with_bystander.built.runtime_id(0, "bystander")
    assert bystander not in directive.emphasis_asset_ids
    cue = next(c for c in with_bystander.motion if c.asset_id == bystander)
    assert not (cue.params.get("character_emphasis") or {}).get("applied")
    assert not _segments(cue, "ESTABLISH")


# 4. Non-character icons never receive character high-scale behavior --------------------
def test_non_character_icons_never_receive_character_emphasis(two_characters) -> None:
    directive = two_characters.choreography.directives[0]
    characters = set(directive.emphasis_asset_ids)
    for cue in two_characters.motion:
        if cue.asset_id in characters:
            continue
        assert "character_emphasis" not in cue.params
        assert not _segments(cue, "ESTABLISH")
        assert all(
            abs(float(frame["scale"]) - 1.0) <= 0.095 + 1e-9
            for segment in cue.segments for frame in segment.program.get("keyframes", [])
        )


# 5 + 14 + 17. Relations only with authored evidence; no relations stays valid ------------
def test_no_relations_scene_is_valid_and_invents_no_interaction(no_relations) -> None:
    directive = no_relations.choreography.directives[0]
    assert not directive.interactions or not any(r.executable for r in directive.interactions)
    for cue in no_relations.motion:
        assert not [s for s in cue.segments if s.phase in {"INTERACT", "REACT"}]


def test_relation_becomes_visible_only_with_authored_evidence(related) -> None:
    directive = related.choreography.directives[0]
    assert any(row.executable for row in directive.interactions)
    phases = {
        segment.phase for cue in related.motion for segment in cue.segments
    }
    assert phases & {"INTERACT", "REACT"}


# 6 + 7 + 9. Cause -> action -> result order, RESULT after its trigger, progressive reveal
def test_progressive_reveal_preserves_cause_action_result_order(related) -> None:
    beat = related.story[0]
    windows = {row.asset_id: row for row in beat.asset_activations}
    reveals = [
        float(row.spoken_start) for row in windows.values() if row.spoken_start is not None
    ]
    assert len(set(round(value, 3) for value in reveals)) >= 3  # not all at once
    hero = windows[related.built.runtime_id(0, "hero")]
    result = windows[related.built.runtime_id(0, "result")]
    assert hero.spoken_start < result.spoken_start


def test_result_never_appears_before_its_semantic_trigger(related) -> None:
    beat = related.story[0]
    result_id = related.built.runtime_id(0, "result")
    activation = next(row for row in beat.asset_activations if row.asset_id == result_id)
    cue = related.cue(0, "result")
    assert cue.start >= float(activation.spoken_start) - 1e-6
    assert all(float(segment.start) >= float(activation.spoken_start) - 1e-6
               for segment in cue.segments)


# 8. Dependency ordering ---------------------------------------------------------------------
def test_dependent_event_never_reveals_before_its_dependency(tmp_path) -> None:
    spec = SceneSpec(
        PHRASE,
        (
            Unit("cause", (1, 1), role="CHARACTER", locator=locator_for(HERO)),
            Unit("effect", (6, 6), role="RESULT", locator=locator_for(RESULT)),
        ),
        (Cutout("cause", HERO, role="CHARACTER"), Cutout("effect", RESULT, role="RESULT")),
        (
            Event("E1", leader="cause", words=(1, 1)),
            Event("E2", leader="effect", words=(6, 6), depends_on=("E1",)),
        ),
    )
    planned = plan([(spec, ())], tmp_path=tmp_path)
    beat = planned.story[0]
    by_event = {}
    for row in beat.asset_activations:
        by_event.setdefault(row.semantic_event_id, []).append(float(row.reveal_start))
    assert min(by_event[f"{planned.built.scene_ids[0]}_E2"]) >= max(
        by_event[f"{planned.built.scene_ids[0]}_E1"]
    ) - 1e-6


# 10 + 11. Settled geometry is Composition's; emphasis returns to it -------------------------
def test_motion_never_changes_composition_and_every_program_settles_on_it(two_characters) -> None:
    assert [
        json.loads(json.dumps(c.model_dump(mode="json"))) for c in two_characters.composition
    ] == two_characters.composition_before
    for cue in two_characters.motion:
        programs = [cue.params.get("program") or {}] + [s.program for s in cue.segments]
        for program in programs:
            frames = program.get("keyframes") or []
            if not frames:
                continue
            last = frames[-1]
            assert (last["dx"], last["dy"], last["scale"]) == (0.0, 0.0, 1.0)
            settle = float(program.get("settle_progress", 1.0))
            at_settle = next(f for f in frames if abs(f["progress"] - settle) < 1e-9)
            assert (at_settle["dx"], at_settle["dy"], at_settle["scale"]) == (0.0, 0.0, 1.0)


def test_emphasis_segment_starts_and_ends_on_composition_geometry(two_characters) -> None:
    cue = two_characters.cue(0, "hero")
    segment = _segments(cue, "ESTABLISH")[0]
    frames = segment.program["keyframes"]
    assert frames[0]["scale"] == frames[-1]["scale"] == 1.0
    assert all(f["dx"] == f["dy"] == 0.0 for f in frames)
    assert max(f["scale"] for f in frames) > 1.0


def test_emphasis_ends_before_the_next_semantic_reveal(two_characters) -> None:
    beat = two_characters.story[0]
    cue = two_characters.cue(0, "hero")
    segment = _segments(cue, "ESTABLISH")[0]
    own = float(segment.start)
    later = [
        float(row.reveal_start) for row in beat.asset_activations
        if row.asset_id != cue.asset_id and row.reveal_start is not None
        and float(row.reveal_start) > float(cue.start) + 1e-6
    ]
    assert segment.start >= cue.end - 1e-9 and own < float(segment.end)
    assert float(segment.end) <= min(later + [float(beat.end)]) + 1e-6


# 12 + 13. No collision introduced, inside the safe frame ----------------------------------------
def test_emphasis_peak_adds_no_collision_and_stays_in_safe_frame(two_characters) -> None:
    profile = HexaVisualProfile.production()
    items = two_characters.layout(0)
    for asset_id in two_characters.choreography.directives[0].emphasis_asset_ids:
        item = next(row for row in items if row.asset_id == asset_id)
        peak = next(
            c for c in two_characters.motion if c.asset_id == asset_id
        ).params["character_emphasis"]["peak_scale"]
        grown = box(item, (0.0, 0.0, peak))
        assert grown[0] >= profile.safe_left and grown[2] <= profile.safe_right
        assert grown[1] >= profile.safe_top and grown[3] <= profile.safe_bottom
        for other in items:
            if other.asset_id == asset_id:
                continue
            assert overlap_ratio(grown, box(other, (0.0, 0.0, 1.0))) <= (
                authored_overlap_ratio(item, other) + 0.005 + 1e-9
            )


def _layout_item(**values) -> LayoutItem:
    base = {"asset_id": "c", "x": 0.5, "y": 0.5, "width": 0.20, "height": 0.40}
    return LayoutItem(**{**base, **values})


def _cue(start=1.0, end=1.2) -> MotionCue:
    program = {
        "name": "x", "settle_progress": 1.0,
        "keyframes": [
            {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
        ],
    }
    return MotionCue(
        beat_id="b", asset_id="c", kind="program_v3", start=start, end=end,
        params={"program": program},
        segments=[MotionSegment(phase="ENTRY", start=start, end=end, program=program)],
    )


def test_emphasis_abstains_at_the_frame_boundary() -> None:
    edge = _layout_item(x=0.10)  # left edge already at the safe margin
    result = apply_character_emphasis(
        _cue(), item=edge, layout_items=[edge], bound=2.0, semantic_event_id="E",
    )
    audit = result.params["character_emphasis"]
    assert (audit["applied"], audit["reason"]) == (False, "no_safe_headroom")
    assert not [s for s in result.segments if s.phase == "ESTABLISH"]


def test_emphasis_abstains_when_a_neighbour_would_be_overlapped() -> None:
    item = _layout_item()
    neighbour = _layout_item(asset_id="n", x=0.5 + 0.2 + 0.001)  # gap smaller than growth
    result = apply_character_emphasis(
        _cue(), item=item, layout_items=[item, neighbour], bound=2.0, semantic_event_id="E",
    )
    assert result.params["character_emphasis"]["applied"] is False


def test_dense_scene_does_not_become_crowded(tmp_path) -> None:
    crowd = tuple(
        (Unit(f"c{i}", (3 + i % 3, 3 + i % 3), role="CHARACTER",
              locator=locator_for((60 + i * 150, 300, 140, 380))),
         Cutout(f"c{i}", (60 + i * 150, 300, 140, 380), role="CHARACTER"))
        for i in range(6)
    )
    spec = _scene(characters=(), objects=(), results=(), leader="c0",
                  extra_units=crowd[1:], participants=())
    planned = plan([spec], tmp_path=tmp_path)
    directive = planned.choreography.directives[0]
    assert len(directive.emphasis_asset_ids) <= 2
    applied = [
        c for c in planned.motion if (c.params.get("character_emphasis") or {}).get("applied")
    ]
    assert len(applied) <= 2


def test_emphasis_abstains_without_a_free_window() -> None:
    item = _layout_item()
    result = apply_character_emphasis(
        _cue(1.0, 1.2), item=item, layout_items=[item], bound=1.25, semantic_event_id="E",
    )
    audit = result.params["character_emphasis"]
    assert (audit["applied"], audit["reason"]) == (False, "no_free_window")


def test_emphasis_never_exceeds_the_bounded_delta() -> None:
    item = _layout_item(width=0.10, height=0.10)
    result = apply_character_emphasis(
        _cue(), item=item, layout_items=[item], bound=5.0, semantic_event_id="E",
    )
    assert result.params["character_emphasis"]["peak_scale"] <= 1.0 + CHARACTER_EMPHASIS_MAX_DELTA + 1e-9


# 15 + 16. Determinism and input-order independence ------------------------------------------
def test_planning_is_deterministic_and_independent_of_asset_order(tmp_path) -> None:
    spec = _scene(
        characters=(("hero", HERO, (2, 2)), ("partner", PARTNER, (4, 4))),
        objects=(("doc", DOCUMENT, (5, 5)),), participants=("partner", "doc"),
    )
    first = plan([spec], tmp_path=tmp_path / "a")
    second = plan([spec], tmp_path=tmp_path / "b")
    shuffled = plan([spec], tmp_path=tmp_path / "c", shuffle=True)

    def snapshot(planned: Planned):
        return sorted(
            json.dumps(
                {**c.model_dump(mode="json")}, sort_keys=True,
            )
            for c in planned.motion
        )

    assert snapshot(first) == snapshot(second)
    assert [d.emphasis_asset_ids for d in first.choreography.directives] == [
        d.emphasis_asset_ids for d in shuffled.choreography.directives
    ]
    assert {c.asset_id: c.params.get("character_emphasis") for c in first.motion} == {
        c.asset_id: c.params.get("character_emphasis") for c in shuffled.motion
    }


# 18. Sparse scene remains sparse ----------------------------------------------------------------
def test_sparse_scene_remains_sparse(tmp_path) -> None:
    spec = _scene(characters=(("hero", HERO, (2, 2)),), objects=(), results=(),
                  participants=())
    planned = plan([spec], tmp_path=tmp_path)
    assert len(planned.motion) == 1
    assert len(planned.composition[0].items) == 1


# 20. Fail closed without choreography evidence ----------------------------------------------------
def test_no_event_flow_evidence_selects_no_character(two_characters) -> None:
    beat = two_characters.story[0]
    assert select_character_emphasis(beat, two_characters.built.assets, ()) == ()


def test_result_assets_are_never_emphasized(tmp_path) -> None:
    result_character = (
        Unit("victim", (7, 7), role="CHARACTER", locator=locator_for(PARTNER)),
        Cutout("victim", PARTNER, role="CHARACTER"),
    )
    spec = SceneSpec(
        PHRASE,
        (
            Unit("hero", (2, 2), role="CHARACTER", locator=locator_for(HERO)),
            result_character[0],
        ),
        (Cutout("hero", HERO, role="CHARACTER"), result_character[1]),
        (Event("E1", leader="hero", words=(2, 7), results=("victim",)),),
    )
    planned = plan([(spec, ())], tmp_path=tmp_path)
    victim = planned.built.runtime_id(0, "victim")
    assert victim not in planned.choreography.directives[0].emphasis_asset_ids


# Visible-behavior evidence: the emphasis is actually rendered ----------------------------------
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_emphasis_is_visible_in_encoded_frames_and_returns_to_rest(tmp_path) -> None:
    from app.render import RenderPlanner
    from app.render.renderer import FFmpegRenderer
    from app.text import TextPlanner

    spec = _scene(characters=(("hero", HERO, (2, 2)),), objects=(), results=(),
                  participants=())
    built = build_package(
        [spec[0]], namespace="S41V", image_root=tmp_path / "images", write_images=True,
    )
    transcript = _slow(built.transcript, SLOW)
    story = StoryPlanner().plan(built.package, transcript, built.assets)
    choreography = ChoreographyDirector().plan(built.package, story, built.assets)
    composition = CompositionPlanner().plan(story, built.assets, choreography)
    motion = ReferenceMotionEnforcer().enforce(
        MotionPlanner().plan(story, composition, choreography, built.assets)
    )
    cue = motion[0]
    emphasis = cue.params["character_emphasis"]
    assert emphasis["applied"] is True
    text = TextPlanner().plan(
        transcript=transcript, story=story, assets=built.assets,
        package=built.package, choreography=choreography,
    )
    workspace = tmp_path / "render"
    workspace.mkdir()
    plan_, _ = RenderPlanner().compile(
        transcript, built.assets, story, composition, motion, workspace, text=text,
    )
    video = FFmpegRenderer("ffmpeg").render(plan_, tmp_path / "video.mp4")

    def ink(at: float) -> int:
        import subprocess

        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=480:270,format=gray", "-f", "rawvideo", "pipe:1"],
            check=True, capture_output=True,
        ).stdout
        frame = np.frombuffer(raw, dtype=np.uint8)
        return int((frame < 235).sum())

    segment = next(s for s in cue.segments if s.phase == "ESTABLISH")
    peak_time = segment.start + (segment.end - segment.start) * 0.45
    rest_before = ink(cue.end + 0.03)
    at_peak = ink(peak_time)
    rest_after = ink(min(float(plan_.duration) - 0.1, segment.end + 0.25))
    assert at_peak > rest_before * 1.04
    assert abs(rest_after - rest_before) <= rest_before * 0.01
    assert json.dumps(emphasis)  # audit stays machine-readable


# Visible cause/action/result: authored directional relations are drawn --------------------------
def _render(planned: Planned, tmp_path: Path) -> tuple[Path, object]:
    from app.render import RenderPlanner
    from app.render.renderer import FFmpegRenderer
    from app.text import TextPlanner

    text = TextPlanner().plan(
        transcript=planned.transcript, story=planned.story, assets=planned.assets,
        package=planned.package, choreography=planned.choreography,
    )
    workspace = tmp_path / "render"
    workspace.mkdir()
    plan_, _ = RenderPlanner().compile(
        planned.transcript, planned.assets, planned.story, planned.composition,
        planned.motion, workspace, text=text,
    )
    return FFmpegRenderer("ffmpeg").render(plan_, tmp_path / "video.mp4"), plan_


def _frame(video: Path, at: float) -> np.ndarray:
    import subprocess

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", "scale=960:540,format=rgb24", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(540, 960, 3)


def _connection_segments(planned: Planned):
    return [
        (cue, segment) for cue in planned.motion for segment in cue.segments
        if segment.connection
    ]


def test_directional_relation_marks_a_connection_and_descriptive_one_does_not(tmp_path) -> None:
    directional = plan(
        [_scene(relations=(("hero", "ATTACKS", "doc"),))], tmp_path=tmp_path / "a")
    descriptive = plan(
        [_scene(relations=(("hero", "SPECIFIES", "doc"),))], tmp_path=tmp_path / "b")
    unrelated = plan([_scene()], tmp_path=tmp_path / "c")
    marked = _connection_segments(directional)
    assert len(marked) == 1
    segment = marked[0][1]
    assert segment.phase == "INTERACT" and segment.relationship == "ATTACKS"
    assert not _connection_segments(descriptive)
    assert not _connection_segments(unrelated)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_authored_relation_is_visibly_drawn_between_its_two_elements(tmp_path) -> None:
    planned = plan([_scene(relations=(("hero", "ATTACKS", "doc"),))], tmp_path=tmp_path)
    video, plan_ = _render(planned, tmp_path)
    cue, segment = _connection_segments(planned)[0]
    source = next(i for i in planned.composition[0].items if i.asset_id == segment.source_asset_id)
    target = next(i for i in planned.composition[0].items if i.asset_id == segment.target_asset_id)
    midpoint = ((source.x + target.x) / 2, (source.y + target.y) / 2)
    px, py = int(midpoint[0] * 960), int(midpoint[1] * 540)

    def dark_near(frame: np.ndarray) -> int:
        patch = frame[max(0, py - 12): py + 12, max(0, px - 12): px + 12].astype(int)
        return int(((patch.sum(axis=2)) < 200).sum())

    beat = planned.story[0]
    by_asset = {c.asset_id: c for c in planned.motion}
    appears = max(
        float(segment.start), float(by_asset[segment.source_asset_id].start),
        float(by_asset[segment.target_asset_id].start),
    )
    before = _frame(video, max(0.05, appears - 0.1))
    after = _frame(video, min(float(beat.end) - 0.1, appears + 0.6))
    assert dark_near(after) > dark_near(before) + 20
    rect = (min(source.x, target.x), min(source.y, target.y))
    assert rect  # geometry came from Composition boxes only


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_no_connection_is_drawn_without_authored_relation(tmp_path) -> None:
    planned = plan([_scene()], tmp_path=tmp_path)
    video, _plan = _render(planned, tmp_path)
    beat = planned.story[0]
    items = {i.asset_id: i for i in planned.composition[0].items}
    hero = items[planned.built.runtime_id(0, "hero")]
    doc = items[planned.built.runtime_id(0, "doc")]
    frame = _frame(video, float(beat.end) - 0.1)
    px, py = int((hero.x + doc.x) / 2 * 960), int((hero.y + doc.y) / 2 * 540)
    patch = frame[py - 12: py + 12, px - 12: px + 12].astype(int)
    assert int((patch.sum(axis=2) < 200).sum()) == 0


def test_connection_abstains_when_it_would_cross_a_third_element() -> None:
    from app.render.connection import _endpoints

    source, target = (0.0, 100.0, 100.0, 200.0), (500.0, 100.0, 600.0, 200.0)
    blocker = (250.0, 80.0, 350.0, 220.0)
    assert _endpoints(source, target, []) is not None
    assert _endpoints(source, target, [blocker]) is None
    assert _endpoints(source, (90.0, 100.0, 190.0, 200.0), []) is None  # too close


def test_static_reveal_is_replaced_by_an_emphasis_that_starts_with_the_reveal() -> None:
    item = _layout_item()
    cue = _cue(1.0, 1.2)
    result = apply_character_emphasis(
        cue, item=item, layout_items=[item], bound=1.8, semantic_event_id="E",
    )
    audit = result.params["character_emphasis"]
    assert audit["applied"] is True and audit["start"] == 1.0
    phases = [(segment.phase, segment.start) for segment in result.segments]
    assert phases == [("ESTABLISH", 1.0)]  # the static ENTRY is replaced, never doubled


def test_moving_entry_is_preserved_and_emphasis_waits_for_it_to_settle() -> None:
    item = _layout_item()
    cue = _cue(1.0, 1.2)
    moving = {**cue.params["program"], "keyframes": [
        {"progress": 0.0, "dx": 0.03, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
    ]}
    cue = cue.model_copy(update={
        "params": {"program": moving},
        "segments": [MotionSegment(phase="ENTRY", start=1.0, end=1.2, program=moving)],
    })
    result = apply_character_emphasis(
        cue, item=item, layout_items=[item], bound=2.0, semantic_event_id="E",
    )
    assert [segment.phase for segment in result.segments] == ["ENTRY", "ESTABLISH"]
    assert result.params["character_emphasis"]["start"] == 1.2


# Supporting-element de-emphasis for characters that cannot scale ---------------------------
from app.motion.emphasis import (  # noqa: E402
    SUPPORT_DIP_MAX_DELTA,
    SUPPORT_DIP_MAX_ELEMENTS,
    deemphasize_supporting,
)


def _carry(cue, *, item):
    return MotionSegment(
        phase="ENTRY", start=float(cue.start), end=float(cue.end),
        program=dict(cue.params["program"]),
    )


def _focus_cue(window=(2.0, 2.6), applied=False, reason="no_safe_headroom") -> MotionCue:
    cue = _cue(1.8, 2.0).model_copy(update={"asset_id": "hero"})
    audit = {"applied": applied, "reason": reason}
    if window:
        audit["window"] = list(window)
    return cue.model_copy(update={"params": {**cue.params, "character_emphasis": audit}})


def _support(asset_id: str, start=0.5, end=0.7) -> MotionCue:
    return _cue(start, end).model_copy(update={"asset_id": asset_id})


def _items(*ids: str) -> list[LayoutItem]:
    return [_layout_item(asset_id="hero", x=0.2, width=0.2, height=0.9)] + [
        _layout_item(asset_id=name, x=0.45 + 0.1 * index, y=0.5, width=0.18, height=0.3)
        for index, name in enumerate(ids)
    ]


def _recede(cues, items, protected=frozenset({"hero"})):
    return deemphasize_supporting(
        cues, focus_asset_id="hero", layout_items=items, protected_asset_ids=set(protected),
        semantic_event_id="E", carry_entry=_carry,
    )


def test_settled_supporting_elements_recede_and_return_to_composition_geometry() -> None:
    out = {c.asset_id: c for c in _recede([_focus_cue(), _support("a"), _support("b")],
                                          _items("a", "b"))}
    for key in ("a", "b"):
        segment = next(s for s in out[key].segments if s.semantic_action == "DEEMPHASIZE")
        scales = [f["scale"] for f in segment.program["keyframes"]]
        assert scales[0] == scales[-1] == 1.0
        assert 1.0 - SUPPORT_DIP_MAX_DELTA - 1e-9 <= min(scales) <= 0.96 + 1e-9
        assert all(f["dx"] == f["dy"] == 0.0 for f in segment.program["keyframes"])
        assert (segment.start, segment.end) == (2.0, 2.6)
    assert out["hero"].params["supporting_deemphasis"]["assets"] == ["a", "b"]


def test_characters_and_the_focus_are_never_receded() -> None:
    cues = [_focus_cue(), _support("partner"), _support("a")]
    out = {c.asset_id: c for c in _recede(cues, _items("partner", "a"),
                                          protected={"hero", "partner"})}
    assert not [s for s in out["partner"].segments if s.semantic_action == "DEEMPHASIZE"]
    assert not [s for s in out["hero"].segments if s.semantic_action == "DEEMPHASIZE"]
    assert [s for s in out["a"].segments if s.semantic_action == "DEEMPHASIZE"]


def test_element_expressing_its_own_semantic_phase_keeps_its_geometry() -> None:
    busy = _support("a")
    busy = busy.model_copy(update={"segments": [
        *busy.segments,
        MotionSegment(phase="INTERACT", start=2.1, end=2.4, program={"keyframes": []}),
    ]})
    out = {c.asset_id: c for c in _recede([_focus_cue(), busy, _support("b")], _items("a", "b"))}
    assert not [s for s in out["a"].segments if s.semantic_action == "DEEMPHASIZE"]
    assert [s for s in out["b"].segments if s.semantic_action == "DEEMPHASIZE"]


def test_element_still_arriving_or_not_yet_visible_is_left_alone() -> None:
    moving = {"name": "x", "settle_progress": 1.0, "keyframes": [
        {"progress": 0.0, "dx": 0.03, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
    ]}
    arriving = _support("a", 1.9, 2.3)
    arriving = arriving.model_copy(update={
        "params": {"program": moving},
        "segments": [MotionSegment(phase="ENTRY", start=1.9, end=2.3, program=moving)],
    })
    later = _support("b", 2.2, 2.4)
    out = _recede([_focus_cue(), arriving, later], _items("a", "b"))
    assert not any(s.semantic_action == "DEEMPHASIZE" for c in out for s in c.segments)
    assert out[0].params["supporting_deemphasis"] == {
        "applied": False, "reason": "no_eligible_support"}


def test_crowded_scene_abstains_instead_of_moving_many_elements() -> None:
    names = [f"s{i}" for i in range(SUPPORT_DIP_MAX_ELEMENTS + 1)]
    out = _recede([_focus_cue(), *[_support(n) for n in names]], _items(*names))
    assert not any(s.semantic_action == "DEEMPHASIZE" for c in out for s in c.segments)
    assert out[0].params["supporting_deemphasis"]["reason"] == "too_many_supporting"


def test_no_recede_when_the_character_itself_scaled_or_has_no_window() -> None:
    for cue in (_focus_cue(applied=True, reason="x"), _focus_cue(window=None)):
        out = _recede([cue, _support("a")], _items("a"))
        assert not any(s.semantic_action == "DEEMPHASIZE" for c in out for s in c.segments)


def test_tiny_element_that_cannot_clear_the_readability_floor_is_not_receded() -> None:
    items = _items("a")
    items[1] = items[1].model_copy(update={"width": 0.03, "height": 0.05})
    out = _recede([_focus_cue(), _support("a")], items)
    assert not any(s.semantic_action == "DEEMPHASIZE" for c in out for s in c.segments)


def test_full_height_character_keeps_geometry_while_supporting_element_recedes(tmp_path) -> None:
    tall = (60, 20, 200, 960)
    doc = (400, 300, 300, 300)
    spec = _scene(
        characters=(("hero", tall, (5, 5)),), objects=(("doc", doc, (2, 2)),),
        results=(), participants=("doc",),
    )
    planned = plan([spec], tmp_path=tmp_path)
    hero = planned.cue(0, "hero")
    assert hero.params["character_emphasis"]["reason"] == "no_safe_headroom"
    assert not [s for s in hero.segments if s.phase == "ESTABLISH"]
    support = planned.cue(0, "doc")
    dip = [s for s in support.segments if s.semantic_action == "DEEMPHASIZE"]
    assert len(dip) == 1
    assert dip[0].start >= float(hero.start) - 1e-6
    assert planned.composition_before == json.loads(json.dumps(
        [c.model_dump(mode="json") for c in planned.composition]))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_supporting_element_visibly_recedes_and_returns_exactly(tmp_path) -> None:
    tall, doc = (60, 20, 200, 960), (400, 300, 300, 300)
    spec = _scene(characters=(("hero", tall, (5, 5)),), objects=(("doc", doc, (2, 2)),),
                  results=(), participants=("doc",))
    planned = plan([spec], tmp_path=tmp_path)
    video, _plan = _render(planned, tmp_path)
    support = planned.cue(0, "doc")
    segment = next(s for s in support.segments if s.semantic_action == "DEEMPHASIZE")
    item = next(i for i in planned.composition[0].items if i.asset_id == support.asset_id)

    def ink(at: float) -> int:
        frame = _frame(video, at).astype(int)
        left, right = int((item.x - item.width / 2 - 0.03) * 960), int((item.x + item.width / 2 + 0.03) * 960)
        top, bottom = int((item.y - item.height / 2 - 0.03) * 540), int((item.y + item.height / 2 + 0.03) * 540)
        region = frame[max(0, top):bottom, max(0, left):right]
        return int((region.sum(axis=2) < 700).sum())

    rest = ink(float(segment.start) - 0.05)
    peak = ink(float(segment.start) + 0.45 * (float(segment.end) - float(segment.start)))
    after = ink(float(segment.end) + 0.15)
    assert peak < rest * 0.97
    assert abs(after - rest) <= rest * 0.002  # codec noise only: geometry is exactly restored
