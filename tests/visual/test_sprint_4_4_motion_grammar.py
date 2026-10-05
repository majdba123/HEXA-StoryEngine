"""Sprint 4.4 - reference-derived entry motion (permanent regression gate).

Contracts, not pixels: every newly entering asset gets an opacity entry on exactly its Story
window (reveal -> settle); the reveal frame is already visible, nothing shows earlier, and
opacity is exactly 1.0 by settle. The Choreography leader also scales in from ~0.94 when no
other motion owns it. RESULT, relation participants, support and Pass2 families get opacity
only; a family shares one clock or fails closed. Sprint 4.1/4.2 motion, Story timing and
Composition geometry are inputs only. Encoded tests prove the ramp in real frames.
"""
from __future__ import annotations

import inspect
import json
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pytest

import app.motion.entry_grammar as grammar_module
from app.choreography import ChoreographyDirective, ChoreographyPlan, InteractionIntent, SequencePhase
from app.models import LayoutItem, MotionCue, MotionSegment, VisualAsset
from app.motion import EntryMotionGrammar, ReferenceMotionEnforcer
from app.motion.collision import box
from app.motion.entry_grammar import ENTRY_OPACITY_INITIAL, ENTRY_SCALE_IN
from app.render.renderer import FFmpegRenderer
from app.shared.errors import StageFailedError
from app.shared.handoff import LayerHandoffValidator
from tests.visual.test_sprint_4_2_semantic_relationship_flow import Planned, flow_scene, plan

W, H, FPS = 1920, 1080, 30
# An earlier support element opens the scene (hard cut); the leader then enters with opacity.
LEADER_SCENE = dict(relations=(), events=(), extra=(("note", (700, 700, 200, 180), (1, 1), "supporting"),))


@dataclass
class Pair:
    grammar: Planned
    baseline: Planned


def _with_grammar(planned: Planned) -> Planned:
    motion = EntryMotionGrammar().apply(planned.motion, composition=planned.composition,
                                        choreography=planned.choreography, assets=planned.assets)
    return replace(planned, motion=motion)


def _plan_pair(specs, tmp_path: Path, *, shuffle: bool = False) -> Pair:
    baseline = plan(specs, tmp_path=tmp_path, shuffle=shuffle)  # certified Sprint 4.3 motion
    return Pair(_with_grammar(baseline), baseline)


@pytest.fixture(scope="module")
def leader(tmp_path_factory) -> Pair:
    return _plan_pair([flow_scene(**LEADER_SCENE)], tmp_path_factory.mktemp("leader"))


@pytest.fixture(scope="module")
def handoff(tmp_path_factory) -> Pair:
    return _plan_pair([flow_scene()], tmp_path_factory.mktemp("handoff"))


def _grammar(cue: MotionCue) -> dict:
    return cue.params.get("entry_grammar") or {}


def _strip(cue: MotionCue) -> dict:
    row = cue.model_dump(mode="json")
    row["params"].pop("entry_grammar", None)
    row["params"].pop("entry_opacity", None)
    return row


