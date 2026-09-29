from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from pathlib import Path
import random
import statistics

from PIL import Image
import pytest

from app.canonical import (
    CanonicalAsset,
    CanonicalPackage,
    CanonicalRelation,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
    CanonicalSemanticGroup,
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
    phrase: str | None = None
    phrase_end: float | None = None
    sequence: int | None = None
    group: str | None = None
    group_policy: str = "SEQUENTIAL_WITHIN_PHRASE"


def _pipeline(
    root: Path,
    specs: list[Spec],
    duration: float,
    *,
    order=None,
    planners=None,
    extra_asset_ids: list[str] | None = None,
    pass2_children: list[tuple[str, str]] | None = None,
    relations: tuple[CanonicalRelation, ...] = (),
    asset_boxes: dict[str, tuple[int, int, int, int]] | None = None,
    asset_images: dict[str, Path] | None = None,
):
    """Final-Package semantics + forced alignment; production computes all windows."""
    root.mkdir(parents=True, exist_ok=True)
    image = root / "scene.png"
    Image.new("RGBA", (96, 96), "white").save(image)
    event_ids = list(dict.fromkeys(row.event for row in specs))
    # One authored phrase per distinct reveal instant. Assets at the same event/anchor
    # intentionally share a script span and are a legal cohort; different anchors in
    # the same event retain different asset-level spans.
    phrase_anchors = {
        phrase: min(row.anchor for row in specs if row.phrase == phrase)
        for phrase in dict.fromkeys(row.phrase for row in specs if row.phrase)
    }

    def reveal_key(row: Spec) -> tuple[str, float]:
        if row.phrase is not None:
            return row.phrase, phrase_anchors[row.phrase]
        return f"{row.event}@{row.anchor}", row.anchor

    reveal_keys = list(dict.fromkeys(reveal_key(row) for row in specs))
    event_reveal_keys = {
        event: list(
            dict.fromkeys(
                reveal_key(row)
                for row in specs
                if row.event == event
            )
        )
        for event in event_ids
    }
    tokens = {key: f"concept{i}" for i, key in enumerate(reveal_keys)}
    script = " ".join(tokens.values())
    spans = {}
    cursor = 0
    for key in reveal_keys:
        spans[key] = (cursor, cursor + len(tokens[key]))
        cursor += len(tokens[key]) + 1
    units = tuple(
        CanonicalAsset(
            unit_id=row.asset,
            asset_id=row.asset,
            scene_id="scene",
            role=row.role,
            semantic_role=row.role,
            sequence_order=(
                row.sequence
                if row.sequence is not None
                else reveal_keys.index(reveal_key(row)) + 1
            ),
            semantic_group_id=row.group,
            script_text=tokens[reveal_key(row)],
            script_span=CanonicalScriptSpan(
                text=tokens[reveal_key(row)],
                global_char_start=spans[reveal_key(row)][0],
                global_char_end=spans[reveal_key(row)][1],
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
            script_text=" ".join(
                tokens[key] for key in event_reveal_keys[event]
            ),
            script_span=CanonicalScriptSpan(
                text=" ".join(tokens[key] for key in event_reveal_keys[event]),
                global_char_start=min(spans[key][0] for key in event_reveal_keys[event]),
                global_char_end=max(spans[key][1] for key in event_reveal_keys[event]),
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
                relations=relations,
                semantic_groups=tuple(
                    CanonicalSemanticGroup(
                        semantic_group_id=group,
                        animation_policy=next(row.group_policy for row in specs if row.group == group),
                        asset_ids=tuple(row.asset for row in specs if row.group == group),
                    )
                    for group in dict.fromkeys(row.group for row in specs if row.group)
                ),
            ),
        ),
    )
    transcript = Transcript(
        duration=duration,
        segments=[],
        timing_source="forced_alignment",
        words=[
            TranscriptWord(
                start=key[1],
                end=min(
                    duration,
                    max(
                        key[1] + 0.08,
                        *(row.phrase_end or 0.0 for row in specs if reveal_key(row) == key),
                    ),
                ),
                text=tokens[key],
                char_start=spans[key][0],
                char_end=spans[key][1],
            )
            for key in reveal_keys
        ],
    )
    by_id = {row.asset: row for row in specs}
    assets = [
        VisualAsset(
            id=asset_id,
            scene_id="scene",
            role=by_id[asset_id].role.lower(),
            image_path=(asset_images or {}).get(asset_id, image),
            extraction_method="test3-semantic-certification",
            source_bbox=(asset_boxes or {}).get(asset_id, (70 - i * 3, 8 + i * 3, 18, 18)),
            source_canvas_width=96,
            source_canvas_height=96,
            source_area_ratio=0.30 - i * 0.007,
            can_animate_independently=True,
        )
        for i, asset_id in enumerate(order or [row.asset for row in specs])
    ]
    for i, asset_id in enumerate(extra_asset_ids or []):
        assets.append(VisualAsset(
            id=asset_id,
            scene_id="scene",
            role="supporting",
            image_path=image,
            extraction_method="test3-unbound-cutout",
            source_bbox=(8 + i * 4, 70 - i * 3, 12, 12),
            source_canvas_width=96,
            source_canvas_height=96,
            source_area_ratio=max(0.01, 0.08 - i * 0.006),
            can_animate_independently=True,
        ))
    if pass2_children:
        parent_ids = {parent_id for parent_id, _child_id in pass2_children}
        assets = [
            asset.model_copy(update={
                "asset_family_id": asset.id,
                "render_as_family_canvas": True,
                "extraction_method": f"{asset.extraction_method}+pass2_main",
            })
            if asset.id in parent_ids else asset
            for asset in assets
        ]
        runtime_by_id = {asset.id: asset for asset in assets}
        for parent_id, child_id in pass2_children:
            parent = runtime_by_id[parent_id]
            child = parent.model_copy(update={
                "id": child_id,
                "role": "secondary_object",
                "confidence": min(parent.confidence, 0.95),
                "extraction_method": f"{parent.extraction_method}+pass2_secondary",
                "independent": True,
                "compound": False,
                "component_count": 1,
                "can_animate_independently": True,
                "parent_asset_id": parent_id,
                "asset_family_id": parent_id,
                "render_as_family_canvas": True,
            })
            assets.append(child)
            runtime_by_id[child_id] = child
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


def test_relation_result_has_one_consequence_gesture(tmp_path: Path):
    """A target that is the authored result must not acknowledge and pay off twice."""
    _, choreography, _, motion, _ = _pipeline(
        tmp_path,
        [Spec("source", "cause", 0.3), Spec("result", "effect", 1.2, role="RESULT")],
        3.0,
        relations=(CanonicalRelation(
            subject_asset_id="source", object_asset_id="result", relation_type="PROGRESSES_TO",
        ),),
    )
    assert choreography.directives[0].interactions
    result = next(cue for cue in motion if cue.asset_id == "result")
    consequences = [s for s in result.segments if s.phase in {"INTERACT", "REACT", "PAYOFF"}]
    assert [s.phase for s in consequences] == ["PAYOFF"]


def test_same_event_same_timestamp_has_one_attention_owner_without_comparison(
    tmp_path: Path,
):
    story, _, _, motion, _ = _pipeline(
        tmp_path / "same-instant-owner",
        [
            Spec(
                "support-character", "E1", 0.40, role="CHARACTER",
                leader=False, phrase="character-span", sequence=1, group="g",
            ),
            Spec(
                "support-action", "E1", 0.40, role="ACTION",
                leader=False, phrase="action-span", sequence=2, group="g",
            ),
            Spec(
                "result", "E1", 0.90, role="RESULT",
                leader=True, phrase="result-span", sequence=3, group="g",
            ),
        ],
        2.0,
    )
    windows = {
        row.asset_id: story_activation_window(row, story[0])[1]
        for row in story[0].asset_activations
    }
    assert windows["support-character"].reveal_start == pytest.approx(0.40)
    assert windows["support-action"].reveal_start == pytest.approx(0.40)

    focus = {cue.asset_id: cue.params["semantic_focus"] for cue in motion}
    same_instant = [focus["support-character"], focus["support-action"]]
    assert sum(row["cohort_gain"] == pytest.approx(1.0) for row in same_instant) == 1
    assert focus["support-action"]["cohort_gain"] == pytest.approx(1.0)
    assert focus["support-character"]["cohort_gain"] < 1.0
    assert min(row["cohort_gain"] for row in same_instant) <= 0.58
    # The later authored result keeps its own independent Hero moment.
    assert focus["result"]["cohort_gain"] == pytest.approx(1.0)


def test_dependency_linked_events_at_same_timestamp_share_one_attention_owner(
    tmp_path: Path,
):
    story, _, _, motion, _ = _pipeline(
        tmp_path / "dependency-same-instant",
        [
            Spec(
                "upstream", "E1", 0.40, role="OBJECT",
                leader=True, phrase="upstream-span", sequence=1, group="g",
            ),
            Spec(
                "downstream", "E2", 0.40, role="ACTION",
                leader=True, phrase="downstream-span", sequence=2, group="g",
            ),
        ],
        1.5,
    )
    windows = {
        row.asset_id: story_activation_window(row, story[0])[1]
        for row in story[0].asset_activations
    }
    assert windows["upstream"].reveal_start == pytest.approx(0.40)
    assert windows["downstream"].reveal_start == pytest.approx(0.40)
    downstream_activation = next(
        row for row in story[0].asset_activations if row.asset_id == "downstream"
    )
    assert "E1" in downstream_activation.semantic_event_dependency_ids

    focus = {cue.asset_id: cue.params["semantic_focus"] for cue in motion}
    assert focus["downstream"]["cohort_gain"] == pytest.approx(1.0)
    assert focus["upstream"]["cohort_gain"] < 1.0
    assert focus["upstream"]["cohort_role"] != "leader"


def test_enable_relation_same_anchor_keeps_reaction_with_one_hero(
    tmp_path: Path,
):
    story, choreography, _, motion, _ = _pipeline(
        tmp_path / "enable-same-anchor",
        [
            Spec(
                "source", "E1", 0.40, role="PRIMARY", leader=True,
                phrase="source-span", phrase_end=0.80, sequence=1, group="g",
            ),
            Spec(
                "target", "E2", 0.40, role="OBJECT", leader=True,
                phrase="target-span", phrase_end=0.80, sequence=2, group="g",
            ),
        ],
        1.8,
        relations=(CanonicalRelation(
            subject_asset_id="source",
            object_asset_id="target",
            relation_type="ENABLES",
        ),),
    )
    assert choreography.directives[0].interactions

    focus = {cue.asset_id: cue.params["semantic_focus"] for cue in motion}
    assert focus["target"]["cohort_gain"] == pytest.approx(1.0)
    assert focus["target"]["cohort_role"] == "leader"
    assert focus["source"]["cohort_gain"] < 1.0
    assert focus["source"]["cohort_role"] != "leader"

    source = next(cue for cue in motion if cue.asset_id == "source")
    target = next(cue for cue in motion if cue.asset_id == "target")
    assert [
        (segment.phase, segment.involvement)
        for segment in source.segments
        if segment.relationship == "ENABLES"
    ] == [("INTERACT", "SOURCE")]
    assert [
        (segment.phase, segment.involvement)
        for segment in target.segments
        if segment.relationship == "ENABLES"
    ] == [("REACT", "TARGET")]

    source_window = next(
        story_activation_window(row, story[0])[1]
        for row in story[0].asset_activations
        if row.asset_id == "source"
    )
    target_window = next(
        story_activation_window(row, story[0])[1]
        for row in story[0].asset_activations
        if row.asset_id == "target"
    )
    assert source_window.reveal_start == pytest.approx(0.40)
    assert target_window.reveal_start == pytest.approx(0.40)


def _windows(story):
    return {
        row.asset_id: story_activation_window(row, story[0])[1]
        for row in story[0].asset_activations
        if story_activation_window(row, story[0])[1] is not None
    }


def _focus(motion):
    return {cue.asset_id: cue.params["semantic_focus"] for cue in motion}


def _gesture_energy(cue) -> float:
    """Measure the renderer-facing transform authored before Composition settle."""
    frames = cue.params["program"]["keyframes"]
    return sum(
        hypot(right["dx"] - left["dx"], right["dy"] - left["dy"])
        + abs(right["scale"] - left["scale"]) * 0.20
        for left, right in zip(frames, frames[1:])
        if left["progress"] < cue.params["program"]["settle_progress"] + 1e-9
    )


def _assert_focus_hierarchy(
    motion, *, leaders: set[str], supports: set[str] | None = None
):
    """Certify that semantic authority is expressed by the actual Motion program."""
    by_id = {cue.asset_id: cue for cue in motion}
    leader_floor = min(_gesture_energy(by_id[asset_id]) for asset_id in leaders)
    if supports:
        support_ceiling = max(_gesture_energy(by_id[asset_id]) for asset_id in supports)
        assert support_ceiling <= leader_floor * 0.72
    for cue in by_id.values():
        frames = cue.params["program"]["keyframes"]
        assert frames[-1]["dx"] == pytest.approx(0.0)
        assert frames[-1]["dy"] == pytest.approx(0.0)
        assert frames[-1]["scale"] == pytest.approx(1.0)


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
    _assert_focus_hierarchy(motion, leaders={"A"}, supports={"B"})


def test_true_same_anchor_cohort_has_one_perceptual_leader(tmp_path: Path):
    specs = [
        Spec("leader", "E1", 0.8, "PRIMARY"),
        Spec("support-a", "E1", 0.8, "SUPPORT", False),
        Spec("support-b", "E1", 0.8, "OBJECT", False),
    ]
    _story, motion, _windows_by_asset = _certify(
        tmp_path / "perceptual-cohort", specs, 2.5
    )
    _assert_focus_hierarchy(
        motion,
        leaders={"leader"},
        supports={"support-a", "support-b"},
    )


def test_same_event_three_asset_level_anchors_reveal_progressively(tmp_path: Path):
    specs = [
        Spec("character", "E1", 0.45, "CHARACTER"),
        Spec("support", "E1", 1.35, "SUPPORT", False),
        Spec("object", "E1", 3.80, "RESULT", False),
    ]
    story, motion, windows = _certify(tmp_path / "same-event-progressive", specs, 5.5)
    assert [windows[row.asset].reveal_start for row in specs] == pytest.approx(
        [0.45, 1.35, 3.80]
    )
    assert all(_focus(motion)[row.asset]["cohort_role"] == "independent" for row in specs)
    assert set(story[0].active_visual_semantic_state or {}) == {
        "character", "support", "object"
    }


def test_same_event_true_cohort_then_later_asset(tmp_path: Path):
    specs = [
        Spec("A", "E1", 0.70, "PRIMARY"),
        Spec("B", "E1", 0.70, "SUPPORT", False),
        Spec("C", "E1", 2.65, "RESULT", False),
    ]
    _story, motion, windows = _certify(tmp_path / "same-event-mixed", specs, 4.0)
    assert windows["A"].reveal_start == windows["B"].reveal_start
    assert windows["C"].reveal_start == pytest.approx(2.65)
    assert _focus(motion)["A"]["cohort_role"] == "leader"
    assert _focus(motion)["B"]["cohort_role"] != "independent"
    assert _focus(motion)["C"]["cohort_role"] == "independent"


def test_same_event_black_hat_shape_transfers_focus_by_asset_anchor(tmp_path: Path):
    specs = [
        Spec("actor", "broad-event", 0.40, "CHARACTER"),
        Spec("negation", "broad-event", 1.05, "SUPPORT", False),
        Spec("target", "broad-event", 2.90, "OBJECT", False),
    ]
    story, motion, windows = _certify(tmp_path / "same-event-black-shape", specs, 4.5)
    assert [windows[row.asset].reveal_start for row in specs] == pytest.approx(
        [0.40, 1.05, 2.90]
    )
    assert all(_focus(motion)[row.asset]["cohort_gain"] == pytest.approx(1.0) for row in specs)
    assert set(story[0].active_visual_semantic_state or {}) == {
        "actor", "negation", "target"
    }


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


def test_distinct_phrases_override_misleading_sequence_order(tmp_path: Path):
    specs = [
        Spec("A", "shared", 0.4, sequence=3, group="progression"),
        Spec("B", "shared", 1.3, sequence=1, group="progression", leader=False),
        Spec("C", "shared", 3.0, sequence=2, group="progression", leader=False),
    ]
    story, *_ = _pipeline(tmp_path / "distinct-span-conflict", specs, 4.0)
    windows = _windows(story)
    assert [windows[key].reveal_start for key in ("A", "B", "C")] == pytest.approx(
        [0.4, 1.3, 3.0]
    )


@pytest.mark.parametrize(
    "name,duration,count,phrase_end",
    [
        ("short", 0.60, 6, 0.58),
        ("long", 3.00, 8, 2.80),
    ],
)
def test_same_phrase_sequence_uses_available_phrase_window(
    tmp_path: Path, name: str, duration: float, count: int, phrase_end: float
):
    specs = [
        Spec(
            f"asset-{index}",
            "timeline",
            0.05,
            phrase="one-authored-phrase",
            phrase_end=phrase_end,
            sequence=index + 1,
            leader=index == 0,
        )
        for index in range(count)
    ]
    scrambled = [row.asset for row in specs[2::3] + specs[0::3] + specs[1::3]]
    story, _choreography, composition, motion, _render = _pipeline(
        tmp_path / f"same-phrase-{name}", specs, duration, order=scrambled
    )
    windows = _windows(story)
    starts = [windows[row.asset].reveal_start for row in specs]
    assert starts == sorted(starts)
    assert len(set(starts)) == count
    assert starts[0] == pytest.approx(0.05)
    assert starts[-1] < phrase_end
    assert all(
        0.05 <= windows[row.asset].reveal_start < windows[row.asset].settle_at <= phrase_end
        for row in specs
    )
    assert all(cue.end > cue.start for cue in motion)
    assert all(layout.beat_id == story[0].id for layout in composition)


def test_same_phrase_explicit_cohort_then_later_rank(tmp_path: Path):
    specs = [
        Spec("A", "E1", 0.2, phrase="shared", phrase_end=1.2, sequence=1, group="g"),
        Spec(
            "B", "E1", 0.2, leader=False, phrase="shared", phrase_end=1.2,
            sequence=1, group="g",
        ),
        Spec(
            "C", "E1", 0.2, leader=False, phrase="shared", phrase_end=1.2,
            sequence=2, group="g",
        ),
    ]
    story, *_ = _pipeline(tmp_path / "cohort-then-progress", specs, 1.5)
    windows = _windows(story)
    assert windows["A"].reveal_start == pytest.approx(windows["B"].reveal_start)
    assert windows["C"].reveal_start > windows["A"].reveal_start
    assert windows["C"].settle_at <= 1.2


def test_explicit_simultaneous_group_ignores_sequence_rank(tmp_path: Path):
    specs = [
        Spec(
            asset, "E1", 0.2, leader=index == 0, phrase="shared", phrase_end=1.2,
            sequence=index + 1, group="unit", group_policy="SIMULTANEOUS_VISUAL_UNIT",
        )
        for index, asset in enumerate(("A", "B", "C"))
    ]
    story, *_ = _pipeline(tmp_path / "explicit-simultaneous", specs, 1.5)
    starts = [_windows(story)[asset].reveal_start for asset in ("A", "B", "C")]
    assert starts == pytest.approx([0.2, 0.2, 0.2])


@pytest.mark.parametrize(
    "name,duration,anchors",
    [
        ("small-medium-large", 3.0, (0.45, 0.78, 1.11)),
        ("calendar-progression", 3.0, (0.70, 0.91, 1.14)),
        ("very-fast", 0.8, (0.10, 0.28, 0.47)),
        ("slow", 8.0, (0.70, 3.20, 6.50)),
    ],
)
def test_sequential_motion_preserves_authored_anchors_and_settle_identity(
    tmp_path: Path, name: str, duration: float, anchors: tuple[float, float, float]
):
    specs = [
        Spec("z-tiny", "E1", anchors[0], "OBJECT"),
        Spec("a-huge", "E2", anchors[1], "ACTION"),
        Spec("m-medium", "E3", anchors[2], "RESULT"),
    ]
    _story, motion, windows = _certify(
        tmp_path / name,
        specs,
        duration,
        order=["m-medium", "z-tiny", "a-huge"],
    )
    assert [windows[row.asset].reveal_start for row in specs] == pytest.approx(anchors)
    by_id = {cue.asset_id: cue for cue in motion}
    assert [by_id[row.asset].start for row in specs] == pytest.approx(anchors)
    assert all(cue.end > cue.start for cue in motion)
    assert all(
        all(segment.end > segment.start for segment in cue.segments)
        for cue in motion
    )
    for cue in motion:
        frames = cue.params["program"]["keyframes"]
        assert [frame["progress"] for frame in frames] == sorted(
            frame["progress"] for frame in frames
        )
        assert frames[-1]["dx"] == pytest.approx(0.0)
        assert frames[-1]["dy"] == pytest.approx(0.0)
        assert frames[-1]["scale"] == pytest.approx(1.0)


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


def test_1000_generated_cases_use_story_owned_windows(tmp_path: Path):
    rng = random.Random(0x5EAA17C)
    errors, lifecycles = [], 0
    for case in range(1000):
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
            # Deliberately cover true cohorts and 2/3/5 distinct asset anchors inside
            # one event. The independent oracle remains the asset span + word timing.
            distinct = (1, 2, 3, 5)[case % 4]
            anchor_index = first + ((i - first) % distinct)
            anchor_index = min(anchor_index, count - 1)
            specs.append(
                Spec(
                    f"asset-{i}",
                    event,
                    anchors[anchor_index],
                    "RESULT" if event_index == event_count - 1 else "OBJECT",
                    not any(row.event == event for row in specs),
                )
            )
        story, _motion, windows = _certify(tmp_path / f"generated-{case}", specs, duration)
        errors.extend(abs(windows[row.asset].reveal_start - row.anchor) for row in specs)
        lifecycles += len(story[0].active_visual_semantic_state or {})
    assert lifecycles >= 1000
    assert max(errors) <= 0.05
    assert statistics.median(errors) <= 0.05
    assert statistics.quantiles(errors, n=100, method="inclusive")[94] <= 0.05


def test_1000_generated_same_phrase_sequences_are_ordered(tmp_path: Path):
    rng = random.Random(0x5E0A0DE)
    lifecycles = 0
    for case in range(1000):
        duration = rng.uniform(0.5, 3.0)
        count = rng.randint(3, min(8, 1 + int(duration / 0.025)))
        phrase_start = rng.uniform(0.02, duration * 0.15)
        phrase_end = rng.uniform(max(phrase_start + 0.25, duration * 0.55), duration * 0.98)
        specs = [
            Spec(
                f"asset-{index}",
                "progression",
                phrase_start,
                phrase="generated-shared-phrase",
                phrase_end=phrase_end,
                sequence=index + 1,
                leader=index == 0,
            )
            for index in range(count)
        ]
        shuffled = [row.asset for row in sorted(specs, key=lambda _row: rng.random())]
        story, _choreography, _composition, motion, _render = _pipeline(
            tmp_path / f"generated-sequence-{case}",
            specs,
            duration,
            order=shuffled,
        )
        windows = _windows(story)
        starts = [windows[row.asset].reveal_start for row in specs]
        assert starts == sorted(starts)
        assert len(set(starts)) == count
        assert all(
            phrase_start <= windows[row.asset].reveal_start
            < windows[row.asset].settle_at <= phrase_end
            for row in specs
        )
        assert all(segment.phase != "EXIT" for cue in motion for segment in cue.segments)
        lifecycles += count
    assert lifecycles >= 3000


@pytest.mark.parametrize(
    "family,scene_count",
    [
        ("presenter-icons", 40),
        ("icons-only", 40),
        ("timeline", 40),
        ("dense-network", 40),
        ("comparison", 40),
        ("relation", 40),
        ("result-payoff", 40),
        ("mixed-duration", 40),
    ],
)
def test_package_shaped_multi_asset_stress(
    tmp_path: Path, family: str, scene_count: int
):
    """Eight package families: 320 scenes and 2,560 asset lifecycles."""
    family_index = (
        "presenter-icons", "icons-only", "timeline", "dense-network",
        "comparison", "relation", "result-payoff", "mixed-duration",
    ).index(family)
    distribution = (1, 2, 3, 5, 8, 10, 15, 20)
    total_assets = 0
    for scene_index in range(scene_count):
        count = distribution[scene_index % len(distribution)]
        event_count = min(6, max(1, (count + 1) // 2))
        duration = 1.0 + (scene_index % 11)
        specs = []
        for asset_index in range(count):
            event_index = min(event_count - 1, asset_index * event_count // count)
            event = f"E{event_index}"
            first_in_event = next(
                index
                for index in range(count)
                if min(event_count - 1, index * event_count // count) == event_index
            )
            within_event = asset_index - first_in_event
            anchor_step = (0.0, 0.008, 0.012, 0.018, 0.024, 0.03, 0.036, 0.042)[
                family_index
            ]
            anchor = min(
                duration * 0.92,
                0.08 + event_index * duration * 0.72 / event_count
                + (within_event % (family_index + 2)) * anchor_step * duration,
            )
            specs.append(
                Spec(
                    f"asset-{asset_index}",
                    event,
                    anchor,
                    "RESULT" if event_index == event_count - 1 else "OBJECT",
                    not any(row.event == event for row in specs),
                    phrase=(
                        "package-shared-phrase"
                        if family in {"timeline", "mixed-duration"} and scene_index % 2
                        else None
                    ),
                    phrase_end=(
                        duration * 0.95
                        if family in {"timeline", "mixed-duration"} and scene_index % 2
                        else None
                    ),
                    sequence=(
                        asset_index + 1
                        if family in {"timeline", "mixed-duration"} and scene_index % 2
                        else None
                    ),
                )
            )
        if family in {"timeline", "mixed-duration"} and scene_index % 2:
            story, _choreography, _composition, motion, _render = _pipeline(
                tmp_path / f"package-{family}-{scene_index}", specs, duration
            )
            starts = [_windows(story)[row.asset].reveal_start for row in specs]
            assert starts == sorted(starts)
            assert len(set(starts)) == count
            assert all(segment.phase != "EXIT" for cue in motion for segment in cue.segments)
        else:
            _certify(
                tmp_path / f"package-{family}-{scene_index}",
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

def test_pass2_child_provenance_cannot_preempt_single_group_semantics(
    tmp_path: Path,
):
    """A detached Pass2 child is not semantically equivalent to its source parent."""
    # Script/span order follows narration. sequence_order is deliberately
    # different for negation/vulnerability so precise speech timing must win.
    specs = [
        Spec("actor", "broad-event", 0.40, "CHARACTER", True, sequence=1, group="g"),
        Spec("negation", "broad-event", 1.05, "RESULT", False, sequence=3, group="g"),
        Spec("vulnerability", "broad-event", 2.90, "OBJECT", False, sequence=2, group="g"),
    ]
    child_id = "negation:secondary-01"
    story, _choreography, _composition, _motion, _render = _pipeline(
        tmp_path / "pass2-child-single-group",
        specs,
        4.2,
        pass2_children=[("negation", child_id)],
    )
    windows = _windows(story)
    child = next(
        row for row in story[0].asset_activations if row.asset_id == child_id
    )

    assert child.source == "final_package_scene_context_tail"
    assert child.visual_focus == "CONTEXT"
    assert child.semantic_event_id is None
    assert windows[child_id].reveal_start > windows["negation"].reveal_start
    assert windows[child_id].reveal_start >= windows["vulnerability"].reveal_start
    assert "inherits_parent_semantic_time" not in child.evidence
    assert "inherits_latest_authored_spoken_anchor" in child.evidence


def test_pass2_child_in_multi_group_scene_abstains_instead_of_inheriting_parent(
    tmp_path: Path,
):
    specs = [
        Spec("left", "E1", 0.40, group="g1", sequence=1),
        Spec("right", "E2", 1.80, group="g2", sequence=1),
    ]
    child_id = "left:secondary-01"
    story, *_ = _pipeline(
        tmp_path / "pass2-child-multi-group",
        specs,
        3.0,
        pass2_children=[("left", child_id)],
    )
    activation = next(
        row for row in story[0].asset_activations if row.asset_id == child_id
    )
    has_v2, window = story_activation_window(activation, story[0])

    assert has_v2 is True and window is None
    assert activation.source == "semantic_abstention"
    assert "independent_runtime_cutout_requires_semantic_identity" in activation.evidence
    assert "inherits_parent_semantic_time" not in activation.evidence
    assert child_id not in (story[0].active_visual_semantic_state or {})


def test_96_generated_pass2_children_never_preempt_authored_semantics(
    tmp_path: Path,
):
    checked = 0
    for case in range(96):
        count = 2 + case % 7
        duration = max(2.0, 0.9 + count * 0.58)
        specs = [
            Spec(
                f"asset-{index}",
                "broad-event",
                0.25 + index * 0.48,
                "RESULT" if index == count - 1 else "OBJECT",
                index == 0,
                sequence=index + 1,
                group="single-group",
            )
            for index in range(count)
        ]
        parent_id = specs[(case * 3) % count].asset
        children = [
            (parent_id, f"{parent_id}:secondary-{index + 1:02d}")
            for index in range(1 + case % 3)
        ]
        story, _choreography, _composition, _motion, _render = _pipeline(
            tmp_path / f"pass2-provenance-{case}",
            specs,
            duration,
            pass2_children=children,
        )
        windows = _windows(story)
        latest_authored = max(windows[row.asset].reveal_start for row in specs)
        for _parent, child_id in children:
            activation = next(
                row for row in story[0].asset_activations if row.asset_id == child_id
            )
            assert activation.source == "final_package_scene_context_tail"
            assert activation.visual_focus == "CONTEXT"
            assert activation.semantic_event_id is None
            assert windows[child_id].reveal_start >= latest_authored
            assert "inherits_parent_semantic_time" not in activation.evidence
            checked += 1

    assert checked == 192


def test_unbound_single_group_cutout_waits_for_latest_authored_anchor(tmp_path: Path):
    """Unknown detached visuals cannot pre-empt known narration in a one-group Scene."""
    # Script/span order follows narration. sequence_order is deliberately
    # different for negation/vulnerability so precise speech timing must win.
    specs = [
        Spec("actor", "broad-event", 0.40, "CHARACTER", True, sequence=1, group="g"),
        Spec("negation", "broad-event", 1.05, "RESULT", False, sequence=3, group="g"),
        Spec("vulnerability", "broad-event", 2.90, "OBJECT", False, sequence=2, group="g"),
    ]
    story, _choreography, _composition, motion, _render = _pipeline(
        tmp_path / "unbound-late-context",
        specs,
        4.2,
        extra_asset_ids=["unbound-chip"],
    )
    windows = _windows(story)
    assert windows["unbound-chip"].reveal_start > windows["vulnerability"].reveal_start
    assert windows["unbound-chip"].reveal_start > windows["negation"].reveal_start

    activation = next(
        row for row in story[0].asset_activations if row.asset_id == "unbound-chip"
    )
    assert activation.source == "final_package_scene_context_tail"
    assert activation.visual_focus == "CONTEXT"
    assert activation.semantic_event_id is None
    assert activation.semantic_event_order == 1
    assert "derived_unbound_cutout_late_context" in activation.evidence
    assert "inherits_latest_authored_spoken_anchor" in activation.evidence
    assert "anchor_asset_id=vulnerability" in activation.evidence

    focus = _focus(motion)
    assert focus["unbound-chip"]["role"] == "CONTEXT"
    assert all(segment.phase != "EXIT" for cue in motion for segment in cue.segments)


def test_unbound_cutout_in_multi_group_scene_remains_safe_abstention(tmp_path: Path):
    """Do not guess which semantic group owns an extra runtime cutout."""
    specs = [
        Spec("left", "E1", 0.40, group="g1", sequence=1),
        Spec("right", "E2", 1.80, group="g2", sequence=1),
    ]
    story, *_ = _pipeline(
        tmp_path / "unbound-multi-group",
        specs,
        3.0,
        extra_asset_ids=["unknown-extra"],
    )
    activation = next(
        row for row in story[0].asset_activations if row.asset_id == "unknown-extra"
    )
    has_v2, window = story_activation_window(activation, story[0])
    assert has_v2 is True and window is None
    assert activation.source == "semantic_abstention"
    assert "SAFE_ABSTENTION" in activation.evidence
    assert "unknown-extra" not in (story[0].active_visual_semantic_state or {})


def test_300_generated_unbound_cutouts_never_preempt_authored_semantics(tmp_path: Path):
    """Stress ZERO_OR_ONE_OR_MANY runtime cutout cardinality across varied scenes."""
    rng = random.Random(0xC07E57)
    checked = 0
    for case in range(300):
        duration = rng.uniform(1.2, 9.0)
        authored_count = rng.randint(2, 8)
        extra_count = rng.randint(1, 5)
        anchors = sorted(
            rng.uniform(0.08, duration * 0.82)
            for _ in range(authored_count)
        )
        specs = [
            Spec(
                f"authored-{index}",
                "broad-event",
                anchor,
                "RESULT" if index == authored_count - 1 else "OBJECT",
                index == 0,
                sequence=(index * 3) % authored_count + 1,
                group="single-group",
            )
            for index, anchor in enumerate(anchors)
        ]
        extra_ids = [f"extra-{index}" for index in range(extra_count)]
        story, _choreography, _composition, motion, _render = _pipeline(
            tmp_path / f"unbound-generated-{case}",
            specs,
            duration,
            extra_asset_ids=extra_ids,
        )
        windows = _windows(story)
        latest_authored = max(windows[row.asset].reveal_start for row in specs)
        extra_starts = [windows[asset_id].reveal_start for asset_id in extra_ids]
        assert extra_starts == sorted(extra_starts)
        assert all(start >= latest_authored for start in extra_starts)
        for asset_id in extra_ids:
            activation = next(
                row for row in story[0].asset_activations if row.asset_id == asset_id
            )
            assert activation.source == "final_package_scene_context_tail"
            assert activation.visual_focus == "CONTEXT"
            assert activation.semantic_event_id is None
        assert all(segment.phase != "EXIT" for cue in motion for segment in cue.segments)
        checked += len(extra_ids)
    assert checked >= 300