from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.models import MotionCue, RenderPlan, StoryBeat
from app.shared.errors import DependencyUnavailableError, StageFailedError
from app.shared.process import run_hidden
from app.render.motion import FFmpegMotionAdapter
from app.render.text import TextRenderer
from app.render.transition import VisualTransitionPolicy


class FFmpegRenderer:
    """Parallel beat-segment renderer with deterministic concat.

    Beat segments are encoded independently for bounded render cost and recovery. Visual
    cutouts stay opaque while moving: alpha crossfades on a white canvas create the exact
    washed-out "ghost" silhouette that looks like a bad mask. True persistent assets are
    held in place; unrelated outgoing artwork is never carried into the next beat.
    """

    def __init__(
        self,
        ffmpeg_bin: str = "ffmpeg",
        *,
        text_font_family: str = "Noto Kufi Arabic",
    ) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.text_renderer = TextRenderer(font_family=text_font_family)
        self.transition_policy = VisualTransitionPolicy()
        self.motion_adapter = FFmpegMotionAdapter()

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
        transition = self.transition_policy.decide(previous_beat, previous_layout, layout)
        persistent_ids = transition.persistent_asset_ids

        command: list[str] = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
        for item in ordered_items:
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

        for layer_index, item in enumerate(ordered_items):
            cue = motion.get((beat.id, item.asset_id))
            box_w, box_h, target_x, target_y = self._geometry(plan, item)
            start, end, fade_duration = self._cue_window(
                beat=beat,
                cue=cue,
                segment_start=segment_start,
                duration=duration,
            )
            persistent = item.asset_id in persistent_ids
            render_constraints = (
                cue.params.get("render_constraints", {})
                if cue is not None and isinstance(cue.params, dict)
                else {}
            )
            geometry_locked = render_constraints.get("geometry_lock") == "authored_footprint"
            alpha_only_reveal = render_constraints.get("reveal_mode") == "alpha_only"

            source_label = f"asset{layer_index}"
            base_source_label = f"asset{layer_index}base"
            # Keep cutout alpha exactly as authored. The transparent pad gives Motion a
            # stable Composition-sized transform box, so scale pulses can happen around
            # the element centre without changing semantic placement.
            filters.append(
                f"[{layer_index}:v]format=rgba,setsar=1,"
                f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
                f"loop=loop=-1:size=1:start=0,trim=duration={duration:.6f},setpts=PTS-STARTPTS"
                f"[{base_source_label}]"
            )
            transform_source_label = base_source_label
            if alpha_only_reveal and not persistent:
                reveal_label = f"asset{layer_index}reveal"
                filters.append(
                    f"[{transform_source_label}]fade=t=in:st={start:.6f}:"
                    f"d={fade_duration:.6f}:alpha=1[{reveal_label}]"
                )
                transform_source_label = reveal_label

            scale_expr = "1"
            if (
                not geometry_locked
                and cue is not None
                and self.motion_adapter.supports(cue)
            ):
                scale_expr = self.motion_adapter.scale_expression(
                    cue=cue,
                    segment_start=segment_start,
                    segment_duration=duration,
                )
            if scale_expr != "1":
                filters.append(
                    f"[{transform_source_label}]scale="
                    f"w='max(2,iw*({scale_expr}))':h='max(2,ih*({scale_expr}))':eval=frame"
                    f"[{source_label}]"
                )
            else:
                filters.append(f"[{transform_source_label}]null[{source_label}]")

            kind = cue.kind if cue else "reveal_in"
            if geometry_locked:
                x_expr = str(target_x)
                y_expr = str(target_y)
            elif cue is not None and self.motion_adapter.supports(cue):
                x_expr, y_expr = self.motion_adapter.position_expressions(
                    cue=cue,
                    target_x=target_x,
                    target_y=target_y,
                    canvas_width=plan.width,
                    canvas_height=plan.height,
                    segment_start=segment_start,
                    segment_duration=duration,
                )
                if scale_expr != "1":
                    x_expr = f"({x_expr})+({box_w}-overlay_w)/2"
                    y_expr = f"({y_expr})+({box_h}-overlay_h)/2"
            elif kind == "handoff_in":
                x_expr = self._entry_expression(target_x, start, end, offset=58)
                y_expr = str(target_y)
            elif kind == "emphasis_in":
                x_expr = str(target_x)
                y_expr = self._entry_expression(target_y, start, end, offset=20)
            elif kind == "soft_in":
                x_expr = str(target_x)
                y_expr = self._entry_expression(target_y, start, end, offset=12)
            else:
                x_expr = str(target_x)
                y_expr = self._entry_expression(target_y, start, end, offset=30)

            next_label = f"mix{layer_index}"
            enable_start = 0.0 if persistent else start
            # Primary artwork must cover the entire authored visual beat. Motion may
            # intentionally begin a few frames after beat.start (for anticipation or
            # narration pacing), but hiding the primary until cue.start exposes the
            # white canvas between beats. Keep it visible at the program's first offset
            # from the beat boundary and let the trajectory begin at the exact cue time.
            # Support layers still obey their staggered cue starts.
            if not persistent and item.asset_id in beat.primary_asset_ids:
                authored_start = max(0.0, beat.start - segment_start)
                enable_start = (
                    0.0
                    if authored_start <= (1.0 / plan.fps) + 1e-6
                    else authored_start
                )
            filters.append(
                f"[{composite_label}][{source_label}]overlay=x='{x_expr}':y='{y_expr}':"
                f"enable='between(t,{enable_start:.6f},{duration:.6f})':eof_action=pass:shortest=0"
                f"[{next_label}]"
            )
            composite_label = next_label

        ass_path = self.text_renderer.write_beat_ass(
            plan,
            beat,
            segment_start=segment_start,
            duration=duration,
            output=target.parent / f"{target.stem}-text.ass",
        )
        if ass_path is not None:
            text_label = "textmix"
            filters.append(self.text_renderer.ass_filter(ass_path, composite_label, text_label))
            composite_label = text_label

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
    def _entry_expression(target: int, start: float, end: float, *, offset: int) -> str:
        duration = max(0.05, end - start)
        # Smoothstep easing keeps strong motion without the abrupt constant-speed
        # slide that made short beats feel rushed. p is clamped by the surrounding
        # conditionals to the [0, 1] movement interval.
        p = f"((t-{start:.6f})/{duration:.6f})"
        eased = f"(3*{p}*{p}-2*{p}*{p}*{p})"
        return (
            f"{target}+if(lt(t,{start:.6f}),{offset},"
            f"if(lt(t,{end:.6f}),{offset}*(1-{eased}),0))"
        )

    @staticmethod
    def _run(command: list[str], message: str) -> None:
        try:
            run_hidden(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise DependencyUnavailableError("ffmpeg is not available") from exc
        except subprocess.CalledProcessError as exc:
            raise StageFailedError(message, details={"stderr": (exc.stderr or "")[-6000:]}) from exc
