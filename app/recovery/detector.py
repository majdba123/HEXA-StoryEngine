from __future__ import annotations

import json
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
    def __init__(self, ffprobe_bin: str = "ffprobe") -> None:
        self.ffprobe_bin = ffprobe_bin

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
            if beat and cue.start < beat.start - 0.12:
                issues.append(DetectedIssue(
                    "ELEMENT_APPEARS_TOO_EARLY",
                    f"Motion begins before narration: {cue.asset_id}",
                    {"beat_id": cue.beat_id, "asset_id": cue.asset_id},
                ))
            if beat and cue.asset_id in beat.primary_asset_ids:
                beat_duration = max(0.05, beat.end - beat.start)
                late_limit = min(0.42, max(0.18, beat_duration * 0.32))
                if cue.start > beat.start + late_limit:
                    issues.append(DetectedIssue(
                        "ELEMENT_APPEARS_TOO_LATE",
                        f"Motion begins too late for narration: {cue.asset_id}",
                        {
                            "beat_id": cue.beat_id,
                            "asset_id": cue.asset_id,
                            "delay": cue.start - beat.start,
                        },
                    ))
        for beat_id, cues in by_beat.items():
            beat = story_by_id.get(beat_id)
            if beat is None:
                continue
            strong = [cue for cue in cues if cue.kind != "context_in"]
            if len(cues) >= 3:
                starts = sorted(cue.start for cue in cues)
                if starts[-1] - starts[0] < 0.08:
                    issues.append(DetectedIssue(
                        "MULTI_ELEMENT_POP",
                        f"Too many simultaneous entrances: {beat_id}",
                        {"beat_id": beat_id, "count": len(cues)},
                    ))

            beat_duration = max(0.05, beat.end - beat.start)
            for cue in strong:
                cue_duration = cue.end - cue.start
                minimum = 0.22 if beat_duration < 0.75 else 0.34
                if cue_duration + 1e-6 < minimum:
                    issues.append(DetectedIssue(
                        "MOTION_TOO_FAST",
                        f"Entrance is too fast to read: {cue.asset_id}",
                        {
                            "beat_id": beat_id,
                            "asset_id": cue.asset_id,
                            "duration": cue_duration,
                            "minimum": minimum,
                        },
                    ))

            if beat_duration >= 0.90 and strong:
                last_motion_end = max(cue.end for cue in strong)
                required_hold = min(0.70, max(0.28, beat_duration * 0.22))
                actual_hold = beat.end - last_motion_end
                if actual_hold + 1e-6 < required_hold:
                    issues.append(DetectedIssue(
                        "INSUFFICIENT_VISUAL_HOLD",
                        f"Beat ends before the composition can be read: {beat_id}",
                        {
                            "beat_id": beat_id,
                            "hold": actual_hold,
                            "required_hold": required_hold,
                        },
                    ))

            max_strong = max(1, min(5, int(beat_duration / 0.42) + 1))
            if len(strong) > max_strong:
                issues.append(DetectedIssue(
                    "MOTION_OVERLOAD",
                    f"Too many strong motions for spoken beat: {beat_id}",
                    {
                        "beat_id": beat_id,
                        "strong_count": len(strong),
                        "maximum": max_strong,
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

        video_duration = float(video_probe.get("format", {}).get("duration") or 0)
        audio_duration = float(audio_probe.get("format", {}).get("duration") or 0)
        drift = abs(video_duration - audio_duration)
        if video_duration > 0 and audio_duration > 0 and drift > 0.25:
            issues.append(DetectedIssue(
                "AUDIO_VIDEO_DRIFT",
                f"Audio/video duration mismatch is {drift:.3f}s",
                {"video_duration": video_duration, "audio_duration": audio_duration, "drift": drift},
            ))
        return self._dedupe(issues)

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
