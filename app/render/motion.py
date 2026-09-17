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
            and isinstance(cue.params.get("program"), dict)
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
            keyframes=keyframes,
            axis="dx",
            scale=canvas_width,
            start=local_start,
            window=window,
        )
        y_offsets = self._axis_expression(
            keyframes=keyframes,
            axis="dy",
            scale=canvas_height,
            start=local_start,
            window=window,
        )
        return f"{target_x}+({x_offsets})", f"{target_y}+({y_offsets})"

    def _axis_expression(
        self,
        *,
        keyframes: list[dict[str, Any]],
        axis: str,
        scale: int,
        start: float,
        window: float,
    ) -> str:
        parsed: list[tuple[float, float, str]] = []
        for frame in keyframes:
            try:
                progress = float(frame["progress"])
                value = float(frame.get(axis, 0.0)) * scale
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
