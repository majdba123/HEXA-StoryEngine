from __future__ import annotations

import math
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config import RenderResourceSettings
from app.motion.continuity import ContinuityContract
from app.models import MotionCue, RenderPlan, StoryBeat
from app.motion.timing import GOLDEN_MINOR
from app.shared.errors import DependencyUnavailableError, StageFailedError
from app.shared.process import run_hidden
from app.motion.interaction import interaction_schedule
from app.motion.spoken_pulse import settled_at
from app.render.connection import (
    connection_specs,
    draw_connection_sequence,
    label_arrow_specs,
    relation_arrow_specs,
    visible_rect,
)
from app.render.expression import compile_expression
from app.render.write_on import authored_path_directions, write_on_filter, write_on_frame_count
from app.render.motion import FFmpegMotionAdapter
from app.render.resources import RenderConcurrencyPolicy
from app.render.text import TextRenderer
from app.render.transition import SceneTransitionMode, VisualTransitionPolicy
from app.shared.frame_grid import beat_segments, first_visible_frame, time_to_frame


# Safest carrier roles (see ``_visual_carrier_asset_id.safety_rank``): CONTEXT, OBJECT,
# CHARACTER/ACTOR and SUPPORT. ACTION, PRIMARY and RESULT content is never shown early.
_SAFE_EARLY_ROLE_RANK = 3

