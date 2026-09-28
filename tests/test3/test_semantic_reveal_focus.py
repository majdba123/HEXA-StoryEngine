from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import statistics

from PIL import Image
import pytest

from app.canonical import (
    CanonicalAsset,
    CanonicalPackage,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
)
from app.choreography import ChoreographyDirector
from app.choreography.models import ChoreographyPlan
from app.composition import CompositionPlanner
from app.models import Transcript, TranscriptWord, VisualAsset
from app.motion import MotionPlanner
from app.motion.timing import story_activation_window
from app.render import RenderPlanner
from app.story import StoryPlanner
from app.story.windows import StoryAssetActivation
from tests.test2.motion.test_rhythm_regressions import _beat, _directive, _layout


@dataclass(frozen=True)
class Spec:
    asset: str
    event: str
    anchor: float
    role: str = "OBJECT"
    leader: bool = True


def _pipeline(root: Path, specs: list[Spec], duration: float, *, order=None, planners=None):
    """Final-Package semantics + forced alignment; production computes all windows."""
    root.mkdir(parents=True, exist_ok=True)
    image = root / "scene.png"
    Image.new("RGBA", (96, 96), "white").save(image)
    event_ids = list(dict.fromkeys(row.event for row in specs))
    tokens = {event: f"concept{i}" for i, event in enumerate(event_ids)}
    script = " ".join(tokens.values())
    spans = {}
    cursor = 0
    for event in event_ids:
        spans[event] = (cursor, cursor + len(tokens[event]))
        cursor += len(tokens[event]) + 1
    units = tuple(
        CanonicalAsset(
            unit_id=row.asset,
            asset_id=row.asset,
            scene_id="scene",
            role=row.role,
            semantic_role=row.role,
            sequence_order=event_ids.index(row.event) + 1,
            script_text=tokens[row.event],
            script_span=CanonicalScriptSpan(
                text=tokens[row.event],
                global_char_start=spans[row.event][0],
                global_char_end=spans[row.event][1],
            ),
            binding_type="EXPLICIT",
            semantic_event_id=row.event,
            visual_focus="RESULT" if row.role == "RESULT" else "PRIMARY" if row.leader else None,
        )
        for row in specs
    )
    events = tuple(
        CanonicalSemanticEvent(
            semantic_event_id=event,
            scene_id="scene",
            script_text=tokens[event],
            script_span=CanonicalScriptSpan(
                text=tokens[event],
                global_char_start=spans[event][0],
                global_char_end=spans[event][1],
            ),
            sequence_order=i + 1,
            visual_leader_asset_id=next(
                row.asset for row in specs if row.event == event and row.leader
            ),
            participant_asset_ids=tuple(row.asset for row in specs if row.event == event),
            result_asset_ids=tuple(
                row.asset for row in specs if row.event == event and row.role == "RESULT"
            ),
            depends_on_event_ids=() if i == 0 else (event_ids[i - 1],),
        )
        for i, event in enumerate(event_ids)
    )
    package = CanonicalPackage(
        root=root,
        package_id=root.name,
        script=script,
        semantic_binding_schema_name="HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
        semantic_bindings_present=True,
        scenes=(
            CanonicalScene(
                id="scene",
                image_path=image,
                order=0,
                script_char_start=0,
                script_char_end=len(script),
                units=units,
                semantic_events=events,
            ),
        ),
    )
    anchors = {event: min(row.anchor for row in specs if row.event == event) for event in event_ids}
    transcript = Transcript(
        duration=duration,
        segments=[],
        timing_source="forced_alignment",
        words=[
            TranscriptWord(
                start=anchors[event],
                end=min(duration, anchors[event] + 0.08),
                text=tokens[event],
                char_start=spans[event][0],
                char_end=spans[event][1],
            )
            for event in event_ids
        ],
    )
    by_id = {row.asset: row for row in specs}
    assets = [
        VisualAsset(
            id=asset_id,
            scene_id="scene",
            role=by_id[asset_id].role.lower(),
            image_path=image,
            extraction_method="test3-semantic-certification",
            source_bbox=(70 - i * 3, 8 + i * 3, 18, 18),
            source_canvas_width=96,
            source_canvas_height=96,
            source_area_ratio=0.30 - i * 0.007,
            can_animate_independently=True,
        )
        for i, asset_id in enumerate(order or [row.asset for row in specs])
    ]
    sp, cp, xp, mp = planners or (
        StoryPlanner(),
        ChoreographyDirector(),
        CompositionPlanner(),
        MotionPlanner(),
    )
    story = sp.plan(package, transcript, assets)
    choreography = cp.plan(package, story, assets)
    composition = xp.plan(story, assets, choreography)
    motion = mp.plan(story, composition, choreography, assets)
    render_root = root / "render-plan"
    render_root.mkdir()
    render, _ = RenderPlanner().compile(transcript, assets, story, composition, motion, render_root)
    return story, choreography, composition, motion, render


