from __future__ import annotations

import subprocess
from pathlib import Path

from app.models import RenderPlan
from app.shared.errors import DependencyUnavailableError, StageFailedError


class FFmpegRenderer:
    """Deterministic layer compositor for the V2 baseline.

    Each composition item is rendered as an independent layer. Motion cues control
    reveal timing and directional entry; the renderer never invents story decisions.
    """

    def __init__(self, ffmpeg_bin: str = "ffmpeg") -> None:
        self.ffmpeg_bin = ffmpeg_bin

    def render(self, plan: RenderPlan, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        assets = {asset.id: asset for asset in plan.assets}
        composition = {beat.beat_id: beat for beat in plan.composition}
        motion = {(cue.beat_id, cue.asset_id): cue for cue in plan.motion}

        command: list[str] = [
            self.ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=white:s={plan.width}x{plan.height}:r={plan.fps}:d={plan.duration:.6f}",
        ]

        layers: list[tuple[int, object, object, object]] = []
        input_index = 1
        for beat in plan.story:
            layout = composition.get(beat.id)
            if not layout:
                continue
            for item in sorted(layout.items, key=lambda row: row.z):
                asset = assets.get(item.asset_id)
                if asset is None:
                    raise StageFailedError(
                        "render plan references missing asset",
                        details={"asset_id": item.asset_id, "beat_id": beat.id},
                    )
                if not asset.image_path.exists():
                    raise StageFailedError(
                        "render asset file is missing",
                        details={"asset_id": asset.id, "path": str(asset.image_path)},
                    )
                command.extend([
                    "-loop",
                    "1",
                    "-t",
                    f"{plan.duration:.6f}",
                    "-i",
                    str(asset.image_path),
                ])
                layers.append((input_index, beat, item, motion.get((beat.id, item.asset_id))))
                input_index += 1

        filters: list[str] = ["[0:v]format=rgba[base0]"]
        previous = "base0"
        for layer_index, (source_index, beat, item, cue) in enumerate(layers):
            box_w = max(2, round(plan.width * item.width))
            box_h = max(2, round(plan.height * item.height))
            target_x = round(plan.width * (item.x - item.width / 2))
            target_y = round(plan.height * (item.y - item.height / 2))

            start = float(cue.start if cue else beat.start)
            end = float(cue.end if cue else min(beat.end, beat.start + 0.35))
            reveal_duration = max(0.05, end - start)
            out_duration = min(0.16, max(0.05, (beat.end - beat.start) * 0.12))
            out_start = max(start + reveal_duration, beat.end - out_duration)

            source_label = f"asset{layer_index}"
            filters.append(
                f"[{source_index}:v]format=rgba,"
                f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease,"
                f"fade=t=in:st={start:.6f}:d={reveal_duration:.6f}:alpha=1,"
                f"fade=t=out:st={out_start:.6f}:d={out_duration:.6f}:alpha=1"
                f"[{source_label}]"
            )

            kind = getattr(cue, "kind", "reveal_in") if cue else "reveal_in"
            if kind == "handoff_in":
                x_expr = self._entry_expression(target_x, start, end, offset=80)
                y_expr = str(target_y)
            else:
                x_expr = str(target_x)
                y_expr = self._entry_expression(target_y, start, end, offset=42)

            next_label = f"mix{layer_index}"
            filters.append(
                f"[{previous}][{source_label}]overlay="
                f"x='{x_expr}':y='{y_expr}':"
                f"enable='between(t,{beat.start:.6f},{beat.end:.6f})':"
                f"eof_action=pass:shortest=0[{next_label}]"
            )
            previous = next_label

        if layers:
            filters.append(f"[{previous}]format=yuv420p[vout]")
        else:
            filters.append("[base0]format=yuv420p[vout]")

        command.extend([
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(plan.fps),
            "-movflags",
            "+faststart",
            str(output),
        ])

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise DependencyUnavailableError("ffmpeg is not available") from exc
        except subprocess.CalledProcessError as exc:
            raise StageFailedError(
                "render failed",
                details={"stderr": (exc.stderr or "")[-6000:]},
            ) from exc

        if not output.exists() or output.stat().st_size == 0:
            raise StageFailedError("renderer produced no output")
        return output

    @staticmethod
    def _entry_expression(target: int, start: float, end: float, *, offset: int) -> str:
        duration = max(0.05, end - start)
        return (
            f"{target}+if(lt(t,{start:.6f}),{offset},"
            f"if(lt(t,{end:.6f}),{offset}*(1-(t-{start:.6f})/{duration:.6f}),0))"
        )
