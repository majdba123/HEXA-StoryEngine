"""Sprint 4.5 - scene releases and text-owner coupling (permanent regression gate).

Boundary policy, planned above the renderer and fail closed: HARD_CUT (the release abstains
and the certified boundary runs unchanged), EXACT_END (the outgoing scene fades out on one
clock and reaches zero on the incoming opener frame) or a short OVERLAP that is allowed only
when nothing collides. Collisions are safety facts that can only downgrade the mode; they
never create continuity. The renderer executes the plan and nothing else. A label moves
beside its owner only on explicit, on-screen ownership with a safe local slot; text timing
is never touched. Encoded tests prove the release in real frames.
"""
from __future__ import annotations

import inspect
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

import app.boundary.release as release_module
from app.boundary import SceneBoundaryPlanner
from app.boundary.release import MIN_RELEASE_FRAMES, OVERLAP_FRAMES, RELEASE_FRAMES
from app.composition import TextCompositionPlanner
from app.composition.text_director import PlacedTextRegion, PlacementResult, TextPlacementDirector
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    MotionSegment,
    RenderPlan,
    SceneBoundaryRelease,
    StoryBeat,
    TextCompositionBeat,
    TextCue,
    TextLayoutItem,
    TextMotionCue,
    TextPlan,
    VisualAsset,
)
from app.render.renderer import FFmpegRenderer
from app.render.transition import SceneTransitionMode, VisualTransitionDecision
from app.shared.frame_grid import beat_segments, first_visible_frame, time_to_frame

W, H, FPS = 1920, 1080, 30
ORDER = {"HARD_CUT": 0, "EXACT_END": 1, "OVERLAP": 2}
_STATIC = {"name": "static_reveal_x", "settle_progress": 1.0, "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"},
]}
# Normalised (x, y, width, height) centre boxes.
OLD_LEFT, OLD_RIGHT = (0.2, 0.3, 0.2, 0.3), (0.8, 0.3, 0.2, 0.3)
NEW_CLEAR, NEW_ON_OLD, NEW_LATER = (0.5, 0.75, 0.2, 0.3), (0.25, 0.35, 0.2, 0.3), (0.8, 0.8, 0.15, 0.2)


def _beat(index: int, start: float, end: float, scene: str | None = None, **extra) -> StoryBeat:
    return StoryBeat(id=f"b{index}", scene_id=scene or f"s{index}", start=start, end=end,
                     narration="x", action="REVEAL", **extra)


def _layout(beat_id: str, boxes: dict[str, tuple]) -> CompositionBeat:
    return CompositionBeat(beat_id=beat_id, items=[
        LayoutItem(asset_id=a, x=x, y=y, width=w, height=h, z=n)
        for n, (a, (x, y, w, h)) in enumerate(boxes.items())])


def _cue(beat_id: str, asset_id: str, start: float, duration: float = 0.25, *, opacity: bool = False,
         segments=()) -> MotionCue:
    params = {"program": json.loads(json.dumps(_STATIC)), "semantic_continuity": {"mode": "ENTER"}}
    if opacity:
        params["entry_opacity"] = {"initial": 0.14, "start": start, "settle": start + duration}
    return MotionCue(beat_id=beat_id, asset_id=asset_id, kind="program_v3", start=start,
                     end=start + duration, params=params, segments=list(segments))


def _asset(asset_id: str, root: Path | None = None, **extra) -> VisualAsset:
    path = (root / f"{asset_id.replace(':', '_')}.png") if root else Path(f"{asset_id}.png")
    return VisualAsset(id=asset_id, scene_id="s", role="supporting", image_path=path,
                       extraction_method="test", **extra)


class Scene:
    """Two unrelated scenes: b1 (two old assets) then b2 whose opener appears `lead` frames in."""

    def __init__(self, *, lead: int = 10, opener=NEW_CLEAR, later: int | None = 30,
                 old=None, opener_opacity: bool = False, new_segments=(), old_segments=(),
                 same_scene: bool = False, root: Path | None = None, old_assets=None):
        self.boundary = 2.0
        self.story = [_beat(1, 0.0, self.boundary, "s1"),
                      _beat(2, self.boundary, 5.0, "s1" if same_scene else "s2")]
        old = old or {"old_a": OLD_LEFT, "old_b": OLD_RIGHT}
        new = {"new_a": opener}
        self.motion = [_cue("b1", a, 0.1 + 0.2 * n, segments=old_segments if n == 0 else ())
                       for n, a in enumerate(old)]
        self.motion.append(_cue("b2", "new_a", self.boundary + lead / FPS, opacity=opener_opacity,
                                segments=new_segments))
        if later is not None:
            new["new_b"] = NEW_LATER
            self.motion.append(_cue("b2", "new_b", self.boundary + later / FPS, opacity=True))
        self.composition = [_layout("b1", old), _layout("b2", new)]
        self.assets = old_assets or [_asset(a, root) for a in (*old, *new)]
        self.text = TextPlan()
        self.text_composition: list = []
        self.text_motion: list = []
        self.lead = lead

    def add_text(self, start_frame: int, end_frame: int, x: float, y: float) -> None:
        start, end = self.boundary + start_frame / FPS, self.boundary + end_frame / FPS
        cue = TextCue(id="t1", beat_id="b2", text="label", semantic_type="emphasis",
                      source_char_start=0, source_char_end=5, spoken_start=start, spoken_end=end,
                      emphasis_time=start, style_id="emphasis")
        self.text = TextPlan(cues=[cue])
        self.text_composition = [TextCompositionBeat(beat_id="b2", items=[
            TextLayoutItem(text_cue_id="t1", x=x, y=y, max_width=0.2)])]
        self.text_motion = [TextMotionCue(beat_id="b2", text_cue_id="t1", kind="text", start=start,
                                          end=end, params={"visible_end": end})]

    def plan(self, planner: SceneBoundaryPlanner | None = None) -> SceneBoundaryRelease:
        rows = (planner or SceneBoundaryPlanner()).plan(
            story=self.story, composition=self.composition, motion=self.motion, assets=self.assets,
            duration=5.0, fps=FPS, text=self.text, text_composition=self.text_composition,
            text_motion=self.text_motion)
        assert [(r.beat_id, r.from_beat_id) for r in rows] == [("b2", "b1")]  # one row per boundary
        return rows[0]

    def render_plan(self, rows=None) -> RenderPlan:
        return RenderPlan(duration=5.0, story=self.story, composition=self.composition,
                          motion=self.motion, assets=self.assets,
                          scene_boundaries=[self.plan()] if rows is None else rows)

    def frame(self, value: float) -> int:
        return round((value - self.boundary) * FPS)