def _windows(story):
    return {
        row.asset_id: story_activation_window(row, story[0])[1]
        for row in story[0].asset_activations
        if story_activation_window(row, story[0])[1] is not None
    }


def _focus(motion):
    return {cue.asset_id: cue.params["semantic_focus"] for cue in motion}


def _certify(root: Path, specs: list[Spec], duration: float, **kwargs):
    story, choreography, composition, motion, render = _pipeline(root, specs, duration, **kwargs)
    assert render.story == story and render.composition == composition and render.motion == motion
    assert len(choreography.directives[0].event_flows) == len({row.event for row in specs})
    windows = _windows(story)
    for row in specs:
        window = windows[row.asset]
        assert window.reveal_start == pytest.approx(row.anchor)
        assert window.reveal_start <= window.semantic_peak <= window.settle_at <= duration
    # Scene lifecycle authority is represented independently from semantic focus:
    # every legitimate asset is active and no Motion program may emit an EXIT.
    assert set(story[0].active_visual_semantic_state or {}) == {row.asset for row in specs}
    assert all(segment.phase != "EXIT" for cue in motion for segment in cue.segments)
    focus = _focus(motion)
    for event in dict.fromkeys(row.event for row in specs):
        cohort = [row for row in specs if row.event == event]
        leader = next(row for row in cohort if row.leader)
        assert focus[leader.asset]["semantic_event_id"] == event
        assert focus[leader.asset]["cohort_gain"] == pytest.approx(1.0)
        assert all(
            focus[row.asset]["cohort_gain"] <= focus[leader.asset]["cohort_gain"] for row in cohort
        )
    return story, motion, windows


@pytest.mark.parametrize(
    "name,duration,pairs",
    [
        ("close-close-late", 6.0, [("A", 0.55), ("B", 0.92), ("C", 4.75)]),
        ("naturally-close", 4.0, [("A", 0.40), ("B", 0.72), ("C", 1.08)]),
        ("wide", 8.0, [("A", 0.60), ("B", 3.10), ("C", 6.70)]),
        ("late-result", 6.0, [("context", 0.40), ("action", 1.30), ("result", 5.40)]),
        ("completed-hold", 6.0, [("A", 0.40), ("B", 2.00)]),
        ("short", 0.90, [("A", 0.12), ("B", 0.31), ("C", 0.55)]),
        ("long", 11.0, [("A", 0.45), ("B", 3.80), ("C", 9.60)]),
    ],
)
def test_true_irregular_semantic_timing(tmp_path: Path, name, duration, pairs):
    specs = [
        Spec(asset, f"E{i}", anchor, "RESULT" if asset == "result" else "OBJECT")
        for i, (asset, anchor) in enumerate(pairs)
    ]
    _story, _motion, windows = _certify(tmp_path / name, specs, duration)
    actual = [windows[row.asset].reveal_start for row in specs]
    assert actual == pytest.approx([row.anchor for row in specs])
    if name == "close-close-late":
        assert actual[1] - actual[0] < 0.5 and actual[2] > 4.5
    if name == "naturally-close":
        assert actual[2] < 1.2
    if name in {"wide", "late-result", "long"}:
        assert actual[-1] > duration * 0.75


def test_same_event_cohort_and_late_event(tmp_path: Path):
    specs = [
        Spec("A", "E1", 1.0, "PRIMARY"),
        Spec("B", "E1", 1.0, "SUPPORT", False),
        Spec("C", "E2", 4.2, "RESULT"),
    ]
    _story, motion, windows = _certify(tmp_path / "cohort", specs, 6.0)
    assert windows["A"].reveal_start == windows["B"].reveal_start
    assert windows["C"].reveal_start == pytest.approx(4.2)
    assert _focus(motion)["A"]["cohort_gain"] > _focus(motion)["B"]["cohort_gain"]