# -- unit scaffolding ----------------------------------------------------------------------
_STATIC = {"name": "static_reveal_x", "settle_progress": 0.78, "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_in_out_cubic"},
    {"progress": 0.78, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"},
]}
_DIRECTIONAL = {"name": "reference_slide_settle", "settle_progress": 0.78, "keyframes": [
    {"progress": 0.0, "dx": -0.04, "dy": 0.0, "scale": 0.985, "easing": "ease_in_out_cubic"},
    {"progress": 0.78, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"},
]}


def _cue(asset_id: str, start: float = 1.0, duration: float = 0.25, *, program=None, segments=(),
         mode: str = "ENTER", lock: bool = False) -> MotionCue:
    params = {"program": json.loads(json.dumps(program or _STATIC)),
              "semantic_continuity": {"mode": mode}}
    if lock:
        params["render_constraints"] = {"geometry_lock": "authored_footprint"}
    return MotionCue(beat_id="b", asset_id=asset_id, kind="program_v3", start=start,
                     end=start + duration, params=params, segments=list(segments))


def _asset(asset_id: str, **extra) -> VisualAsset:
    return VisualAsset(id=asset_id, scene_id="s", role="supporting",
                       image_path=Path(f"{asset_id}.png"), extraction_method="test", **extra)


def _directive(*, leader=None, result=None) -> ChoreographyDirective:
    interactions = ()
    if result:
        interactions = (InteractionIntent(semantic_action="RESULTS_IN", relationship="RESULTS_IN",
                                          subject_asset_id=None, object_asset_id=None,
                                          result_asset_id=result),)
    return ChoreographyDirective(beat_id="b", sequence_id="q", phase=SequencePhase.SETUP,
                                 action="REVEAL", primary_asset_id=leader, interactions=interactions)


def _run(cues, directive=None, assets=None, *, opener: bool = True) -> dict[str, MotionCue]:
    """Run the grammar on one beat; by default an earlier cue opens the scene first."""
    from app.models import CompositionBeat

    if opener:
        cues = [_cue("opener", 0.0, 0.3), *cues]
        assets = [_asset("opener"), *(assets or [_asset(c.asset_id) for c in cues[1:]])]
    ids = [c.asset_id for c in cues]
    layout = CompositionBeat(beat_id="b", items=[
        LayoutItem(asset_id=a, x=0.15 + 0.2 * n, y=0.5, width=0.2, height=0.3)
        for n, a in enumerate(ids)])
    out = EntryMotionGrammar().apply(
        cues, composition=[layout],
        choreography=ChoreographyPlan(directives=(directive,)) if directive else None,
        assets=assets or [_asset(a) for a in ids])
    return {c.asset_id: c for c in out}


def _fade(cue: MotionCue, *, segment_start: float = 0.0, effective: float | None = None) -> str:
    start = float(cue.start) - segment_start
    return FFmpegRenderer._entry_opacity_filter(
        cue, segment_start=segment_start,
        effective_reveal_start=start if effective is None else effective, fps=FPS)


def _alpha_at(fade: str, t: float) -> float:
    st = float(fade.split("st=")[1].split(":")[0])
    d = float(fade.split(":d=")[1].split(":")[0])
    return max(0.0, min(1.0, (t - st) / d))


# Support: opacity only; the Story window is the clock ----------------------------------------
def test_support_gets_opacity_entry_only_on_its_story_window() -> None:
    out = _run([_cue("support", 1.0, 0.25)])
    cue = out["support"]
    assert cue.params["entry_opacity"] == {"initial": ENTRY_OPACITY_INITIAL, "start": 1.0, "settle": 1.25}
    assert _grammar(cue) == {"opacity": True, "scale_in": False}
    assert cue.params["program"] == _STATIC and (cue.start, cue.end) == (1.0, 1.25)


# Leader: opacity + restrained scale-in ending on identity ------------------------------------
def test_leader_gets_restrained_scale_in_ending_on_identity() -> None:
    cue = _run([_cue("lead")], _directive(leader="lead"))["lead"]
    frames = cue.params["program"]["keyframes"]
    assert _grammar(cue) == {"opacity": True, "scale_in": True}
    assert frames[0]["scale"] == ENTRY_SCALE_IN and 0.90 <= ENTRY_SCALE_IN < 1.0
    assert all(f["dx"] == 0.0 and f["dy"] == 0.0 and f["scale"] <= 1.0 for f in frames)
    assert (frames[-1]["dx"], frames[-1]["dy"], frames[-1]["scale"]) == (0.0, 0.0, 1.0)


# RESULT / protected motion: never a stacked scale --------------------------------------------
def test_result_and_protected_motion_get_opacity_without_stacked_scale() -> None:
    payoff = MotionSegment(phase="PAYOFF", start=1.0, end=1.25, program=dict(_DIRECTIONAL))
    emphasis = MotionSegment(phase="ESTABLISH", start=1.3, end=1.9, semantic_action="EMPHASIZE",
                             program=dict(_DIRECTIONAL))
    for segment in (payoff, emphasis):
        before = _cue("x", segments=[segment])
        cue = _run([before], _directive(leader="x", result="x"))["x"]
        assert _grammar(cue) == {"opacity": True, "scale_in": False}
        assert cue.params["program"] == before.params["program"] and cue.segments == before.segments


# Longer certified directional entry keeps its motion and gains opacity ------------------------
def test_directional_entry_is_preserved_and_gains_opacity() -> None:
    before = _cue("lead", duration=0.6, program=_DIRECTIONAL)
    cue = _run([before], _directive(leader="lead"))["lead"]
    assert cue.params["program"] == before.params["program"]
    assert _grammar(cue) == {"opacity": True, "scale_in": False}


# Short entry opacity survives the Reference contract ------------------------------------------
def test_short_entry_opacity_survives_reference_motion_enforcer() -> None:
    cues = list(_run([_cue("lead", duration=0.25, program=_DIRECTIONAL), _cue("s", 2.0, 0.2)],
                     _directive(leader="lead")).values())
    enforced = {c.asset_id: c for c in ReferenceMotionEnforcer().enforce(cues)}
    for key in ("lead", "s"):
        assert enforced[key].params["entry_opacity"]["initial"] == ENTRY_OPACITY_INITIAL
    assert all(f["dx"] == 0.0 for f in enforced["lead"].params["program"]["keyframes"])
    scaled = _run([_cue("lead", duration=0.25)], _directive(leader="lead"))["lead"]
    assert ReferenceMotionEnforcer().enforce([scaled])[0] == scaled  # scale-in is not directional


# Fail closed --------------------------------------------------------------------------------
def test_ineligible_entries_keep_the_certified_hard_reveal() -> None:
    early = MotionSegment(phase="ESTABLISH", start=0.5, end=0.9, program=dict(_STATIC))
    cases = {
        "not_entering": _cue("a", mode="PERSIST"),
        "short_window": _cue("a", duration=0.06),
        "visible_before_reveal": _cue("a", segments=[early]),
    }
    for reason, before in cases.items():
        cue = _run([before], _directive(leader="a"))["a"]
        assert _grammar(cue) == {"opacity": False, "reason": reason}
        assert "entry_opacity" not in cue.params and cue.params["program"] == before.params["program"]
        assert _fade(cue) == ""


def test_scene_opener_is_chosen_by_existing_authority_never_by_geometry() -> None:
    # A faint first frame over an empty canvas is a near-white flash (FinalMediaVerifier), so
    # one opener keeps the certified hard reveal. Motion never ranks importance itself.
    from app.choreography import SemanticEventFlow
    from app.models import CompositionBeat

    def run(directive, ids=("small", "big", "later"), assets=None):
        cues = [_cue(a, 1.5 if a == "later" else 1.0 + 0.01 * n) for n, a in enumerate(ids)]
        sizes = {"small": 0.08, "big": 0.4}
        layout = CompositionBeat(beat_id="b", items=[
            LayoutItem(asset_id=a, x=0.2 + 0.2 * n, y=0.5, width=sizes.get(a.split(":")[0], 0.1),
                       height=sizes.get(a.split(":")[0], 0.1)) for n, a in enumerate(ids)])
        out = EntryMotionGrammar().apply(
            cues, composition=[layout], choreography=ChoreographyPlan(directives=(directive,)),
            assets=assets or [_asset(a) for a in ids])
        return {c.asset_id: _grammar(c) for c in out}

    hard = {"opacity": False, "reason": "opens_scene"}
    led = replace(_directive(), event_flows=(SemanticEventFlow(event_id="E", leader_asset_ids=("small",)),))
    out = run(led)  # the authored leader opens, even though it is the smaller element
    assert out["small"] == hard and out["big"]["opacity"] is True and out["later"]["opacity"] is True
    out = run(_directive(leader="small"))  # no event leader: Choreography primary
    assert out["small"] == hard and out["big"]["opacity"] is True
    out = run(_directive())  # no authority at all: every opening family fails closed
    assert out["small"] == hard and out["big"] == hard and out["later"]["opacity"] is True
    two = replace(_directive(), event_flows=(SemanticEventFlow(event_id="E", leader_asset_ids=("small", "big")),))
    assert run(two)["small"] == hard and run(two)["big"] == hard  # ambiguous leaders: fail closed
    out = run(_directive(), ids=("small", "later"))  # a single opening family needs no choice
    assert out["small"] == hard and out["later"]["opacity"] is True
    family = [_asset("big", render_as_family_canvas=True),
              _asset("big:secondary-01", parent_asset_id="big", asset_family_id="big",
                     render_as_family_canvas=True), _asset("small"), _asset("later")]
    led_big = replace(_directive(), event_flows=(SemanticEventFlow(event_id="E", leader_asset_ids=("big",)),))
    out = run(led_big, ids=("big", "big:secondary-01", "small", "later"), assets=family)
    assert out["big"] == hard and out["big:secondary-01"] == hard  # one family, one opening behavior
    assert out["small"]["opacity"] is True


# Pass2 family: one synchronized clock, or nothing --------------------------------------------
def test_pass2_family_layers_share_one_opacity_clock_or_fail_closed() -> None:
    assets = [_asset("m", render_as_family_canvas=True),
              _asset("m:secondary-01", parent_asset_id="m", asset_family_id="m",
                     render_as_family_canvas=True)]
    out = _run([_cue("m"), _cue("m:secondary-01", lock=True)], _directive(leader="m"), assets)
    assert out["m"].params["entry_opacity"] == out["m:secondary-01"].params["entry_opacity"]
    assert _fade(out["m"]) == _fade(out["m:secondary-01"]) != ""
    for key in ("m", "m:secondary-01"):  # rigid unit: no scale gesture on any layer
        cue = out[key]
        assert _grammar(cue) == {"opacity": True, "scale_in": False}
        assert cue.params["program"] == _STATIC
    split = _run([_cue("m", 1.0), _cue("m:secondary-01", 1.4, lock=True)], _directive(leader="m"), assets)
    for key in ("m", "m:secondary-01"):
        cue = split[key]
        assert _grammar(cue) == {"opacity": False, "reason": "family_clock_mismatch"}
        assert _fade(cue) == ""


# Renderer clock: visible at reveal, never earlier, exactly 1.0 by settle ---------------------
def test_renderer_clock_is_visible_at_reveal_and_full_by_settle() -> None:
    cue = _run([_cue("a", 1.013, 0.25)])["a"]
    fade = _fade(cue)
    first = np.ceil(1.013 * FPS) / FPS
    assert _alpha_at(fade, first) == pytest.approx(ENTRY_OPACITY_INITIAL, abs=1e-4)
    assert _alpha_at(fade, cue.end) == pytest.approx(1.0, abs=1e-4)
    assert 0.0 < _alpha_at(fade, first + 1 / FPS) < 1.0
    assert _fade(cue, segment_start=0.5) != ""  # segment-local time
    assert _alpha_at(_fade(cue, segment_start=0.5), first - 0.5) == pytest.approx(ENTRY_OPACITY_INITIAL, abs=1e-4)
    assert _fade(cue, effective=0.5) == ""       # already visible earlier: never hide it
    assert _fade(cue, segment_start=1.0) == ""   # no room for the pre-roll: keep the hard reveal
    assert FFmpegRenderer._entry_opacity_filter(None, segment_start=0.0, effective_reveal_start=0.0, fps=FPS) == ""
    broken = cue.model_copy(update={"params": {**cue.params, "entry_opacity": {"initial": 1.5}}})
    assert _fade(broken) == ""


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
@pytest.mark.parametrize("start,duration", [(0.5343, 0.131), (0.5010, 0.25), (0.5661, 0.11)])
def test_encoded_alpha_clock_is_exact_on_the_reveal_frame(start, duration, tmp_path) -> None:
    # Real FFmpeg, production filter text: short non-frame-aligned windows must still show the
    # reveal frame at the initial opacity (never 0) and reach full opacity at the settle frame.
    from PIL import Image

    Image.new("RGBA", (64, 64), (0, 0, 0, 255)).save(tmp_path / "ink.png")
    cue = _run([_cue("a", start, duration)])["a"]
    fade = _fade(cue)
    assert fade
    first = int(np.ceil(start * FPS - 1e-9))
    enable = FFmpegRenderer._frame_threshold(first, FPS)
    graph = (f"[1:v]format=rgba,loop=loop=-1:size=1:start=0,trim=duration=1,setpts=PTS-STARTPTS{fade}[a];"
             f"[0:v][a]overlay=enable='gte(t,{enable:.6f})':eof_action=pass,format=gray[v]")
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=white:s=64x64:r={FPS}:d=1",
         "-loop", "1", "-framerate", str(FPS), "-i", str(tmp_path / "ink.png"),
         "-filter_complex", graph, "-map", "[v]", "-frames:v", str(FPS), "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(FPS, 64, 64)
    assert len(raw) == FPS * 64 * 64                                   # no duration change
    ink = 1.0 - frames.mean(axis=(1, 2)) / 255.0
    settle = int(np.ceil((start + duration) * FPS - 1e-9))
    assert frames[:first].min() >= 254                                 # no pixel before reveal
    assert frames[settle:].max() <= 1                                  # final opacity exactly 1.0
    assert ink[first] == pytest.approx(ENTRY_OPACITY_INITIAL, abs=0.03)  # reveal frame is visible
    assert all(ink[n] < ink[n + 1] for n in range(first, settle - 1))  # monotonic ramp
    assert ink[settle] > 0.99                                          # exactly full by settle


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_pass2_family_layers_share_the_exact_same_opacity_clock(tmp_path) -> None:
    from PIL import Image

    assets = [_asset("m", render_as_family_canvas=True),
              _asset("m:secondary-01", parent_asset_id="m", asset_family_id="m",
                     render_as_family_canvas=True)]
    out = _run([_cue("m", 0.5343, 0.2), _cue("m:secondary-01", 0.5343, 0.2, lock=True)],
               _directive(leader="m"), assets)
    fades = [_fade(out["m"]), _fade(out["m:secondary-01"])]
    assert fades[0] == fades[1] != ""
    for n, x in enumerate((0, 32)):  # each layer inks its own half of the canvas
        layer = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        layer.paste((0, 0, 0, 255), (x, 0, x + 32, 64))
        layer.save(tmp_path / f"layer{n}.png")
    chain = "format=rgba,loop=loop=-1:size=1:start=0,trim=duration=1,setpts=PTS-STARTPTS"
    graph = (f"[1:v]{chain}{fades[0]}[a];[2:v]{chain}{fades[1]}[b];"
             "[0:v][a]overlay=eof_action=pass[m];[m][b]overlay=eof_action=pass,format=gray[v]")
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=white:s=64x64:r={FPS}:d=1",
         "-loop", "1", "-framerate", str(FPS), "-i", str(tmp_path / "layer0.png"),
         "-loop", "1", "-framerate", str(FPS), "-i", str(tmp_path / "layer1.png"),
         "-filter_complex", graph, "-map", "[v]", "-frames:v", str(FPS), "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(FPS, 64, 64).astype(int)
    left, right = frames[:, 8:56, 4:28].mean(axis=(1, 2)), frames[:, 8:56, 36:60].mean(axis=(1, 2))
    assert np.abs(left - right).max() <= 1.0          # identical opacity on every encoded frame
    assert left.min() <= 1 and 30 < left[int(np.ceil(0.5343 * FPS))] < 250  # it does ramp


def _probe(path: Path, *entries: str) -> str:
    return subprocess.run(["ffprobe", "-v", "error", *entries, "-of", "csv=p=0", str(path)],
                          check=True, capture_output=True, text=True).stdout


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_entry_opacity_changes_no_duration_pts_or_av_sync(handoff, tmp_path) -> None:
    from app.final import FinalExporter, FinalMediaVerifier

    grammar, plan_ = _render(handoff.grammar, tmp_path / "grammar")
    baseline, _ = _render(handoff.baseline, tmp_path / "baseline")
    assert any("fade=t=in" in g.read_text(encoding="utf-8") for g in (tmp_path / "grammar").rglob("*.ffgraph"))
    audio = tmp_path / "audio.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=220:duration={float(plan_.duration):.3f}", str(audio)], check=True)
    rows = {}
    for tag, video in (("grammar", grammar), ("baseline", baseline)):
        pts = [float(x) for x in _probe(video, "-select_streams", "v", "-show_entries",
                                        "packet=pts_time").split() if x.strip(",")]
        final = FinalExporter("ffmpeg").mux(video, audio, tmp_path / f"{tag}.mp4")
        issues = FinalMediaVerifier("ffprobe", "ffmpeg").inspect(
            final, audio, first_spoken_start=plan_.story[0].audio_start)
        rows[tag] = {
            "pts": pts,
            "stream": _probe(video, "-select_streams", "v", "-show_entries",
                             "stream=codec_name,r_frame_rate,avg_frame_rate,nb_frames,duration"),
            "final": _probe(final, "-show_entries", "stream=codec_name,duration,start_time"),
            "issues": [i.code for i in issues],
        }
    assert rows["grammar"]["pts"] == rows["baseline"]["pts"]                # no PTS change
    assert rows["grammar"]["pts"] == sorted(set(rows["grammar"]["pts"]))    # strictly increasing
    assert rows["grammar"]["stream"] == rows["baseline"]["stream"]          # CFR 30, same frames/duration
    assert "30/1" in rows["grammar"]["stream"]
    assert rows["grammar"]["final"] == rows["baseline"]["final"]            # A/V start + durations
    assert rows["grammar"]["issues"] == rows["baseline"]["issues"] == []