# -- boundary policy ------------------------------------------------------------------------
def test_exact_end_is_the_default_release_when_the_opener_lands_on_old_artwork() -> None:
    scene = Scene(lead=10, opener=NEW_ON_OLD)
    row = scene.plan()
    assert (row.mode, row.reason) == ("EXACT_END", "exact_end_release")
    assert row.downgrade_reason == "opener_collides_with_outgoing_artwork"
    assert scene.frame(row.opener_at) == scene.frame(row.release_end) == 10  # zero on the opener frame
    assert scene.frame(row.release_start) == 10 - RELEASE_FRAMES
    assert row.audit["artwork_collisions"] >= 1 and row.audit["overlap_frames"] == 0


def test_collision_free_boundary_gets_the_short_reference_overlap() -> None:
    row = Scene(lead=10).plan()
    assert (row.mode, row.reason, row.downgrade_reason) == ("OVERLAP", "collision_free_overlap", None)
    start, zero, opener = (round((v - 2.0) * FPS) for v in (row.release_start, row.release_end, row.opener_at))
    assert (opener, zero - opener, zero - start) == (10, OVERLAP_FRAMES, RELEASE_FRAMES)
    assert start < opener  # the release begins before the opener, never after it


@pytest.mark.parametrize("lead,mode", [(1, "HARD_CUT"), (4, "HARD_CUT"), (5, "EXACT_END"), (6, "EXACT_END"), (40, "EXACT_END")])
def test_release_needs_five_to_seven_frames_before_the_opener_or_stays_a_hard_cut(lead, mode) -> None:
    scene = Scene(lead=lead, opener=NEW_ON_OLD, later=60)
    row = scene.plan()
    assert row.mode == mode
    if mode == "HARD_CUT":
        assert row.reason == "release_window_too_short"
        assert row.release_start is row.release_end is row.opener_at is None  # nothing for the renderer
    else:
        frames = scene.frame(row.release_end) - scene.frame(row.release_start)
        assert frames == min(RELEASE_FRAMES, lead) and MIN_RELEASE_FRAMES <= frames <= 7
        assert scene.frame(row.release_start) >= 0  # Story time is never stretched backwards


def test_short_lead_can_overlap_only_when_collision_free() -> None:
    assert Scene(lead=3).plan().mode == "OVERLAP"         # 2 frames before + 4 after the opener
    assert Scene(lead=3, opener=NEW_ON_OLD).plan().mode == "HARD_CUT"
    assert Scene(lead=1).plan().mode == "HARD_CUT"        # the release would start before the scene


def test_overlap_reaches_zero_before_any_later_reveal_or_is_downgraded() -> None:
    capped = Scene(lead=10, later=14).plan()
    assert capped.mode == "OVERLAP" and round((capped.release_end - 2.0) * FPS) == 13
    tight = Scene(lead=10, later=13).plan()
    assert (tight.mode, tight.downgrade_reason) == ("EXACT_END", "overlap_window_insufficient")


def test_incoming_text_over_outgoing_artwork_downgrades_overlap_only_inside_the_overlap() -> None:
    scene = Scene(lead=10)
    scene.add_text(10, 40, OLD_LEFT[0], OLD_LEFT[1])  # visible during the overlap, on old artwork
    row = scene.plan()
    assert (row.mode, row.downgrade_reason) == ("EXACT_END", "incoming_text_over_outgoing_artwork")
    scene.add_text(20, 40, OLD_LEFT[0], OLD_LEFT[1])  # appears after the outgoing scene is gone
    assert scene.plan().mode == "OVERLAP"
    scene.add_text(10, 40, 0.5, 0.2)                  # during the overlap but on free canvas
    assert scene.plan().mode == "OVERLAP"


