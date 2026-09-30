"""Real FFmpeg encodes (320x180) proving handoff frame coverage on decoded frames.

Each case renders a short plan, decodes every frame and asserts that no frame inside the
handoff window is blank, that the incoming artwork appears on exactly Story's first
encoded frame (never earlier) and that the final-media white-flash verifier agrees.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.final import FinalMediaVerifier
from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    MotionCue,
    RenderPlan,
    StoryBeat,
    StorySemanticContext,
    VisualAsset,
)
from app.render.renderer import FFmpegRenderer

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required",
)

# Artwork styles: every one must be owned by the coverage logic, not only large blobs.
STYLES = {
    "incoming": lambda d: d.rounded_rectangle((8, 8, 212, 212), radius=24, fill=(225, 55, 45, 255)),
    "large": lambda d: d.rounded_rectangle((8, 8, 212, 212), radius=24, fill=(25, 65, 190, 255)),
    "small": lambda d: d.ellipse((90, 90, 130, 130), fill=(200, 40, 40, 255)),
    "light": lambda d: d.rounded_rectangle((20, 20, 200, 200), radius=20, fill=(235, 225, 160, 255)),
    "dark": lambda d: d.rounded_rectangle((20, 20, 200, 200), radius=20, fill=(10, 10, 20, 255)),
    "thin": lambda d: (d.line((20, 20, 200, 200), fill=(0, 0, 0, 255), width=3),
                       d.line((20, 200, 200, 20), fill=(0, 0, 0, 255), width=3)),
    "padded": lambda d: d.rectangle((95, 95, 125, 125), fill=(20, 120, 60, 255)),
}


def _asset(path: Path, style: str) -> None:
    image = Image.new("RGBA", (220, 220), (255, 255, 255, 0))
    STYLES[style](ImageDraw.Draw(image))
    image.save(path)


def _frames(path: Path) -> list[np.ndarray]:
    capture = cv2.VideoCapture(str(path))
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    return frames


def _ink(frame: np.ndarray) -> int:
    """Pixels that are visibly not white (any style, including thin dark lines)."""
    return int(np.count_nonzero(np.min(frame, axis=2) < 235))


def _build(tmp: Path, *, fps, boundary, reveal_frames, mode="motion", style="large",
           incoming_style="incoming", persistent=False, opening_delay_frames=None):
    old, new = tmp / "old.png", tmp / "new.png"
    _asset(old, style)
    _asset(new, incoming_style)
    seg_start = round(boundary * fps) / fps
    reveal = seg_start + reveal_frames / fps
    duration = boundary + 0.7
    assets = [VisualAsset(id="old", scene_id="s1", role="primary", image_path=old, extraction_method="t"),
              VisualAsset(id="new", scene_id="s2", role="primary", image_path=new, extraction_method="t")]
    story = [StoryBeat(id="b1", scene_id="s1", start=0.0, end=boundary, narration="o",
                       primary_asset_ids=["old"], action="INTRODUCE"),
             StoryBeat(id="b2", scene_id="s2", start=boundary, end=duration, narration="n",
                       primary_asset_ids=["new"], action="INTRODUCE")]
    if mode == "object":
        story[0] = story[0].model_copy(update={"asset_activations": [AssetActivation(
            asset_id="old", semantic_unit_id="u-old",
            continuity={"mode": "TRANSFORM_TO", "target_asset_id": "u-new"})]})
        story[1] = story[1].model_copy(update={"asset_activations": [AssetActivation(
            asset_id="new", semantic_unit_id="u-new")]})
    elif mode == "blur":
        story[1] = story[1].model_copy(update={"semantic_context": StorySemanticContext(
            scene_metadata={"transition_style": "soft_blur_bridge"})})
    comp = [CompositionBeat(beat_id="b1", items=[LayoutItem(asset_id="old", x=.5, y=.5, width=.22, height=.38)]),
            CompositionBeat(beat_id="b2", items=[LayoutItem(asset_id="new", x=.5, y=.5, width=.22, height=.38)])]
    motion = [MotionCue(beat_id="b1", asset_id="old", kind="reveal_in", start=0.0, end=0.16),
              MotionCue(beat_id="b2", asset_id="new", kind="reveal_in", start=reveal, end=reveal + 0.18)]
    plan = RenderPlan(width=320, height=180, fps=fps, duration=duration, story=story,
                      composition=comp, motion=motion, assets=assets)
    return plan, round(seg_start * fps), round(reveal * fps), duration


def _render(tmp: Path, plan: RenderPlan, name: str) -> tuple[Path, list[np.ndarray]]:
    out = tmp / f"{name}.mp4"
    FFmpegRenderer("ffmpeg").render(plan, out)
    return out, _frames(out)


HANDOFFS = [
    (30, 0.42, 2, "motion"), (30, 0.42, 5, "motion"), (30, 0.5, 2, "motion"), (30, 0.5, 5, "motion"),
    (24, 0.5, 1, "motion"), (24, 0.5, 4, "motion"), (24, 0.5, 7, "motion"), (25, 0.48, 3, "motion"),
    (60, 0.5, 4, "motion"), (60, 0.5, 10, "motion"),
    (30, 0.42, 2, "object"), (30, 0.5, 5, "object"), (24, 0.5, 4, "object"), (60, 0.5, 10, "object"),
    (30, 0.42, 2, "blur"), (30, 0.5, 5, "blur"), (24, 0.5, 4, "blur"), (25, 0.48, 6, "blur"),
]


@pytest.mark.parametrize(("fps", "boundary", "reveal_frames", "mode"), HANDOFFS)
def test_handoff_window_has_no_blank_encoded_frame(tmp_path, fps, boundary, reveal_frames, mode) -> None:
    plan, seg_frame, reveal_frame, duration = _build(
        tmp_path, fps=fps, boundary=boundary, reveal_frames=reveal_frames, mode=mode,
    )
    out, frames = _render(tmp_path, plan, "h")
    # Every frame from the last outgoing frame through the first incoming frame has ink.
    for n in range(seg_frame - 1, reveal_frame + 2):
        assert _ink(frames[n]) > 0, f"frame {n} is blank (segment={seg_frame}, reveal={reveal_frame})"
    # The incoming artwork (red-ish) is visible on Story's first frame and not before it.
    centre = lambda n: frames[n][90, 160]  # noqa: E731  (BGR)
    assert int(centre(reveal_frame)[2]) > int(centre(reveal_frame)[0]) + 45
    assert not (int(centre(reveal_frame - 1)[2]) > int(centre(reveal_frame - 1)[0]) + 45)
    assert FinalMediaVerifier("ffprobe", "ffmpeg")._white_flash_frames(out, duration) == []


@pytest.mark.parametrize("style", ["small", "light", "dark", "thin", "padded"])
@pytest.mark.parametrize("which", ["outgoing", "incoming"])
def test_small_light_dark_thin_and_padded_artwork_keeps_coverage(tmp_path, style, which) -> None:
    kwargs = {"style": style} if which == "outgoing" else {"incoming_style": style}
    plan, seg_frame, reveal_frame, duration = _build(
        tmp_path, fps=30, boundary=0.42, reveal_frames=2, **kwargs,
    )
    _out, frames = _render(tmp_path, plan, f"s-{style}-{which}")
    for n in range(seg_frame, reveal_frame + 2):
        assert _ink(frames[n]) > 0, f"{style}/{which}: frame {n} blank"


def test_persistent_asset_never_disappears_and_returns(tmp_path) -> None:
    """The same asset across a same-scene boundary stays visible on every frame."""
    art = tmp_path / "keep.png"
    _asset(art, "large")
    asset = VisualAsset(id="keep", scene_id="s1", role="primary", image_path=art, extraction_method="t")
    cont = {"mode": "PERSIST"}
    story = [
        StoryBeat(id="p1", scene_id="s1", start=0.0, end=0.4, narration="a", primary_asset_ids=["keep"],
                  action="INTRODUCE",
                  asset_activations=[AssetActivation(asset_id="keep", semantic_unit_id="u", continuity=cont)]),
        StoryBeat(id="p2", scene_id="s1", start=0.4, end=0.9, narration="b", primary_asset_ids=["keep"],
                  action="EXPLAIN", asset_activations=[AssetActivation(asset_id="keep", semantic_unit_id="u")]),
    ]
    item = LayoutItem(asset_id="keep", x=.5, y=.5, width=.22, height=.38)
    plan = RenderPlan(
        width=320, height=180, fps=30, duration=0.9, story=story, assets=[asset],
        composition=[CompositionBeat(beat_id="p1", items=[item]), CompositionBeat(beat_id="p2", items=[item])],
        motion=[MotionCue(beat_id="p1", asset_id="keep", kind="reveal_in", start=0.0, end=0.16)],
    )
    _out, frames = _render(tmp_path, plan, "persist")
    assert all(_ink(frame) > 0 for frame in frames[2:]), [_ink(f) for f in frames]


def test_opening_never_exposes_a_leader_early_and_is_judged_by_the_verifier(tmp_path) -> None:
    """A first reveal that is an event LEADER is never shown before its cue; the pre-narration
    frames are proven empty by the encoded verifier's pre-roll rule, not filled."""
    art = tmp_path / "leader.png"
    _asset(art, "large")
    asset = VisualAsset(id="a1", scene_id="s1", role="primary", image_path=art, extraction_method="t")
    beat = StoryBeat(id="o1", scene_id="s1", start=0.0, end=2.0, narration="a", audio_start=0.28,
                     audio_end=2.0, primary_asset_ids=["a1"], action="INTRODUCE")
    plan = RenderPlan(
        width=320, height=180, fps=30, duration=2.0, story=[beat], assets=[asset],
        composition=[CompositionBeat(beat_id="o1", items=[LayoutItem(asset_id="a1", x=.5, y=.5, width=.22, height=.38)])],
        motion=[MotionCue(beat_id="o1", asset_id="a1", kind="reveal_in", start=0.28, end=0.5,
                          params={"semantic_focus": {"semantic_role": "PRIMARY",
                                                     "semantic_event_roles": ["LEADER"]}})],
    )
    out, frames = _render(tmp_path, plan, "leader")
    assert all(_ink(frames[n]) == 0 for n in range(0, 9))  # nothing shown before its cue
    assert _ink(frames[9]) > 0  # first encoded frame of the reveal
    verifier = FinalMediaVerifier("ffprobe", "ffmpeg")
    # Pre-narration silence is pre-roll ...
    assert verifier._white_flash_frames(out, 2.0, first_spoken_start=0.28) == []
    # ... but a blank stretch AFTER the first spoken word is still a flash.
    assert verifier._white_flash_frames(out, 2.0, first_spoken_start=0.0) != []
    assert verifier._white_flash_frames(out, 2.0) != []


