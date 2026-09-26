from __future__ import annotations

from typing import Any

from app.models import MotionCue


class FFmpegMotionAdapter:
    """Translate backend-neutral Motion V3 keyframes to FFmpeg overlay expressions."""

    ENGINE_VERSION = 3

    @classmethod
    def supports(cls, cue: MotionCue | None) -> bool:
        return bool(
            cue
            and cue.kind == "program_v3"
            and cue.params.get("engine_version") == cls.ENGINE_VERSION
            and (isinstance(cue.params.get("program"), dict) or bool(cue.segments))
        )

    def position_expressions(
        self,
        *,
        cue: MotionCue,
        target_x: int,
        target_y: int,
        canvas_width: int,
        canvas_height: int,
        segment_start: float,
        segment_duration: float,
    ) -> tuple[str, str]:
        program = cue.params.get("program")
        if cue.segments:
            x_offsets = self._segmented_axis_expression(
                cue=cue, axis="dx", scale=canvas_width,
                segment_start=segment_start, segment_duration=segment_duration, default=0.0,
            )
            y_offsets = self._segmented_axis_expression(
                cue=cue, axis="dy", scale=canvas_height,
                segment_start=segment_start, segment_duration=segment_duration, default=0.0,
            )
        else:
            if not isinstance(program, dict):
                return str(target_x), str(target_y)
            keyframes = program.get("keyframes")
            if not isinstance(keyframes, list) or len(keyframes) < 2:
                return str(target_x), str(target_y)
            local_start = max(0.0, float(cue.start) - segment_start)
            local_end = min(
                segment_duration,
                max(local_start + 0.05, float(cue.end) - segment_start),
            )
            window = max(0.05, local_end - local_start)
            x_offsets = self._axis_expression(
                keyframes=keyframes, axis="dx", scale=canvas_width,
                start=local_start, window=window,
            )
            y_offsets = self._axis_expression(
                keyframes=keyframes, axis="dy", scale=canvas_height,
                start=local_start, window=window,
            )
        return f"{target_x}+({x_offsets})", f"{target_y}+({y_offsets})"


    def scale_expression(
        self,
        *,
        cue: MotionCue,
        segment_start: float,
        segment_duration: float,
    ) -> str:
        if cue.segments:
            return self._segmented_axis_expression(
                cue=cue, axis="scale", scale=1,
                segment_start=segment_start, segment_duration=segment_duration, default=1.0,
            )
        program = cue.params.get("program")
        if not isinstance(program, dict):
            return "1"
        keyframes = program.get("keyframes")
        if not isinstance(keyframes, list) or len(keyframes) < 2:
            return "1"
        local_start = max(0.0, float(cue.start) - segment_start)
        local_end = min(
            segment_duration,
            max(local_start + 0.05, float(cue.end) - segment_start),
        )
        window = max(0.05, local_end - local_start)
        return self._axis_expression(
            keyframes=keyframes, axis="scale", scale=1,
            start=local_start, window=window, default=1.0,
        )

    def _segmented_axis_expression(
        self,
        *,
        cue: MotionCue,
        axis: str,
        scale: int,
        segment_start: float,
        segment_duration: float,
        default: float,
    ) -> str:
        expression = self._number(default)
        entry = next((row for row in cue.segments if row.phase == "ENTRY"), None)
        if entry is not None:
            keyframes = entry.program.get("keyframes")
            if isinstance(keyframes, list) and len(keyframes) >= 2:
                start = max(0.0, float(entry.start) - segment_start)
                end = min(segment_duration, max(start + 0.05, float(entry.end) - segment_start))
                expression = self._axis_expression(
                    keyframes=keyframes, axis=axis, scale=scale,
                    start=start, window=max(0.05, end - start), default=default,
                )

        for row in sorted(
            (item for item in cue.segments if item.phase != "ENTRY"),
            key=lambda item: (item.start, item.end, item.phase),
        ):
            keyframes = row.program.get("keyframes")
            if not isinstance(keyframes, list) or len(keyframes) < 2:
                continue
            start = max(0.0, float(row.start) - segment_start)
            end = min(segment_duration, float(row.end) - segment_start)
            if end <= start + 1e-6:
                continue
            active = self._axis_expression(
                keyframes=keyframes, axis=axis, scale=scale,
                start=start, window=max(0.05, end - start), default=default,
            )
            expression = f"if(between(t,{start:.6f},{end:.6f}),{active},{expression})"
        return expression

    def _axis_expression(
        self,
        *,
        keyframes: list[dict[str, Any]],
        axis: str,
        scale: int,
        start: float,
        window: float,
        default: float = 0.0,
    ) -> str:
        parsed: list[tuple[float, float, str]] = []
        for frame in keyframes:
            try:
                progress = float(frame["progress"])
                value = float(frame.get(axis, default)) * scale
                easing = str(frame.get("easing") or "ease_out_cubic")
            except (KeyError, TypeError, ValueError):
                continue
            parsed.append((progress, value, easing))
        if len(parsed) < 2:
            return "0"

        parsed.sort(key=lambda row: row[0])
        first_value = parsed[0][1]
        expression = self._number(parsed[-1][1])
        for index in range(len(parsed) - 2, -1, -1):
            left_progress, left_value, easing = parsed[index]
            right_progress, right_value, _ = parsed[index + 1]
            segment_start = start + left_progress * window
            segment_end = start + right_progress * window
            duration = max(0.001, segment_end - segment_start)
            p = f"((t-{segment_start:.6f})/{duration:.6f})"
            eased = self._easing_expression(easing, p)
            delta = right_value - left_value
            interpolation = f"{self._number(left_value)}+({self._number(delta)})*({eased})"
            expression = f"if(lt(t,{segment_end:.6f}),{interpolation},{expression})"

        return f"if(lt(t,{start:.6f}),{self._number(first_value)},{expression})"

    @staticmethod
    def _easing_expression(name: str, p: str) -> str:
        if name == "linear":
            return p
        if name == "ease_in_cubic":
            return f"({p})*({p})*({p})"
        if name == "ease_out_cubic":
            return f"1-pow(1-({p}),3)"
        if name == "ease_in_out_cubic":
            return f"if(lt({p},0.5),4*({p})*({p})*({p}),1-pow(-2*({p})+2,3)/2)"
        if name == "smoothstep":
            return f"3*({p})*({p})-2*({p})*({p})*({p})"
        if name == "ease_out_expo":
            return f"if(gte({p},1),1,1-pow(2,-10*({p})))"
        if name == "ease_out_back":
            return f"1+2.70158*pow(({p})-1,3)+1.70158*pow(({p})-1,2)"
        return f"1-pow(1-({p}),3)"

    @staticmethod
    def _number(value: float) -> str:
        if abs(value) < 1e-9:
            return "0"
        return f"{value:.6f}".rstrip("0").rstrip(".")