@pytest.mark.parametrize("segment", [
    dict(phase="INTERACT"), dict(phase="PAYOFF"), dict(phase="REACT"),
    dict(phase="ESTABLISH", semantic_action="EMPHASIZE"), dict(phase="ESTABLISH", connection=True),
])
def test_protected_sprint_4_1_and_4_2_motion_never_runs_under_an_overlap(segment) -> None:
    start = 2.0 + 11 / FPS
    protected = MotionSegment(start=start, end=start + 0.3, **segment)
    row = Scene(lead=10, new_segments=(protected,)).plan()
    assert (row.mode, row.downgrade_reason) == ("EXACT_END", "protected_motion_conflict")
    late = MotionSegment(start=2.0 + 20 / FPS, end=2.0 + 30 / FPS, **segment)
    assert Scene(lead=10, new_segments=(late,)).plan().mode == "OVERLAP"


def test_release_never_starts_before_the_outgoing_scene_finished_its_last_action() -> None:
    # The previous scene's motion runs into the next beat: no release may start under it.
    running = MotionSegment(phase="PAYOFF", start=1.8, end=2.0 + 8 / FPS)
    row = Scene(lead=10, opener=NEW_ON_OLD, old_segments=(running,)).plan()
    assert (row.mode, row.reason) == ("HARD_CUT", "outgoing_action_incomplete")
    almost = MotionSegment(phase="PAYOFF", start=1.8, end=2.0 + 5 / FPS)
    row = Scene(lead=10, opener=NEW_ON_OLD, old_segments=(almost,)).plan()
    assert row.mode == "EXACT_END"
    assert round((row.release_end - row.release_start) * FPS) == MIN_RELEASE_FRAMES  # shortest legal release


def test_release_abstains_when_the_opener_is_not_solid_so_no_near_white_frame_appears() -> None:
    row = Scene(lead=10, opener=NEW_ON_OLD, opener_opacity=True).plan()
    assert (row.mode, row.reason) == ("HARD_CUT", "opener_not_solid")


class _Classifier:
    def __init__(self, **decision):
        self.decision = decision

    def decide(self, previous_beat, previous_layout, current_layout, *, current_beat=None):
        base = dict(persistent_asset_ids=frozenset(),
                    carry_outgoing_asset_ids=frozenset(i.asset_id for i in previous_layout.items),
                    mode=SceneTransitionMode.MOTION_HANDOFF, reason="cross_scene_motion_handoff")
        return VisualTransitionDecision(**{**base, **self.decision})


@pytest.mark.parametrize("decision,reason", [
    (dict(mode=SceneTransitionMode.OBJECT_HANDOFF, reason="authored_object_continuity"), "authored_object_continuity"),
    (dict(mode=SceneTransitionMode.BLUR_BRIDGE, reason="explicit_blur_intent"), "explicit_blur_intent"),
    (dict(persistent_asset_ids=frozenset({"old_a"})), "cross_scene_motion_handoff"),
])
def test_authored_continuity_and_persistence_keep_their_certified_boundary(decision, reason) -> None:
    planner = SceneBoundaryPlanner()
    planner.classifier = _Classifier(**decision)
    row = Scene(lead=10).plan(planner)
    assert (row.mode, row.reason) == ("HARD_CUT", f"abstain:legacy_boundary:{reason}")
    assert row.release_start is None


def test_same_scene_boundary_is_never_released() -> None:
    row = Scene(lead=10, same_scene=True).plan()
    assert row.mode == "HARD_CUT" and row.reason.startswith("abstain:legacy_boundary")


def test_collisions_only_downgrade_and_never_create_continuity() -> None:
    for lead in (2, 3, 5, 8, 12):
        free, hit = Scene(lead=lead).plan(), Scene(lead=lead, opener=NEW_ON_OLD).plan()
        assert ORDER[hit.mode] <= ORDER[free.mode]          # a collision can only lower the mode
    source = inspect.getsource(release_module)
    for word in ("persistent_asset_ids=", "TRANSFORM", "morph", "object_handoff_pairs"):
        assert word not in source                            # no persistence, identity or morphing
    scene = Scene(lead=10, opener=NEW_ON_OLD)
    before = [m.model_dump() for m in (*scene.story, *scene.composition, *scene.motion)]
    scene.plan()
    assert before == [m.model_dump() for m in (*scene.story, *scene.composition, *scene.motion)]


def test_pass2_family_leaves_on_one_clock_or_the_release_abstains() -> None:
    old = {"fam": OLD_LEFT, "fam:secondary-01": OLD_LEFT, "old_b": OLD_RIGHT}
    family = dict(asset_family_id="fam", render_as_family_canvas=True)
    assets = [_asset("fam", **family), _asset("fam:secondary-01", parent_asset_id="fam", **family),
              _asset("old_b"), _asset("new_a"), _asset("new_b")]
    scene = Scene(lead=10, old=old, old_assets=assets)
    row = scene.plan()
    assert row.mode == "OVERLAP" and row.audit["outgoing_pass2_families"] == 1
    assert row.audit["outgoing_assets"] == 3              # one release clock for all three layers
    split = SceneBoundaryPlanner()
    split.classifier = _Classifier(carry_outgoing_asset_ids=frozenset({"fam", "old_b"}))
    row = scene.plan(split)                               # one family layer would stay behind
    assert (row.mode, row.reason) == ("HARD_CUT", "pass2_family_cannot_share_one_clock")