def test_black_hat_like_multi_event_focus_transfer(tmp_path: Path):
    specs = [
        Spec("character", "search", 0.48, "CHARACTER", False),
        Spec("vulnerability", "search", 0.48),
        Spec("profit", "profit", 4.63, "RESULT"),
    ]
    story, motion, windows = _certify(tmp_path / "black-like", specs, 6.0)
    focus = _focus(motion)
    assert focus["vulnerability"]["cohort_gain"] > focus["character"]["cohort_gain"]
    assert focus["profit"]["semantic_event_order"] > focus["vulnerability"]["semantic_event_order"]
    assert windows["profit"].reveal_start == pytest.approx(4.63)
    assert set(story[0].active_visual_semantic_state or {}) == {row.asset for row in specs}


def test_presenter_yields_focus_to_later_icon(tmp_path: Path):
    specs = [
        Spec("huge-presenter", "intro", 0.35, "CHARACTER"),
        Spec("small-icon", "explain", 3.7, "RESULT"),
    ]
    story, motion, _ = _certify(tmp_path / "presenter", specs, 5.0)
    focus = _focus(motion)
    assert (
        focus["small-icon"]["semantic_event_order"]
        > focus["huge-presenter"]["semantic_event_order"]
    )
    assert focus["small-icon"]["role"] == "RESULT"
    assert set(story[0].active_visual_semantic_state or {}) == {"huge-presenter", "small-icon"}


def test_authored_order_beats_input_id_and_geometry(tmp_path: Path):
    specs = [
        Spec("z-last-id", "E1", 0.55),
        Spec("a-first-id", "E2", 1.75),
        Spec("m-middle-id", "E3", 4.25),
    ]
    _story, _motion, windows = _certify(
        tmp_path / "order", specs, 5.5, order=["m-middle-id", "z-last-id", "a-first-id"]
    )
    assert sorted(windows, key=lambda key: windows[key].reveal_start) == [
        "z-last-id",
        "a-first-id",
        "m-middle-id",
    ]


def test_comparison_group_has_coordinated_focus(tmp_path: Path):
    specs = [
        Spec("left", "compare", 1.0),
        Spec("right", "compare", 1.0, leader=False),
        Spec("unrelated", "later", 4.0, "SUPPORT"),
    ]
    _story, motion, _ = _certify(tmp_path / "comparison", specs, 5.0)
    focus = _focus(motion)
    assert focus["left"]["cohort_gain"] == pytest.approx(1.0)
    assert 0.0 < focus["right"]["cohort_gain"] < 1.0
    assert focus["unrelated"]["semantic_event_id"] != "compare"


def test_safe_abstention_has_no_reveal_or_focus():
    row = StoryAssetActivation(
        asset_id="abstain",
        semantic_unit_id="abstain",
        semantic_event_id="safe",
        confidence=0.0,
        source="semantic_abstention",
        policy="FALLBACK",
        activation_policy="SAFE_ABSTENTION",
    )
    assert story_activation_window(row, None) == (True, None)
    beat = _beat(
        "safe", start=0.0, end=1.0, narration="unresolved", activations=[row], primary=["abstain"]
    )
    cue = MotionPlanner().plan(
        [beat],
        [_layout(beat.id, ["abstain"])],
        ChoreographyPlan(directives=(_directive(beat.id, primary="abstain"),)),
    )[0]
    assert cue.params["semantic_focus"]["active"] is False
    assert cue.params["semantic_focus"]["cohort_gain"] == pytest.approx(0.0)
    assert cue.params["semantic_focus"]["cohort_role"] == "abstention"