# Protected Sprint 4.1 / 4.2 behavior and Story/Composition are unchanged ----------------------
def test_protected_motion_story_and_composition_are_unchanged(handoff, leader) -> None:
    for pair in (handoff, leader):
        g, b = pair.grammar, pair.baseline
        assert [(c.beat_id, c.asset_id, c.start, c.end, c.kind, c.segments) for c in g.motion] == [
            (c.beat_id, c.asset_id, c.start, c.end, c.kind, c.segments) for c in b.motion]
        for new, old in zip(g.motion, b.motion):
            if not _grammar(new).get("scale_in"):
                assert _strip(new) == _strip(old)
        assert [x.model_dump(mode="json") for x in g.story] == [x.model_dump(mode="json") for x in b.story]
        assert [x.model_dump(mode="json") for x in g.composition] == g.composition_before
    assert handoff.grammar.flows() == handoff.baseline.flows()
    assert [s for c in handoff.grammar.motion for s in c.segments if s.semantic_action == "FOCUS_HANDOFF"]


# Final identity + handoff contract on the final plan ------------------------------------------
def test_final_plan_ends_on_identity_and_satisfies_the_handoff_contract(leader, handoff) -> None:
    for pair in (leader, handoff):
        final = pair.grammar
        LayerHandoffValidator.require_motion_for_text_and_render(
            story=final.story, assets=final.assets, composition=final.composition,
            choreography=final.choreography, motion=final.motion)
        for cue in final.motion:
            for program in [cue.params["program"], *(s.program for s in cue.segments)]:
                last = (program.get("keyframes") or [{"dx": 0.0, "dy": 0.0, "scale": 1.0}])[-1]
                assert (last["dx"], last["dy"], last["scale"]) == (0.0, 0.0, 1.0)
            clock = cue.params.get("entry_opacity")
            if clock:
                assert (clock["start"], clock["settle"]) == (cue.start, cue.end)
    (scaled,) = [c for c in leader.grammar.motion if _grammar(c).get("scale_in")]
    assert scaled.asset_id == leader.grammar.choreography.directives[0].primary_asset_id
    bad = scaled.model_copy(update={"params": {**scaled.params, "entry_opacity": {
        "initial": ENTRY_OPACITY_INITIAL, "start": scaled.start, "settle": scaled.end + 0.5}}})
    motion = [bad if c is scaled else c for c in leader.grammar.motion]
    with pytest.raises(StageFailedError):
        LayerHandoffValidator.require_motion_for_text_and_render(
            story=leader.grammar.story, assets=leader.grammar.assets,
            composition=leader.grammar.composition, choreography=leader.grammar.choreography,
            motion=motion)