def test_every_boundary_is_audited_on_the_frame_grid_and_planning_is_deterministic() -> None:
    scene = Scene(lead=10, opener=NEW_ON_OLD)
    row = scene.plan()
    for value in (row.opener_at, row.release_start, row.release_end):
        assert abs(value * FPS - round(value * FPS)) < 1e-6
    assert row.reason and row.audit["opener_frame"] == 10 and row.audit["next_reveal_frame"] == 30
    shuffled = Scene(lead=10, opener=NEW_ON_OLD)
    shuffled.motion.reverse()
    shuffled.assets.reverse()
    shuffled.story.reverse()
    assert shuffled.plan().model_dump() == row.model_dump()
    assert SceneBoundaryPlanner().plan(story=scene.story[:1], composition=scene.composition,
                                       motion=scene.motion, assets=scene.assets, duration=5.0) == []


def test_opener_is_the_first_frame_motion_shows_anything_including_proxy_segments() -> None:
    proxy = MotionSegment(phase="ESTABLISH", start=2.0 + 8 / FPS, end=2.0 + 16 / FPS)
    row = Scene(lead=12, opener=NEW_ON_OLD, new_segments=(proxy,)).plan()
    assert row.audit["opener_frame"] == 8 and round((row.release_end - 2.0) * FPS) == 8
    hidden = Scene(lead=10, opener=NEW_ON_OLD)
    hidden.story[1] = _beat(2, 2.0, 5.0, "s2", active_visual_semantic_state={"new_b": "x"})
    assert hidden.plan().audit["opener_frame"] == 30      # inactive artwork is not an opener


def test_frame_grid_is_one_shared_authority_for_planner_and_renderer() -> None:
    for value in (0.0, 0.0333, 0.5343, 2.0, 91.918):
        assert FFmpegRenderer._first_visible_frame(value, FPS) == first_visible_frame(value, FPS)
        assert FFmpegRenderer._time_to_frame(value, FPS, 3000) == time_to_frame(value, FPS, 3000)
    story = [_beat(3, 3.21, 4.0), _beat(1, 0.4, 1.9), _beat(2, 1.9, 3.21)]
    segments = beat_segments(story, duration=4.0, fps=FPS)
    assert [s.beat.id for s in segments] == ["b1", "b2", "b3"]
    assert segments[0].previous_beat is None and segments[2].previous_beat.id == "b2"
    for left, right in zip(segments, segments[1:]):
        assert left.start_frame + left.frame_count == right.start_frame  # contiguous, no gap
    assert segments[-1].start_frame + segments[-1].frame_count == 120
    assert "beat_segments(" in inspect.getsource(FFmpegRenderer.render)


# -- renderer executes, never decides -------------------------------------------------------
class _Capture(FFmpegRenderer):
    def __init__(self):
        super().__init__("ffmpeg")
        self.graphs: dict[str, list[str]] = {}

    def _encode_args(self, filters, target, fps, frame_count):
        self.graphs[target.stem] = list(filters)
        return []

    def _run(self, command, message):
        return None


def _ink(path: Path, box=(8, 8, 56, 56), size=(64, 64)) -> None:
    from PIL import Image

    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste((0, 0, 0, 255), box)
    image.save(path)


def _graph(scene: Scene, rows, tmp_path: Path) -> list[str]:
    for asset in scene.assets:
        if not asset.image_path.exists():
            _ink(asset.image_path)
    plan_ = scene.render_plan(rows)
    renderer = _Capture()
    segment = beat_segments(plan_.story, duration=plan_.duration, fps=FPS)[1]
    renderer._render_beat_segment(
        plan_, segment.beat, segment.previous_beat, segment.start_frame / FPS, segment.frame_count,
        tmp_path / "0002-b2.mp4", {a.id: a for a in plan_.assets},
        {c.beat_id: c for c in plan_.composition}, {(c.beat_id, c.asset_id): c for c in plan_.motion})
    return renderer.graphs["0002-b2"]


def _old(graph: list[str]) -> list[str]:
    return [f for f in graph if "old" in f.rsplit("[", 1)[-1] or f.endswith("[bridgebase]")]


def test_renderer_executes_exact_end_as_one_group_fade_without_the_legacy_drift(tmp_path) -> None:
    scene = Scene(lead=10, opener=NEW_ON_OLD, root=tmp_path)
    row = scene.plan()
    graph = _graph(scene, [row], tmp_path)
    legacy = _graph(scene, [], tmp_path)
    fades = [f for f in graph if "fade=t=out" in f]
    assert len(fades) == 1 and fades[0].endswith("[oldrelease]")       # one clock for the scene
    assert f"st={4 / FPS:.6f}:d={6 / FPS:.6f}:alpha=1" in fades[0]     # frames 4..10 of the segment
    assert any(f.startswith("color=c=white@0.0:") and f.endswith("[oldbase0]") for f in graph)
    assert not any("fade=t=out" in f for f in legacy)
    assert any(f.startswith("color=c=white:") and f.endswith("[oldbase0]") for f in legacy)
    moving = [f for f in _old(legacy) if "overlay=x='" in f and "+(0)*" not in f.split(":y=")[0]]
    assert moving                                                      # certified drift exists...
    assert all("+(0)*" in f.split(":y=")[0] and "+(0)*" in f.split(":y=")[1]
               for f in _old(graph) if "overlay=x='" in f)             # ...and is not stacked on the fade
    assert [f for f in graph if f not in _old(graph)] == [f for f in legacy if f not in _old(legacy)]


