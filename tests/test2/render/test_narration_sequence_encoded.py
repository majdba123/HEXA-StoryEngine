"""Production-planner sequences measured again in decoded FFmpeg pixels."""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
import pytest

from app.canonical import CanonicalRelation
from app.models import MotionCue
from app.shared.errors import StageFailedError
from app.render.renderer import FFmpegRenderer
from app.render.verification import EncodedMotionVerifier
from tests.test3.test_semantic_reveal_focus import Spec, _pipeline, _windows


CASES = {
    "negation-vulnerability-result": [
        Spec("character", "event", 0.10, role="CHARACTER"),
        Spec("negation", "event", 0.55),
        Spec("vulnerability", "event", 1.05),
        Spec("result", "event", 1.55, role="RESULT"),
    ],
    "small-to-largest": [Spec(f"size{i}", "event", 0.1 + i * 0.45) for i in range(4)],
    "account-employee-permission": [
        Spec("account", "event", 0.10), Spec("employee", "event", 0.65),
        Spec("permission", "event", 1.25, role="RESULT"),
    ],
    "program-install-system": [
        Spec("program", "cause", 0.10), Spec("install", "cause", 0.65, role="ACTION"),
        Spec("system", "effect", 1.25, role="RESULT"),
    ],
    "context-return": [Spec("context", "event", 0.10), Spec("return", "event", 0.65)],
    "calendar-progression": [Spec(f"calendar{i}", "event", 0.1 + i * 0.32) for i in range(4)],
    "message-action-target": [
        Spec("message", "cause", 0.10), Spec("action", "cause", 0.65, role="ACTION"),
        Spec("target", "effect", 1.25, role="RESULT"),
    ],
    "authored-cohort": [Spec("left", "event", 0.10), Spec("right", "event", 0.10)],
    "precise-speech-over-sequence-order": [
        Spec(
            "character", "event", 0.10, role="CHARACTER", leader=False,
            group="g", sequence=1,
        ),
        Spec(
            "negation", "event", 0.55, role="RESULT", leader=True,
            group="g", sequence=3,
        ),
        Spec(
            "vulnerability", "event", 1.05, role="OBJECT", leader=False,
            group="g", sequence=2,
        ),
    ],
    "dependent-authored-cohort": [
        Spec(
            "context", "E1", 0.30, role="OBJECT", leader=True,
            phrase="context-span", group="g", sequence=1,
        ),
        Spec(
            "return", "E2", 0.30, role="ACTION", leader=True,
            phrase="return-span", group="g", sequence=2,
        ),
    ],
    "subframe-distinct-reveals": [
        Spec("first", "event", 0.101, group="tight", sequence=1),
        Spec("second", "event", 0.109, leader=False, group="tight", sequence=2),
        Spec(
            "third", "event", 0.117, leader=False, group="tight",
            sequence=3, phrase_end=0.40,
        ),
    ],
}


def test_frame_safe_group_reveal_starts_preserve_distinct_subframe_order() -> None:
    starts = FFmpegRenderer._frame_safe_group_reveal_starts(
        rows=[
            ("first", 0.101, {"semantic_group_id": "tight", "sequence_order": 1}),
            ("second", 0.109, {"semantic_group_id": "tight", "sequence_order": 2}),
            ("third", 0.117, {"semantic_group_id": "tight", "sequence_order": 3}),
        ],
        fps=30,
        duration=2.6,
    )
    frames = [
        math.ceil(starts[asset] * 30 - 1e-9)
        for asset in ("first", "second", "third")
    ]
    assert frames == [4, 5, 6]
    # Thresholds must still be later than the previous frame timestamp, otherwise
    # the renderer could reveal a semantic asset one encoded frame early.
    assert all(
        starts[asset] > (frame - 1) / 30
        for asset, frame in zip(("first", "second", "third"), frames)
    )