# Determinism, input-order independence, no package-specific logic -----------------------------
def test_planning_is_deterministic_and_generic(tmp_path) -> None:
    first = _plan_pair([flow_scene(**LEADER_SCENE)], tmp_path / "a").grammar
    again = _plan_pair([flow_scene(**LEADER_SCENE)], tmp_path / "b").grammar
    shuffled = _plan_pair([flow_scene(**LEADER_SCENE)], tmp_path / "c", shuffle=True).grammar
    dump = lambda p: [json.dumps(c.model_dump(mode="json"), sort_keys=True) for c in p.motion]  # noqa: E731
    assert dump(first) == dump(again) and sorted(dump(first)) == sorted(dump(shuffled))
    source = inspect.getsource(grammar_module).upper()
    for token in ("SCENE_0", "BLACK_HAT", "INSIDER", "HACKTIVIST", "WHITE_HAT", "MAIN_HEXA", "PROMO"):
        assert token not in source


def test_pipeline_applies_entry_grammar_after_the_reference_contract() -> None:
    import app.pipeline as pipeline_module

    source = inspect.getsource(pipeline_module)
    assert (source.index("self.motion_reference.enforce(") < source.index("self.entry_grammar.apply(")
            < source.index("require_motion_for_text_and_render("))


# Encoded frames: reveal visible, nothing early, full by settle, exact rest, verifiers ---------
def _frame(video: Path, index: int) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"select=eq(n\\,{index}),format=gray",
         "-frames:v", "1", "-fps_mode", "passthrough", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(H, W).astype(float)