def test_renderer_keeps_the_certified_boundary_whenever_the_release_abstains(tmp_path) -> None:
    scene = Scene(lead=3, opener=NEW_ON_OLD, root=tmp_path)
    assert scene.plan().mode == "HARD_CUT"
    assert _graph(scene, None, tmp_path) == _graph(scene, [], tmp_path)   # abstention == Sprint 4.4
    legacy_plan = RenderPlan.model_validate(json.loads(scene.render_plan([]).model_dump_json()) | {})
    payload = json.loads(legacy_plan.model_dump_json())
    payload.pop("scene_boundaries")
    assert RenderPlan.model_validate(payload).scene_boundaries == []     # older plans still load


def test_renderer_fails_closed_on_any_release_it_cannot_execute_exactly(tmp_path) -> None:
    scene = Scene(lead=10, opener=NEW_ON_OLD, root=tmp_path)
    row, legacy = scene.plan(), _graph(scene, [], tmp_path)
    frame = 1 / FPS
    broken = [
        row.model_copy(update={"opener_at": row.opener_at + frame, "release_end": row.release_end + frame}),
        row.model_copy(update={"release_start": row.release_start + 0.011}),      # off the frame grid
        row.model_copy(update={"from_beat_id": "other"}),
        row.model_copy(update={"release_end": row.release_end + frame}),          # EXACT_END must end on the opener
        row.model_copy(update={"mode": "OVERLAP"}),                               # OVERLAP must pass the opener
        row.model_copy(update={"release_start": row.release_start - 1.0}),        # before the segment
        row.model_copy(update={"release_start": None}),
    ]
    for bad in broken:
        assert _graph(scene, [bad], tmp_path) == legacy
    plan_ = scene.render_plan([row])
    window = dict(plan=plan_, beat=scene.story[1], previous_beat=scene.story[0], has_outgoing=True,
                  incoming_start=10 / FPS, segment_start=2.0, frame_count=90)
    execute = FFmpegRenderer._scene_release_window
    assert execute(transition_mode=SceneTransitionMode.MOTION_HANDOFF, **window) == pytest.approx(
        (4 / FPS, 6 / FPS, 10.25 / FPS))
    for mode in (SceneTransitionMode.CLEAN_HANDOFF, SceneTransitionMode.OBJECT_HANDOFF,
                 SceneTransitionMode.BLUR_BRIDGE, SceneTransitionMode.NONE):
        assert execute(transition_mode=mode, **window) is None                   # renderer re-checks its own class
    assert execute(transition_mode=SceneTransitionMode.MOTION_HANDOFF, **{**window, "has_outgoing": False}) is None


def test_renderer_holds_no_boundary_semantics_and_the_legacy_policy_is_untouched() -> None:
    import app.render.transition as transition

    execute = inspect.getsource(FFmpegRenderer._scene_release_window)
    for word in ("collision", "footprint", "text_composition", "semantic"):
        assert word not in execute
    for word in ("scene_boundaries", "EXACT_END", "OVERLAP", "SceneBoundaryRelease"):
        assert word not in inspect.getsource(transition)
    import app.pipeline as pipeline

    source = inspect.getsource(pipeline)
    assert (source.index("require_text_render_contract(") < source.index("self.scene_boundaries.plan(")
            < source.index("self.render_planner.compile("))
    assert "scene_boundaries=scene_boundaries" in source


# -- encoded frames -------------------------------------------------------------------------
def _encode(scene: Scene, rows, workspace: Path) -> np.ndarray:
    for asset in scene.assets:
        if not asset.image_path.exists():
            _ink(asset.image_path)
    workspace.mkdir(parents=True, exist_ok=True)
    video = FFmpegRenderer("ffmpeg").render(scene.render_plan(rows), workspace / "video.mp4")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", "scale=480:270,format=gray",
                          "-f", "rawvideo", "pipe:1"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, 270, 480).astype(float)


def _region(box, pad: float = 0.0):
    x, y, w, h = box
    return (slice(int((y - h / 2 + pad) * 270), int((y + h / 2 - pad) * 270)),
            slice(int((x - w / 2 + pad) * 480), int((x + w / 2 - pad) * 480)))