class FFmpegRenderer:
    """Parallel beat-segment renderer with deterministic concat.

    Beat segments are encoded independently for bounded render cost. Visual
    cutouts stay opaque once settled and while moving: alpha crossfades on a white canvas
    create the exact washed-out "ghost" silhouette that looks like a bad mask. The single
    exception is Motion's entry opacity clock (Sprint 4.4): a short reveal -> settle ramp
    on the asset's own layer, shared by every layer of a Pass2 family. Scene boundaries
    use a bounded opaque outgoing bridge behind crisp incoming artwork; explicit authored
    handoffs may blur that old full-scene bridge before it is removed. When the plan
    carries a scene-boundary release (Sprint 4.5), the whole outgoing scene fades as one
    group on the planned clock instead of drifting; the renderer only executes it.
    """

    def __init__(
        self,
        ffmpeg_bin: str = "ffmpeg",
        *,
        resources: RenderResourceSettings | None = None,
        defer_cleanup: bool = False,
    ) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.resources = resources or RenderResourceSettings.from_env()
        self.concurrency = RenderConcurrencyPolicy(self.resources)
        self.defer_cleanup = defer_cleanup
        self.last_worker_count: int | None = None
        self._filter_complex_file_option_cache: str | None = None
        self.text_renderer = TextRenderer()
        self.transition_policy = VisualTransitionPolicy()
        self.lifecycle = ContinuityContract()
        self.motion_adapter = FFmpegMotionAdapter()


    def preflight(self, root: Path) -> Path:
        """Run a real H.264 encode before expensive StoryEngine stages begin.

        This validates the installed FFmpeg binary, the selected file-backed complex
        filter syntax, libx264, pixel format, and the same CRF/fps path used by real
        beat segments. It intentionally renders only two tiny frames.
        """
        root.mkdir(parents=True, exist_ok=True)
        target = root / "ffmpeg-render-preflight.mp4"
        command = [
            self.ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=160x90:r=30:d=0.10",
        ]
        command.extend(
            self._encode_args(
                ["[0:v]format=yuv420p[vout]"],
                target,
                fps=30,
                frame_count=2,
            )
        )
        self._run(command, "ffmpeg render preflight failed")
        if not target.exists() or target.stat().st_size == 0:
            raise StageFailedError(
                "ffmpeg render preflight produced no output",
                details={"code": "RENDER_PREFLIGHT_EMPTY"},
            )
        return target

    def render(
        self,
        plan: RenderPlan,
        output: Path,
    ) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        story = sorted(plan.story, key=lambda beat: (beat.start, beat.end, beat.id))
        if not story:
            return self._render_blank(plan, output)

        assets = {asset.id: asset for asset in plan.assets}
        composition = {beat.beat_id: beat for beat in plan.composition}
        motion = {(cue.beat_id, cue.asset_id): cue for cue in plan.motion}
        segment_root = output.parent / f"{output.stem}-segments"
        if segment_root.is_symlink():
            raise StageFailedError("renderer segment directory must not be a symlink")
        segment_root.mkdir(parents=True, exist_ok=True)
        # Resolve file-backed filter transport before worker threads begin. Pipeline
        # preflight normally seeds the cache, but direct renderer callers get the same
        # fail-fast guarantee without a capability-probe race between segments.
        self._filter_complex_file_option(segment_root)

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

        for segment in beat_segments(story, duration=plan.duration, fps=plan.fps):
            jobs.append((
                segment.index,
                segment.beat,
                segment.previous_beat,
                segment.start_frame / plan.fps,
                segment.frame_count,
                segment_root / f"{segment.index:04d}-{segment.beat.id}.mp4",
            ))

        worker_count = self.concurrency.workers(width=plan.width, height=plan.height)
        self.last_worker_count = worker_count

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
        if any(not segment.is_file() or segment.stat().st_size == 0 for segment in segments):
            raise StageFailedError("render segment missing or empty before concat")
        self._concat_segments(segments, output)
        if not self.resources.keep_intermediates and not self.defer_cleanup:
            self.cleanup_intermediates(output, source_paths={Path(a.image_path) for a in plan.assets})
        return output

    @staticmethod
    def cleanup_intermediates(output: Path, *, source_paths: set[Path] | None = None) -> None:
        """Remove only recognized renderer files after all workers and concat finish."""
        segment_root = output.parent / f"{output.stem}-segments"
        if segment_root.is_symlink() or segment_root.resolve().parent != output.parent.resolve():
            raise StageFailedError("unsafe renderer cleanup path")
        if source_paths and any(segment_root == source or segment_root in source.parents
                                for source in (p.resolve() for p in source_paths)):
            raise StageFailedError("renderer cleanup overlaps a source asset")
        allowed = re.compile(
            r"(?:\d{4}-(?:prelude|beat-[\w-]+)(?:\.mp4|-filter-complex\.ffgraph|"
            r"-text(?:-under)?\.ass|-connection-\d+(?:-\d+)?\.png|-blur-[a-z]*\d+-\d+\.cmd|-defocus-\d+\.cmd)|ffmpeg-filter-option-probe\.ffgraph)"
        )
        if segment_root.exists():
            for path in segment_root.iterdir():
                if path.is_symlink() or not path.is_file() or not allowed.fullmatch(path.name):
                    continue
                path.unlink()
            if not any(segment_root.iterdir()):
                segment_root.rmdir()
        concat_file = output.parent / f"{output.stem}-concat.txt"
        if concat_file.is_file() and not concat_file.is_symlink():
            concat_file.unlink()

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
        if beat.active_visual_semantic_state is not None:
            active_asset_ids = set(beat.active_visual_semantic_state)
            ordered_items = [
                item for item in ordered_items if item.asset_id in active_asset_ids
            ]
        if not ordered_items:
            self._render_color_segment(plan, duration, target, frame_count=frame_count)
            return
        wash = self._focus_wash(
            plan=plan, beat=beat, ordered_items=ordered_items, motion=motion,
            segment_start=segment_start, duration=duration,
        )
        if wash is not None:
            # The resolved focus is drawn above the receded backdrop: Motion planned it
            # only where the focus overlaps no other asset, so this z move is invisible
            # outside the wash.
            ordered_items = (
                [item for item in ordered_items if item.asset_id not in wash["focus"]]
                + [item for item in ordered_items if item.asset_id in wash["focus"]]
            )
        previous_layout = composition.get(previous_beat.id) if previous_beat else None
        transition = self.transition_policy.decide(
            previous_beat,
            previous_layout,
            layout,
            current_beat=beat,
        )
        previous_motion_by_asset = (
            {
                item.asset_id: motion[(previous_beat.id, item.asset_id)]
                for item in previous_layout.items
                if (previous_beat.id, item.asset_id) in motion
            }
            if previous_beat is not None and previous_layout is not None
            else {}
        )
        lifecycle = self.lifecycle.classify_boundary(
            previous_layout=previous_layout,
            current_layout=layout,
            previous_motion_by_asset=previous_motion_by_asset,
            previous_beat=previous_beat,
            current_beat=beat,
        )
        if lifecycle.invalid_terminal_persistence:
            raise StageFailedError(
                "render lifecycle contract violated",
                details={
                    "code": "TERMINAL_EXIT_ON_PERSISTENT_ASSET",
                    "from_beat_id": previous_beat.id if previous_beat is not None else None,
                    "to_beat_id": beat.id,
                    "asset_ids": sorted(lifecycle.invalid_terminal_persistence),
                },
            )
        persistent_ids = transition.persistent_asset_ids
        object_target_by_outgoing = dict(transition.object_handoff_pairs)
        current_items_by_id = {item.asset_id: item for item in ordered_items}
        handoffs = self._handoff_sources(
            beat=beat,
            previous_beat=previous_beat,
            previous_layout=previous_layout,
            ordered_items=ordered_items,
            motion=motion,
        )
        overlap_exits = self._planned_overlap_exits(plan, beat, previous_beat)
        overlap_items = [
            item for item in (previous_layout.items if previous_layout is not None else [])
            if item.asset_id in overlap_exits and item.asset_id not in handoffs
        ]
        outgoing_items = (
            sorted(
                (
                    item for item in previous_layout.items
                    if item.asset_id in transition.carry_outgoing_asset_ids
                    and item.asset_id not in handoffs
                    and item.asset_id not in overlap_exits  # leaves on its own planned path
                ),
                key=lambda row: row.z,
            )
            if previous_layout is not None
            else []
        )
        carried_wash = self._carried_wash(
            plan=plan, previous_beat=previous_beat, previous_layout=previous_layout, motion=motion,
        )
        if carried_wash is not None:
            outgoing_items = (
                [item for item in outgoing_items if item.asset_id not in carried_wash["focus"]]
                + [item for item in outgoing_items if item.asset_id in carried_wash["focus"]]
            )
        incoming_start, _incoming_reveal = self._incoming_handoff_window(
            beat=beat,
            ordered_items=ordered_items,
            segment_start=segment_start,
            duration=duration,
            motion=motion,
        )
        bridge_start = 0.0
        bridge_end = 0.0
        if outgoing_items and transition.mode in {
            SceneTransitionMode.OBJECT_HANDOFF,
            SceneTransitionMode.MOTION_HANDOFF,
            SceneTransitionMode.BLUR_BRIDGE,
        }:
            bridge_start, bridge_end = self._scene_bridge_window(
                incoming_start=incoming_start,
                segment_duration=duration,
                preferred_duration=float(transition.bridge_duration),
                fps=plan.fps,
                allow_focus_overlap=(
                    transition.mode
                    in {SceneTransitionMode.OBJECT_HANDOFF, SceneTransitionMode.BLUR_BRIDGE}
                ),
            )
        release = self._scene_release_window(
            plan=plan,
            beat=beat,
            previous_beat=previous_beat,
            transition_mode=transition.mode,
            has_outgoing=bool(outgoing_items),
            incoming_start=incoming_start,
            segment_start=segment_start,
            frame_count=frame_count,
        )
        if release is not None:
            bridge_start, bridge_end = release[0], release[2]
        bridge_duration = max(0.0, bridge_end - bridge_start)
        planned_exits = self._planned_exit_starts(plan, beat, previous_beat) if release is not None else {}
        exit_vectors = self._planned_exit_vectors(plan, beat, previous_beat) if release is not None else {}
        exit_blur_spec = self._planned_exit_blur(plan, beat, previous_beat)
        visual_carrier_id = (
            None
            if bridge_duration > 0 or previous_beat is None
            else self._visual_carrier_asset_id(
                beat=beat,
                ordered_items=ordered_items,
                motion=motion,
                persistent_ids=persistent_ids,
                fps=plan.fps,
            )
        )
        self._require_handoff_coverage(
            beat=beat,
            is_opening=previous_beat is None,
            ordered_items=ordered_items,
            persistent_ids=persistent_ids,
            # A planned whip/exit block is drawn still from the first frame until it leaves
            # at the opener, so it carries the frames before the first reveal.
            covered=(bridge_duration > 0 or visual_carrier_id is not None or bool(handoffs)
                     or bool(overlap_items)),
            incoming_start=incoming_start,
            fps=plan.fps,
        )

        command: list[str] = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
        for item in ordered_items:
            asset = assets.get(item.asset_id)
            if asset is None or not asset.image_path.exists():
                raise StageFailedError(
                    "render plan references missing asset",
                    details={"asset_id": item.asset_id, "beat_id": beat.id},
                )
            command.extend(["-loop", "1", "-framerate", str(plan.fps), "-i", str(asset.image_path)])
        for item in outgoing_items:
            asset = assets.get(item.asset_id)
            if asset is None or not asset.image_path.exists():
                raise StageFailedError(
                    "scene bridge references missing outgoing asset",
                    details={"asset_id": item.asset_id, "beat_id": beat.id},
                )
            command.extend(["-loop", "1", "-framerate", str(plan.fps), "-i", str(asset.image_path)])
        handoff_items = [
            next(row for row in previous_layout.items if row.asset_id == source_id)
            for source_id in sorted(handoffs)
        ] if previous_layout is not None else []
        for item in handoff_items:
            command.extend(["-loop", "1", "-framerate", str(plan.fps), "-i", str(assets[item.asset_id].image_path)])
        layout_boxes = {
            item.asset_id: (float(geometry[2]), float(geometry[3]),
                            float(geometry[2] + geometry[0]), float(geometry[3] + geometry[1]))
            for item in ordered_items
            for geometry in (self._geometry(plan, item),)
        }
        drawn = {asset_id: visible_rect(box, assets[asset_id].image_path) for asset_id, box in layout_boxes.items()}
        images = {item.asset_id: assets[item.asset_id].image_path for item in ordered_items}
        beat_cues = {item.asset_id: motion[(beat.id, item.asset_id)]
                     for item in ordered_items if (beat.id, item.asset_id) in motion}
        labels = self.text_renderer.label_anchors(plan, beat)
        scale = plan.projection.scale if plan.projection else 1.0
        # Elements interact when the narration states their relation: the cause -> effect
        # arrow on the shared interaction schedule (motion/interaction); it supersedes the
        # older box-to-box connector for the beat.
        interactions = interaction_schedule(beat, beat_cues)
        connections = relation_arrow_specs(
            interactions=[(row.source, row.target, row.arrow_start) for row in interactions],
            visible=drawn, images=images, boxes=layout_boxes, obstacles=[label.box for label in labels],
            segment_start=segment_start, duration=duration, frame=(plan.width, plan.height), spatial_scale=scale,
        ) if interactions else connection_specs(
            beat=beat, items=layout_boxes, cues=beat_cues, segment_start=segment_start, duration=duration,
            spatial_scale=scale,
        )
        # Reference grammar G17: each placed keyword points at the artwork it names.
        connections += label_arrow_specs(
            labels=labels, visible=drawn,
            settled={asset_id: settled_at(cue) for asset_id, cue in beat_cues.items()},
            images=images, boxes=layout_boxes, segment_start=segment_start, duration=duration,
            frame=(plan.width, plan.height), spatial_scale=scale,
        )
        # Reference grammar G5: authored arrow/path artwork writes on along its relation.
        path_directions = authored_path_directions(beat, {
            item.asset_id: (geometry[2] + geometry[0] / 2.0, geometry[3] + geometry[1] / 2.0)
            for item in ordered_items
            for geometry in (self._geometry(plan, item),)
        }, parent_of={item.asset_id: assets[item.asset_id].parent_asset_id for item in ordered_items},
            images={item.asset_id: assets[item.asset_id].image_path for item in ordered_items})
        connection_inputs = len(ordered_items) + len(outgoing_items) + len(handoff_items)
        for connection_index, connection in enumerate(connections):
            # Reference grammar G5: the arrow writes on (numbered frames), then holds.
            pattern, _frames = draw_connection_sequence(
                connection, (plan.width, plan.height),
                target.parent / f"{target.stem}-connection-{connection_index}",
                spatial_scale=plan.projection.scale if plan.projection else 1.0, fps=plan.fps,
            )
            command.extend(["-framerate", str(plan.fps), "-start_number", "0", "-i", pattern])

        overlap_inputs = connection_inputs + len(connections)
        for item in overlap_items:
            command.extend(["-loop", "1", "-framerate", str(plan.fps), "-i", str(assets[item.asset_id].image_path)])

        filters: list[str] = [
            f"color=c=white:s={plan.width}x{plan.height}:r={plan.fps}:d={duration:.6f},"
            "format=rgba[base0]"
        ]
        composite_label = "base0"

        if bridge_duration > 0:
            # Keep the outgoing scene crisp while waiting for a later Story-owned
            # incoming reveal. Only the short handoff interval receives exit motion
            # and optional blur; a narration gap must never become a long blurred hold.
            # A planned release fades the outgoing artwork only, never the background:
            # the group is composited on a transparent canvas.
            # A receded backdrop is held as one opaque picture (its grey wash included), so a
            # planned release fades the whole washed frame instead of only its artwork.
            old_canvas = "white@0.0" if release is not None and carried_wash is None else "white"
            filters.append(
                f"color=c={old_canvas}:s={plan.width}x{plan.height}:r={plan.fps}:"
                f"d={bridge_end:.6f},format=rgba[oldbase0]"
            )
            old_label = "oldbase0"
            input_offset = len(ordered_items)
            for bridge_index, item in enumerate(outgoing_items):
                if (carried_wash is not None and item.asset_id in carried_wash["focus"]
                        and not carried_wash.get("applied")):
                    filters.append(f"[{old_label}]{self._wash_chain(plan, carried_wash)},format=rgba[oldwashed]")
                    old_label = "oldwashed"
                    carried_wash["applied"] = True
                input_index = input_offset + bridge_index
                box_w, box_h, target_x, target_y = self._geometry(plan, item)
                source_label = f"oldasset{bridge_index}"
                filters.append(
                    f"[{input_index}:v]format=rgba,setsar=1,"
                    f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease:"
                    f"force_divisible_by=2,"
                    f"pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
                    f"loop=loop=-1:size=1:start=0,trim=duration={bridge_end:.6f},"
                    f"setpts=PTS-STARTPTS[{source_label}]"
                )
                target_item = current_items_by_id.get(
                    object_target_by_outgoing.get(item.asset_id, "")
                )
                # The planned opacity release owns the boundary: the legacy exit drift
                # is not stacked on top of it. Without a release only an authored blur
                # bridge or an authored object handoff (target-seeking) may drift: an
                # ordinary outgoing cutout never starts an exit it cannot finish before it
                # is removed, so it stays still and leaves on the incoming opener frame.
                drifts = release is None and (
                    transition.mode == SceneTransitionMode.BLUR_BRIDGE or target_item is not None)
                horizontal, vertical = self._bridge_exit_offset(
                    plan=plan,
                    item=item,
                    mode=transition.mode,
                    target_item=target_item,
                ) if drifts else (0, 0)
                progress_expr = self._bridge_progress_expression(
                    start=bridge_start,
                    duration=bridge_duration,
                )
                exit_start = planned_exits.get(item.asset_id)
                if release is not None and exit_start is not None:
                    # A planned exit: opaque, from the planned start until the cutout is
                    # completely off the canvas on the last frame before the opener, which
                    # removes the outgoing scene. Boundary only plans exits that fit.
                    exit_begin = max(0.0, float(exit_start) - segment_start)
                    exit_end = release[2] - 0.75 / plan.fps
                    if exit_end > exit_begin + 0.5 / plan.fps:
                        horizontal, vertical = self._offcanvas_exit_offset(plan=plan, item=item), 0
                        vector = exit_vectors.get(item.asset_id)
                        if vector is not None:
                            projection = plan.projection
                            reference_w = (projection.reference_width * projection.scale
                                           if projection is not None else plan.width)
                            reference_h = (projection.reference_height * projection.scale
                                           if projection is not None else plan.height)
                            horizontal = round(vector[0] * reference_w)
                            vertical = round(vector[1] * reference_h)
                        progress_expr = self._bridge_progress_expression(
                            start=exit_begin, duration=exit_end - exit_begin,
                        )
                next_old = f"oldmix{bridge_index}"
                old_x = f"{target_x}+({horizontal})*{progress_expr}"
                old_y = f"{target_y}+({vertical})*{progress_expr}"
                exit_blur = self._motion_blur_windows(
                    plan=plan, spec=exit_blur_spec if exit_start is not None and release is not None else None,
                    x_expr=old_x, y_expr=old_y, scale_expr="1", box=(box_w, box_h),
                    visible=(0.0, bridge_end), duration=duration,
                )
                if exit_blur:
                    filters.extend(self._motion_blur_filters(
                        windows=exit_blur, source_label=source_label, sharp_label=f"{source_label}sharp",
                        scale_chain="null", centred=False, under_label=old_label, out_label=next_old,
                        x_expr=old_x, y_expr=old_y, visible=(0.0, bridge_end), target=target,
                        key=f"old{bridge_index}",
                    ))
                else:
                    filters.append(
                        f"[{old_label}][{source_label}]overlay="
                        f"x='{old_x}':"
                        f"y='{old_y}':"
                        f"enable='between(t,0,{bridge_end:.6f})':"
                        f"eof_action=pass:shortest=0[{next_old}]"
                    )
                old_label = next_old

            if carried_wash is not None and not carried_wash.get("applied") and outgoing_items:
                filters.append(f"[{old_label}]{self._wash_chain(plan, carried_wash)},format=rgba[oldwashed]")
                old_label = "oldwashed"
                carried_wash["applied"] = True
            if transition.mode == SceneTransitionMode.BLUR_BRIDGE:
                filters.append(f"[{old_label}]split=2[oldcrisp][oldblurbase]")
                filters.append(
                    f"[oldblurbase]gblur=sigma="
                    f"{transition.blur_sigma * (plan.projection.scale if plan.projection else 1.0):.3f}:"
                    "steps=2[oldfx]"
                )
                filters.append(
                    f"[{composite_label}][oldcrisp]overlay=x=0:y=0:"
                    f"enable='between(t,0,{bridge_start:.6f})':"
                    f"eof_action=pass:shortest=0[oldhold]"
                )
                filters.append(
                    f"[oldhold][oldfx]overlay=x=0:y=0:"
                    f"enable='between(t,{bridge_start:.6f},{bridge_end:.6f})':"
                    f"eof_action=pass:shortest=0[bridgebase]"
                )
            else:
                if release is not None and release[1] > 0:
                    # One opacity clock for the whole outgoing scene, so every layer of
                    # every Pass2 family leaves together.
                    filters.append(
                        f"[{old_label}]settb=AVTB,fade=t=out:st={release[0]:.6f}:"
                        f"d={release[1]:.6f}:alpha=1[oldrelease]"
                    )
                    old_label = "oldrelease"
                filters.append(
                    f"[{composite_label}][{old_label}]overlay=x=0:y=0:"
                    f"enable='between(t,0,{bridge_end:.6f})':"
                    f"eof_action=pass:shortest=0[bridgebase]"
                )
            composite_label = "bridgebase"

        # VP4 planned full-frame exit (Boundary-owned): the outgoing hero stays still until
        # the planned start, then slides with smoothstep until it is outside the canvas.
        # It sits under every incoming asset; the renderer only executes the plan.
        unit_left = min((self._geometry(plan, row)[2] for row in overlap_items), default=0)
        unit_right = max((self._geometry(plan, row)[2] + self._geometry(plan, row)[0] for row in overlap_items),
                         default=0)
        unit_top = min((self._geometry(plan, row)[3] for row in overlap_items), default=0)
        unit_bottom = max((self._geometry(plan, row)[3] + self._geometry(plan, row)[1] for row in overlap_items),
                          default=0)
        for exit_index, item in enumerate(overlap_items):
            spec = overlap_exits[item.asset_id]
            box_w, box_h, target_x, target_y = self._geometry(plan, item)
            begin = max(0.0, float(spec["start"]) - segment_start)
            finish = max(begin + 1.0 / plan.fps, float(spec["end"]) - segment_start)
            margin = max(4, round(4 * (plan.projection.scale if plan.projection else 1.0)))
            # One rigid offset for the whole leaving unit (a Pass2 family moves as one).
            is_vertical = float(spec.get("axis", 0.0)) > 0.5
            travel = (
                -(unit_bottom + margin) if float(spec["direction"]) < 0
                else plan.height - unit_top + margin
            ) if is_vertical else (
                -(unit_right + margin) if float(spec["direction"]) < 0
                else plan.width - unit_left + margin
            )
            progress = f"clip((t-{begin:.6f})/{finish - begin:.6f},0,1)"
            label = f"overlapexit{exit_index}"
            # Reference G9/G16: a planned "fade" exit clears the old scene in place (to the
            # white canvas); only a "whip" travels and smears.
            fading = float(spec.get("fade", 0.0)) > 0.5
            fade_out = (f",settb=AVTB,fade=t=out:st={begin:.6f}:d={finish - begin:.6f}:alpha=1"
                        if fading else "")
            filters.append(
                f"[{overlap_inputs + exit_index}:v]format=rgba,setsar=1,"
                f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
                f"loop=loop=-1:size=1:start=0,trim=duration={duration:.6f},setpts=PTS-STARTPTS"
                f"{fade_out}[{label}]"
            )
            travelled = "0" if fading else f"({travel})*(3*pow({progress},2)-2*pow({progress},3))"
            exit_x = str(target_x) if is_vertical else f"{target_x}+{travelled}"
            exit_y = f"{target_y}+{travelled}" if is_vertical else str(target_y)
            exit_blur = self._motion_blur_windows(
                plan=plan, spec=exit_blur_spec, x_expr=exit_x, y_expr=exit_y, scale_expr="1",
                box=(box_w, box_h), visible=(0.0, finish), duration=duration,
            )
            if exit_blur:
                filters.extend(self._motion_blur_filters(
                    windows=exit_blur, source_label=label, sharp_label=f"{label}sharp", scale_chain="null",
                    centred=False, under_label=composite_label, out_label=f"{label}mix", x_expr=exit_x,
                    y_expr=exit_y, visible=(0.0, finish), target=target, key=f"ovx{exit_index}",
                ))
            else:
                filters.append(
                    f"[{composite_label}][{label}]overlay="
                    f"x='{exit_x}':y='{exit_y}':"
                    f"enable='between(t,0,{finish:.6f})':eof_action=pass:shortest=0[{label}mix]"
                )
            composite_label = f"{label}mix"

        frame_safe_reveal_starts = self._frame_safe_group_reveal_starts(
            rows=[
                (
                    item.asset_id,
                    self._cue_window(
                        beat=beat,
                        cue=motion.get((beat.id, item.asset_id)),
                        segment_start=segment_start,
                        duration=duration,
                    )[0],
                    (
                        motion[(beat.id, item.asset_id)].params.get("motion_order", {})
                        if (beat.id, item.asset_id) in motion
                        and isinstance(motion[(beat.id, item.asset_id)].params, dict)
                        else {}
                    ),
                )
                for item in ordered_items
                if item.asset_id not in persistent_ids
                and item.asset_id != visual_carrier_id
            ],
            fps=plan.fps,
            duration=duration,
        )

        # Planned handoff (Sprint 7): the outgoing representation stays on its final pose,
        # opaque and still, through the frame before its successor's first visible frame,
        # then leaves on exactly that frame: no exit drift, no fade, no overlap, no gap.
        handoff_offset = len(ordered_items) + len(outgoing_items)
        for handoff_index, item in enumerate(handoff_items):
            successor = handoffs[item.asset_id]
            successor_start = frame_safe_reveal_starts.get(
                successor,
                self._cue_window(
                    beat=beat, cue=motion.get((beat.id, successor)),
                    segment_start=segment_start, duration=duration,
                )[0],
            )
            # Successor on frame 0: the source input is still consumed, never enabled.
            last = (first_visible_frame(successor_start, plan.fps) - 0.5) / plan.fps
            box_w, box_h, target_x, target_y = self._geometry(plan, item)
            label = f"handoff{handoff_index}"
            filters.append(
                f"[{handoff_offset + handoff_index}:v]format=rgba,setsar=1,"
                f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
                f"loop=loop=-1:size=1:start=0,trim=duration={duration:.6f},setpts=PTS-STARTPTS[{label}]"
            )
            filters.append(
                f"[{composite_label}][{label}]overlay=x={target_x}:y={target_y}:"
                f"enable='between(t,0,{last:.6f})':eof_action=pass:shortest=0[{label}mix]"
            )
            composite_label = f"{label}mix"

        text_under = None
        if wash is not None:
            focus_ids = wash["focus"]
            text_under = self.text_renderer.write_beat_ass(
                plan,
                beat,
                segment_start=segment_start,
                duration=duration,
                output=target.parent / f"{target.stem}-text-under.ass",
                include=lambda cue: bool(cue.anchor_asset_id) and cue.anchor_asset_id not in focus_ids,
            )
        for layer_index, item in enumerate(ordered_items):
            cue = motion.get((beat.id, item.asset_id))
            if wash is not None and item.asset_id in wash["focus"] and not wash.get("applied"):
                # Backdrop recession (VNext2 PAYOFF): everything already composited, and
                # the labels of receding assets, blur and wash toward grey on one clock
                # while the resolved focus stays crisp above it.
                if text_under is not None:
                    filters.append(self.text_renderer.ass_filter(text_under, composite_label, "washtext"))
                    composite_label = "washtext"
                filters.extend(self._focus_wash_filters(plan, wash, composite_label, duration))
                composite_label = "washed"
                wash["applied"] = True
            box_w, box_h, target_x, target_y = self._geometry(plan, item)
            start, end, _fade_duration = self._cue_window(
                beat=beat,
                cue=cue,
                segment_start=segment_start,
                duration=duration,
            )
            effective_reveal_start = frame_safe_reveal_starts.get(
                item.asset_id, start
            )
            self._require_encoded_entry_window(
                cue=cue,
                authored_start=start,
                authored_end=end,
                effective_reveal_start=effective_reveal_start,
                fps=plan.fps,
                beat_id=beat.id,
                asset_id=item.asset_id,
            )
            persistent = item.asset_id in persistent_ids
            visual_carrier = item.asset_id == visual_carrier_id
            render_constraints = (
                cue.params.get("render_constraints", {})
                if cue is not None and isinstance(cue.params, dict)
                else {}
            )
            geometry_locked = render_constraints.get("geometry_lock") == "authored_footprint"
            source_label = f"asset{layer_index}"
            base_source_label = f"asset{layer_index}base"
            # Keep cutout alpha exactly as authored. The transparent pad gives Motion a
            # stable Composition-sized transform box, so scale pulses can happen around
            # the element centre without changing semantic placement.
            entry_fade = (
                ""
                if persistent or visual_carrier or item.asset_id in handoffs.values()
                else self._entry_opacity_filter(
                    cue,
                    segment_start=segment_start,
                    effective_reveal_start=effective_reveal_start,
                    fps=plan.fps,
                )
            )
            if (
                item.asset_id in path_directions
                and not (persistent or visual_carrier or item.asset_id in handoffs.values())
            ):
                entry_fade = self._path_write_on_filter(
                    cue, image_path=assets[item.asset_id].image_path, box=(box_w, box_h),
                    direction=path_directions[item.asset_id], segment_start=segment_start,
                    effective_reveal_start=effective_reveal_start, fps=plan.fps,
                ) or entry_fade
            # Reference G19 landing: the object sharpens while it shrinks onto its size.
            landing_cue = cue
            if cue is not None and isinstance(cue.params, dict) and cue.params.get("family_follow"):
                landing_cue = motion.get((beat.id, cue.params["family_follow"]), cue)
            defocus = (
                ""
                if persistent or visual_carrier or item.asset_id in handoffs.values()
                else self._landing_defocus_filter(
                    landing_cue, effective_reveal_start=effective_reveal_start, fps=plan.fps,
                    pixel_scale=plan.projection.scale if plan.projection else 1.0,
                    commands=target.parent / f"{target.stem}-defocus-{layer_index}.cmd",
                    name=f"df{layer_index}",
                )
            )
            filters.append(
                f"[{layer_index}:v]format=rgba,setsar=1,"
                f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
                f"loop=loop=-1:size=1:start=0,trim=duration={duration:.6f},setpts=PTS-STARTPTS"
                f"{entry_fade}{defocus}[{base_source_label}]"
            )
            # Authored alpha stays intact after the entry. The only alpha change is the
            # Motion-owned entry clock (reveal -> settle); family layers share one clock,
            # so a Pass2 family never fades as separate pieces.
            transform_source_label = base_source_label

            # A geometry-locked Pass2 layer that Motion bound to its family primary (same
            # Composition box) is drawn with the primary's transform: identical box and
            # identical expressions keep the family pixel-aligned while it moves as one.
            leader_id = (cue.params.get("family_follow")
                         if cue is not None and isinstance(cue.params, dict) else None)
            leader_cue = motion.get((beat.id, leader_id)) if leader_id else None
            leader_item = current_items_by_id.get(leader_id) if leader_id else None
            follows = bool(
                geometry_locked and leader_cue is not None and leader_item is not None
                and self.motion_adapter.supports(leader_cue)
                and self._geometry(plan, leader_item) == (box_w, box_h, target_x, target_y)
                and not (leader_cue.params.get("render_constraints") or {}).get("geometry_lock")
            )
            transform_cue = leader_cue if follows else cue

            scale_expr = "1"
            if (
                (not geometry_locked or follows)
                and transform_cue is not None
                and self.motion_adapter.supports(transform_cue)
            ):
                scale_expr = self.motion_adapter.scale_expression(
                    cue=transform_cue,
                    segment_start=segment_start,
                    segment_duration=duration,
                )
            scale_chain = (
                f"scale=w='max(2,iw*({scale_expr}))':h='max(2,ih*({scale_expr}))':eval=frame"
                if scale_expr != "1" else "null"
            )

            kind = cue.kind if cue else "reveal_in"
            if geometry_locked and not follows:
                x_expr = str(target_x)
                y_expr = str(target_y)
            elif transform_cue is not None and self.motion_adapter.supports(transform_cue):
                x_expr, y_expr = self.motion_adapter.position_expressions(
                    cue=transform_cue,
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
                x_expr = self._entry_expression(
                    target_x, start, end,
                    offset=round(58 * (plan.projection.scale if plan.projection else 1.0)),
                )
                y_expr = str(target_y)
            elif kind == "emphasis_in":
                x_expr = str(target_x)
                y_expr = self._entry_expression(
                    target_y, start, end,
                    offset=round(20 * (plan.projection.scale if plan.projection else 1.0)),
                )
            elif kind == "soft_in":
                x_expr = str(target_x)
                y_expr = self._entry_expression(
                    target_y, start, end,
                    offset=round(12 * (plan.projection.scale if plan.projection else 1.0)),
                )
            else:
                x_expr = str(target_x)
                y_expr = self._entry_expression(
                    target_y, start, end,
                    offset=round(30 * (plan.projection.scale if plan.projection else 1.0)),
                )

            next_label = f"mix{layer_index}"
            # Semantic visibility is authoritative: every non-persistent asset stays
            # hidden until its Motion/Story reveal window. The only exception is one
            # deliberately selected boundary carrier, used solely to avoid a blank
            # frame between beats. Story's legacy area-ranked primary must never make
            # a future semantic result visible early.
            enable_start, enable_end = self.asset_visibility_window(
                cue=cue,
                segment_start=segment_start,
                duration=duration,
                reveal_start=effective_reveal_start,
                persistent=(persistent or visual_carrier),
            )
            blur = self._motion_blur_windows(
                plan=plan,
                spec=(transform_cue.params.get("motion_blur")
                      if transform_cue is not None and isinstance(transform_cue.params, dict)
                      and (not geometry_locked or follows) else None),
                x_expr=x_expr, y_expr=y_expr, scale_expr=scale_expr, box=(box_w, box_h),
                visible=(enable_start, enable_end), duration=duration,
            )
            if not blur:
                filters.append(f"[{transform_source_label}]{scale_chain}[{source_label}]")
                filters.append(
                    f"[{composite_label}][{source_label}]overlay=x='{x_expr}':y='{y_expr}':"
                    f"enable='between(t,{enable_start:.6f},{enable_end:.6f})':eof_action=pass:shortest=0"
                    f"[{next_label}]"
                )
            else:
                filters.extend(self._motion_blur_filters(
                    windows=blur, source_label=transform_source_label, sharp_label=source_label,
                    scale_chain=scale_chain, centred=scale_expr != "1", under_label=composite_label,
                    out_label=next_label, x_expr=x_expr, y_expr=y_expr,
                    visible=(enable_start, enable_end), target=target, key=str(layer_index),
                ))
            composite_label = next_label

        for connection_index, connection in enumerate(connections):
            label = f"connection{connection_index}"
            filters.append(
                f"[{connection_inputs + connection_index}:v]format=rgba,"
                f"tpad=start_duration={connection.start:.6f}:start_mode=add:color=black@0.0:"
                f"stop_mode=clone:stop_duration={duration:.6f},"
                f"trim=duration={duration:.6f},setpts=PTS-STARTPTS[{label}]"
            )
            next_label = f"connmix{connection_index}"
            filters.append(
                f"[{composite_label}][{label}]overlay=x=0:y=0:"
                f"enable='between(t,{connection.start:.6f},{min(duration, connection.end):.6f})':"
                f"eof_action=pass:shortest=0[{next_label}]"
            )
            composite_label = next_label

        ass_path = self.text_renderer.write_beat_ass(
            plan,
            beat,
            segment_start=segment_start,
            duration=duration,
            output=target.parent / f"{target.stem}-text.ass",
            include=(
                None if wash is None
                else lambda cue: not cue.anchor_asset_id or cue.anchor_asset_id in wash["focus"]
            ),
        )
        if ass_path is not None:
            text_label = "textmix"
            filters.append(self.text_renderer.ass_filter(ass_path, composite_label, text_label))
            composite_label = text_label

        filters.append(f"[{composite_label}]format=yuv420p[vout]")
        command.extend(self._encode_args(filters, target, plan.fps, frame_count))
        self._run(command, "render segment failed")



    @staticmethod
    def _motion_blur_windows(
        *,
        plan: RenderPlan,
        spec: dict | None,
        x_expr: str,
        y_expr: str,
        scale_expr: str,
        box: tuple[int, int],
        visible: tuple[float, float],
        duration: float,
    ) -> list[dict]:
        """Per-frame directional blur for one drawn element, from the exact drawn position.

        Motion decides *whether* an element is blurred (``params["motion_blur"]``); here
        each encoded frame gets the smear of the displacement the element's centre travels
        during that frame's exposure (centred on the frame): direction = displacement
        direction, length = displacement, sharp wherever it rests. Contiguous blurred frames
        form windows; frames outside them are drawn exactly as without blur.
        """
        if not isinstance(spec, dict) or spec.get("owner") not in {"MOTION", "BOUNDARY"}:
            return []
        fps = plan.fps
        shutter = max(0.0, min(1.0, float(spec.get("shutter", 0.5))))
        if shutter <= 0.0:
            return []
        # Lengths are fractions of the content height: the projected reference frame on
        # a projected target, the canvas itself otherwise.
        content_height = (plan.projection.reference_height * plan.projection.scale
                          if plan.projection else plan.height)
        min_px = float(spec.get("min_length", 0.0)) * content_height
        max_px = float(spec.get("max_length", 1.0)) * content_height
        x_of, y_of = compile_expression(x_expr), compile_expression(y_expr)
        s_of = compile_expression(scale_expr) if scale_expr != "1" else (lambda t: 1.0)
        box_w, box_h = box
        centred = scale_expr != "1"

        def centre(t: float) -> tuple[float, float]:
            s = s_of(t)
            width, height = (max(2.0, box_w * s), max(2.0, box_h * s)) if centred else (box_w, box_h)
            return x_of(t, width, height) + width / 2.0, y_of(t, width, height) + height / 2.0

        half = shutter / (2.0 * fps)
        first = max(0, math.ceil(visible[0] * fps - 1e-9))
        last = min(round(duration * fps) - 1, math.floor(visible[1] * fps + 1e-9))
        frames: list[tuple[int, float, float]] = []  # (frame, radius before transform scale, angle)
        for n in range(first, last + 1):
            t = n / fps
            (x0, y0), (x1, y1) = centre(t - half), centre(t + half)
            length = math.hypot(x1 - x0, y1 - y0)
            # an exposure that jumps further than four maximum smears is a cut, not motion
            if not math.isfinite(length) or length < min_px or length > 4.0 * max_px:
                continue
            # dblur is symmetric; its 10-90 % edge spread is ~3.3 x radius, a box exposure
            # of length L spreads 0.8 L: radius = 0.24 L. Applied before the transform scale.
            radius = 0.24 * min(length, max_px) / max(0.05, s_of(t))
            if radius < 0.25:
                continue
            frames.append((n, radius, math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0))
        windows: list[dict] = []
        for n, radius, angle in frames:
            if windows and n == windows[-1]["frames"][-1][0] + 1:
                windows[-1]["frames"].append((n, radius, angle))
            else:
                windows.append({"frames": [(n, radius, angle)]})
        for window in windows:
            rows = window["frames"]
            window["start"] = (rows[0][0] - 0.5) / fps
            window["end"] = (rows[-1][0] + 0.5) / fps
            window["margin"] = math.ceil(4.0 * max(row[1] for row in rows)) + 2
            window["fps"] = fps
        return windows

    @staticmethod
    def _motion_blur_filters(
        *,
        windows: list[dict],
        source_label: str,
        sharp_label: str,
        scale_chain: str,
        centred: bool,
        under_label: str,
        out_label: str,
        x_expr: str,
        y_expr: str,
        visible: tuple[float, float],
        target: Path,
        key: str,
    ) -> list[str]:
        """Draw an element sharp outside its blur windows and blurred inside them.

        Each window is its own short branch (trimmed to the window, so no other frame is
        touched): padded so the smear is never clipped by the box, premultiplied so
        transparent pixels never bleed colour into the smear (no halo), directionally
        blurred frame by frame (``sendcmd``), then given the same transform as the sharp
        element. A centred transform already absorbs the padding; otherwise the overlay
        is shifted by it. A branch keeps one spare frame past its window: with
        ``eof_action=pass`` the overlay drops the frame that arrives together with the
        branch's end of stream, which removed the element on a window's last frame (and
        on every one-frame window). The spare frame is outside the overlay's enable.
        """
        def escape(value: Path) -> str:
            return str(value.resolve()).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")

        # Pin the split input: premultiply/dblur work in planar formats, and a shared split
        # would otherwise move the sharp branch to them too (rounding its edges by 1-2 levels).
        filters = [f"[{source_label}]format=rgba,split={len(windows) + 1}[{sharp_label}pre]"
                   + "".join(f"[mb{key}src{index}]" for index in range(len(windows))),
                   f"[{sharp_label}pre]{scale_chain}[{sharp_label}]"]
        inside = "+".join(f"between(t,{w['start']:.6f},{w['end']:.6f})" for w in windows)
        shown = f"between(t,{visible[0]:.6f},{visible[1]:.6f})"
        middle = f"mb{key}sharp"
        filters.append(
            f"[{under_label}][{sharp_label}]overlay=x='{x_expr}':y='{y_expr}':"
            f"enable='{shown}*not({inside})':eof_action=pass:shortest=0[{middle}]"
        )
        for index, window in enumerate(windows):
            margin, fps = window["margin"], window["fps"]
            instance = f"dblur@mb{key}x{index}"
            commands = target.parent / f"{target.stem}-blur-{key}-{index}.cmd"
            commands.write_text("".join(
                f"{max(0.0, n / fps - 0.0005):.6f} {instance} radius {radius:.3f}, {instance} angle {angle:.3f};\n"
                for n, radius, angle in window["frames"]
            ), encoding="utf-8")
            n0, r0, a0 = window["frames"][0]
            filters.append(
                f"[mb{key}src{index}]trim=start={window['start']:.6f}:end={window['end'] + 1.0 / fps:.6f},"
                f"pad=iw+{2 * margin}:ih+{2 * margin}:{margin}:{margin}:color=0x00000000,"
                f"premultiply=inplace=1,sendcmd=f='{escape(commands)}',"
                f"{instance}=angle={a0:.3f}:radius={r0:.3f},unpremultiply=inplace=1,"
                f"{scale_chain}[mb{key}blur{index}]"
            )
            x_blur = x_expr if centred else f"({x_expr})-{margin}"
            y_blur = y_expr if centred else f"({y_expr})-{margin}"
            label = out_label if index == len(windows) - 1 else f"mb{key}mix{index}"
            filters.append(
                f"[{middle}][mb{key}blur{index}]overlay=x='{x_blur}':y='{y_blur}':"
                f"enable='{shown}*between(t,{window['start']:.6f},{window['end']:.6f})':"
                f"eof_action=pass:shortest=0[{label}]"
            )
            middle = label
        return filters

    @staticmethod
    def _focus_wash(
        *,
        plan: RenderPlan,
        beat: StoryBeat,
        ordered_items: list,
        motion: dict[tuple[str, str], MotionCue],
        segment_start: float,
        duration: float,
    ) -> dict | None:
        """The beat's planned backdrop recession in segment-local seconds, or None.

        Motion owns every decision (``params["focus_wash"]`` on the resolved focus); the
        renderer only fails closed when the plan no longer matches what is on screen.
        """
        present = {item.asset_id for item in ordered_items}
        for item in ordered_items:
            cue = motion.get((beat.id, item.asset_id))
            spec = cue.params.get("focus_wash") if cue is not None and isinstance(cue.params, dict) else None
            if not isinstance(spec, dict):
                continue
            focus = {str(asset_id) for asset_id in spec.get("focus_asset_ids") or []} & present
            if not focus or focus == present:
                return None
            start = float(spec["start"]) - segment_start
            end = min(duration, float(spec.get("end", segment_start + duration)) - segment_start)
            ramp = float(spec.get("ramp", 5 / plan.fps))
            if start < 0.0 or end - start + 1e-6 < ramp:
                return None
            return {
                "focus": focus, "start": start, "end": end, "ramp": ramp,
                "blur": float(spec.get("blur_px", 0.0)),
                "tint": str(spec.get("tint", "#FFFFFF")).lstrip("#"),
                "tint_alpha": max(0.0, min(1.0, float(spec.get("tint_alpha", 0.5)))),
            }
        return None

    @staticmethod
    def _wash_chain(plan: RenderPlan, wash: dict) -> str:
        """Blur and grey-tint filters for a receded backdrop (alpha is kept as composited)."""
        sigma = wash["blur"] * (plan.projection.scale if plan.projection else 1.0)
        tint, alpha = wash["tint"], wash["tint_alpha"]
        red, green, blue = (int(tint[i:i + 2], 16) for i in (0, 2, 4))
        keep = 1.0 - alpha
        lut = (f"lutrgb=r='val*{keep:.4f}+{red * alpha:.3f}':g='val*{keep:.4f}+{green * alpha:.3f}':"
               f"b='val*{keep:.4f}+{blue * alpha:.3f}'")
        return (f"gblur=sigma={sigma:.3f}:steps=2," if sigma > 0.05 else "") + lut

    @classmethod
    def _focus_wash_filters(cls, plan: RenderPlan, wash: dict, source_label: str, duration: float) -> list[str]:
        """Crossfade the composited backdrop into its receded copy on one clock."""
        start, ramp, end = wash["start"], wash["ramp"], wash["end"]
        release = (
            f",fade=t=out:st={end - ramp:.6f}:d={ramp:.6f}:alpha=1"
            if end < duration - 0.5 / plan.fps else ""
        )
        chain = cls._wash_chain(plan, wash).replace(
            "steps=2,", f"steps=2:enable='gte(t,{max(0.0, start - 1.0 / plan.fps):.6f})',", 1)
        return [
            f"[{source_label}]split=2[washsharp][washsrc]",
            f"[washsrc]{chain},format=rgba,settb=AVTB,"
            f"fade=t=in:st={start:.6f}:d={ramp:.6f}:alpha=1{release}[washfx]",
            "[washsharp][washfx]overlay=x=0:y=0:eof_action=pass:shortest=0[washed]",
        ]

    @classmethod
    def _carried_wash(
        cls,
        *,
        plan: RenderPlan,
        previous_beat: StoryBeat | None,
        previous_layout,
        motion: dict[tuple[str, str], MotionCue],
    ) -> dict | None:
        """A backdrop wash still on at the previous beat's last frame: the held picture of
        that scene keeps it until the incoming opener removes it."""
        if previous_beat is None or previous_layout is None:
            return None
        wash = cls._focus_wash(
            plan=plan, beat=previous_beat, ordered_items=list(previous_layout.items), motion=motion,
            segment_start=float(previous_beat.start), duration=float(previous_beat.end) - float(previous_beat.start),
        )
        if wash is None or wash["end"] < float(previous_beat.end) - float(previous_beat.start) - 1.0 / plan.fps:
            return None
        return wash

    @classmethod
    def _scene_release_window(
        cls,
        *,
        plan: RenderPlan,
        beat: StoryBeat,
        previous_beat: StoryBeat | None,
        transition_mode: SceneTransitionMode,
        has_outgoing: bool,
        incoming_start: float,
        segment_start: float,
        frame_count: int,
    ) -> tuple[float, float, float] | None:
        """Execute a planned scene release: (fade start, fade duration, cover end).

        The plan decides; this only maps it onto the segment's frame grid. Anything the
        renderer cannot execute exactly as planned returns None, which keeps the certified
        boundary behaviour (fail closed).
        """
        if previous_beat is None or not has_outgoing:
            return None
        if transition_mode != SceneTransitionMode.MOTION_HANDOFF:
            return None
        row = next((item for item in plan.scene_boundaries if item.beat_id == beat.id), None)
        if row is None or row.mode == "HARD_CUT" or row.from_beat_id != previous_beat.id:
            return None
        if row.opener_at is None or row.release_start is None or row.release_end is None:
            return None
        fps = plan.fps
        frames = []
        for value in (row.opener_at, row.release_start, row.release_end):
            exact = (float(value) - segment_start) * fps
            if abs(exact - round(exact)) > 1e-3:
                return None
            frames.append(round(exact))
        opener, start, zero = frames
        if opener != cls._first_visible_frame(incoming_start, fps):
            return None
        if row.mode in {"HOLD_TO_OPENER", "CRISP_HANDOFF"}:
            if start != opener or zero != opener or opener <= 0 or opener >= frame_count:
                return None
            # Cover the last frame before the opener; the outgoing scene has no fade
            # or exit drift, and the next opener keeps its original frame.
            return 0.0, 0.0, (opener - 0.25) / fps
        if start < 0 or zero - start < 2 or zero > frame_count:
            return None
        if (row.mode == "EXACT_END" and zero != opener) or (row.mode == "OVERLAP" and zero <= opener):
            return None
        duration = frame_count / fps
        cover_end = max(
            cls._frame_safe_bridge_end(
                incoming_start=incoming_start, segment_duration=duration, fps=fps),
            # Cover through the zero-opacity frame so frame zero - 1 keeps its last fade step
            # (a quarter frame keeps the bound rounding-safe).
            min(duration, (zero + 0.25) / fps),
        )
        return start / fps, (zero - start) / fps, cover_end

    @staticmethod
    def _bridge_exit_offset(
        *,
        plan: RenderPlan,
        item,
        mode: SceneTransitionMode,
        target_item=None,
    ) -> tuple[int, int]:
        """Give outgoing artwork a readable directional exit before scene replacement."""
        if plan.projection is not None:
            projection = plan.projection
            def inverse(row):
                if row is None:
                    return None
                return row.model_copy(update={
                    "x": (row.x * plan.width - projection.offset_x)
                         / (projection.reference_width * projection.scale),
                    "y": (row.y * plan.height - projection.offset_y)
                         / (projection.reference_height * projection.scale),
                })
            reference = plan.model_copy(update={
                "width": projection.reference_width,
                "height": projection.reference_height,
                "projection": None,
            })
            dx, dy = FFmpegRenderer._bridge_exit_offset(
                plan=reference, item=inverse(item), mode=mode, target_item=inverse(target_item),
            )
            return round(dx * projection.scale), round(dy * projection.scale)
        if mode == SceneTransitionMode.OBJECT_HANDOFF and target_item is not None:
            raw_dx = round((float(target_item.x) - float(item.x)) * plan.width * 0.55)
            raw_dy = round((float(target_item.y) - float(item.y)) * plan.height * 0.55)
            dx = max(-140, min(140, raw_dx))
            dy = max(-80, min(80, raw_dy))
            if abs(dx) >= 48 or abs(dy) >= 18:
                return dx, dy

        if mode == SceneTransitionMode.BLUR_BRIDGE:
            horizontal_ratio, vertical_ratio = 0.030, 0.020
        elif mode == SceneTransitionMode.OBJECT_HANDOFF:
            horizontal_ratio, vertical_ratio = 0.040, 0.026
        else:
            horizontal_ratio, vertical_ratio = 0.050, 0.032

        horizontal = max(48, min(120, round(plan.width * horizontal_ratio)))
        vertical = max(18, min(64, round(plan.height * vertical_ratio)))
        if item.x < 0.44:
            dx = -horizontal
        elif item.x > 0.56:
            dx = horizontal
        else:
            # Central visuals clear vertically so the incoming focal element can own
            # the centre rather than inheriting a tiny near-zero horizontal nudge.
            dx = 0
        dy = -vertical if item.y <= 0.5 else vertical
        return dx, dy


    @staticmethod
    def _planned_overlap_exits(
        plan: RenderPlan, beat: StoryBeat, previous_beat: StoryBeat | None,
    ) -> dict[str, dict[str, float]]:
        """Boundary's planned full-frame exits into this segment (empty otherwise)."""
        if previous_beat is None:
            return {}
        row = next((r for r in plan.scene_boundaries
                    if r.beat_id == beat.id and r.from_beat_id == previous_beat.id), None)
        return dict(row.overlap_exits) if row is not None else {}

    @staticmethod
    def _planned_exit_blur(plan: RenderPlan, beat: StoryBeat, previous_beat: StoryBeat | None) -> dict:
        """Boundary's blur of the exits it planned for this boundary (empty: drawn sharp)."""
        if previous_beat is None:
            return {}
        row = next((r for r in plan.scene_boundaries
                    if r.beat_id == beat.id and r.from_beat_id == previous_beat.id), None)
        return dict(row.exit_motion_blur) if row is not None else {}

    @staticmethod
    def _planned_exit_vectors(
        plan: RenderPlan, beat: StoryBeat, previous_beat: StoryBeat | None,
    ) -> dict[str, tuple[float, float]]:
        """Flow vectors are frame-independent and shared by rigid cutout families.

        Old SceneBoundaryRelease records without flow vectors use the certified
        nearest-horizontal exit, preserving legacy renders byte-for-byte.
        """
        if previous_beat is None:
            return {}
        row = next((row for row in plan.scene_boundaries
                    if row.beat_id == beat.id and row.from_beat_id == previous_beat.id), None)
        if row is None or row.mode != "CRISP_HANDOFF":
            return {}
        audit = row.audit.get("exit") or {}
        entries = audit.get("vectors") or {}
        output = {}
        for asset_id, vector in entries.items():
            if isinstance(vector, (list, tuple)) and len(vector) == 2:
                dx, dy = float(vector[0]), float(vector[1])
                if math.isfinite(dx) and math.isfinite(dy):
                    output[str(asset_id)] = (dx, dy)
        return output

    @staticmethod
    def _planned_exit_starts(
        plan: RenderPlan, beat: StoryBeat, previous_beat: StoryBeat | None,
    ) -> dict[str, float]:
        """Exit starts of the planned CRISP_HANDOFF for this boundary (empty otherwise)."""
        if previous_beat is None:
            return {}
        row = next((r for r in plan.scene_boundaries
                    if r.beat_id == beat.id and r.from_beat_id == previous_beat.id), None)
        if row is None or row.mode != "CRISP_HANDOFF":
            return {}
        return dict(row.exit_starts)

    @classmethod
    def _offcanvas_exit_offset(cls, *, plan: RenderPlan, item) -> int:
        """Horizontal offset that takes the cutout box completely off the canvas through
        its nearest side edge (the direction Boundary timed the exit for)."""
        box_w, _box_h, target_x, _target_y = cls._geometry(plan, item)
        margin = max(4, round(4 * (plan.projection.scale if plan.projection else 1.0)))
        left, right = target_x + box_w + margin, plan.width - target_x + margin
        return -left if left <= right else right

    @staticmethod
    def _bridge_progress_expression(*, start: float, duration: float) -> str:
        """Smooth scene-handoff travel instead of a mechanical linear slide."""
        duration = max(0.05, float(duration))
        end = float(start) + duration
        p = f"((t-{float(start):.6f})/{duration:.6f})"
        smooth = f"(3*({p})*({p})-2*({p})*({p})*({p}))"
        return (
            f"if(lt(t,{float(start):.6f}),0,"
            f"if(gte(t,{end:.6f}),1,{smooth}))"
        )

    @classmethod
    def _scene_bridge_window(
        cls,
        *,
        incoming_start: float,
        segment_duration: float,
        preferred_duration: float,
        fps: int | None = None,
        allow_focus_overlap: bool = True,
    ) -> tuple[float, float]:
        """Place a bounded bridge around the first Story-owned incoming reveal.

        A delayed semantic reveal keeps the old scene crisp until shortly before the
        new visual enters. The bridge itself remains short, so blur never turns a
        narration gap into a long soft background hold.
        """
        duration = max(0.0, float(segment_duration))
        if duration <= 0.0 or preferred_duration <= 0.0:
            return 0.0, 0.0
        bridge = min(duration, max(0.20, float(preferred_duration)))
        incoming = max(0.0, min(duration, float(incoming_start)))
        lead = min(0.16, max(0.10, bridge * GOLDEN_MINOR))
        start = max(0.0, incoming - lead)
        end = min(duration, start + bridge)
        if not allow_focus_overlap:
            # An unrelated outgoing scene may cover a narration gap, but it must be
            # gone once the first encoded incoming frame owns focus. Continuous time
            # may land between frame timestamps, so cover through that frame boundary;
            # incoming artwork is composited above this one-frame safety overlap.
            safe_end = cls._frame_safe_bridge_end(
                incoming_start=incoming,
                segment_duration=duration,
                fps=fps,
            )
            start = max(0.0, safe_end - bridge)
            end = safe_end
        if incoming < duration and end <= incoming:
            if allow_focus_overlap:
                end = min(duration, incoming + min(0.12, duration - incoming))
        if fps is not None and fps > 0 and incoming < duration:
            # Whatever the mode, the outgoing cover must reach the first encoded frame on
            # which the incoming artwork is visible (never an empty handoff frame).
            end = max(end, cls._frame_safe_bridge_end(
                incoming_start=incoming, segment_duration=duration, fps=fps,
            ))
        return start, max(start, end)

    @staticmethod
    def _first_visible_frame(start: float, fps: int) -> int:
        """Encoded frame n (timestamp n/fps) that first satisfies ``t >= start``.

        The encoded frame grid is the render authority. ``1e-9`` only absorbs the float
        error of a start that was computed to sit exactly on a frame (for example
        ``k/fps`` reached through subtraction); it is far below one frame.
        """
        return first_visible_frame(start, fps)

    @staticmethod
    def _frame_threshold(frame: int, fps: int) -> float:
        """Overlay ``enable`` threshold whose first visible frame is exactly ``frame``.

        FFmpeg evaluates ``enable`` on frame timestamps and the filtergraph text carries
        only six decimals. A threshold written at (or derived from) the frame timestamp
        ``k/fps`` can round a hair *after* frame k and postpone visibility by one frame;
        the same start can land either side of the grid depending on the decimal. A
        threshold a quarter frame inside the gap after frame k-1 keeps every earlier frame
        hidden and frame k visible whichever way the text rounds, and any continuous
        start between frame k-1 and frame k maps to the same first visible frame.
        """
        return max(0.0, (int(frame) - 0.25) / float(fps))

    @classmethod
    def _frame_safe_reveal_threshold(cls, start: float, fps: int) -> float:
        return cls._frame_threshold(cls._first_visible_frame(start, fps), fps)

    @classmethod
    def _frame_safe_bridge_end(
        cls, *, incoming_start: float, segment_duration: float, fps: int | None
    ) -> float:
        """End of the outgoing cover: through the first encoded frame that shows the incoming.

        The outgoing layer must still own that frame, because the incoming artwork becomes
        visible on it only at the quarter-frame threshold and trim/overlay bounds are
        also rounded to six decimals. Ending a quarter frame after the frame timestamp
        keeps the frame inside the window whichever way the bound rounds.
        """
        incoming = max(0.0, min(float(segment_duration), float(incoming_start)))
        if fps is None or fps <= 0:
            return incoming
        first_incoming_frame = cls._first_visible_frame(incoming, fps)
        return min(float(segment_duration), (first_incoming_frame + 0.25) / fps)

    @classmethod
    def _visual_carrier_asset_id(
        cls,
        *,
        beat: StoryBeat,
        ordered_items: list,
        motion: dict[tuple[str, str], MotionCue],
        persistent_ids: frozenset[str],
        fps: int = 30,
    ) -> str | None:
        """Choose one low-risk boundary carrier without leaking future semantics.

        Only assets whose cue begins at (or very near) the earliest semantic reveal are
        eligible. Within that cohort, authored CONTEXT/OBJECT/CHARACTER support is safer
        than PRIMARY/ACTION and RESULT is deliberately last. This preserves the no-white
        handoff guarantee while preventing a later result from being exposed just because
        it is large or Story's legacy primary.
        """
        if persistent_ids or not ordered_items:
            return None

        rows: list[dict[str, object]] = []
        for original_index, item in enumerate(ordered_items):
            cue = motion.get((beat.id, item.asset_id))
            start = float(cue.start if cue is not None else beat.start)
            params = (
                cue.params
                if cue is not None and isinstance(cue.params, dict)
                else {}
            )
            order = params.get("motion_order", {})
            if not isinstance(order, dict):
                order = {}
            focus = params.get("semantic_focus", {})
            if not isinstance(focus, dict):
                focus = {}
            try:
                sequence_order = int(order.get("sequence_order", 10_000) or 10_000)
            except (TypeError, ValueError):
                sequence_order = 10_000
            try:
                internal_index = int(order.get("internal_index", 0) or 0)
            except (TypeError, ValueError):
                internal_index = 0
            rows.append({
                "start": start,
                "sequence_order": sequence_order,
                "internal_index": internal_index,
                "original_index": original_index,
                "asset_id": item.asset_id,
                "coverage": max(0.0, float(item.width) * float(item.height)),
                "semantic_role": str(
                    focus.get("semantic_role") or "UNKNOWN"
                ).upper(),
                "focus_role": str(focus.get("role") or "SUPPORT").upper(),
                "visual_focus": str(focus.get("visual_focus") or "").upper(),
            })
        if not rows:
            return None

        earliest = min(float(row["start"]) for row in rows)
        # A boundary carrier is an execution convenience, never semantic authority.
        # If Story's earliest incoming reveal is later than the beat boundary, exposing
        # any current-scene asset from t=0 would be an illegal early reveal. Let the
        # authored outgoing bridge/background cover that gap instead.
        if earliest > float(beat.start) + 1e-9:
            return None
        tolerance = max(0.08, 2.0 / max(1, fps))
        cohort = [
            row for row in rows
            if float(row["start"]) <= earliest + tolerance
        ]

        def safety_rank(
            row: dict[str, object],
        ) -> tuple[int, int, int, int]:
            semantic_role = str(row["semantic_role"])
            focus_role = str(row["focus_role"])
            visual_focus = str(row["visual_focus"])
            if visual_focus == "CONTEXT" or focus_role == "CONTEXT":
                role_rank = 0
            elif semantic_role == "OBJECT" and visual_focus != "RESULT":
                role_rank = 1
            elif (
                semantic_role in {"CHARACTER", "ACTOR"}
                or focus_role in {"CHARACTER", "ACTOR"}
            ):
                role_rank = 2
            elif semantic_role == "SUPPORT" or focus_role == "SUPPORT":
                role_rank = 3
            elif semantic_role == "ACTION" or focus_role == "ACTION":
                role_rank = 4
            elif visual_focus == "PRIMARY" or focus_role == "PRIMARY":
                role_rank = 5
            elif (
                semantic_role == "RESULT"
                or visual_focus == "RESULT"
                or focus_role == "RESULT"
            ):
                role_rank = 9
            else:
                role_rank = 6
            return (
                role_rank,
                int(row["internal_index"]),
                int(row["sequence_order"]),
                int(row["original_index"]),
            )

        return str(min(cohort, key=safety_rank)["asset_id"])

    @staticmethod
    def _handoff_sources(
        *,
        beat: StoryBeat,
        previous_beat: StoryBeat | None,
        previous_layout,
        ordered_items: list,
        motion: dict[tuple[str, str], MotionCue],
    ) -> dict[str, str]:
        """Outgoing runtime asset -> incoming runtime asset for planned handoffs.

        Executes the plan's explicit ``handoff_from`` instruction only; the renderer never
        decides which assets continue. An instruction that does not resolve to exactly one
        visible asset of the immediately previous beat fails closed.
        """
        output: dict[str, str] = {}
        for item in ordered_items:
            cue = motion.get((beat.id, item.asset_id))
            spec = cue.params.get("handoff_from") if cue is not None and isinstance(cue.params, dict) else None
            if spec is None:
                continue
            source = spec.get("asset_id") if isinstance(spec, dict) else None
            visible = (
                previous_layout is not None
                and any(row.asset_id == source for row in previous_layout.items)
                and (
                    previous_beat.active_visual_semantic_state is None
                    or source in previous_beat.active_visual_semantic_state
                )
            ) if previous_beat is not None else False
            if (
                not isinstance(spec, dict)
                or previous_beat is None
                or spec.get("beat_id") != previous_beat.id
                or not visible
                or source in output
            ):
                raise StageFailedError(
                    "planned handoff does not resolve to one visible previous asset",
                    details={"code": "HANDOFF_SOURCE_INVALID", "beat_id": beat.id,
                             "asset_id": item.asset_id, "handoff_from": spec},
                )
            output[str(source)] = item.asset_id
        return output

    @classmethod
    def _require_handoff_coverage(
        cls,
        *,
        beat: StoryBeat,
        is_opening: bool,
        ordered_items: list,
        persistent_ids: frozenset[str],
        covered: bool,
        incoming_start: float,
        fps: int,
    ) -> None:
        """Fail before FFmpeg when an internal boundary would show blank frames.

        Structural and O(items): a beat whose first semantic reveal is later than its
        first encoded frame needs a legal owner for those frames (a persistent asset, an
        outgoing bridge or a boundary carrier); an internal boundary tolerates no blank
        frame. The video opening has no outgoing scene and Story may not reveal content
        before its authored reveal, so it is judged only by the encoded verifier, whose
        pre-narration pre-roll rule (``opening_blank_seconds``) applies there.
        """
        if is_opening or covered or persistent_ids or not ordered_items or fps <= 0:
            return
        blank_frames = cls._first_visible_frame(incoming_start, fps)
        if blank_frames <= 0:
            return
        raise StageFailedError(
            "no legal visual carrier covers the frames before the first semantic reveal",
            details={
                "code": "VISUAL_HANDOFF_COVERAGE_INFEASIBLE",
                "beat_id": beat.id,
                "scene_id": beat.scene_id,
                "opening": is_opening,
                "blank_frames": blank_frames,
                "allowed_blank_frames": 0,
                "first_reveal_seconds": round(float(incoming_start), 6),
                "fps": fps,
            },
        )

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

    @classmethod
    def _landing_defocus_filter(
        cls,
        cue: MotionCue | None,
        *,
        effective_reveal_start: float,
        fps: int,
        pixel_scale: float,
        commands: Path,
        name: str,
    ) -> str:
        """Defocus of a reference landing (G19): ``defocus_px`` on the first visible frame,
        sharp when the landing settles (ease-out), "" for every other asset."""
        spec = cue.params.get("reference_landing") if cue is not None and isinstance(cue.params, dict) else None
        if not isinstance(spec, dict):
            return ""
        sigma0 = float(spec.get("defocus_px", 0.0)) * pixel_scale
        frames = max(1, round(float(spec.get("seconds", 0.0)) * fps))
        if sigma0 < 0.5:
            return ""
        first = cls._first_visible_frame(effective_reveal_start, fps)
        lines = []
        for step in range(frames + 1):
            sigma = sigma0 * (1.0 - step / frames) ** 2
            lines.append(f"{max(0.0, (first + step) / fps - 0.0005):.6f} gblur@{name} sigma {sigma:.3f};")
        commands.parent.mkdir(parents=True, exist_ok=True)
        commands.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path = str(commands.resolve()).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")
        return (f",premultiply=inplace=1,sendcmd=f='{path}',gblur@{name}=sigma=0:steps=2,"
                f"unpremultiply=inplace=1")

    @classmethod
    def _path_write_on_filter(
        cls,
        cue: MotionCue | None,
        *,
        image_path: Path,
        box: tuple[int, int],
        direction: tuple[float, float],
        segment_start: float,
        effective_reveal_start: float,
        fps: int,
    ) -> str:
        """Write-on mask for an authored path inside Motion's reveal -> settle window, or ""
        to keep the normal entry (no settle authority, or the window is too short)."""
        params = cue.params if cue is not None and isinstance(cue.params, dict) else {}
        settle = params.get("semantic_settle_time")
        if type(settle) not in (int, float):
            return ""
        first_frame = cls._first_visible_frame(effective_reveal_start, fps)
        settle_frame = cls._first_visible_frame(float(settle) - segment_start, fps)
        frames = write_on_frame_count(first_frame, settle_frame)
        if not frames:
            return ""
        return write_on_filter(image_path=image_path, box=box, direction=direction,
                               first_frame=first_frame, frames=frames)

    @classmethod
    def _entry_opacity_filter(
        cls,
        cue: MotionCue | None,
        *,
        segment_start: float,
        effective_reveal_start: float,
        fps: int,
    ) -> str:
        """Alpha ramp for Motion's entry opacity clock, or "" to keep the hard reveal.

        The first encoded frame at/after the Story reveal shows ``initial`` opacity and
        the ramp reaches exactly 1.0 at the Story settle. Fails closed (no fade) when the
        asset is visible before its clock starts or the ramp cannot span two frames.
        """
        clock = cue.params.get("entry_opacity") if cue is not None and isinstance(cue.params, dict) else None
        if not isinstance(clock, dict):
            return ""
        try:
            initial = float(clock["initial"])
            start = float(clock["start"]) - segment_start
            settle = float(clock["settle"]) - segment_start
        except (KeyError, TypeError, ValueError):
            return ""
        first_frame = cls._first_visible_frame(start, fps)
        if not 0.0 < initial < 1.0 or cls._first_visible_frame(effective_reveal_start, fps) < first_frame:
            return ""
        first_time = first_frame / float(fps)
        ramp = settle - first_time
        if ramp < 2.0 / fps:
            return ""
        duration = ramp / (1.0 - initial)
        fade_start = first_time - initial * duration
        if fade_start < 0.0:
            return ""
        # A looped image stream ticks in whole frames; the fade would round its start to a
        # frame and can land exactly on the reveal frame (alpha 0, a one-frame-late reveal).
        # A microsecond timebase makes the clock exact at every encoded frame.
        return f",settb=AVTB,fade=t=in:st={fade_start:.6f}:d={duration:.6f}:alpha=1"

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
        if cue is not None and cue.segments:
            # Motion owns execution lifetime. Semantic proxy segments may start
            # before or finish after the owner's Story cue without changing the
            # owner's timing authority, so the renderer must cover the full segment
            # envelope rather than clipping execution to cue.start/cue.end.
            visible_starts = [
                float(segment.start)
                for segment in cue.segments
                if segment.phase != "EXIT"
            ]
            if visible_starts:
                global_start = min(global_start, min(visible_starts))
            global_end = max(
                global_end,
                max(float(segment.end) for segment in cue.segments),
            )
        start = max(0.0, global_start - segment_start)
        end = min(duration, max(start + 0.05, global_end - segment_start))
        reveal_duration = max(0.05, end - start)
        fade_duration = min(0.18, max(0.10, reveal_duration * 0.42))
        return start, end, fade_duration

    @staticmethod
    def _frame_safe_group_reveal_starts(
        *,
        rows: list[tuple[str, float, dict]],
        fps: int,
        duration: float,
    ) -> dict[str, float]:
        """Quantize already-distinct Story reveals without collapsing their order.

        Story owns continuous semantic time and Render owns conversion to encoded frames.
        Within one authored semantic group, two distinct Story reveal times must remain
        distinct first-visible frames. Equal Story timestamps stay equal so simultaneous
        cohorts are never invented into a sequence.

        Quantization only delays to a legal encoded frame; it never reveals early. If
        the segment has too few frames to preserve the authored distinction, fail before
        FFmpeg rather than silently producing a perceptual burst.
        """
        if fps <= 0 or duration <= 0.0:
            return {}
        frame_count = max(1, round(float(duration) * int(fps)))
        max_frame = frame_count - 1
        grouped: dict[str, list[tuple[str, float, int]]] = {}
        output: dict[str, float] = {}
        for asset_id, start, order in rows:
            group_id = order.get("semantic_group_id") if isinstance(order, dict) else None
            if (
                not isinstance(order, dict)
                or not group_id
                or order.get("sequence_order") is None
            ):
                # No authored group order to preserve: quantize this reveal on its own.
                try:
                    output[asset_id] = FFmpegRenderer._frame_safe_reveal_threshold(
                        max(0.0, float(start)), fps
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
                continue
            try:
                sequence_order = int(order.get("sequence_order"))
                raw_start = max(0.0, float(start))
            except (TypeError, ValueError, OverflowError):
                continue
            grouped.setdefault(str(group_id), []).append(
                (asset_id, raw_start, sequence_order)
            )

        for group_id, group_rows in grouped.items():
            ordered = sorted(group_rows, key=lambda row: (row[1], row[2], row[0]))
            clusters: list[list[tuple[str, float, int]]] = []
            for row in ordered:
                if clusters and abs(row[1] - clusters[-1][0][1]) <= 1e-9:
                    clusters[-1].append(row)
                else:
                    clusters.append([row])

            previous_frame: int | None = None
            for cluster in clusters:
                raw_start = cluster[0][1]
                natural_frame = max(0, math.ceil(raw_start * fps - 1e-9))
                assigned_frame = (
                    natural_frame
                    if previous_frame is None
                    else max(natural_frame, previous_frame + 1)
                )
                if assigned_frame > max_frame:
                    raise StageFailedError(
                        "encoded frame budget cannot preserve authored reveal order",
                        details={
                            "code": "ENCODED_REVEAL_ORDER_INFEASIBLE",
                            "semantic_group_id": group_id,
                            "raw_reveal_start": raw_start,
                            "required_frame": assigned_frame,
                            "last_frame": max_frame,
                            "fps": fps,
                            "duration": duration,
                            "asset_ids": [row[0] for row in cluster],
                        },
                    )
                # Put the continuous-time threshold safely inside the gap after the
                # previous frame (see _frame_threshold). No earlier encoded frame can
                # pass it, so Story's first-visible-frame authority is preserved.
                frame_threshold = FFmpegRenderer._frame_threshold(assigned_frame, fps)
                for asset_id, _start, _sequence in cluster:
                    output[asset_id] = frame_threshold
                previous_frame = assigned_frame
        return output

    @staticmethod
    def _cue_has_nonzero_entry_motion(cue: MotionCue | None) -> bool:
        if cue is None:
            return False
        programs = []
        if isinstance(cue.params, dict):
            program = cue.params.get("program")
            if isinstance(program, dict):
                programs.append(program)
        programs.extend(
            segment.program
            for segment in cue.segments
            if segment.phase == "ENTRY" and isinstance(segment.program, dict)
        )
        for program in programs:
            keyframes = program.get("keyframes")
            if not isinstance(keyframes, list):
                continue
            for frame in keyframes:
                if not isinstance(frame, dict):
                    continue
                try:
                    if (
                        abs(float(frame.get("dx", 0.0))) > 1e-9
                        or abs(float(frame.get("dy", 0.0))) > 1e-9
                        or abs(float(frame.get("scale", 1.0)) - 1.0) > 1e-9
                    ):
                        return True
                except (TypeError, ValueError, OverflowError):
                    continue
        return False

    @classmethod
    def _require_encoded_entry_window(
        cls,
        *,
        cue: MotionCue | None,
        authored_start: float,
        authored_end: float,
        effective_reveal_start: float,
        fps: int,
        beat_id: str,
        asset_id: str,
    ) -> None:
        """Fail before FFmpeg when frame ordering would hide all authored ENTRY motion."""
        if (
            fps <= 0
            or effective_reveal_start <= authored_start + 1e-9
            or not cls._cue_has_nonzero_entry_motion(cue)
        ):
            return
        first_visible_frame = math.ceil(effective_reveal_start * fps - 1e-9)
        first_visible_time = first_visible_frame / float(fps)
        if first_visible_time < authored_end - 1e-9:
            return
        raise StageFailedError(
            "encoded reveal ordering leaves no legal frame for authored entry motion",
            details={
                "code": "ENCODED_REVEAL_ORDER_INFEASIBLE",
                "beat_id": beat_id,
                "asset_id": asset_id,
                "authored_start": authored_start,
                "authored_end": authored_end,
                "effective_reveal_start": effective_reveal_start,
                "first_visible_frame": first_visible_frame,
                "fps": fps,
            },
        )

    @staticmethod
    def asset_visibility_window(
        *,
        cue: MotionCue | None,
        segment_start: float,
        duration: float,
        reveal_start: float,
        persistent: bool,
    ) -> tuple[float, float]:
        """Return the renderer-facing overlay window for one resolved lifecycle."""
        enable_start = 0.0 if persistent else reveal_start
        exit_segments = (
            [segment for segment in cue.segments if segment.phase == "EXIT"]
            if cue is not None
            else []
        )
        enable_end = duration
        if exit_segments:
            exit_end = min(float(segment.end) for segment in exit_segments) - segment_start
            enable_end = max(enable_start, min(duration, exit_end))
        return enable_start, enable_end

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

    def _encode_args(
        self,
        filters: list[str],
        target: Path,
        fps: int,
        frame_count: int,
    ) -> list[str]:
        # Never place a production filter graph directly on the process command
        # line. Dense scenes can generate many overlays/motion expressions and
        # exceed Windows CreateProcess limits (WinError 206) long before FFmpeg
        # itself sees the request. A per-segment script keeps command length
        # bounded on every platform and also leaves useful render diagnostics.
        target.parent.mkdir(parents=True, exist_ok=True)
        filter_script = target.parent / f"{target.stem}-filter-complex.ffgraph"
        filter_script.write_text(";\n".join(filters) + "\n", encoding="utf-8")
        return [
            "-filter_complex_threads",
            "1",
            self._filter_complex_file_option(target.parent),
            str(filter_script),
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


    def _filter_complex_file_option(self, probe_root: Path | None = None) -> str:
        """Select a file-backed complex-filter option by executing a real probe.

        FFmpeg builds vary across operating systems and versions, and help text does
        not reliably advertise the generic file-option syntax. Capability must be
        proven by execution, not inferred from ``ffmpeg -h full``.
        """
        if self._filter_complex_file_option_cache is not None:
            return self._filter_complex_file_option_cache

        if probe_root is None:
            with tempfile.TemporaryDirectory(prefix="hexa-filter-probe-") as temp_dir:
                return self._probe_filter_complex_file_option(Path(temp_dir))
        return self._probe_filter_complex_file_option(probe_root)

    def _probe_filter_complex_file_option(self, probe_root: Path) -> str:
        probe_root.mkdir(parents=True, exist_ok=True)
        filter_script = probe_root / "ffmpeg-filter-option-probe.ffgraph"
        filter_script.write_text(
            "[0:v]format=yuv420p[vout]\n",
            encoding="utf-8",
        )

        failures: dict[str, str] = {}
        for option in ("-/filter_complex", "-filter_complex_script"):
            command = [
                self.ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=white:s=16x16:r=1:d=0.04",
                option,
                str(filter_script),
                "-map",
                "[vout]",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ]
            try:
                run_hidden(command, check=True, capture_output=True, text=True)
            except FileNotFoundError as exc:
                raise DependencyUnavailableError(
                    "ffmpeg is not available",
                    details={"code": "FFMPEG_UNAVAILABLE", "binary": self.ffmpeg_bin},
                ) from exc
            except OSError as exc:
                raise StageFailedError(
                    "failed to execute ffmpeg filter-file capability probe",
                    details={
                        "code": "FFMPEG_CAPABILITY_PROBE_FAILED",
                        "binary": self.ffmpeg_bin,
                        "os_error": str(exc),
                    },
                ) from exc
            except subprocess.CalledProcessError as exc:
                failures[option] = (exc.stderr or "")[-4000:]
                continue

            self._filter_complex_file_option_cache = option
            return option

        raise StageFailedError(
            "ffmpeg does not support the production file-backed complex-filter path",
            details={
                "code": "FFMPEG_FILTER_FILE_UNSUPPORTED",
                "binary": self.ffmpeg_bin,
                "attempts": failures,
            },
        )

    @staticmethod
    def _time_to_frame(value: float, fps: int, total_frames: int) -> int:
        return time_to_frame(value, fps, total_frames)

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
        except OSError as exc:
            # Windows may surface CreateProcess command-line overflow as a
            # FileNotFoundError subclass with WinError 206. That is not a missing
            # FFmpeg dependency and must never be misreported as one.
            if getattr(exc, "winerror", None) == 206:
                raise StageFailedError(
                    "render process command exceeded the Windows process limit",
                    details={
                        "code": "RENDER_PROCESS_COMMAND_LIMIT",
                        "winerror": 206,
                        "argument_count": len(command),
                        "command_characters": sum(len(str(arg)) + 1 for arg in command),
                    },
                ) from exc
            if isinstance(exc, FileNotFoundError):
                raise DependencyUnavailableError(
                    "ffmpeg is not available",
                    details={"code": "FFMPEG_UNAVAILABLE", "binary": command[0] if command else None},
                ) from exc
            raise StageFailedError(
                message,
                details={
                    "code": "RENDER_PROCESS_OS_ERROR",
                    "os_error": str(exc),
                    "errno": getattr(exc, "errno", None),
                },
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "")[-6000:]
            normalized = stderr.lower()
            if (
                "filter_complex_script" in normalized
                and ("unrecognized option" in normalized or "option not found" in normalized)
            ):
                code = "FFMPEG_FILTER_FILE_UNSUPPORTED"
            elif (
                "unknown encoder 'libx264'" in normalized
                or "encoder (codec h264) not found" in normalized
            ):
                code = "FFMPEG_H264_ENCODER_UNAVAILABLE"
            else:
                code = "FFMPEG_COMMAND_FAILED"
            raise StageFailedError(
                message,
                details={"code": code, "stderr": stderr},
            ) from exc