def test_frame_safe_visibility_fails_closed_if_nonzero_entry_would_be_fully_hidden() -> None:
    cue = MotionCue(
        beat_id="beat",
        asset_id="asset",
        kind="program_v3",
        start=0.10,
        end=0.20,
        params={
            "engine_version": 3,
            "program": {
                "name": "moving",
                "settle_progress": 1.0,
                "keyframes": [
                    {"progress": 0.0, "dx": 0.02, "dy": 0.0, "scale": 1.0, "easing": "linear"},
                    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
                ],
            },
        },
    )
    with pytest.raises(StageFailedError) as caught:
        FFmpegRenderer._require_encoded_entry_window(
            cue=cue,
            authored_start=0.10,
            authored_end=0.20,
            effective_reveal_start=0.225,
            fps=30,
            beat_id="beat",
            asset_id="asset",
        )
    assert getattr(caught.value, "effective_code", None) == "ENCODED_REVEAL_ORDER_INFEASIBLE"


@pytest.mark.parametrize("case", CASES)
def test_narration_sequence_survives_encode(tmp_path: Path, case: str):
    specs = CASES[case]
    colors = [(220, 35, 35), (35, 190, 35), (35, 35, 220), (190, 35, 190)]
    images, boxes = {}, {}
    for i, spec in enumerate(specs):
        path = tmp_path / f"chip-{i}.png"
        image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((8, 8, 87, 87), fill=(*colors[i], 255))
        image.save(path)
        images[spec.asset] = path
        boxes[spec.asset] = (3 + i * 23, 32, 18, 28)
    relations = ()
    if case in {"program-install-system", "message-action-target"}:
        relations = (CanonicalRelation(
            subject_asset_id=specs[1].asset, object_asset_id=specs[2].asset,
            relation_type="PROGRESSES_TO",
        ),)
    story, _, _, motion, plan = _pipeline(
        tmp_path / "pipeline", specs, 2.6, relations=relations,
        asset_images=images, asset_boxes=boxes,
    )
    video = FFmpegRenderer("ffmpeg").render(plan, tmp_path / "sequence.mp4")
    capture = cv2.VideoCapture(str(video))
    samples = [[] for _ in specs]
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.int16)
            for i, color in enumerate(colors[:len(specs)]):
                # Chroma identifies the authored chip through fades and H.264 noise.
                high = np.array(color) > 100
                mask = (rgb[..., high].min(axis=2) - rgb[..., ~high].max(axis=2)) > 40
                ys, xs = np.where(mask)
                samples[i].append((len(xs), float(xs.mean()) if len(xs) else 0,
                                   float(ys.mean()) if len(xs) else 0))
    finally:
        capture.release()
    windows = _windows(story)
    first_frames = []
    for spec, rows in zip(specs, samples):
        active = [i for i, row in enumerate(rows) if row[0] >= 8]
        assert active, spec.asset
        first = active[0]
        first_frames.append(first)
        legal = math.ceil(windows[spec.asset].reveal_start * plan.fps - 1e-9)
        assert legal <= first <= legal + 6, (spec.asset, legal, first)
        assert active == list(range(first, len(rows))), "intermediate disappearance"
        cue = next(c for c in motion if c.asset_id == spec.asset)
        settled = max([cue.end, *(s.end for s in cue.segments)])
        calm = np.array(rows[math.ceil(settled * plan.fps) + 2:])
        assert len(calm) > 2
        assert np.ptp(calm[:, 1:], axis=0).max() <= 1.0, "post-settle motion"
    if case in {"authored-cohort", "dependent-authored-cohort"}:
        assert len(set(first_frames)) == 1
    else:
        assert all(a < b for a, b in zip(first_frames, first_frames[1:])), first_frames
    if case == "precise-speech-over-sequence-order":
        by_id = {cue.asset_id: cue for cue in motion}
        assert by_id["negation"].params["motion_order"]["sequence_order"] == 3
        assert by_id["vulnerability"].params["motion_order"]["sequence_order"] == 2
        assert windows["negation"].reveal_start < windows["vulnerability"].reveal_start
    if relations:
        target = next(c for c in motion if c.asset_id == specs[-1].asset)
        assert [s.phase for s in target.segments if s.phase != "ENTRY"] == ["PAYOFF"]
    report = EncodedMotionVerifier().inspect(video=video, plan=plan)
    assert report.ok, report.violations