def _darkness(frames: np.ndarray, box, pad: float = 0.06) -> np.ndarray:
    return 1.0 - frames[(slice(None), *_region(box, pad))].mean(axis=(1, 2)) / 255.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_exact_end_fades_the_old_scene_to_zero_on_the_opener_frame(tmp_path) -> None:
    scene = Scene(lead=10, opener=NEW_CLEAR, root=tmp_path)
    row = scene.plan().model_copy(update={"mode": "EXACT_END"})
    exact = row.model_copy(update={"release_start": row.opener_at - 6 / FPS, "release_end": row.opener_at})
    frames, legacy = _encode(scene, [exact], tmp_path / "exact"), _encode(scene, [], tmp_path / "legacy")
    assert frames.shape == legacy.shape == (150, 270, 480)               # no duration change
    b = 60                                                               # first frame of the new beat
    for old in (OLD_LEFT, OLD_RIGHT):
        ink = _darkness(frames, old)
        assert ink[b + 4] > 0.97                                         # still solid before the release
        assert all(ink[n] > ink[n + 1] for n in range(b + 4, b + 10))    # monotonic 6-frame fade
        assert ink[b + 9] > 0.05 and ink[b + 10] < 0.01                  # visible until, gone on, the opener
        assert 0.4 < ink[b + 7] < 0.6                                    # linear: half way at the middle
    left, right = _darkness(frames, OLD_LEFT), _darkness(frames, OLD_RIGHT)
    assert np.abs(left - right)[b:b + 12].max() < 0.02                   # every old layer on one clock
    new = _darkness(frames, NEW_CLEAR)
    assert new[b + 9] < 0.01 and new[b + 10] > 0.97                      # opener keeps its hard reveal
    assert (frames >= 245).reshape(len(frames), -1).mean(axis=1)[b:b + 12].max() < 0.99  # never near-white
    assert frames[:, :20, 220:260].min() >= 250                          # the background is never faded
    assert np.abs(frames[:b] - legacy[:b]).mean() < 0.5                  # previous beat untouched
    assert np.abs(frames[b + 10:] - legacy[b + 10:]).mean() < 0.5        # identical once released
    # No drift under the fade: the artwork never leaves its own Composition box.
    outside = frames[b:b + 10].copy()
    for box in (OLD_LEFT, OLD_RIGHT, NEW_CLEAR, NEW_LATER):
        outside[(slice(None), *_region(box, -0.01))] = 255.0
    assert outside.min() >= 250
    assert (legacy[b + 2:b + 10] < 128).any(axis=0)[_region((0.2, 0.3, 0.3, 0.4))].sum() > (
        (legacy[b] < 128)[_region((0.2, 0.3, 0.3, 0.4))].sum())           # the certified cut did drift


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_overlap_keeps_old_artwork_only_four_frames_past_the_opener(tmp_path) -> None:
    scene = Scene(lead=10, root=tmp_path)
    row = scene.plan()
    assert row.mode == "OVERLAP"
    frames = _encode(scene, [row], tmp_path / "overlap")
    b = 60
    old, new = _darkness(frames, OLD_LEFT), _darkness(frames, NEW_CLEAR)
    assert old[b + 8] > 0.97 and new[b + 10] > 0.97                       # release starts 2 frames early
    assert all(old[n] > old[n + 1] for n in range(b + 8, b + 14))
    assert old[b + 13] > 0.05 and old[b + 14] < 0.01                      # zero 4 frames after the opener
    assert old[b + 10] == pytest.approx(4 / 6, abs=0.06)                  # both scenes share the opener frame
    assert (frames >= 245).reshape(len(frames), -1).mean(axis=1)[b:b + 16].max() < 0.99


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_pass2_family_layers_leave_on_exactly_the_same_clock(tmp_path) -> None:
    old = {"fam": (0.25, 0.3, 0.3, 0.3), "fam:secondary-01": (0.25, 0.3, 0.3, 0.3), "old_b": OLD_RIGHT}
    family = dict(asset_family_id="fam", render_as_family_canvas=True)
    assets = [_asset("fam", tmp_path, **family),
              _asset("fam:secondary-01", tmp_path, parent_asset_id="fam", **family),
              _asset("old_b", tmp_path), _asset("new_a", tmp_path), _asset("new_b", tmp_path)]
    _ink(assets[0].image_path, (4, 8, 30, 56))                           # each layer inks its own half
    _ink(assets[1].image_path, (34, 8, 60, 56))
    scene = Scene(lead=10, old=old, old_assets=assets, root=tmp_path)
    frames = _encode(scene, None, tmp_path / "family")
    b = 60
    # The 64 px square art is fitted into the box: layer one inks x 0.18-0.24, layer two 0.26-0.32.
    half_a = _darkness(frames, (0.21, 0.3, 0.05, 0.15), 0.0)
    half_b = _darkness(frames, (0.29, 0.3, 0.05, 0.15), 0.0)
    assert half_a[b + 7] > 0.9 and half_a[b + 14] < 0.01
    assert np.abs(half_a - half_b)[b:b + 16].max() < 0.02                 # no seam, no layer left behind
    seam = _darkness(frames, (0.25, 0.3, 0.09, 0.15), 0.0)
    assert seam[b:b + 16].max() <= max(half_a[b:b + 16].max(), half_b[b:b + 16].max()) + 0.02  # no dark stacking


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_real_pipeline_boundary_passes_both_verifiers(tmp_path) -> None:
    from app.final import FinalExporter, FinalMediaVerifier
    from app.motion import EntryMotionGrammar
    from app.render import RenderPlanner
    from app.render.verification import EncodedMotionVerifier
    from app.text import TextPlanner
    from tests.visual.test_sprint_4_2_semantic_relationship_flow import flow_scene, plan

    planned = plan([flow_scene(), flow_scene()], tmp_path=tmp_path / "pkg")
    motion = EntryMotionGrammar().apply(planned.motion, composition=planned.composition,
                                        choreography=planned.choreography, assets=planned.assets)
    text = TextPlanner().plan(transcript=planned.transcript, story=planned.story, assets=planned.assets,
                              package=planned.package, choreography=planned.choreography)
    rows = SceneBoundaryPlanner().plan(story=planned.story, composition=planned.composition, motion=motion,
                                       assets=planned.assets, duration=planned.transcript.duration, text=text)
    assert len(rows) == len(planned.story) - 1 and all(r.reason for r in rows)
    workspace = tmp_path / "render"
    workspace.mkdir()
    plan_, path = RenderPlanner().compile(planned.transcript, planned.assets, planned.story, planned.composition,
                                          motion, workspace, text=text, scene_boundaries=rows)
    assert json.loads(path.read_text(encoding="utf-8"))["scene_boundaries"][0]["mode"] == rows[0].mode
    video = FFmpegRenderer("ffmpeg").render(plan_, workspace / "video.mp4")
    report = EncodedMotionVerifier().inspect(video=video, plan=plan_)
    assert report.ok, report.violations
    audio = tmp_path / "audio.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=220:duration={float(plan_.duration):.3f}", str(audio)], check=True)
    final = FinalExporter("ffmpeg").mux(video, audio, tmp_path / "final.mp4")
    FinalMediaVerifier("ffprobe", "ffmpeg").require(final, audio, first_spoken_start=plan_.story[0].audio_start)


