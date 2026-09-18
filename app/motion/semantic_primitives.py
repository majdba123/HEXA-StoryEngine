from __future__ import annotations

from app.models import LayoutItem
from app.motion.models import MotionKeyframe, MotionProgram
from app.motion.primitives import MotionPrimitiveLibrary


class SemanticMotionPrimitiveLibrary(MotionPrimitiveLibrary):
    """Role-aware semantic motion layered on the proven primitive library.

    The legacy primary action primitives remain intact. This adapter only adds explicit
    REACT/CONNECT actions and prevents generic support layers from post-settle wobbling.
    """

    def build_family_secondary(self) -> MotionProgram:
        """Reveal a registered Pass2 family layer without changing its footprint.

        Pass2 family layers share the parent canvas and therefore already encode their
        authoritative resting registration. Translation or scale would sweep the alpha
        footprint through pixels that are intentionally empty in the authored final
        state. Keep geometry fixed and let the renderer reveal the layer with alpha.
        """
        return MotionProgram(
            name="family_secondary_footprint_locked_reveal",
            settle_progress=0.42,
            keyframes=(
                MotionKeyframe(0.0, 0.0, 0.0, 1.0, "smoothstep"),
                MotionKeyframe(0.42, 0.0, 0.0, 1.0, "smoothstep"),
                MotionKeyframe(1.0, 0.0, 0.0, 1.0, "smoothstep"),
            ),
        )

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
        participant_role: str = "SUPPORT",
    ) -> MotionProgram:
        primary = index == 0 if is_primary is None else is_primary
        if visual_duration < 0.18:
            return self._minimal(primary=primary)
        action = action.upper()
        hook = hook_kind != "NONE"
        energy = max(0.35, min(1.0, energy))
        vector = self._clamp_vector(interaction_vector, 0.20 if hook else 0.15)
        if not primary:
            return self._semantic_support(
                action=action,
                item=item,
                index=index,
                vector=vector,
                hook=hook,
                energy=energy,
                variant=variant,
                participant_role=participant_role,
            )
        if action == "REACT":
            return self._react(item, vector, hook, energy)
        if action == "CONNECT":
            return self._connect(item, vector, hook, energy, variant)
        if action == "FOCUS":
            return self._settle_focus(item, hook, energy, variant, phase)
        return super().build(
            action=action,
            item=item,
            index=index,
            count=count,
            visual_duration=visual_duration,
            interaction_vector=vector,
            phase=phase,
            hook_kind=hook_kind,
            hook_mechanism=hook_mechanism,
            energy=energy,
            tension=tension,
            variant=variant,
            is_primary=True,
        )

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
        participant_role: str = "SUPPORT",
    ) -> MotionProgram:
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
            participant_role=participant_role,
        )
        px, py = self._clamp_vector(previous_offset, 0.42 if same_asset else 0.34)
        previous_scale = max(0.62, min(1.45, previous_scale))
        hook = hook_kind != "NONE"
        arrival = 0.30 if hook else 0.38
        if not same_asset:
            arrival = 0.34 if hook else 0.42
        frames = [
            MotionKeyframe(0.0, px, py, previous_scale, "ease_in_out_cubic"),
            MotionKeyframe(arrival, 0.0, 0.0, 1.0, "ease_out_expo"),
        ]
        tail = [frame for frame in base.keyframes if frame.progress > base.settle_progress + 1e-9]
        if tail and base.settle_progress < 1.0:
            span = 1.0 - base.settle_progress
            for frame in tail:
                normalized = (frame.progress - base.settle_progress) / span
                progress = max(arrival + 0.001, min(1.0, arrival + normalized * (1.0 - arrival)))
                if progress >= 1.0 - 1e-9:
                    continue
                frames.append(MotionKeyframe(progress, frame.dx, frame.dy, frame.scale, frame.easing))
        frames.append(MotionKeyframe(1.0))
        prefix = "continuity" if same_asset else "handoff"
        return MotionProgram(
            name=f"{prefix}_then_{base.name}",
            settle_progress=arrival,
            keyframes=tuple(frames),
        )

    def _settle_focus(self, item, hook, energy, variant, phase) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, variant)
        settle = 0.34 if hook or phase in {"ACTION", "CONSEQUENCE"} else 0.40
        return MotionProgram(
            name="focus_settle_hold",
            settle_progress=settle,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(settle),
                MotionKeyframe(1.0),
            ),
        )

    def _react(self, item, vector, hook, energy) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, 1)
        vx, vy = vector if vector != (0.0, 0.0) else (self._edge_direction(item) * 0.05, 0.0)
        return MotionProgram(
            name="react_turn_response",
            settle_progress=0.34,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.34),
                MotionKeyframe(0.60, -vx * 0.18, -vy * 0.18 - 0.012, 1.055, "ease_out_back"),
                MotionKeyframe(0.80, -vx * 0.06, -vy * 0.06, 1.02, "smoothstep"),
                MotionKeyframe(1.0),
            ),
        )

    def _connect(self, item, vector, hook, energy, variant) -> MotionProgram:
        ex, ey, es = self._entry(item, hook, energy, variant)
        vx, vy = vector if vector != (0.0, 0.0) else (-self._edge_direction(item) * 0.08, 0.0)
        return MotionProgram(
            name="connect_bridge",
            settle_progress=0.32,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, es, "ease_out_expo"),
                MotionKeyframe(0.32),
                MotionKeyframe(0.58, vx * 0.30, vy * 0.30, 1.025, "ease_in_out_cubic"),
                MotionKeyframe(0.78, vx * 0.48, vy * 0.48, 1.04, "ease_out_cubic"),
                MotionKeyframe(1.0),
            ),
        )

    def _semantic_support(
        self,
        *,
        action,
        item,
        index,
        vector,
        hook,
        energy,
        variant,
        participant_role,
    ) -> MotionProgram:
        direction = self._edge_direction(item)
        ex = direction * (0.045 if hook else 0.024) * (0.8 + energy * 0.4)
        ey = (0.032 if (index + variant) % 2 else -0.024) * energy
        role = str(participant_role or "SUPPORT").upper()
        if role == "RESULT":
            return MotionProgram(
                name="result_reveal_once",
                settle_progress=0.44,
                keyframes=(
                    MotionKeyframe(0.0, ex, ey, 0.94, "ease_out_cubic"),
                    MotionKeyframe(0.44),
                    MotionKeyframe(0.72, 0.0, -0.012, 1.07, "ease_out_back"),
                    MotionKeyframe(1.0),
                ),
            )
        if role == "OBJECT" and action in {"REJECT", "BLOCK", "LOCK", "TRAVEL", "CONNECT"}:
            vx, vy = vector
            target = {
                "REJECT": (-vx * 0.12, -vy * 0.12, 1.04),
                "BLOCK": (-vx * 0.08, -vy * 0.08, 1.03),
                "LOCK": (vx * 0.08, vy * 0.08, 0.97),
                "TRAVEL": (vx * 0.10, vy * 0.10, 1.04),
                "CONNECT": (vx * 0.08, vy * 0.08, 1.03),
            }[action]
            return MotionProgram(
                name=f"object_receive_{action.lower()}",
                settle_progress=0.44,
                keyframes=(
                    MotionKeyframe(0.0, ex, ey, 0.96, "ease_out_cubic"),
                    MotionKeyframe(0.44),
                    MotionKeyframe(0.72, target[0], target[1], target[2], "ease_out_cubic"),
                    MotionKeyframe(1.0),
                ),
            )
        if role == "ACTOR" and action in {"REJECT", "BLOCK", "REACT", "RESOLVE"}:
            reaction = {
                "REJECT": (-vector[0] * 0.18, -vector[1] * 0.18, 1.07),
                "BLOCK": (-vector[0] * 0.11, -vector[1] * 0.11, 1.04),
                "REACT": (-direction * 0.018, -0.012, 1.06),
                "RESOLVE": (direction * 0.012, -0.014, 1.05),
            }[action]
            return MotionProgram(
                name=f"actor_react_once_{action.lower()}",
                settle_progress=0.46,
                keyframes=(
                    MotionKeyframe(0.0, ex, ey, 0.96, "ease_out_cubic"),
                    MotionKeyframe(0.46),
                    MotionKeyframe(0.74, reaction[0], reaction[1], reaction[2], "ease_out_back"),
                    MotionKeyframe(1.0),
                ),
            )
        return MotionProgram(
            name="support_settle_hold",
            settle_progress=0.46,
            keyframes=(
                MotionKeyframe(0.0, ex, ey, 0.97 if hook else 0.985, "ease_out_cubic"),
                MotionKeyframe(0.46),
                MotionKeyframe(1.0),
            ),
        )
