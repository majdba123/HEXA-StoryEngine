from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.models import RenderPlan
from app.shared.errors import DependencyUnavailableError, StageFailedError


class FFmpegRenderer:
    """Parallel beat-segment renderer with deterministic concat.

    Strict object extraction increases the number of independent layers. Rendering one
    giant sequential overlay graph makes that cost roughly multiply by full-video
    duration. V2 renders short beat-owned segments independently, in bounded parallel,
    then stream-concats identical H.264 segments. This also establishes the right
    boundary for future per-beat cache/recovery.
    """

    def __init__(self, ffmpeg_bin: str = "ffmpeg") -> None:
        self.ffmpeg_bin = ffmpeg_bin

    def render(self, plan: RenderPlan, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        story = sorted(plan.story, key=lambda beat: (beat.start, beat.end, beat.id))
        if not story:
            return self._render_blank(plan, output)

        assets = {asset.id: asset for asset in plan.assets}
        composition = {beat.beat_id: beat for beat in plan.composition}
        motion = {(cue.beat_id, cue.asset_id): cue for cue in plan.motion}
        segment_root = output.parent / f"{output.stem}-segments"
        segment_root.mkdir(parents=True, exist_ok=True)

        jobs: list[tuple[int, object, float, Path]] = []
        if story[0].start > 0.02:
            prelude = segment_root / "0000-prelude.mp4"
            self._render_color_segment(plan, story[0].start, prelude)

        for index, beat in enumerate(story, start=1):
            next_start = story[index].start if index < len(story) else plan.duration
            segment_end = min(plan.duration, max(beat.end, next_start))
            duration = max(0.05, segment_end - beat.start)
            target = segment_root / f"{index:04d}-{beat.id}.mp4"
            jobs.append((index, beat, duration, target))

        worker_env = os.getenv("HEXA_RENDER_WORKERS")
        if worker_env:
            try:
                worker_count = max(1, min(8, int(worker_env)))
            except ValueError:
                worker_count = 1
        else:
            worker_count = max(1, min(4, (os.cpu_count() or 2) // 2))

        failures: list[Exception] = []
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="hexa-render") as pool:
            futures = {
                pool.submit(
                    self._render_beat_segment,
                    plan,
                    beat,
                    duration,
                    target,
                    assets,
                    composition,
                    motion,
                ): target
                for _, beat, duration, target in jobs
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:  # noqa: PERF203 - collect all worker failures
                    failures.append(exc)
        if failures:
            first = failures[0]
            if isinstance(first, (DependencyUnavailableError, StageFailedError)):
                raise first
            raise StageFailedError("parallel render segment failed", details={"error": str(first)})

        segments: list[Path] = []
        prelude = segment_root / "0000-prelude.mp4"
        if prelude.exists():
            segments.append(prelude)
        segments.extend(target for _, _, _, target in jobs)
        self._concat_segments(segments, output)
        return output

    def _render_beat_segment(
        self,
        plan: RenderPlan,
        beat,
        duration: float,
        target: Path,
        assets: dict,
        composition: dict,
        motion: dict,
    ) -> None:
        layout = composition.get(beat.id)
        if not layout or not layout.items:
            self._render_color_segment(plan, duration, target)
            return

        command: list[str] = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
        ordered_items = sorted(layout.items, key=lambda row: row.z)
        for item in ordered_items:
            asset = assets.get(item.asset_id)
            if asset is None or not asset.image_path.exists():
                raise StageFailedError(
                    "render plan references missing asset",
                    details={"asset_id": item.asset_id, "beat_id": beat.id},
                )
            command.extend(["-i", str(asset.image_path)])

        filters: list[str] = [
            f"color=c=white:s={plan.width}x{plan.height}:r={plan.fps}:d={duration:.6f},format=rgba[base0]"
        ]
        previous = "base0"
        for layer_index, item in enumerate(ordered_items):
            cue = motion.get((beat.id, item.asset_id))
            box_w = max(2, round(plan.width * item.width))
            box_h = max(2, round(plan.height * item.height))
            target_x = round(plan.width * (item.x - item.width / 2))
            target_y = round(plan.height * (item.y - item.height / 2))
            global_start = float(cue.start if cue else beat.start)
            global_end = float(cue.end if cue else min(beat.end, beat.start + 0.32))
            start = max(0.0, global_start - beat.start)
            end = min(duration, max(start + 0.05, global_end - beat.start))
            reveal_duration = max(0.05, end - start)
            source_label = f"asset{layer_index}"
            filters.append(
                f"[{layer_index}:v]format=rgba,"
                f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease,"
                f"loop=loop=-1:size=1:start=0,trim=duration={duration:.6f},setpts=PTS-STARTPTS,"
                f"fade=t=in:st={start:.6f}:d={reveal_duration:.6f}:alpha=1[{source_label}]"
            )
            kind = getattr(cue, "kind", "reveal_in") if cue else "reveal_in"
            if kind == "context_in":
                x_expr = str(target_x)
                y_expr = str(target_y)
            elif kind == "handoff_in":
                x_expr = self._entry_expression(target_x, start, end, offset=64)
                y_expr = str(target_y)
            elif kind == "emphasis_in":
                x_expr = str(target_x)
                y_expr = self._entry_expression(target_y, start, end, offset=20)
            else:
                x_expr = str(target_x)
                y_expr = self._entry_expression(target_y, start, end, offset=32)
            next_label = f"mix{layer_index}"
            filters.append(
                f"[{previous}][{source_label}]overlay=x='{x_expr}':y='{y_expr}':"
                f"enable='between(t,{start:.6f},{duration:.6f})':eof_action=pass:shortest=0[{next_label}]"
            )
            previous = next_label
        filters.append(f"[{previous}]format=yuv420p[vout]")
        command.extend(self._encode_args(filters, target, plan.fps))
        self._run(command, "render segment failed")

    def _render_color_segment(self, plan: RenderPlan, duration: float, target: Path) -> None:
        command = [
            self.ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=white:s={plan.width}x{plan.height}:r={plan.fps}:d={duration:.6f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(plan.fps),
            str(target),
        ]
        self._run(command, "blank render segment failed")

    def _render_blank(self, plan: RenderPlan, output: Path) -> Path:
        self._render_color_segment(plan, plan.duration, output)
        return output

    def _concat_segments(self, segments: list[Path], output: Path) -> None:
        if not segments:
            raise StageFailedError("renderer produced no segments")
        concat_file = output.parent / f"{output.stem}-concat.txt"
        concat_file.write_text(
            "".join(f"file '{str(path.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in segments),
            encoding="utf-8",
        )
        command = [
            self.ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
        self._run(command, "render concat failed")
        if not output.exists() or output.stat().st_size == 0:
            raise StageFailedError("renderer produced no output")

    @staticmethod
    def _encode_args(filters: list[str], target: Path, fps: int) -> list[str]:
        return [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            str(target),
        ]

    @staticmethod
    def _entry_expression(target: int, start: float, end: float, *, offset: int) -> str:
        """Cubic smoothstep entry: strong but less abrupt than the old linear slide."""
        duration = max(0.05, end - start)
        p = f"((t-{start:.6f})/{duration:.6f})"
        eased = f"(3*{p}*{p}-2*{p}*{p}*{p})"
        return (
            f"{target}+if(lt(t,{start:.6f}),{offset},"
            f"if(lt(t,{end:.6f}),{offset}*(1-{eased}),0))"
        )

    @staticmethod
    def _run(command: list[str], message: str) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise DependencyUnavailableError("ffmpeg is not available") from exc
        except subprocess.CalledProcessError as exc:
            raise StageFailedError(message, details={"stderr": (exc.stderr or "")[-6000:]}) from exc
