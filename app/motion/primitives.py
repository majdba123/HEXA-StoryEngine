from __future__ import annotations

from math import hypot

from app.models import LayoutItem
from app.motion.models import MotionKeyframe, MotionProgram


class MotionPrimitiveLibrary:
    """Semantic motion primitives driven by Choreography, never scene IDs.

    Programs first make an asset readable at Composition's target, then perform a
    meaning-bearing action/reaction. This prevents the old "enter then hold" pattern.
    """

    def build(
        self,
        *,
        action: str,
        item: LayoutItem,
        index: int,
        count: int,
        visual_duration: float,
        interaction_vector: tuple[float, float] = (0.0, 0.0),
        phase: str = "ACTION",
        hook_kind: str = "NONE",
        hook_mechanism: str = "NONE",
        energy: float = 0.6,
        tension: float = 0.0,
        variant: int = 0,
        is_primary: bool | None = None,
    ) -> MotionProgram:
        primary = index == 0 if is_primary is None else is_primary
        if visual_duration < 0.18:
            return self._minimal(primary=primary)

        action = action.upper()
        hook = hook_kind != "NONE"
        hook_mechanism = hook_mechanism.upper()
        energy = max(0.35, min(1.0, energy))
        tension = max(0.0, min(1.0, tension))
        vx, vy = self._clamp_vector(interaction_vector, 0.20 if hook else 0.15)
        if hook_mechanism == "CONTRADICTION":
            energy = min(1.0, energy + 0.10)
        elif hook_mechanism == "PAYOFF":
            tension *= 0.72

        if not primary:
            return self._support(
                action=action,
                item=item,
                index=index,
                vector=(vx, vy),
                hook=hook,
                energy=energy,
                variant=variant,
            )

        if action == "REJECT":
            return self._reject(item, (vx, vy), hook, energy, tension)
        if action == "BLOCK":
            return self._block(item, (vx, vy), hook, energy)
        if action == "LOCK":
            return self._lock(item, (vx, vy), hook, energy)
        if action == "LOOP":
            return self._loop(item, (vx, vy), hook, energy)
        if action == "TRAVEL":
            return self._travel(item, (vx, vy), hook, energy, variant)
        if action == "SCAN":
            return self._scan(item, (vx, vy), hook, energy)
        if action == "COMPARE":
            return self._compare(item, hook, energy, variant)
        if action == "PROTECT":
            return self._protect(item, hook, energy)
        if action == "RESOLVE":
            return self._resolve(item, hook, energy, variant)
        if action == "REVEAL":
            return self._reveal(item, hook, energy, variant)
        return self._focus(item, hook, energy, variant, phase)

    def build_continuity(
        self,
        *,
        action: str,
        item: LayoutItem,
        index: int,
        count: int,
        visual_duration: float,
        previous_offset: tuple[float, float],
        previous_scale: float,
        interaction_vector: tuple[float, float] = (0.0, 0.0),
        phase: str = "ACTION",
        hook_kind: str = "NONE",
        hook_mechanism: str = "NONE",
        energy: float = 0.6,
        tension: float = 0.0,
        variant: int = 0,
        same_asset: bool = True,
        is_primary: bool | None = None,
    ) -> MotionProgram:
        """Compose continuity *with* the semantic action instead of replacing it.

        The previous implementation used continuity as the entire motion program. That
        created visually smooth baton passes but suppressed REJECT/BLOCK/LOCK/etc. The
        reference style depends on both: first preserve the viewer's focal point, then
        perform a meaning-bearing action. This method therefore replaces only the base
        primitive's entrance phase and keeps its semantic action/reaction tail intact.
        """

        base = self.build(
            action=action,
            item=item,
            index=index,
            count=count,
            visual_duration=visual_duration,
            interaction_vector=interaction_vector,
            phase=phase,
            hook_kind=hook_kind,
            hook_mechanism=hook_mechanism,
            energy=energy,
            tension=tension,
            variant=variant,
            is_primary=is_primary,
        )

        px, py = self._clamp_vector(previous_offset, 0.42 if same_asset else 0.34)
        previous_scale = max(0.62, min(1.45, previous_scale))
        hook = hook_kind != "NONE"
        arrival_progress = 0.30 if hook else 0.38
        if not same_asset:
            # Match-cut handoffs need a readable travel beat; they should not masquerade
            # as a physical morph between unrelated illustrations.
            arrival_progress = 0.34 if hook else 0.42

        frames: list[MotionKeyframe] = [
            MotionKeyframe(0.0, px, py, previous_scale, "ease_in_out_cubic"),
            MotionKeyframe(arrival_progress, 0.0, 0.0, 1.0, "ease_out_expo"),
        ]

        tail = [frame for frame in base.keyframes if frame.progress > base.settle_progress + 1e-9]
        if tail and base.settle_progress < 1.0:
            tail_span = 1.0 - base.settle_progress
            remaining = 1.0 - arrival_progress
            for frame in tail:
                normalized = (frame.progress - base.settle_progress) / tail_span
                progress = arrival_progress + normalized * remaining
                # Avoid a floating-point collision with the authored arrival keyframe.
                progress = max(arrival_progress + 0.001, min(1.0, progress))
                if progress >= 1.0 - 1e-9:
                    continue
                frames.append(MotionKeyframe(
                    progress,
                    frame.dx,
                    frame.dy,
                    frame.scale,
                    frame.easing,
                ))

        frames.append(MotionKeyframe(1.0))
        prefix = "continuity" if same_asset else "handoff"
        return MotionProgram(
            name=f"{prefix}_then_{base.name}",
            settle_progress=arrival_progress,
            keyframes=tuple(frames),
        )

    def build_legacy(
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
            direction = self._edge_direction(item)
            amplitude = max(0.012, 0.024 - min(index, 4) * 0.0025)
            return MotionProgram(
                name="support_stagger",
                settle_progress=1.0,
                keyframes=(
                    MotionKeyframe(0.0, dx=direction * amplitude * 0.55, dy=amplitude, easing="ease_out_cubic"),
                    MotionKeyframe(0.82, dx=-direction * 0.0015, dy=-0.002, easing="smoothstep"),
                    MotionKeyframe(1.0),
                ),
            )
        action = action.upper()
        direction = self._edge_direction(item)
        if action == "HANDOFF":
            return MotionProgram(name="handoff_travel", settle_progress=1.0, keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.062, dy=0.008, easing="ease_out_cubic"),
                MotionKeyframe(0.64, dx=-direction * 0.006, dy=-0.004, easing="smoothstep"),
                MotionKeyframe(0.84, dx=direction * 0.002, dy=0.001, easing="smoothstep"),
                MotionKeyframe(1.0),
            ))
        if action == "RESULT":
            return MotionProgram(name="result_impact", settle_progress=1.0, keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.018, dy=0.030, easing="ease_out_expo"),
                MotionKeyframe(0.52, dx=-direction * 0.004, dy=-0.006, easing="smoothstep"),
                MotionKeyframe(0.70, dx=0.0, dy=0.0, easing="ease_in_out_cubic"),
                MotionKeyframe(0.84, dx=-direction * 0.006, dy=0.0, easing="smoothstep"),
                MotionKeyframe(1.0),
            ))
        if action == "EMPHASIZE":
            return MotionProgram(name="emphasis_hit", settle_progress=1.0, keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.014, dy=0.024, easing="ease_out_expo"),
                MotionKeyframe(0.62, dx=-direction * 0.003, dy=-0.005, easing="smoothstep"),
                MotionKeyframe(0.82, dx=direction * 0.001, dy=0.001, easing="smoothstep"),
                MotionKeyframe(1.0),
            ))
        if action == "COMPARE":
            compare_direction = -1.0 if item.x <= 0.5 else 1.0
            if index % 2:
                compare_direction *= -1.0
            return MotionProgram(name="compare_opposed", settle_progress=1.0, keyframes=(
                MotionKeyframe(0.0, dx=compare_direction * 0.048, dy=0.010, easing="ease_out_cubic"),
                MotionKeyframe(0.78, dx=-compare_direction * 0.003, dy=-0.002, easing="smoothstep"),
                MotionKeyframe(1.0),
            ))
        if action == "REVEAL_DETAIL":
            return MotionProgram(name="reveal_detail", settle_progress=1.0, keyframes=(
                MotionKeyframe(0.0, dx=direction * 0.022, dy=0.020, easing="ease_out_cubic"),
                MotionKeyframe(0.80, dx=-direction * 0.002, dy=-0.003, easing="smoothstep"),
                MotionKeyframe(1.0),
            ))
        return MotionProgram(name="introduce_settle", settle_progress=1.0, keyframes=(
            MotionKeyframe(0.0, dx=direction * 0.042, dy=0.014, easing="ease_out_expo"),
            MotionKeyframe(0.76, dx=-direction * 0.004, dy=-0.003, easing="smoothstep"),
            MotionKeyframe(1.0),
        ))

    @staticmethod
    def _edge_direction(item: LayoutItem) -> float:
        return -1.0 if item.x < 0.5 else 1.0

    @staticmethod
    def _clamp_vector(vector: tuple[float, float], limit: float) -> tuple[float, float]:
        x, y = vector
        length = hypot(x, y)
        if length <= 1e-9:
            return (0.0, 0.0)
        if length <= limit:
            return (x, y)
        scale = limit / length
        return (x * scale, y * scale)

    def _entry(self, item: LayoutItem, hook: bool, energy: float, variant: int) -> tuple[float, float, float]:
        direction = self._edge_direction(item)
        amplitude = (0.11 if hook else 0.065) * (0.75 + 0.5 * energy)
        mode = variant % 4
        if mode == 0:
            return direction * amplitude, 0.040 * energy, 0.92 if hook else 0.96
        if mode == 1:
            return direction * 0.018, 0.095 * energy, 0.90 if hook else 0.95
        if mode == 2:
            return direction * amplitude * 1.35, -0.018 * energy, 0.94
        return direction * amplitude * 0.85, -0.082 * energy, 0.91 if hook else 0.96

    def _reject(self, item, vector, hook, energy, tension) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, 2)
        vx, vy = vector if vector != (0.0, 0.0) else (-self._edge_direction(item) * 0.10, 0.0)
        force = 0.55 + 0.35 * max(energy, tension)
        return MotionProgram(
            name="reject_attempt_recoil",
            settle_progress=0.30,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.30),
                MotionKeyframe(0.52, vx * force, vy * force, 1.05, "ease_in_out_cubic"),
                MotionKeyframe(0.60, vx * force * 0.92, vy * force * 0.92, 0.98, "linear"),
                MotionKeyframe(0.75, -vx * 0.30, -vy * 0.30, 1.08, "ease_out_back"),
                MotionKeyframe(1.0),
            ),
        )

    def _block(self, item, vector, hook, energy) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, 0)
        vx, vy = vector if vector != (0.0, 0.0) else (-self._edge_direction(item) * 0.09, 0.0)
        return MotionProgram(
            name="block_hit_stop",
            settle_progress=0.32,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.32),
                MotionKeyframe(0.58, vx * 0.48, vy * 0.48, 1.035, "ease_in_cubic"),
                MotionKeyframe(0.64, vx * 0.50, vy * 0.50, 1.035, "linear"),
                MotionKeyframe(0.78, -vx * 0.16, -vy * 0.16, 1.02, "ease_out_back"),
                MotionKeyframe(1.0),
            ),
        )

    def _lock(self, item, vector, hook, energy) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, 1)
        vx, vy = vector
        return MotionProgram(
            name="lock_extract_settle",
            settle_progress=0.34,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.34),
                MotionKeyframe(0.56, vx * 0.34, vy * 0.34 - 0.018, 0.95, "ease_in_out_cubic"),
                MotionKeyframe(0.72, vx * 0.18, vy * 0.18, 1.06, "ease_out_back"),
                MotionKeyframe(1.0),
            ),
        )

    def _loop(self, item, vector, hook, energy) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, 2)
        vx, vy = vector if vector != (0.0, 0.0) else (-self._edge_direction(item) * 0.07, 0.0)
        a = 0.30 + energy * 0.20
        return MotionProgram(
            name="repeat_attempts",
            settle_progress=0.26,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.26),
                MotionKeyframe(0.42, vx * a, vy * a, 1.03, "ease_in_out_cubic"),
                MotionKeyframe(0.54, -vx * 0.13, -vy * 0.13, 0.98, "ease_out_cubic"),
                MotionKeyframe(0.68, vx * a * 0.92, vy * a * 0.92, 1.03, "ease_in_out_cubic"),
                MotionKeyframe(0.80, -vx * 0.10, -vy * 0.10, 0.99, "ease_out_cubic"),
                MotionKeyframe(1.0),
            ),
        )

    def _travel(self, item, vector, hook, energy, variant) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, variant)
        vx, vy = vector if vector != (0.0, 0.0) else (-self._edge_direction(item) * 0.11, -0.02)
        return MotionProgram(
            name="travel_connect_handoff",
            settle_progress=0.30,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.30),
                MotionKeyframe(0.54, vx * 0.28, vy * 0.28 - 0.025, 1.02, "ease_in_out_cubic"),
                MotionKeyframe(0.76, vx * 0.58, vy * 0.58, 1.04, "ease_in_out_cubic"),
                MotionKeyframe(1.0),
            ),
        )

    def _scan(self, item, vector, hook, energy) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, 3)
        vx, vy = vector
        direction = self._edge_direction(item)
        return MotionProgram(
            name="scan_pass_focus",
            settle_progress=0.32,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.32),
                MotionKeyframe(0.50, direction * 0.026, -0.010, 1.05, "ease_out_cubic"),
                MotionKeyframe(0.68, vx * 0.20 - direction * 0.018, vy * 0.20 + 0.008, 1.03, "ease_in_out_cubic"),
                MotionKeyframe(1.0),
            ),
        )

    def _compare(self, item, hook, energy, variant) -> MotionProgram:
        direction = self._edge_direction(item) * (-1.0 if variant % 2 else 1.0)
        ex, ey, es = self._entry(item, hook, energy, variant)
        return MotionProgram(
            name="compare_opposed_focus",
            settle_progress=0.32,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.32),
                MotionKeyframe(0.56, direction * 0.060 * energy, 0.0, 1.05, "ease_in_out_cubic"),
                MotionKeyframe(0.74, -direction * 0.025 * energy, 0.0, 0.98, "ease_out_back"),
                MotionKeyframe(1.0),
            ),
        )

    def _protect(self, item, hook, energy) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, 1)
        return MotionProgram(
            name="protect_close_shield",
            settle_progress=0.34,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.34),
                MotionKeyframe(0.56, 0.0, -0.022 * energy, 0.94, "ease_in_out_cubic"),
                MotionKeyframe(0.72, 0.0, 0.006, 1.07, "ease_out_back"),
                MotionKeyframe(1.0),
            ),
        )

    def _resolve(self, item, hook, energy, variant) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, variant)
        direction = self._edge_direction(item)
        return MotionProgram(
            name="resolve_release",
            settle_progress=0.34,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.34),
                MotionKeyframe(0.56, -direction * 0.030 * energy, -0.028 * energy, 1.08, "ease_out_back"),
                MotionKeyframe(0.76, direction * 0.012, 0.008, 1.02, "smoothstep"),
                MotionKeyframe(1.0),
            ),
        )

    def _reveal(self, item, hook, energy, variant) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, variant)
        direction = self._edge_direction(item)
        return MotionProgram(
            name="reveal_breathe",
            settle_progress=0.36,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.36),
                MotionKeyframe(0.66, -direction * 0.018 * energy, -0.010, 1.055, "ease_out_back"),
                MotionKeyframe(1.0),
            ),
        )

    def _focus(self, item, hook, energy, variant, phase) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, variant)
        direction = self._edge_direction(item)
        follow = 0.028 if phase in {"ACTION", "CONSEQUENCE"} else 0.016
        return MotionProgram(
            name="focus_story_beat",
            settle_progress=0.38,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.38),
                MotionKeyframe(0.68, -direction * follow * energy, -0.008, 1.04, "ease_out_back"),
                MotionKeyframe(1.0),
            ),
        )

    def _support(self, *, action, item, index, vector, hook, energy, variant) -> MotionProgram:
        direction = self._edge_direction(item)
        ex = direction * (0.050 if hook else 0.028) * (0.8 + energy * 0.4)
        ey = (0.052 if (index + variant) % 2 else -0.038) * energy
        # Supports are response actors: important negative/transaction actions make them
        # react after the primary hit instead of all entering at once.
        reaction = {
            "REJECT": (-vector[0] * 0.24, -vector[1] * 0.24, 1.08),
            "BLOCK": (-vector[0] * 0.16, -vector[1] * 0.16, 1.05),
            "LOCK": (vector[0] * 0.12, vector[1] * 0.12, 0.96),
            "LOOP": (-direction * 0.024, 0.0, 1.04),
            "PROTECT": (0.0, -0.018, 1.06),
            "RESOLVE": (-direction * 0.020, -0.018, 1.07),
        }.get(action, (-direction * 0.012, -0.008, 1.035))
        return MotionProgram(
            name=f"support_react_{action.lower()}",
            settle_progress=0.44,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, 0.94 if hook else 0.97, "ease_out_cubic"),
                MotionKeyframe(0.44),
                MotionKeyframe(0.70, reaction[0], reaction[1], reaction[2], "ease_out_back"),
                MotionKeyframe(1.0),
            ),
        )

    @staticmethod
    def _minimal(*, primary: bool) -> MotionProgram:
        return MotionProgram(
            name="minimal_settle",
            settle_progress=1.0,
            keyframes=(
                MotionKeyframe(0.0, dy=0.010 if primary else 0.006, scale=0.98, easing="ease_out_cubic"),
                MotionKeyframe(1.0),
            ),
        )
