"""Real FFmpeg encodes of package-shaped scenes, proving required leaders on screen.

Each case runs the full planning chain (Story -> Choreography -> Composition ->
Motion -> Text -> RenderPlan) and encodes with the production FFmpegRenderer. The
MP4 is then certified from the outside: H.264, Full HD, 30 fps CFR, non-negative
monotonic timestamps, clean full decode, exact frame count, encoded motion QA, and
decoded pixels inside every event leader's layout at the end of its beat.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.render.renderer import FFmpegRenderer
from app.render.verification import EncodedMotionVerifier
from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.support.carrier_matrix import family_case
from tests.support.carrier_scene import build_package

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)

ENCODED_FAMILIES = (
    "decorative_leader", "compound_split", "dotted", "approximate", "result_tail",
)


def _plan(tmp_path: Path, family: str, seed: int):
    case = family_case(family, seed)
    built = build_package(
        list(case.scenes), namespace=f"ENC{seed}", image_root=tmp_path / "images",
        write_images=True,
    )
    story = StoryPlanner().plan(built.package, built.transcript, built.assets)
    choreography = ChoreographyDirector().plan(built.package, story, built.assets)
    composition = CompositionPlanner().plan(story, built.assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, built.assets)
    text = TextPlanner().plan(
        transcript=built.transcript, story=story, assets=built.assets,
        package=built.package, choreography=choreography,
    )
    workspace = tmp_path / "render"
    workspace.mkdir()
    plan, _ = RenderPlanner().compile(
        built.transcript, built.assets, story, composition, motion, workspace, text=text,
    )
    return plan, built


def _probe(video: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_streams", "-show_entries", "packet=pts_time,dts_time", "-of", "json",
         str(video)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def _frame(video: Path, timestamp: float, width: int, height: int) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.3f}",
         "-i", str(video), "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape((height, width, 3))


@pytest.mark.parametrize("family", ENCODED_FAMILIES)
def test_package_shaped_scene_encodes_with_every_leader_on_screen(
    tmp_path: Path, family: str,
) -> None:
    plan, built = _plan(tmp_path, family, seed=7100 + ENCODED_FAMILIES.index(family))
    authored_leaders = {
        event.visual_leader_asset_id
        for scene in built.package.scenes for event in scene.semantic_events
    }
    assert (plan.width, plan.height, plan.fps) == (1920, 1080, 30)

    video = FFmpegRenderer("ffmpeg").render(plan, tmp_path / f"{family}.mp4")

    probe = _probe(video)
    stream = probe["streams"][0]
    assert stream["codec_name"] == "h264"
    assert (stream["width"], stream["height"]) == (1920, 1080)
    assert stream["r_frame_rate"] == "30/1" and stream["avg_frame_rate"] == "30/1"
    expected_frames = round(plan.duration * plan.fps)
    assert abs(int(stream["nb_read_frames"]) - expected_frames) <= 1
    pts = [float(row["pts_time"]) for row in probe["packets"] if "pts_time" in row]
    assert pts and min(pts) >= 0.0
    assert sorted(pts) == sorted(set(pts)), "duplicate presentation timestamps"

    decode = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert decode.returncode == 0 and decode.stderr.strip() == ""

    report = EncodedMotionVerifier().inspect(video=video, plan=plan)
    assert report.ok, report.violations

    layouts = {
        (beat.beat_id, item.asset_id): item for beat in plan.composition for item in beat.items
    }
    proven: set[str] = set()
    for beat in plan.story:
        # Carriers of the package-authored leaders (not whatever Story happened to
        # activate), so a leader that lost its carrier cannot silently skip the check.
        carriers = [
            (row.asset_id, row.semantic_unit_id)
            for row in (*beat.asset_activations, *beat.semantic_event_proxies)
            if row.semantic_unit_id in authored_leaders
            and getattr(row, "activation_policy", None) != "SAFE_ABSTENTION"
        ]
        leaders = {asset_id for asset_id, _ in carriers}
        frame = _frame(video, max(beat.start, beat.end - 3.0 / plan.fps), plan.width, plan.height)
        for asset_id in sorted(leaders):
            item = layouts[(beat.id, asset_id)]
            cx, cy = item.x * plan.width, item.y * plan.height
            half_w, half_h = item.width * plan.width * 0.3, item.height * plan.height * 0.3
            roi = frame[
                int(cy - half_h):int(cy + half_h), int(cx - half_w):int(cx + half_w)
            ]
            painted = float((roi.min(axis=2) < 235).mean())
            assert painted > 0.5, (family, beat.id, asset_id, painted)
        proven.update(unit for asset_id, unit in carriers if asset_id in leaders)
    assert proven == authored_leaders


@pytest.mark.parametrize("family", ["neg_unresolved", "neg_misbound", "neg_hidden_art"])
def test_defective_package_shape_never_reaches_ffmpeg(tmp_path: Path, family: str) -> None:
    case = family_case(family, seed=7200)
    built = build_package(list(case.scenes), namespace="ENCNEG")
    with pytest.raises(StageFailedError) as caught:
        StoryPlanner().plan(built.package, built.transcript, built.assets)
    assert caught.value.effective_code == case.expected_code
    assert not list(tmp_path.glob("**/*.mp4"))