def _render(planned: Planned, workspace: Path):
    from app.render import RenderPlanner
    from app.text import TextPlanner

    text = TextPlanner().plan(transcript=planned.transcript, story=planned.story,
                              assets=planned.assets, package=planned.package,
                              choreography=planned.choreography)
    workspace.mkdir(parents=True)
    plan_, _ = RenderPlanner().compile(planned.transcript, planned.assets, planned.story,
                                       planned.composition, planned.motion, workspace, text=text)
    return FFmpegRenderer("ffmpeg").render(plan_, workspace / "video.mp4"), plan_


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_entry_is_visible_at_reveal_never_early_and_full_by_settle(leader, tmp_path) -> None:
    from app.render.verification import EncodedMotionVerifier

    grammar, final_plan = _render(leader.grammar, tmp_path / "grammar")
    baseline, _ = _render(leader.baseline, tmp_path / "baseline")
    report = EncodedMotionVerifier().inspect(video=grammar, plan=final_plan)
    assert report.ok, report.violations

    checked = 0
    for cue in leader.grammar.motion:
        if not _grammar(cue).get("opacity"):
            continue
        item = next(i for i in leader.grammar.composition[0].items if i.asset_id == cue.asset_id)
        left, top, right, bottom = box(item, (0.0, 0.0, 1.0))
        region = (slice(int(top * H), int(bottom * H)), slice(int(left * W), int(right * W)))
        reveal = int(np.ceil(cue.start * FPS - 1e-9))
        settle = int(np.ceil(cue.end * FPS - 1e-9))
        blank = 255.0 - _frame(grammar, reveal - 1)[region]
        rest = 255.0 - _frame(grammar, settle + 4)[region]
        ink = lambda n: float((255.0 - _frame(grammar, n)[region] - blank).sum() / (rest - blank).sum())  # noqa: E731
        assert abs(float(blank.mean()) - float((255.0 - _frame(baseline, reveal - 1)[region]).mean())) < 0.5
        assert 0.07 < ink(reveal) < 0.22              # reveal frame visible at ~10-15%, not a pop
        assert ink(reveal) < ink(reveal + 2) <= 1.02  # ramps upward
        assert ink(settle) > 0.97                     # full opacity by settle
        assert np.abs(_frame(grammar, settle + 4)[region] - _frame(baseline, settle + 4)[region]).mean() < 1.0
        assert (255.0 - _frame(baseline, reveal)[region]).sum() > 0.9 * rest.sum()  # 4.3 was a hard cut
        checked += 1
    assert checked >= 1



@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_and_final_media_verifiers_pass_with_entry_opacity(handoff, tmp_path) -> None:
    from app.final import FinalExporter, FinalMediaVerifier
    from app.render.verification import EncodedMotionVerifier

    assert any(_grammar(c).get("opacity") for c in handoff.grammar.motion)
    video, final_plan = _render(handoff.grammar, tmp_path / "render")
    report = EncodedMotionVerifier().inspect(video=video, plan=final_plan)
    assert report.ok, report.violations
    audio = tmp_path / "audio.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=220:duration={float(final_plan.duration):.3f}", str(audio)], check=True)
    final = FinalExporter("ffmpeg").mux(video, audio, tmp_path / "final.mp4")
    FinalMediaVerifier("ffprobe", "ffmpeg").require(  # no white flash, codec, duration, sync
        final, audio, first_spoken_start=final_plan.story[0].audio_start)
