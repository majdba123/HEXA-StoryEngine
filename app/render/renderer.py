from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.models import MotionCue, RenderPlan, StoryBeat
from app.shared.errors import DependencyUnavailableError, StageFailedError


class FFmpegRenderer:
    """Parallel beat renderer with semantic motion and continuous handoffs.

    Beat segments are encoded independently for bounded render cost and recovery. Each
    incoming actor executes its authored entry plus optional in-frame travel/scale.
    During the following beat, the previous composition executes its authored exit while
    fading under the incoming composition. This keeps the timeline visually continuous
    without putting arbitrary delays back into Story or speech alignment.
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

        total_frames = max(1, round(plan.duration * plan.fps))
        first_frame = self._time_to_frame(story[0].start, plan.fps, total_frames)
        jobs: list[tuple[int, StoryBeat, StoryBeat | None, float, int, Path]] = []
        if first_frame > 0:
            prelude = segment_root / "0000-prelude.mp4"
            self._render_color_segment(
                plan,
                first_frame / plan.fps,
                prelude,
                frame_count=first_frame,
            )

        start_frame = first_frame
        for index, beat in enumerate(story, start=1):
            if index < len(story):
                end_frame = self._time_to_frame(story[index].start, plan.fps, total_frames)
            else:
                end_frame = total_frames
            end_frame = max(start_frame + 1, min(total_frames, end_frame))
            frame_count = end_frame - start_frame
            segment_start = start_frame / plan.fps
            target = segment_root / f"{index:04d}-{beat.id}.mp4"
            previous_beat = story[index - 2] if index > 1 else None
            jobs.append((index, beat, previous_beat, segment_start, frame_count, target))
            start_frame = end_frame

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
                    previous_beat,
                    segment_start,
                    frame_count,
                    target,
                    assets,
                    composition,
                    motion,
                ): target
                for _, beat, previous_beat, segment_start, frame_count, target in jobs
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
        segments.extend(target for _, _, _, _, _, target in jobs)
        self._concat_segments(segments, output)
        return output

    def _render_beat_segment(
        self,
        plan: RenderPlan,
        beat: StoryBeat,
        previous_beat: StoryBeat | None,
        segment_start: float,
        frame_count: int,
        target: Path,
        assets: dict,
        composition: dict,
        motion: dict[tuple[str, str], MotionCue],
    ) -> None:
        duration = frame_count / plan.fps
        layout = composition.get(beat.id)
        if not layout or not layout.items:
            self._render_color_segment(plan, duration, target, frame_count=frame_count)
            return

        ordered_items = sorted(layout.items, key=lambda row: row.z)
        previous_layout = composition.get(previous_beat.id) if previous_beat else None
        outgoing_items = (
            sorted(previous_layout.items, key=lambda row: row.z)
            if previous_layout and previous_layout.items
            else []
        )

        command: list[str] = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
        for item in [*outgoing_items, *ordered_items]:
            asset = assets.get(item.asset_id)
            if asset is None or not asset.image_path.exists():
                raise StageFailedError(
                    "render plan references missing asset",
                    details={"asset_id": item.asset_id, "beat_id": beat.id},
                )
            command.extend(["-loop", "1", "-framerate", str(plan.fps), "-i", str(asset.image_path)])

        filters: list[str] = [
            f"color=c=white:s={plan.width}x{plan.height}:r={plan.fps}:d={duration:.6f},"
            "format=rgba[base0]"
        ]
        composite_label = "base0"

        handoff_start, handoff_fade = self._incoming_handoff_window(
            beat=beat,
            ordered_items=ordered_items,
            segment_start=segment_start,
            duration=duration,
            motion=motion,
        )
        if outgoing_items:
            fade_duration = min(
                handoff_fade,
                max(1.0 / plan.fps, duration - handoff_start),
            )
            for input_index, item in enumerate(outgoing_items):
                box_w, box_h, target_x, target_y = self._geometry(plan, item)
                previous_cue = (
                    motion.get((previous_beat.id, item.asset_id))
                    if previous_beat is not None
                    else None
                )
                exit_dx = self._param_float(previous_cue, "exit_dx_ratio", 0.0) * box_w
                exit_dy = self._param_float(previous_cue, "exit_dy_ratio", 0.0) * box_h
                exit_scale = self._param_float(previous_cue, "exit_scale", 1.0)
                exit_end = min(duration, handoff_start + fade_duration)
                scale_expr = self._scale_expression(
                    start=handoff_start,
                    end=exit_end,
                    from_scale=1.0,
                    to_scale=exit_scale,
                    easing="ease_in_cubic",
                )
                x_motion = self._phase_delta_expression(
                    start=handoff_start,
                    end=exit_end,
                    delta=exit_dx,
                    easing="ease_in_cubic",
                )
                y_motion = self._phase_delta_expression(
                    start=handoff_start,
                    end=exit_end,
                    delta=exit_dy,
                    easing="ease_in_cubic",
                )
                source_label = f"outgoing{input_index}"
                filters.append(
                    f"[{input_index}:v]format=rgba,"
                    f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease,"
                    f"scale=w='iw*({scale_expr})':h='ih*({scale_expr})':eval=frame,"
                    f"trim=duration={duration:.6f},"
                    "setpts=PTS-STARTPTS,"
                    f"fade=t=out:st={handoff_start:.6f}:d={fade_duration:.6f}:alpha=1"
                    f"[{source_label}]"
                )
                next_label = f"outmix{input_index}"
                x_expr = f"{target_x}+({box_w}-overlay_w)/2+({x_motion})"
                y_expr = f"{target_y}+({box_h}-overlay_h)/2+({y_motion})"
                filters.append(
                    f"[{composite_label}][{source_label}]overlay=x='{x_expr}':y='{y_expr}':"
                    f"enable='between(t,0,{duration:.6f})':eof_action=pass:shortest=0"
                    f"[{next_label}]"
                )
                composite_label = next_label

        input_offset = len(outgoing_items)
        for layer_index, item in enumerate(ordered_items):
            cue = motion.get((beat.id, item.asset_id))
            box_w, box_h, target_x, target_y = self._geometry(plan, item)
            start, end, fade_duration = self._cue_window(
                beat=beat,
                cue=cue,
                segment_start=segment_start,
                duration=duration,
            )
            input_index = input_offset + layer_index
            source_label = f"asset{layer_index}"

            entry_dx, entry_dy = self._legacy_entry_delta(cue, box_w=box_w, box_h=box_h)
            entry_scale = self._param_float(cue, "entry_scale", 1.0)
            travel_start, travel_end = self._travel_window(
                cue=cue,
                segment_start=segment_start,
                duration=duration,
                fallback=end,
            )
            travel_enabled = bool(cue and cue.params.get("travel_enabled", False)) and travel_end > travel_start
            travel_dx = self._param_float(cue, "travel_dx_ratio", 0.0) * box_w if travel_enabled else 0.0
            travel_dy = self._param_float(cue, "travel_dy_ratio", 0.0) * box_h if travel_enabled else 0.0
            travel_scale = self._param_float(cue, "travel_scale", 1.0) if travel_enabled else 1.0

            entry_x = self._entry_delta_expression(start, end, entry_dx)
            entry_y = self._entry_delta_expression(start, end, entry_dy)
            travel_x = self._phase_delta_expression(
                start=travel_start,
                end=travel_end,
                delta=travel_dx,
                easing="smoothstep",
            )
            travel_y = self._phase_delta_expression(
                start=travel_start,
                end=travel_end,
                delta=travel_dy,
                easing="smoothstep",
            )
            entry_scale_expr = self._scale_expression(
                start=start,
                end=end,
                from_scale=entry_scale,
                to_scale=1.0,
                easing="ease_out_cubic",
            )
            if travel_enabled:
                travel_scale_expr = self._scale_expression(
                    start=travel_start,
                    end=travel_end,
                    from_scale=1.0,
                    to_scale=travel_scale,
                    easing="smoothstep",
                )
                scale_expr = f"({entry_scale_expr})*({travel_scale_expr})"
            else:
                scale_expr = entry_scale_expr

            filters.append(
                f"[{input_index}:v]format=rgba,"
                f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease,"
                f"scale=w='iw*({scale_expr})':h='ih*({scale_expr})':eval=frame,"
                f"trim=duration={duration:.6f},setpts=PTS-STARTPTS,"
                f"fade=t=in:st={start:.6f}:d={fade_duration:.6f}:alpha=1[{source_label}]"
            )
            x_expr = f"{target_x}+({box_w}-overlay_w)/2+({entry_x})+({travel_x})"
            y_expr = f"{target_y}+({box_h}-overlay_h)/2+({entry_y})+({travel_y})"
            next_label = f"mix{layer_index}"
            filters.append(
                f"[{composite_label}][{source_label}]overlay=x='{x_expr}':y='{y_expr}':"
                f"enable='between(t,{start:.6f},{duration:.6f})':eof_action=pass:shortest=0"
                f"[{next_label}]"
            )
            composite_label = next_label
        filters.append(f"[{composite_label}]format=yuv420p[vout]")
        command.extend(self._encode_args(filters, target, plan.fps, frame_count))
        self._run(command, "render segment failed")

    @classmethod
    def _incoming_handoff_window(
        cls,
        *,
        beat: StoryBeat,
        ordered_items: list,
        segment_start: float,
        duration: float,
        motion: dict[tuple[str, str], MotionCue],
    ) -> tuple[float, float]:
        windows: list[tuple[float, float]] = []
        for item in ordered_items:
            start, _, fade_duration = cls._cue_window(
                beat=beat,
                cue=motion.get((beat.id, item.asset_id)),
                segment_start=segment_start,
                duration=duration,
            )
            windows.append((start, fade_duration))
        if not windows:
            return 0.0, min(0.12, duration)
        return min(windows, key=lambda row: row[0])

    @staticmethod
    def _cue_window(
        *,
        beat: StoryBeat,
        cue: MotionCue | None,
        segment_start: float,
        duration: float,
    ) -> tuple[float, float, float]:
        global_start = float(cue.start if cue else beat.start)
        global_end = float(cue.end if cue else min(beat.end, beat.start + 0.32))
        start = max(0.0, global_start - segment_start)
        end = min(duration, max(start + 0.05, global_end - segment_start))
        reveal_duration = max(0.05, end - start)
        fade_duration = min(0.18, max(0.10, reveal_duration * 0.42))
        return start, end, fade_duration

    @staticmethod
    def _travel_window(
        *,
        cue: MotionCue | None,
        segment_start: float,
        duration: float,
        fallback: float,
    ) -> tuple[float, float]:
        if cue is None or not cue.params.get("travel_enabled", False):
            return fallback, fallback
        global_start = float(cue.params.get("travel_start", cue.end))
        global_end = float(cue.params.get("travel_end", global_start))
        start = max(0.0, min(duration, global_start - segment_start))
        end = max(start, min(duration, global_end - segment_start))
        return start, end

    @staticmethod
    def _geometry(plan: RenderPlan, item) -> tuple[int, int, int, int]:
        box_w = max(2, round(plan.width * item.width))
        box_h = max(2, round(plan.height * item.height))
        target_x = round(plan.width * (item.x - item.width / 2))
        target_y = round(plan.height * (item.y - item.height / 2))
        return box_w, box_h, target_x, target_y

    def _render_color_segment(
        self,
        plan: RenderPlan,
        duration: float,
        target: Path,
        *,
        frame_count: int | None = None,
    ) -> None:
        frame_count = frame_count or max(1, round(duration * plan.fps))
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
            "-bf",
            "0",
            "-r",
            str(plan.fps),
            "-frames:v",
            str(frame_count),
            str(target),
        ]
        self._run(command, "blank render segment failed")

    def _render_blank(self, plan: RenderPlan, output: Path) -> Path:
        frame_count = max(1, round(plan.duration * plan.fps))
        self._render_color_segment(
            plan,
            frame_count / plan.fps,
            output,
            frame_count=frame_count,
        )
        return output

    def _concat_segments(self, segments: list[Path], output: Path) -> None:
        if not segments:
            raise StageFailedError("renderer produced no segments")
        concat_file = output.parent / f"{output.stem}-concat.txt"
        concat_file.write_text(
            "".join(
                f"file '{str(path.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
                for path in segments
            ),
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
    def _encode_args(
        filters: list[str],
        target: Path,
        fps: int,
        frame_count: int,
    ) -> list[str]:
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
            "-bf",
            "0",
            "-r",
            str(fps),
            "-frames:v",
            str(frame_count),
            str(target),
        ]

    @staticmethod
    def _time_to_frame(value: float, fps: int, total_frames: int) -> int:
        return max(0, min(total_frames, round(max(0.0, value) * fps)))

    @staticmethod
    def _param_float(cue: MotionCue | None, key: str, default: float) -> float:
        if cue is None:
            return default
        try:
            return float(cue.params.get(key, default))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _legacy_entry_delta(cls, cue: MotionCue | None, *, box_w: int, box_h: int) -> tuple[float, float]:
        if cue is not None and int(cue.params.get("motion_version", 1)) >= 2:
            return (
                cls._param_float(cue, "entry_dx_ratio", 0.0) * box_w,
                cls._param_float(cue, "entry_dy_ratio", 0.0) * box_h,
            )
        kind = cue.kind if cue else "reveal_in"
        if kind == "handoff_in":
            return 58.0, 0.0
        if kind == "emphasis_in":
            return 0.0, 20.0
        if kind == "soft_in":
            return 0.0, 12.0
        return 0.0, 30.0

    @classmethod
    def _entry_delta_expression(cls, start: float, end: float, delta: float) -> str:
        if abs(delta) < 1e-6:
            return "0"
        progress = cls._eased_progress_expression(start, end, "ease_out_cubic")
        return f"({delta:.6f})*(1-({progress}))"

    @classmethod
    def _phase_delta_expression(cls, *, start: float, end: float, delta: float, easing: str) -> str:
        if abs(delta) < 1e-6 or end <= start:
            return "0"
        progress = cls._eased_progress_expression(start, end, easing)
        return f"({delta:.6f})*({progress})"

    @classmethod
    def _scale_expression(
        cls,
        *,
        start: float,
        end: float,
        from_scale: float,
        to_scale: float,
        easing: str,
    ) -> str:
        if end <= start or abs(to_scale - from_scale) < 1e-6:
            return f"{to_scale:.6f}"
        progress = cls._eased_progress_expression(start, end, easing)
        delta = to_scale - from_scale
        return f"({from_scale:.6f}+({delta:.6f})*({progress}))"

    @staticmethod
    def _eased_progress_expression(start: float, end: float, easing: str) -> str:
        duration = max(0.05, end - start)
        raw = f"((t-{start:.6f})/{duration:.6f})"
        p = f"max(0,min(1,{raw}))"
        if easing == "ease_out_cubic":
            return f"(1-pow(1-({p}),3))"
        if easing == "ease_in_cubic":
            return f"pow(({p}),3)"
        return f"(3*({p})*({p})-2*({p})*({p})*({p}))"

    @staticmethod
    def _entry_expression(target: int, start: float, end: float, *, offset: int) -> str:
        # Backward-compatible helper retained for callers/tests that still exercise the
        # V1 expression directly. V2 rendering uses normalized semantic deltas above.
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
