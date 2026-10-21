"""Camera drift: a slow, continuous push on each idea (retention review 2026-10-21).

A held picture with nothing moving reads as a frozen screen. Explainer edits keep a very
slow camera move under a still idea. Here the whole frame zooms CAMERA_AMPLITUDE (1.2 %)
over each idea, in and out on alternate ideas, eased (zero speed at every idea change), so
the camera is continuous everywhere - never a jump, never a reset. Ideas are the stretches
between screen clears (every Boundary row that is not an idea board).

It is applied to the encoded video after encoded-motion QA (which certifies the authored
motion itself) with FFmpeg ``perspective`` (cubic, sub-pixel, constant frame size: no
jitter, measured sharpness unchanged). Text and artwork move together. The editable
Premiere timeline does not carry it (a camera move is the editor's choice there).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.models import RenderPlan
from app.shared.errors import StageFailedError
from app.shared.process import run_hidden

CAMERA_DRIFT = True
CAMERA_AMPLITUDE = 0.012
_MIN_IDEA_SECONDS = 0.5


def idea_keys(plan: RenderPlan) -> list[tuple[float, float]]:
    """(time, zoom) keys: one per idea start, alternating 0 and CAMERA_AMPLITUDE."""
    beats = {beat.id: beat for beat in plan.story}
    starts = [0.0]
    for row in sorted(plan.scene_boundaries, key=lambda row: beats[row.beat_id].start if row.beat_id in beats else 0.0):
        beat = beats.get(row.beat_id)
        if beat is None or (row.audit or {}).get("hero_exit") == "idea_board":
            continue
        if float(beat.start) - starts[-1] >= _MIN_IDEA_SECONDS:
            starts.append(float(beat.start))
    starts.append(float(plan.duration))
    return [(time, CAMERA_AMPLITUDE if index % 2 else 0.0) for index, time in enumerate(starts)]


def zoom_expression(keys: list[tuple[float, float]], fps: int) -> str:
    """FFmpeg expression of the zoom at frame ``in`` (eased between keys)."""
    time = f"(in/{fps})"
    expression = f"{keys[-1][1]:.6f}"
    for (t0, z0), (t1, z1) in reversed(list(zip(keys, keys[1:]))):
        span = max(1e-3, t1 - t0)
        u = f"clip(({time}-{t0:.6f})/{span:.6f},0,1)"
        eased = f"({u}*{u}*(3-2*{u}))"
        expression = f"if(lt({time},{t1:.6f}),{z0:.6f}+({z1 - z0:.6f})*{eased},{expression})"
    return expression


def apply(plan: RenderPlan, video: Path, output: Path, *, ffmpeg_bin: str, filter_option: str) -> Path:
    """``video`` with the camera drift, re-encoded at the renderer's quality."""
    z = zoom_expression(idea_keys(plan), plan.fps)
    dx, dy = f"(W*({z})/(2*(1+{z})))", f"(H*({z})/(2*(1+{z})))"
    graph = (f"[0:v]perspective=x0='{dx}':y0='{dy}':x1='W-{dx}':y1='{dy}':x2='{dx}':y2='H-{dy}'"
             f":x3='W-{dx}':y3='H-{dy}':interpolation=cubic:eval=frame,format=yuv420p[vout]")
    script = output.with_suffix(".camera.ffgraph")
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(graph + "\n", encoding="utf-8")
    command = [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
               "-filter_complex_threads", "1", filter_option, str(script), "-map", "[vout]", "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-bf", "0",
               "-r", str(plan.fps), str(output)]
    try:
        run_hidden(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except subprocess.CalledProcessError as exc:
        raise StageFailedError("camera drift encode failed", details={
            "code": "CAMERA_DRIFT_FAILED", "stderr": (exc.stderr or "")[-400:]}) from exc
    finally:
        script.unlink(missing_ok=True)
    return output


def apply_or_keep(plan: RenderPlan, video: Path, output: Path, *, ffmpeg_bin: str,
                  filter_option: str) -> tuple[Path, dict]:
    """The drifted video, or the original when the drift is off or fails (recorded)."""
    if not CAMERA_DRIFT:
        return video, {"camera": "off"}
    try:
        result = apply(plan, video, output, ffmpeg_bin=ffmpeg_bin, filter_option=filter_option)
    except (StageFailedError, OSError) as exc:
        return video, {"camera": "skipped", "error": str(exc)[:300]}
    if not result.is_file() or result.stat().st_size == 0:
        return video, {"camera": "skipped", "error": "empty output"}
    return result, {"camera": "drift", "ideas": len(idea_keys(plan)) - 1, "amplitude": CAMERA_AMPLITUDE}
