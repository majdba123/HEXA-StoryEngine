from __future__ import annotations

from app.models import LayoutItem

from app.motion.models import MotionKeyframe, MotionProgram


class MotionPrimitiveLibrary:
    """Reusable semantic motion primitives expressed relative to Composition."""

    def build(
        self,
        *,
        action: str,
        item: LayoutItem,
        index: int,
        count: int,
        visual_duration: float,
    ) -> MotionProgram:
        primary = index == 0
        if visual_duration < 0.24:
            return self._minimal(primary=primary)

        if not primary:
            return self._support(item=item, index=index, count=count)

        action = action.upper()
        if action == "HANDOFF":
            return self._handoff(item)
        if action == "RESULT":
            return self._result(item)
        if action == "EMPHASIZE":
            return self._emphasis(item)
        if action == "COMPARE":
            return self._compare(item, index)
        if action == "REVEAL_DETAIL":
            return self._reveal(item)
        return self._introduce(item)

    @staticmethod
    def _edge_direction(item: LayoutItem) -> float:
        return -1.0 if item.x < 0.48 else 1.0

    def _introduce(self, item: LayoutItem) -> MotionProgram:
        direction = self._edge_direction(item)
        return MotionProgram(
            name="introduce_settle",
            keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.042, dy=0.014, easing="ease_out_expo"),
                MotionKeyframe(0.76, dx=-direction * 0.004, dy=-0.003, easing="smoothstep"),
                MotionKeyframe(1.0),
            ),
        )

    def _handoff(self, item: LayoutItem) -> MotionProgram:
        direction = self._edge_direction(item)
        return MotionProgram(
            name="handoff_travel",
            keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.062, dy=0.008, easing="ease_out_cubic"),
                MotionKeyframe(0.64, dx=-direction * 0.006, dy=-0.004, easing="smoothstep"),
                MotionKeyframe(0.84, dx=direction * 0.002, dy=0.001, easing="smoothstep"),
                MotionKeyframe(1.0),
            ),
        )

    def _result(self, item: LayoutItem) -> MotionProgram:
        direction = self._edge_direction(item)
        return MotionProgram(
            name="result_impact",
            keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.018, dy=0.030, easing="ease_out_expo"),
                MotionKeyframe(0.52, dx=-direction * 0.004, dy=-0.006, easing="smoothstep"),
                MotionKeyframe(0.70, dx=0.0, dy=0.0, easing="ease_in_out_cubic"),
                MotionKeyframe(0.84, dx=-direction * 0.006, dy=0.0, easing="smoothstep"),
                MotionKeyframe(1.0),
            ),
        )

    def _emphasis(self, item: LayoutItem) -> MotionProgram:
        direction = self._edge_direction(item)
        return MotionProgram(
            name="emphasis_hit",
            keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.014, dy=0.024, easing="ease_out_expo"),
                MotionKeyframe(0.62, dx=-direction * 0.003, dy=-0.005, easing="smoothstep"),
                MotionKeyframe(0.82, dx=direction * 0.001, dy=0.001, easing="smoothstep"),
                MotionKeyframe(1.0),
            ),
        )

    def _compare(self, item: LayoutItem, index: int) -> MotionProgram:
        direction = -1.0 if item.x <= 0.5 else 1.0
        if index % 2:
            direction *= -1.0
        return MotionProgram(
            name="compare_opposed",
            keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.048, dy=0.010, easing="ease_out_cubic"),
                MotionKeyframe(0.78, dx=-direction * 0.003, dy=-0.002, easing="smoothstep"),
                MotionKeyframe(1.0),
            ),
        )

    def _reveal(self, item: LayoutItem) -> MotionProgram:
        direction = self._edge_direction(item)
        return MotionProgram(
            name="reveal_detail",
            keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.022, dy=0.020, easing="ease_out_cubic"),
                MotionKeyframe(0.80, dx=-direction * 0.002, dy=-0.003, easing="smoothstep"),
                MotionKeyframe(1.0),
            ),
        )

    def _support(self, *, item: LayoutItem, index: int, count: int) -> MotionProgram:
        del count
        direction = self._edge_direction(item)
        amplitude = max(0.012, 0.024 - min(index, 4) * 0.0025)
        return MotionProgram(
            name="support_stagger",
            keyframes=(
                MotionKeyframe(
                    0.0,
                    dx=direction * amplitude * 0.55,
                    dy=amplitude,
                    easing="ease_out_cubic",
                ),
                MotionKeyframe(0.82, dx=-direction * 0.0015, dy=-0.002, easing="smoothstep"),
                MotionKeyframe(1.0),
            ),
        )

    @staticmethod
    def _minimal(*, primary: bool) -> MotionProgram:
        return MotionProgram(
            name="minimal_settle",
            keyframes=(
                MotionKeyframe(
                    0.0,
                    dy=0.008 if primary else 0.005,
                    easing="ease_out_cubic",
                ),
                MotionKeyframe(1.0),
            ),
        )