def _crafted_video(tmp_path: Path, blocks: list[tuple[str, float]], name: str) -> Path:
    """30 fps H.264 clip from solid blocks: 'white', or 'art' (a clearly visible square)."""
    import subprocess

    white = np.full((180, 320, 3), 255, dtype=np.uint8)
    art = white.copy()
    art[45:135, 115:205] = (30, 70, 190)  # RGB
    data = b"".join(
        (white if kind == "white" else art).tobytes()
        for kind, seconds in blocks for _ in range(round(seconds * 30))
    )
    out = tmp_path / f"{name}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", "320x180", "-r", "30", "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-bf", "0", str(out)], input=data, check=True,
    )
    return out


def test_verifier_stays_strict_for_internal_white_frames_whatever_the_pre_roll(tmp_path) -> None:
    video = _crafted_video(tmp_path, [("art", 1.0), ("white", 0.2), ("art", 1.0)], "internal")
    verifier = FinalMediaVerifier("ffprobe", "ffmpeg")
    for first_word in (None, 0.0, 0.5, 1.0, 5.0):
        flashes = verifier._white_flash_frames(video, 2.2, first_spoken_start=first_word)
        assert len(flashes) >= 5, (first_word, flashes)
        assert all(0.95 < f["time"] < 1.25 for f in flashes)


@pytest.mark.parametrize(("blank", "first_word", "flagged"), [
    (0.28, 0.28, False),  # blank opening ends exactly at the first spoken word: pre-roll
    (0.28, 0.0, True),    # narration had already started: a real gap
    (0.28, None, True),   # unknown pre-roll falls back to the edge guard only
    (0.9, 0.9, False),
    (1.5, 1.5, True),     # silence longer than the cap is not treated as intentional pre-roll
])
def test_opening_pre_roll_is_bounded_by_the_first_spoken_word(tmp_path, blank, first_word, flagged) -> None:
    video = _crafted_video(tmp_path, [("white", blank), ("art", 6.0)], f"open-{blank}-{first_word}")
    flashes = FinalMediaVerifier("ffprobe", "ffmpeg")._white_flash_frames(
        video, blank + 6.0, first_spoken_start=first_word,
    )
    assert bool(flashes) is flagged, flashes