# -- text-owner coupling --------------------------------------------------------------------
OWNER_BOX = (0.75, 0.6, 0.16, 0.24)


def _text_cue(start: float = 1.0, end: float = 1.4, *, authored: bool = True, anchor: str | None = "owner") -> TextCue:
    return TextCue(id="t1", beat_id="b1", text="label", semantic_type="emphasis", source_char_start=0,
                   source_char_end=5, spoken_start=start, spoken_end=end, emphasis_time=start,
                   anchor_asset_id=anchor, style_id="emphasis", priority=100,
                   package_evidence=["final_package_text_anchor"] if authored else [])


def _text_scene(tmp_path: Path, extra: dict | None = None):
    boxes = {"owner": OWNER_BOX, "other": (0.2, 0.3, 0.2, 0.3), **(extra or {})}
    assets = {a: _asset(a, tmp_path) for a in boxes}
    for asset in assets.values():
        _ink(asset.image_path, (0, 0, 64, 64))
    return _beat(1, 0.0, 4.0), _layout("b1", boxes), assets


def _abstention(cue: TextCue, *, owner_start: float = 0.5, scene_start: float = 0.2, visible_end: float = 2.0,
                beat: StoryBeat | None = None) -> str | None:
    beat = beat or _beat(1, 0.0, 4.0)
    layout = _layout("b1", {"owner": OWNER_BOX, "other": (0.2, 0.3, 0.2, 0.3)})
    motion = {("b1", "owner"): _cue("b1", "owner", owner_start), ("b1", "other"): _cue("b1", "other", scene_start)}
    return TextCompositionPlanner._owner_abstention(beat, layout, layout, cue, visible_end, motion)


def test_text_is_coupled_only_on_explicit_ownership_with_the_owner_on_screen() -> None:
    assert _abstention(_text_cue()) is None                                   # authored, owner already visible
    assert _abstention(_text_cue(authored=False)) == "ownership_not_authored"
    assert _abstention(_text_cue(anchor=None)) == "ownership_not_authored"
    assert _abstention(_text_cue(anchor="ghost")) == "owner_not_in_scene"
    assert _abstention(_text_cue(), owner_start=2.5) == "future_owner"        # owner arrives after the text left
    assert _abstention(_text_cue(), owner_start=1.2) == "owner_absent_when_text_appears"
    assert _abstention(_text_cue(start=0.1, end=0.4), owner_start=0.5, visible_end=0.45) == "future_owner"
    assert _abstention(_text_cue(start=0.1, end=0.6), owner_start=0.5, visible_end=1.0) == "held_previous_scene"
    assert _abstention(_text_cue(), visible_end=4.5) == "owner_not_present_through_text"
    inactive = _beat(1, 0.0, 4.0, active_visual_semantic_state={"other": "x"})
    assert _abstention(_text_cue(), beat=inactive) == "owner_not_in_scene"
    assert _abstention(_text_cue(start=0.5), owner_start=0.5) is None         # appears with its owner


def _far(director: TextPlacementDirector, cue: TextCue, x: float = 0.25, y: float = 0.85) -> PlacementResult:
    width, height = director.estimated_box(cue)
    item = TextLayoutItem(text_cue_id=cue.id, x=x, y=y, max_width=width, anchor_asset_id="owner", placement="bottom")
    return PlacementResult(item=item, box=director._box(x, y, width, height), zone="bottom", score=0.0,
                           visual_overlap=0.0, text_overlap=0.0)


def _couple(tmp_path, *, extra=None, concurrent=(), connectors=(), current=None):
    beat, layout, assets = _text_scene(tmp_path, extra)
    director, cue = TextPlacementDirector(), _text_cue()
    current = current or _far(director, cue)
    owner = next(i for i in layout.items if i.asset_id == "owner")
    result, audit = director.couple_to_owner(
        beat=beat, visual=layout, cue=cue, owner=owner, current=current, concurrent_text=list(concurrent),
        assets_by_id=assets, connectors=list(connectors))
    return director, cue, current, layout, assets, result, audit