def test_500_generated_cases_use_story_owned_windows(tmp_path: Path):
    rng = random.Random(0x5EAA17C)
    errors, lifecycles = [], 0
    for case in range(500):
        duration, count = rng.uniform(0.5, 12.0), rng.randint(1, 20)
        if case % 4 == 0 and count >= 3:
            anchors = [0.10 * duration, 0.16 * duration] + [
                rng.uniform(0.72, 0.92) * duration for _ in range(count - 2)
            ]
        elif case % 4 == 1:
            anchors = [rng.uniform(0.03, 0.25) * duration for _ in range(count)]
        elif case % 4 == 2:
            anchors = [rng.uniform(0.65, 0.92) * duration for _ in range(count)]
        else:
            anchors = [rng.uniform(0.03, 0.92) * duration for _ in range(count)]
        anchors.sort()
        event_count = rng.randint(1, min(10, count))
        specs = []
        for i in range(count):
            event_index = min(event_count - 1, i * event_count // count)
            first = next(
                j
                for j in range(count)
                if min(event_count - 1, j * event_count // count) == event_index
            )
            event = f"E{event_index}"
            specs.append(
                Spec(
                    f"asset-{i}",
                    event,
                    anchors[first],
                    "RESULT" if event_index == event_count - 1 else "OBJECT",
                    not any(row.event == event for row in specs),
                )
            )
        story, _motion, windows = _certify(tmp_path / f"generated-{case}", specs, duration)
        errors.extend(abs(windows[row.asset].reveal_start - row.anchor) for row in specs)
        lifecycles += len(story[0].active_visual_semantic_state or {})
    assert lifecycles >= 500
    assert max(errors) <= 0.05
    assert statistics.median(errors) <= 0.05
    assert statistics.quantiles(errors, n=100, method="inclusive")[94] <= 0.05


@pytest.mark.parametrize("scene_count", [35, 40, 35, 40])
def test_package_shaped_multi_asset_stress(tmp_path: Path, scene_count: int, request):
    """Four deterministic package-scale populations, with dense semantic scenes."""
    distribution = (1, 2, 3, 5, 8, 10, 14, 20)
    total_assets = 0
    for scene_index in range(scene_count):
        count = distribution[scene_index % len(distribution)]
        event_count = min(6, max(1, (count + 1) // 2))
        duration = 1.0 + (scene_index % 11)
        specs = []
        for asset_index in range(count):
            event_index = min(event_count - 1, asset_index * event_count // count)
            event = f"E{event_index}"
            anchor = min(duration * 0.92, 0.08 + event_index * duration * 0.82 / event_count)
            specs.append(
                Spec(
                    f"asset-{asset_index}",
                    event,
                    anchor,
                    "RESULT" if event_index == event_count - 1 else "OBJECT",
                    not any(row.event == event for row in specs),
                )
            )
        _certify(
            tmp_path / f"package-{request.node.callspec.indices['scene_count']}-{scene_index}",
            specs,
            duration,
        )
        total_assets += count
    assert total_assets > scene_count


def test_shared_planners_are_package_local(tmp_path: Path):
    planners = (StoryPlanner(), ChoreographyDirector(), CompositionPlanner(), MotionPlanner())
    a = [Spec("A", "E1", 0.4), Spec("B", "E2", 2.8)]
    b = [Spec("X", "X1", 0.7), Spec("Y", "X2", 1.1), Spec("Z", "X3", 5.2)]
    a1, b1 = (
        _pipeline(tmp_path / "a1", a, 6.0, planners=planners),
        _pipeline(tmp_path / "b1", b, 6.0, planners=planners),
    )
    b2, a2 = (
        _pipeline(tmp_path / "b2", b, 6.0, planners=planners),
        _pipeline(tmp_path / "a2", a, 6.0, planners=planners),
    )
    assert [row.model_dump(exclude={"id"}) for row in a1[0]] == [
        row.model_dump(exclude={"id"}) for row in a2[0]
    ]
    assert [row.model_dump(exclude={"beat_id"}) for row in b1[3]] == [
        row.model_dump(exclude={"beat_id"}) for row in b2[3]
    ]


def test_legacy_package_keeps_deterministic_fallback(tmp_path: Path):
    root = tmp_path / "legacy"
    root.mkdir()
    image = root / "scene.png"
    Image.new("RGBA", (32, 32), "white").save(image)
    package = CanonicalPackage(
        root=root,
        package_id="legacy",
        script="legacy",
        scenes=(
            CanonicalScene(
                id="legacy", image_path=image, order=0, script_char_start=0, script_char_end=6
            ),
        ),
    )
    transcript = Transcript(
        duration=2.0,
        segments=[],
        words=[TranscriptWord(start=0.2, end=0.6, text="legacy", char_start=0, char_end=6)],
    )
    asset = VisualAsset(
        id="legacy-asset",
        scene_id="legacy",
        role="object",
        image_path=image,
        extraction_method="legacy",
    )
    first, second = (
        StoryPlanner().plan(package, transcript, [asset]),
        StoryPlanner().plan(package, transcript, [asset]),
    )
    assert first == second and first[0].active_visual_semantic_state is None
