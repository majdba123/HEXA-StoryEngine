from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.shared.errors import DependencyUnavailableError, StageFailedError
from app.shared.process import run_hidden


@dataclass(frozen=True, slots=True)
class FinalMediaIssue:
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


class FinalMediaVerifier:
    """Prove final encoded-media integrity without mutating the output."""

    def __init__(self, ffprobe_bin: str = "ffprobe", ffmpeg_bin: str = "ffmpeg") -> None:
        self.ffprobe_bin = ffprobe_bin
        self.ffmpeg_bin = ffmpeg_bin

    def inspect(self, video: Path, audio: Path) -> list[FinalMediaIssue]:
        if not video.exists() or video.stat().st_size == 0:
            return [FinalMediaIssue("FINAL_MISSING_OUTPUT", "Final output is missing")]
        try:
            video_probe = self._probe(video)
            audio_probe = self._probe(audio)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return [FinalMediaIssue("FINAL_UNREADABLE_MEDIA", str(exc))]

        streams = video_probe.get("streams", [])
        has_video = any(stream.get("codec_type") == "video" for stream in streams)
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
        issues: list[FinalMediaIssue] = []
        if not has_video:
            issues.append(FinalMediaIssue("FINAL_MISSING_VIDEO", "Final output has no video stream"))
        if not has_audio:
            issues.append(FinalMediaIssue("FINAL_MISSING_AUDIO", "Final output has no audio stream"))

        video_stream = next((row for row in streams if row.get("codec_type") == "video"), {})
        mux_audio_stream = next((row for row in streams if row.get("codec_type") == "audio"), {})
        video_duration = self._duration(video_stream, video_probe)
        mux_audio_duration = self._duration(mux_audio_stream, video_probe)
        source_audio_duration = float(audio_probe.get("format", {}).get("duration") or 0)
        stream_drift = abs(video_duration - mux_audio_duration)
        source_drift = abs(mux_audio_duration - source_audio_duration)
        video_start = float(video_stream.get("start_time") or 0)
        audio_start = float(mux_audio_stream.get("start_time") or 0)
        start_drift = abs(video_start - audio_start)
        if (
            video_duration > 0
            and mux_audio_duration > 0
            and (stream_drift > 0.10 or start_drift > 0.05 or source_drift > 0.12)
        ):
            issues.append(FinalMediaIssue(
                "AUDIO_VIDEO_DRIFT",
                (
                    "A/V stream timing mismatch: "
                    f"duration={stream_drift:.3f}s start={start_drift:.3f}s "
                    f"source_audio={source_drift:.3f}s"
                ),
                {
                    "video_duration": video_duration,
                    "mux_audio_duration": mux_audio_duration,
                    "source_audio_duration": source_audio_duration,
                    "stream_drift": stream_drift,
                    "start_drift": start_drift,
                    "source_drift": source_drift,
                },
            ))

        if has_video and video_duration > 0:
            try:
                white_flashes = self._white_flash_frames(video, video_duration)
            except (OSError, subprocess.CalledProcessError) as exc:
                issues.append(FinalMediaIssue(
                    "FINAL_VISUAL_QA_UNAVAILABLE",
                    "Unable to scan final video for encoded white flashes",
                    {"error": str(exc)},
                ))
            else:
                if white_flashes:
                    issues.append(FinalMediaIssue(
                        "VISUAL_WHITE_FLASH",
                        "Final video contains internal near-white handoff frames",
                        {"count": len(white_flashes), "first_frames": white_flashes[:20]},
                    ))
        return self._dedupe(issues)

    def require(self, video: Path, audio: Path) -> None:
        issues = self.inspect(video, audio)
        if issues:
            issue = issues[0]
            raise StageFailedError(
                issue.message,
                details={"code": issue.code, **issue.context},
            )

    def _white_flash_frames(
        self, video: Path, duration: float
    ) -> list[dict[str, float | int]]:
        command = [
            self.ffmpeg_bin, "-hide_banner", "-nostats", "-loglevel", "info",
            "-i", str(video), "-an", "-vf",
            "scale=320:-2:flags=fast_bilinear,negate,blackframe=amount=99:threshold=24",
            "-f", "null", "-",
        ]
        result = run_hidden(command, check=True, capture_output=True, text=True)
        pattern = re.compile(r"frame:(\d+).*?t:([0-9.]+)")
        flashes: list[dict[str, float | int]] = []
        guard = min(0.12, duration / 4.0)
        for match in pattern.finditer(result.stderr or ""):
            frame = int(match.group(1))
            timestamp = float(match.group(2))
            if not (guard < timestamp < duration - guard):
                continue
            if self._frame_has_meaningful_foreground(video, frame):
                continue
            flashes.append({"frame": frame, "time": timestamp})
        return flashes

    def _frame_has_meaningful_foreground(self, video: Path, frame_index: int) -> bool:
        command = [
            self.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-i", str(video),
            "-frames:v", "1", "-vf",
            (
                f"select=eq(n\,{max(0, int(frame_index))}),"
                "scale=160:90:flags=fast_bilinear,format=rgb24"
            ),
            "-f", "rawvideo", "pipe:1",
        ]
        try:
            sampled = run_hidden(command, check=True, capture_output=True, text=False).stdout
        except (OSError, subprocess.CalledProcessError):
            return False
        expected = 160 * 90 * 3
        if not isinstance(sampled, (bytes, bytearray)) or len(sampled) < expected:
            return False
        data = sampled[:expected]
        pixels = 160 * 90
        foreground = 0
        strong_foreground = 0
        for offset in range(0, expected, 3):
            red, green, blue = data[offset:offset + 3]
            minimum = min(red, green, blue)
            maximum = max(red, green, blue)
            if minimum < 245 or maximum - minimum > 7:
                foreground += 1
            if minimum < 235 or maximum - minimum > 16:
                strong_foreground += 1
        return foreground / pixels >= 0.0030 or strong_foreground / pixels >= 0.0015

    @staticmethod
    def _duration(stream: dict, probe: dict) -> float:
        value = stream.get("duration")
        if value not in (None, "N/A", ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
        return float(probe.get("format", {}).get("duration") or 0)

    def _probe(self, path: Path) -> dict:
        command = [
            self.ffprobe_bin, "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ]
        try:
            result = run_hidden(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise DependencyUnavailableError("ffprobe is not available") from exc
        except subprocess.CalledProcessError as exc:
            raise ValueError((exc.stderr or "ffprobe failed")[-2000:]) from exc
        return json.loads(result.stdout)

    @staticmethod
    def _dedupe(issues: list[FinalMediaIssue]) -> list[FinalMediaIssue]:
        seen: set[tuple[str, str]] = set()
        output: list[FinalMediaIssue] = []
        for issue in issues:
            key = (issue.code, json.dumps(issue.context, sort_keys=True, default=str))
            if key not in seen:
                seen.add(key)
                output.append(issue)
        return output
