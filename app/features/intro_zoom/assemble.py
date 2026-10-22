from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

from PIL import Image, ImageChops, ImageStat

from app.features.intro_zoom.models import FPS, PreparedIntro
from app.shared.errors import GenerationCancelledError, StageFailedError
from app.shared.process import run_hidden


def probe(path: Path, ffprobe_bin: str = "ffprobe") -> dict:
    result = run_hidden(
        [ffprobe_bin, "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_name,profile,level,pix_fmt,width,height,r_frame_rate,"
         "avg_frame_rate,time_base,sample_rate,channels,channel_layout,start_time,duration,nb_frames:"
         "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if result.returncode:
        raise StageFailedError("Intro media cannot be probed", details={
            "code": "INTRO_MEDIA_PROBE_FAILED", "path": str(path)})
    return json.loads(result.stdout)


def _stream(data: dict, kind: str) -> dict:
    return next((row for row in data.get("streams", []) if row.get("codec_type") == kind), {})


def _frames(video: dict) -> int:
    try:
        return int(video["nb_frames"])
    except (KeyError, TypeError, ValueError):
        return round(float(video.get("duration") or 0) * FPS)


def _compatible(intro: dict, original: dict) -> bool:
    first, second = _stream(intro, "video"), _stream(original, "video")
    keys = ("codec_name", "profile", "pix_fmt", "width", "height", "r_frame_rate",
            "time_base", "level")
    return (bool(first) and bool(second)
            and all(first.get(key) == second.get(key) for key in keys)
            and first.get("codec_name") == "h264")


def _run(command: list[str], log: Path, cancelled: Callable[[], bool] | None,
         *, timeout: int = 3600) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with log.open("wb") as output:
        try:
            process = subprocess.Popen(command, stdout=output, stderr=output,
                                       creationflags=flags)
        except OSError as exc:
            raise StageFailedError("Intro assembly tool unavailable", details={
                "code": "INTRO_ASSEMBLY_TOOL_UNAVAILABLE", "error": str(exc)}) from exc
        begin = time.monotonic()
        try:
            while process.poll() is None:
                if cancelled and cancelled():
                    raise GenerationCancelledError("Intro Zoom assembly cancelled")
                if time.monotonic() - begin > timeout:
                    raise StageFailedError("Intro assembly timed out", details={
                        "code": "INTRO_ASSEMBLY_TIMEOUT", "log": str(log)})
                time.sleep(0.2)
        except BaseException:
            process.kill()
            process.wait()
            raise
        if process.returncode:
            raise StageFailedError("Intro assembly failed", details={
                "code": "INTRO_ASSEMBLY_FAILED", "log": str(log),
                "stderr_tail": log.read_text(encoding="utf-8", errors="replace")[-2000:]})


def _frame(path: Path, number: int, ffmpeg_bin: str) -> bytes:
    result = run_hidden(
        [ffmpeg_bin, "-v", "error", "-i", str(path), "-map", "0:v:0", "-an",
         "-vf", f"select=eq(n\\,{number})", "-fps_mode", "passthrough",
         "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True, timeout=120,
    )
    if result.returncode or not result.stdout:
        raise StageFailedError("Intro join frame cannot be decoded", details={
            "code": "INTRO_JOIN_FRAME_UNREADABLE", "path": str(path), "frame": number})
    return result.stdout


def _verify(video: Path, intro: Path, original: Path, prepared: PreparedIntro,
            *, ffprobe_bin: str, ffmpeg_bin: str, exact_picture: bool) -> dict:
    joined = probe(video, ffprobe_bin)
    intro_info = probe(intro, ffprobe_bin)
    original_info = probe(original, ffprobe_bin)
    visual = _stream(joined, "video")
    audio = _stream(joined, "audio")
    expected_frames = prepared.frames + _frames(_stream(original_info, "video"))
    actual_frames = _frames(visual)
    video_duration = float(visual.get("duration") or 0)
    audio_duration = float(audio.get("duration") or 0)
    original_duration = float(_stream(original_info, "video").get("duration") or 0)
    expected_duration = prepared.duration + original_duration
    if (not visual or not audio or actual_frames != expected_frames
            or abs(video_duration - expected_duration) > 2 / FPS
            or abs(audio_duration - video_duration) > 0.11):
        raise StageFailedError("Intro join has incorrect frame or audio timing", details={
            "code": "INTRO_JOIN_TIMING", "expected_frames": expected_frames,
            "actual_frames": actual_frames, "video_duration": video_duration,
            "audio_duration": audio_duration, "expected_duration": expected_duration})
    # Verify both sides of the join against their actual decoded source frames. A broken
    # concat often decodes but inserts an empty frame or loses the first story frame.
    for joined_number, reference, reference_number in (
        (prepared.frames - 1, intro, prepared.frames - 1),
        (prepared.frames, original, 0),
    ):
        joined_frame = _frame(video, joined_number, ffmpeg_bin)
        reference_frame = _frame(reference, reference_number, ffmpeg_bin)
        if exact_picture and joined_frame != reference_frame:
            raise StageFailedError("Intro video join changed the boundary frames", details={
                "code": "INTRO_JOIN_PICTURE"})
        if not exact_picture:
            size = (int(visual["width"]), int(visual["height"]))
            candidate_image = Image.frombytes("RGB", size, joined_frame)
            reference_image = Image.frombytes("RGB", size, reference_frame)
            difference = ImageChops.difference(candidate_image, reference_image)
            error = max(ImageStat.Stat(difference).mean)
            if error > 10:
                raise StageFailedError("Intro fallback altered a join frame", details={
                    "code": "INTRO_JOIN_PICTURE", "mean_channel_error": round(error, 3)})
    segment = run_hidden(
        [ffmpeg_bin, "-v", "error", "-xerror", "-ss", f"{max(0, prepared.duration - 0.12):.3f}",
         "-i", str(video), "-t", "0.35", "-f", "null", "-"],
        capture_output=True, timeout=90,
    )
    if segment.returncode:
        raise StageFailedError("Intro join cannot be decoded", details={
            "code": "INTRO_JOIN_DECODE"})
    return {"frames": actual_frames, "video_duration": video_duration,
            "audio_duration": audio_duration, "expected_frames": expected_frames,
            "intro_audio_duration": float(_stream(intro_info, "audio").get("duration") or 0)}


def prepend(intro: Path, original: Path, prepared: PreparedIntro, work: Path,
            *, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe",
            cancelled: Callable[[], bool] | None = None,
            destination: Path | None = None) -> dict:
    """Build and verify a temporary MP4, then atomically replace this bundle's output.

    Video stream-copy is attempted only with matching H.264 stream facts. The original
    audio is decoded and concatenated with exact intro PCM before one AAC encode; this
    avoids AAC priming gaps inherent in packet-level audio concatenation.
    """
    work.mkdir(parents=True, exist_ok=True)
    original_info = probe(original, ffprobe_bin)
    intro_info = probe(intro, ffprobe_bin)
    if not _stream(original_info, "audio") or not _stream(intro_info, "audio"):
        raise StageFailedError("Intro and story both require audio", details={
            "code": "INTRO_AUDIO_MISSING"})
    video_only = work / "joined-video.mp4"
    candidate = work / "candidate.mp4"
    method = "video_stream_copy"
    fallback_reason = None
    try:
        if _compatible(intro_info, original_info):
            listing = work / "video.ffconcat"
            def quote(path: Path) -> str:
                return str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
            listing.write_text(f"ffconcat version 1.0\nfile '{quote(intro)}'\n"
                               f"file '{quote(original)}'\n", encoding="utf-8")
            try:
                _run([ffmpeg_bin, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                      "-i", str(listing), "-map", "0:v:0", "-an", "-c:v", "copy",
                      "-movflags", "+faststart", str(video_only)],
                     work / "video-copy.log", cancelled)
                joined_info = probe(video_only, ffprobe_bin)
                if (_frames(_stream(joined_info, "video"))
                        != prepared.frames + _frames(_stream(original_info, "video"))):
                    raise ValueError("stream copy changed the video frame count")
                if (_frame(video_only, prepared.frames, ffmpeg_bin)
                        != _frame(original, 0, ffmpeg_bin)):
                    raise ValueError("stream copy changed the first original frame")
            except (StageFailedError, ValueError) as exc:
                fallback_reason = str(exc)
                video_only.unlink(missing_ok=True)
        else:
            fallback_reason = "H.264 codec/profile/pixel format/frame clock mismatch"
        if fallback_reason is not None:
            method = "video_reencode_fallback"
            _run([ffmpeg_bin, "-y", "-v", "error", "-i", str(intro), "-i", str(original),
                  "-filter_complex",
                  "[0:v:0]fps=30,format=yuv420p,setpts=PTS-STARTPTS[v0];"
                  "[1:v:0]fps=30,format=yuv420p,setpts=PTS-STARTPTS[v1];"
                  "[v0][v1]concat=n=2:v=1:a=0[v]",
                  "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
                  "-movflags", "+faststart", str(video_only)],
                 work / "video-fallback.log", cancelled)
        duration = prepared.duration
        audio_filter = (
            f"[1:a:0]aresample=48000,aformat=channel_layouts=stereo,apad,"
            f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a0];"
            "[2:a:0]aresample=48000,aformat=channel_layouts=stereo,"
            "asetpts=PTS-STARTPTS[a1];[a0][a1]concat=n=2:v=0:a=1[a]"
        )
        _run([ffmpeg_bin, "-y", "-v", "error", "-i", str(video_only),
              "-i", str(intro), "-i", str(original), "-filter_complex", audio_filter,
              "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
              "-b:a", "192k", "-ar", "48000", "-ac", "2",
              "-movflags", "+faststart", str(candidate)],
             work / "audio-join.log", cancelled)
        facts = _verify(candidate, intro, original, prepared, ffprobe_bin=ffprobe_bin,
                        ffmpeg_bin=ffmpeg_bin, exact_picture=(method == "video_stream_copy"))
        if cancelled and cancelled():
            raise GenerationCancelledError("Intro Zoom assembly cancelled")
        final_path = destination or original
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidate, final_path)
        return {"assembly": method, "fallback_reason": fallback_reason, **facts}
    finally:
        candidate.unlink(missing_ok=True)
        video_only.unlink(missing_ok=True)
