"""Sprint 3.75 holdouts for the opening visual-coverage failure class.

Production diagnostic 570a01cb failed FinalMediaVerifier with VISUAL_WHITE_FLASH on
33 opening frames: narration began 1.12 s before the first exact visual phrase. These
generated Unified 2.0 packages reproduce that shape through the real loader, Story,
Motion, RenderPlan, FFmpeg, mux and the unchanged strict final verifier.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.final import FinalExporter, FinalMediaVerifier
from app.render.renderer import FFmpegRenderer
from app.render.verification import EncodedMotionVerifier
from app.story.windows import StoryAssetActivation
from tests.package_holdouts.cases import opening_coverage_cases
from tests.package_holdouts.test_full_render import _plan

_EVENT_SPOKEN, _PRELUDE, _RESULT_FIRST = opening_coverage_cases()
_AUTHORITY = {_EVENT_SPOKEN.seed: "AUTHORED_EVENT_SPOKEN", _PRELUDE.seed: "SCENE_PRELUDE"}


def _opening_windows(plan) -> dict[str, StoryAssetActivation]:
    beat = plan.story[0]
    return {
        row.asset_id: StoryAssetActivation.from_legacy(row)
        for row in beat.asset_activations
        if row.source == "unified_final_package"
    }


def _render_and_verify(plan, tmp_path: Path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.fail("Sprint 3.75 certification requires ffmpeg and ffprobe")
    video = FFmpegRenderer("ffmpeg").render(plan, tmp_path / "video.mp4")
    audio = tmp_path / "audio.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
         "-t", f"{plan.duration:.3f}", "-c:a", "pcm_s16le", str(audio)],
        check=True,
    )
    final = FinalExporter("ffmpeg").mux(video, audio, tmp_path / "final.mp4")
    issues = FinalMediaVerifier("ffprobe", "ffmpeg").inspect(
        final, audio, first_spoken_start=plan.story[0].audio_start,
    )
    return video, final, issues


def test_opening_lead_fixture_reproduces_the_production_shape(tmp_path: Path) -> None:
    plan = _plan(_PRELUDE, tmp_path)
    beat = plan.story[0]
    windows = _opening_windows(plan)
    phrase_starts = sorted(row.phrase_start for row in windows.values() if row.phrase_start is not None)
    # Narration precedes the first exact visual phrase by more than the bounded lead.
    assert phrase_starts[0] - float(beat.audio_start) > 0.42


@pytest.mark.parametrize("case", [_EVENT_SPOKEN, _PRELUDE], ids=lambda case: case.family)
def test_opening_event_in_progress_is_covered_in_final_media(tmp_path: Path, case) -> None:
    plan = _plan(case, tmp_path)
    beat = plan.story[0]
    windows = _opening_windows(plan)
    established = [row for row in windows.values() if "opening_spoken_coverage" in row.evidence]
    assert len(established) == 1
    carrier = established[0]
    assert f"opening_establish_authority={_AUTHORITY[case.seed]}" in carrier.evidence
    assert carrier.reveal_start == pytest.approx(float(beat.audio_start))
    assert carrier.semantic_event_roles == ["PARTICIPANT"]
    # Exact phrase anchor stays; RESULT and later reveals are untouched.
    assert carrier.phrase_start > carrier.reveal_start
    assert carrier.semantic_peak >= carrier.phrase_start
    for row in windows.values():
        if row is carrier:
            continue
        assert row.reveal_start >= carrier.settle_at - 1e-9
        assert row.reveal_start == pytest.approx(row.phrase_start)

    video, final, issues = _render_and_verify(plan, tmp_path)
    assert issues == []
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(final)],
        check=True, capture_output=True, text=True,
    ).stdout)
    stream = next(row for row in probe["streams"] if row["codec_type"] == "video")
    assert stream["codec_name"] == "h264" and stream["r_frame_rate"] == "30/1"
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(final), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert decoded.returncode == 0 and not decoded.stderr.strip()
    assert EncodedMotionVerifier().inspect(video=final, plan=plan).ok


@pytest.mark.parametrize("case", [_RESULT_FIRST], ids=lambda case: case.family)
def test_opening_without_safe_carrier_fails_closed_in_final_media(tmp_path: Path, case) -> None:
    plan = _plan(case, tmp_path)
    windows = _opening_windows(plan)
    assert all("opening_spoken_coverage" not in row.evidence for row in windows.values())

    _video, _final, issues = _render_and_verify(plan, tmp_path)
    # RESULT is never revealed early; the strict verifier must still catch the gap.
    assert [issue.code for issue in issues] == ["VISUAL_WHITE_FLASH"]
