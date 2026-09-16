from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models import RenderPlan
from app.shared.errors import DependencyUnavailableError


@dataclass(frozen=True, slots=True)
class DetectedIssue:
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


class RecoveryDetector:
    def __init__(self, ffprobe_bin: str = "ffprobe", ffmpeg_bin: str = "ffmpeg") -> None:
        self.ffprobe_bin = ffprobe_bin
        self.ffmpeg_bin = ffmpeg_bin

    def inspect_plan(self, plan: RenderPlan) -> list[DetectedIssue]:
        issues: list[DetectedIssue] = []
        assets = {asset.id: asset for asset in plan.assets}
        composition = {beat.beat_id: beat for beat in plan.composition}

        for asset in plan.assets:
            if not asset.image_path.exists():
                issues.append(DetectedIssue(
                    "ASSET_BAD_CUTOUT",
                    f"Asset file is missing: {asset.id}",
                    {"asset_id": asset.id},
                ))

        for beat in plan.story:
            if beat.action == "HANDOFF" and not beat.handoff_from:
                issues.append(DetectedIssue(
                    "BAD_HANDOFF",
                    f"Handoff has no source: {beat.id}",
                    {"beat_id": beat.id},
                ))
            layout = composition.get(beat.id)
            if layout and layout.items:
                occupancy = min(1.0, sum(max(0.0, item.width) * max(0.0, item.height) for item in layout.items))
                if occupancy < 0.24:
                    issues.append(DetectedIssue(
                        "LOW_SCREEN_OCCUPANCY",
                        f"Beat occupancy is too low: {beat.id}",
                        {"beat_id": beat.id, "occupancy": occupancy},
                    ))
            for asset_id in beat.primary_asset_ids + beat.support_asset_ids:
                if asset_id not in assets:
                    issues.append(DetectedIssue(
                        "ASSET_BAD_CUTOUT",
                        f"Story references unknown asset: {asset_id}",
                        {"asset_id": asset_id, "beat_id": beat.id},
                    ))

        by_beat: dict[str, list] = {}
        story_by_id = {beat.id: beat for beat in plan.story}
        for cue in plan.motion:
            by_beat.setdefault(cue.beat_id, []).append(cue)
            beat = story_by_id.get(cue.beat_id)
            if beat and cue.start < beat.start - 0.04:
                issues.append(DetectedIssue(
                    "ELEMENT_APPEARS_TOO_EARLY",
                    f"Motion begins before its visual beat: {cue.asset_id}",
                    {"beat_id": cue.beat_id, "asset_id": cue.asset_id},
                ))
            if beat and cue.asset_id in beat.primary_asset_ids:
                audio_anchor = beat.audio_start if beat.audio_start is not None else beat.start
                peak_offset = cue.end - audio_anchor
                if peak_offset > 0.12:
                    issues.append(DetectedIssue(
                        "ELEMENT_APPEARS_TOO_LATE",
                        f"Primary motion settles after narration anchor: {cue.asset_id}",
                        {
                            "beat_id": cue.beat_id,
                            "asset_id": cue.asset_id,
                            "peak_offset": peak_offset,
                        },
                    ))
                elif peak_offset < -0.18:
                    issues.append(DetectedIssue(
                        "ELEMENT_APPEARS_TOO_EARLY",
                        f"Primary motion settles too far before narration anchor: {cue.asset_id}",
                        {
                            "beat_id": cue.beat_id,
                            "asset_id": cue.asset_id,
                            "peak_offset": peak_offset,
                        },
                    ))
        for beat_id, cues in by_beat.items():
            if len(cues) >= 3:
                starts = sorted(cue.start for cue in cues)
                start_span = starts[-1] - starts[0]
                beat = story_by_id.get(beat_id)
                audio_anchor = (
                    beat.audio_start if beat and beat.audio_start is not None
                    else beat.start if beat
                    else None
                )
                narration_locked = False
                if audio_anchor is not None:
                    settle_offsets = [cue.end - audio_anchor for cue in cues]
                    narration_locked = all(-0.18 <= offset <= 0.14 for offset in settle_offsets)

                if start_span < 0.08 and not narration_locked:
                    issues.append(DetectedIssue(
                        "MULTI_ELEMENT_POP",
                        f"Too many simultaneous entrances: {beat_id}",
                        {
                            "beat_id": beat_id,
                            "count": len(cues),
                            "start_span": start_span,
                            "audio_anchor": audio_anchor,
                        },
                    ))
        return self._dedupe(issues)

    def inspect_final(self, video: Path, audio: Path) -> list[DetectedIssue]:
        if not video.exists() or video.stat().st_size == 0:
            return [DetectedIssue("FINAL_MISSING_OUTPUT", "Final output is missing")]
        try:
            video_probe = self._probe(video)
            audio_probe = self._probe(audio)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return [DetectedIssue("FINAL_UNREADABLE_MEDIA", str(exc))]

        streams = video_probe.get("streams", [])
        has_video = any(stream.get("codec_type") == "video" for stream in streams)
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
        issues: list[DetectedIssue] = []
        if not has_video:
            issues.append(DetectedIssue("FINAL_MISSING_VIDEO", "Final output has no video stream"))
        if not has_audio:
            issues.append(DetectedIssue("FINAL_MISSING_AUDIO", "Final output has no audio stream"))

        video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        mux_audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
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
            issues.append(DetectedIssue(
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
                issues.append(DetectedIssue(
                    "FINAL_VISUAL_QA_UNAVAILABLE",
                    "Unable to scan final video for encoded white flashes",
                    {"error": str(exc)},
                ))
            else:
                if white_flashes:
                    issues.append(DetectedIssue(
                        "VISUAL_WHITE_FLASH",
                        "Final video contains internal near-white handoff frames",
                        {
                            "count": len(white_flashes),
                            "first_frames": white_flashes[:20],
                        },
                    ))
        return self._dedupe(issues)

    def _white_flash_frames(self, video: Path, duration: float) -> list[dict[str, float | int]]:
        """Detect internal encoded frames that are effectively pure white.

        The renderer intentionally uses a white canvas, but an authored beat should still
        carry visible foreground during an ordinary handoff. We downscale before the scan
        to keep this final QA cheap, invert white to black, then use FFmpeg's blackframe
        detector. Leading/trailing fade latitude is ignored; only internal flashes fail.
        """
        command = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "info",
            "-i",
            str(video),
            "-an",
            "-vf",
            "scale=320:-2:flags=fast_bilinear,negate,blackframe=amount=99:threshold=24",
            "-f",
            "null",
            "-",
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        pattern = re.compile(r"frame:(\d+).*?t:([0-9.]+)")
        flashes: list[dict[str, float | int]] = []
        guard = min(0.12, duration / 4.0)
        for match in pattern.finditer(result.stderr or ""):
            frame = int(match.group(1))
            timestamp = float(match.group(2))
            if guard < timestamp < duration - guard:
                flashes.append({"frame": frame, "time": timestamp})
        return flashes

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
            self.ffprobe_bin,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise DependencyUnavailableError("ffprobe is not available") from exc
        except subprocess.CalledProcessError as exc:
            raise ValueError((exc.stderr or "ffprobe failed")[-2000:]) from exc
        return json.loads(result.stdout)

    @staticmethod
    def _dedupe(issues: list[DetectedIssue]) -> list[DetectedIssue]:
        seen: set[tuple[str, str]] = set()
        output: list[DetectedIssue] = []
        for issue in issues:
            key = (issue.code, json.dumps(issue.context, sort_keys=True, default=str))
            if key not in seen:
                seen.add(key)
                output.append(issue)
        return output