def test_a_distant_label_moves_beside_its_owner_without_touching_any_artwork(tmp_path) -> None:
    director, cue, current, layout, assets, result, audit = _couple(tmp_path)
    assert result is not None and audit["decision"] == "moved"
    width, height = director.estimated_box(cue)
    assert audit["gap_before_px"] > audit["attach_limit_px"] == pytest.approx(height * H, abs=0.1)
    assert audit["gap_after_px"] <= audit["attach_limit_px"]                  # attached: within one label height
    assert audit["gap_after_px"] > 0                                          # ...and not touching the owner
    occupancy = director.occupancy.build(list(layout.items), assets)
    padded = director._expand(result.box, *director._BASE_PROTECTED_PAD)
    assert director.occupancy.overlap(occupancy, padded).occupied_pixels == 0  # existing padding stays clear
    assert director._edge_penalty(result.box) == 0.0                          # inside the safe frame
    assert result.item.font_scale == current.item.font_scale and result.item.max_width == current.item.max_width
    assert result.item.text_cue_id == cue.id and result.item.z == current.item.z
    assert result.item.placement.startswith("anchor_")


def test_label_already_beside_its_owner_keeps_its_certified_placement(tmp_path) -> None:
    director, cue = TextPlacementDirector(), _text_cue()
    near = _far(director, cue, x=OWNER_BOX[0], y=OWNER_BOX[1] - 0.25)
    *_, result, audit = _couple(tmp_path, current=near)
    assert result is None and (audit["decision"], audit["reason"]) == ("kept", "already_attached")


def test_baseline_placement_is_preserved_when_no_safe_local_slot_exists(tmp_path) -> None:
    ring = {f"wall{n}": box for n, box in enumerate([
        (0.75, 0.25, 0.5, 0.3), (0.75, 0.93, 0.5, 0.14), (0.52, 0.6, 0.2, 0.6), (0.95, 0.6, 0.1, 0.6)])}
    *_, result, audit = _couple(tmp_path, extra=ring)
    assert result is None and (audit["decision"], audit["reason"]) == ("kept", "no_safe_local_slot")


def test_local_slot_avoids_captions_and_authored_connectors(tmp_path) -> None:
    director, cue, _, _, _, free, _ = _couple(tmp_path)
    taken = PlacedTextRegion(cue_id="t0", start=0.0, end=9.0, box=free.box, zone=free.zone)
    *_, moved, audit = _couple(tmp_path, concurrent=[taken])
    assert moved is None or director._intersection_ratio(moved.box, free.box) == 0.0   # never on a caption
    box = free.box
    line = ((box[0] * W - 50, (box[1] + box[3]) / 2 * H), (box[2] * W + 50, (box[1] + box[3]) / 2 * H))
    *_, rerouted, _ = _couple(tmp_path, connectors=[line])
    assert rerouted is None or rerouted.box != free.box                                 # never on a connector


def test_text_planner_changes_placement_only_and_audits_every_cue(tmp_path) -> None:
    beat, layout, assets = _text_scene(tmp_path)
    motion = [_cue("b1", "owner", 0.2), _cue("b1", "other", 0.2)]
    cues = [_text_cue(), _text_cue(authored=False).model_copy(update={"id": "t2", "spoken_start": 2.4,
                                                                    "spoken_end": 2.8, "emphasis_time": 2.4})]
    snapshot = [c.model_dump() for c in cues]
    planner = TextCompositionPlanner()
    placed = planner.plan([beat], [layout], cues, list(assets.values()), visual_motion=motion)
    baseline = TextCompositionPlanner()
    baseline._couple_to_authored_owner = lambda **kw: kw["result"]
    certified = baseline.plan([beat], [layout], cues, list(assets.values()), visual_motion=motion)
    assert [c.model_dump() for c in cues] == snapshot                         # text timing is never touched
    assert {r["text_cue_id"] for r in planner.owner_coupling} == {"t1", "t2"}
    rows = {r["text_cue_id"]: r for r in planner.owner_coupling}
    assert (rows["t2"]["decision"], rows["t2"]["reason"]) == ("abstained", "ownership_not_authored")
    new = {i.text_cue_id: i for i in placed[0].items}
    old = {i.text_cue_id: i for i in certified[0].items}
    assert new["t2"] == old["t2"]                                             # abstention == certified placement
    if rows["t1"]["decision"] != "moved":
        assert new["t1"] == old["t1"]
    assert {k: v for k, v in new["t1"].model_dump().items() if k not in ("x", "y", "placement")} == (
        {k: v for k, v in old["t1"].model_dump().items() if k not in ("x", "y", "placement")})


def test_owner_coupling_never_steers_the_scene_lane_of_later_cues() -> None:
    import app.composition.text as text_module

    source = inspect.getsource(text_module.TextCompositionPlanner.plan)
    lane = source[source.index("preferred_zone_by_scene[beat.scene_id] ="):].splitlines()[1]
    assert "certified.zone" in lane and "result.zone" not in lane
    assert "certified.visual_overlap <= 0.015" in source
