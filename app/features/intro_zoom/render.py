from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.features.intro_zoom.geometry import Rect, animated_crop, final_crop
from app.features.intro_zoom.models import FPS, PreparedIntro
from app.features.intro_zoom.validation import open_image
from app.shared.errors import GenerationCancelledError, StageFailedError


def compose_frame(source: Image.Image, width: int, height: int, crop: Rect,
                  background: Image.Image | None = None) -> Image.Image:
    """Contain the source crop and fill edge overflow with a quiet blurred backdrop."""
    if background is None:
        background = ImageEnhance.Brightness(
            ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS)
            .filter(ImageFilter.GaussianBlur(max(6, min(width, height) // 45))),
        ).enhance(0.55)
    frame = background.copy()
    scale = min(width / crop.width, height / crop.height)
    ox = (width - crop.width * scale) / 2
    oy = (height - crop.height * scale) / 2
    left = max(0, crop.x)
    top = max(0, crop.y)
    right = min(source.width, crop.x + crop.width)
    bottom = min(source.height, crop.y + crop.height)
    if right <= left or bottom <= top:
        raise ValueError("Intro crop does not intersect the source image")
    picture = source.crop((left, top, right, bottom))
    rw = max(1, round((right - left) * scale))
    rh = max(1, round((bottom - top) * scale))
    picture = picture.resize((rw, rh), Image.Resampling.LANCZOS)
    frame.paste(picture, (round(ox + (left - crop.x) * scale),
                          round(oy + (top - crop.y) * scale)))
    picture.close()
    return frame


def preview_frame(source: Image.Image, width: int, height: int, prepared: PreparedIntro,
                  *, final: bool) -> Image.Image:
    end = final_crop(source.width, source.height, width, height,
                     prepared.config.focus_x, prepared.config.focus_y,
                     prepared.config.magnification)
    crop = end if final else Rect(0, 0, source.width, source.height)
    return compose_frame(source, width, height, crop)


def render_intro(prepared: PreparedIntro, width: int, height: int, output: Path,
                 *, ffmpeg_bin: str = "ffmpeg", level: int | None = None,
                 timebase: str = "1/15360", cancelled: Callable[[], bool] | None = None,
                 next_frame: Image.Image | None = None) -> Path:
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError("Intro output size must be positive and even")
    if next_frame is not None and next_frame.size != (width, height):
        raise ValueError("Transition frame must match the output size")
    output.parent.mkdir(parents=True, exist_ok=True)
    source = open_image(prepared.config.image)
    end = final_crop(source.width, source.height, width, height,
                     prepared.config.focus_x, prepared.config.focus_y,
                     prepared.config.magnification)
    background = ImageEnhance.Brightness(
        ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS)
        .filter(ImageFilter.GaussianBlur(max(6, min(width, height) // 45))),
    ).enhance(0.55)
    # The existing H.264 target normally uses 1/15360. Match its MP4 video clock.
    timescale = int(timebase.split("/")[1]) if timebase.startswith("1/") else 15360
    command = [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
               "-r", str(FPS), "-i", "pipe:0", "-i", str(prepared.config.audio),
               "-filter_complex",
               (f"[1:a:0]aresample=48000,aformat=channel_layouts=stereo,apad,"
                f"atrim=duration={prepared.duration:.6f},asetpts=PTS-STARTPTS[a]"),
               "-map", "0:v:0", "-map", "[a]", "-frames:v", str(prepared.frames),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-g", "30", "-r", str(FPS),
               "-video_track_timescale", str(timescale),
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-movflags", "+faststart"]
    if level is not None and 30 <= level <= 52:
        command += ["-level:v", f"{level / 10:.1f}"]
    command.append(str(output))
    log_path = output.with_suffix(".ffmpeg.log")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    transition_frames = min(6, prepared.frames // 10) if next_frame is not None else 0
    motion_frames = prepared.frames - transition_frames
    transition_image = next_frame.convert("RGB") if next_frame is not None else None
    completed = False
    try:
        with log_path.open("wb") as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log,
                                       creationflags=flags)
            try:
                assert process.stdin is not None
                for frame_no in range(prepared.frames):
                    if cancelled and cancelled():
                        raise GenerationCancelledError("Intro Zoom cancelled")
                    crop = animated_crop(source.width, source.height, end,
                                         min(frame_no, motion_frames - 1), motion_frames)
                    frame = compose_frame(source, width, height, crop, background)
                    if transition_image is not None and frame_no >= motion_frames:
                        alpha = (frame_no - motion_frames + 1) / transition_frames
                        blended = Image.blend(frame, transition_image, alpha)
                        frame.close()
                        frame = blended
                    process.stdin.write(frame.tobytes())
                    frame.close()
                process.stdin.close()
                if process.wait(timeout=180) != 0:
                    raise StageFailedError("Intro Zoom encode failed", details={
                        "code": "INTRO_ENCODE_FAILED", "log": str(log_path)})
                completed = True
            except BaseException:
                process.kill()
                process.wait()
                raise
    except (OSError, subprocess.TimeoutExpired, BrokenPipeError) as exc:
        raise StageFailedError("Intro Zoom encode failed", details={
            "code": "INTRO_ENCODE_FAILED", "log": str(log_path), "error": str(exc)}) from exc
    finally:
        source.close()
        background.close()
        if transition_image is not None:
            transition_image.close()
        if not completed:
            output.unlink(missing_ok=True)
    if not output.is_file() or output.stat().st_size == 0:
        raise StageFailedError("Intro Zoom encode produced no video", details={
            "code": "INTRO_ENCODE_EMPTY", "log": str(log_path)})
    return output
