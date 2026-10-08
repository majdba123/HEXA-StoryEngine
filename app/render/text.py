from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models import RenderPlan, StoryBeat, TextLayoutItem, TextMotionCue
from app.text.metrics import PRODUCTION_FONT_DIR, PRODUCTION_FONT_FAMILY, TEXT_SHADOW_PX, TextTypographyMetrics


_RLI = "\u2067"
_PDI = "\u2069"


@dataclass(frozen=True, slots=True)
class TextRenderTheme:
    """Premium high-contrast tokens for sparse keyword storytelling."""

    font_family: str = PRODUCTION_FONT_FAMILY
    primary: str = "&H00FFFFFF"       # white fill
    accent: str = "&H00FFFFFF"
    gold: str = "&H00FFFFFF"
    warning: str = "&H00FFFFFF"
    light_outline: str = "&H00000000" # black outline
    dark_outline: str = "&H00000000"  # black outline
    shadow: str = "&H36000000"        # restrained black shadow


class TextRenderer:
    """Render stable Arabic keyword motion through libass/HarfBuzz/FriBidi.

    Inline ASS override spans split the Unicode bidi run and can temporarily reorder
    Arabic words while they reveal. Instead, each reveal state is a complete logical
    phrase shaped by libass as one bidi run. Every state uses a fixed edge anchor, so the
    line grows into its final footprint without re-centering or reversing earlier words.
    """

    def __init__(self) -> None:
        # Vendored production faces only: the same files are measured during planning and
        # handed to libass, so no machine-local substitute can change the typography.
        self.theme = TextRenderTheme()
        self.metrics = TextTypographyMetrics()

    def write_beat_ass(
        self,
        plan: RenderPlan,
        beat: StoryBeat,
        *,
        segment_start: float,
        duration: float,
        output: Path,
    ) -> Path | None:
        events = self._events_for_beat(
            plan,
            beat,
            segment_start=segment_start,
            duration=duration,
        )
        if not events:
            return None
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self._document(plan, events), encoding="utf-8")
        return output

    def write_timeline_ass(self, plan: RenderPlan, output: Path) -> Path | None:
        events: list[str] = []
        for beat in sorted(plan.story, key=lambda row: (row.start, row.end, row.id)):
            events.extend(self._events_for_beat(
                plan,
                beat,
                segment_start=0.0,
                duration=plan.duration,
            ))
        if not events:
            return None
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self._document(plan, events), encoding="utf-8")
        return output

    def _events_for_beat(
        self,
        plan: RenderPlan,
        beat: StoryBeat,
        *,
        segment_start: float,
        duration: float,
    ) -> list[str]:
        cue_by_id = {cue.id: cue for cue in plan.text.cues if cue.beat_id == beat.id}
        style_by_id = {style.id: style for style in plan.text.styles}
        layout_beat = next((row for row in plan.text_composition if row.beat_id == beat.id), None)
        if layout_beat is None:
            return []
        motion_by_id = {
            cue.text_cue_id: cue
            for cue in plan.text_motion
            if cue.beat_id == beat.id
        }

        events: list[str] = []
        for item in sorted(layout_beat.items, key=lambda row: row.z):
            cue = cue_by_id.get(item.text_cue_id)
            motion = motion_by_id.get(item.text_cue_id)
            if cue is None or motion is None:
                continue
            style = style_by_id.get(cue.style_id)
            style_name = self._ass_style_name(style.id if style else cue.semantic_type)
            rtl = self._contains_arabic(cue.text)
            projection = plan.projection
            geometry_plan = plan
            geometry_item = item
            if projection is not None:
                geometry_plan = plan.model_copy(update={
                    "width": projection.reference_width,
                    "height": projection.reference_height,
                    "projection": None,
                })
                geometry_item = item.model_copy(update={
                    "x": (item.x * plan.width - projection.offset_x)
                         / (projection.reference_width * projection.scale),
                    "y": (item.y * plan.height - projection.offset_y)
                         / (projection.reference_height * projection.scale),
                    "max_width": item.max_width * plan.width
                                 / (projection.reference_width * projection.scale),
                })
            style_id = style.id if style else cue.style_id
            face = self.metrics.face_for(cue.text)
            if face is None:
                # Never let libass substitute an OS font (render handoff fails closed first).
                continue
            face_tags = ""
            if face.family != self.theme.font_family:
                base_size = self.metrics.style_spec(style_id, cue.semantic_type)[0]
                pixel = projection.scale if projection else 1.0
                size = max(1, round(self.metrics.font_size(face, base_size) * pixel))
                face_tags = f"\\fn{face.family}\\fs{size}"
            edge_x, ink_center_y, safe_scale = self._safe_text_geometry(
                plan=geometry_plan,
                cue_text=cue.text,
                semantic_type=cue.semantic_type,
                style_id=style_id,
                item=geometry_item,
                rtl=rtl,
                entry_strength=float(motion.params.get("entry_strength", 0.0)),
            )

            def anchor(
                state_text: str,
                *,
                edge_x: float = edge_x,
                ink_center_y: float = ink_center_y,
                scale: float = safe_scale,
                semantic_type: str = cue.semantic_type,
                style_id: str = style_id,
                rtl: bool = rtl,
            ) -> tuple[int, int]:
                # Left-anchored (an4) lines place shaped ink exactly where HarfBuzz
                # does, so each reveal state is positioned from its own measurement and
                # the reading-start edge (right for RTL) never moves between states.
                layout = self.metrics.layout(
                    state_text, style_id=style_id, semantic_type=semantic_type,
                    font_scale=scale,
                )
                x = edge_x - (layout.ink_right if rtl else layout.ink_left)
                y = ink_center_y - (layout.ink_top + layout.ink_bottom) / 2.0
                if projection is not None:
                    x = projection.offset_x + x * projection.scale
                    y = projection.offset_y + y * projection.scale
                return round(x), round(y)

            events.extend(self._cue_events(
                cue_text=cue.text,
                motion=motion,
                item=item,
                style_name=style_name,
                anchor=anchor,
                face_tags=face_tags,
                rtl=rtl,
                font_scale=safe_scale,
                pixel_scale=projection.scale if projection else 1.0,
                segment_start=segment_start,
                duration=duration,
            ))
        return events

    def _cue_events(
        self,
        *,
        cue_text: str,
        motion: TextMotionCue,
        item: TextLayoutItem,
        style_name: str,
        anchor,
        rtl: bool,
        face_tags: str = "",
        font_scale: float,
        pixel_scale: float = 1.0,
        segment_start: float,
        duration: float,
    ) -> list[str]:
        font_scale = max(0.40, min(1.0, float(font_scale)))
        visible_end = float(motion.params.get("visible_end", motion.end))
        event_global_start = max(motion.start, segment_start)
        local_end = min(duration, visible_end - segment_start)
        if local_end <= 0.06 or event_global_start >= segment_start + duration:
            return []

        tokens = sorted(motion.tokens, key=lambda row: (row.start, row.end))
        if not tokens:
            start = max(0.0, event_global_start - segment_start)
            if local_end <= start + 0.04:
                return []
            x, y = anchor(cue_text)
            tags = self._line_tags(
                x=x,
                y=y,
                rtl=rtl,
                first=True,
                font_scale=font_scale,
                pixel_scale=pixel_scale,
                entry_strength=float(motion.params.get("entry_strength", 0.0)),
                entry_duration_ms=int(motion.params.get("entry_duration_ms", 165)),
                face_tags=face_tags,
            )
            return [self._dialogue(start, local_end, style_name, tags, self._directional_text(cue_text, rtl))]

        events: list[str] = []
        for index, token in enumerate(tokens):
            state_global_start = max(event_global_start, token.start)
            if state_global_start >= visible_end:
                continue
            next_start = tokens[index + 1].start if index + 1 < len(tokens) else visible_end
            state_global_end = min(visible_end, max(state_global_start + 0.04, next_start))
            start = max(0.0, state_global_start - segment_start)
            end = min(duration, state_global_end - segment_start)
            if end <= start + 0.02 or start >= duration:
                continue

            # Full logical phrase prefix -> one FriBidi/HarfBuzz shaping run. No inline
            # alpha tags are inserted between Arabic tokens, which eliminates temporary
            # reverse ordering during reveal.
            state_text = " ".join(row.text for row in tokens[: index + 1]).strip()
            if not state_text:
                continue
            x, y = anchor(state_text)
            tags = self._line_tags(
                x=x,
                y=y,
                rtl=rtl,
                first=index == 0,
                font_scale=font_scale,
                pixel_scale=pixel_scale,
                entry_strength=float(motion.params.get("entry_strength", 0.0)),
                entry_duration_ms=int(motion.params.get("entry_duration_ms", 165)),
                face_tags=face_tags,
            )
            events.append(self._dialogue(
                start,
                end,
                style_name,
                tags,
                self._directional_text(state_text, rtl),
            ))
        return events

    def _safe_text_geometry(
        self,
        *,
        plan: RenderPlan,
        cue_text: str,
        semantic_type: str,
        style_id: str,
        item: TextLayoutItem,
        rtl: bool,
        entry_strength: float,
    ) -> tuple[float, float, float]:
        """Place the shaped ink, including its entry path, inside the planned text box.

        Returns the resting ink's reading-start edge (right edge for RTL, left for LTR),
        its vertical centre, and the font scale.

        TextComposition reserves a box of ink plus entry excursion. The line is anchored
        on its reading-start edge (right for RTL) so progressive reveal never re-centers,
        and the whole ``\\move`` path - not only the resting frame - stays in that box.
        The title-safe clamp remains the last guard; it may nudge or shrink text but
        never moves Final Package artwork.
        """
        width = max(1, int(plan.width))
        height = max(1, int(plan.height))
        margin_x = width * 0.045
        margin_y = height * 0.055
        strength = max(0.0, min(1.0, float(entry_strength)))
        entry_x = 14.0 + round(10.0 * strength)
        entry_y = 10.0 + round(5.0 * strength)
        scale = max(0.40, min(1.0, float(item.font_scale)))
        available_width = max(1.0, width - margin_x * 2.0 - entry_x)

        def layout_at(value: float):
            return self.metrics.layout(
                cue_text, style_id=style_id, semantic_type=semantic_type, font_scale=value,
            )

        layout = layout_at(scale)
        for _ in range(3):
            if layout is None or layout.width <= available_width + 0.5:
                break
            scale = max(0.40, scale * available_width / max(1.0, layout.width) * 0.985)
            layout = layout_at(scale)
        if layout is None:
            return width * item.x, height * item.y, scale

        # Vertical: centre the resting ink plus the downward entry offset on the box.
        path_height = layout.height + entry_y
        top = height * item.y - path_height / 2.0
        top = max(margin_y, min(height - margin_y - path_height, top))
        ink_center_y = top + layout.height / 2.0

        # Horizontal: the entry starts outward of the reading-start edge by ``entry_x``.
        box_left = width * (item.x - item.max_width / 2.0)
        box_right = width * (item.x + item.max_width / 2.0)
        if rtl:
            edge_x = box_right - entry_x
            edge_x = max(margin_x + layout.width, min(width - margin_x - entry_x, edge_x))
        else:
            edge_x = box_left + entry_x
            edge_x = max(margin_x + entry_x, min(width - margin_x - layout.width, edge_x))
        return edge_x, ink_center_y, scale

    @staticmethod
    def _line_tags(
        *,
        x: int,
        y: int,
        rtl: bool,
        first: bool,
        font_scale: float = 1.0,
        pixel_scale: float = 1.0,
        entry_strength: float = 0.0,
        entry_duration_ms: int = 165,
        face_tags: str = "",
    ) -> str:
        alignment = 4  # middle-left: ink lands exactly where the shared measurement puts it
        scale = max(40, min(100, round(font_scale * 100)))
        size_tag = f"\\fscx{scale}\\fscy{scale}"
        if first:
            # One bounded entry gesture for the phrase. Semantic focus may make the
            # gesture more decisive, but the final anchor/font/style stay unchanged and
            # there is never a post-arrival bounce.
            strength = max(0.0, min(1.0, float(entry_strength)))
            horizontal = round((14 + round(10 * strength)) * pixel_scale)
            vertical = round((10 + round(5 * strength)) * pixel_scale)
            direction = horizontal if rtl else -horizontal
            duration = max(130, min(240, int(entry_duration_ms)))
            fade = max(45, min(65, round(65 - 15 * strength)))
            return (
                f"\\an{alignment}{face_tags}{size_tag}\\move("
                f"{x + direction},{y + vertical},{x},{y},0,{duration})"
                f"\\fad({fade},0)\\blur{0.35 if pixel_scale == 1.0 else round(0.35 * pixel_scale, 3)}"
            )
        blur = 0.25 if pixel_scale == 1.0 else round(0.25 * pixel_scale, 3)
        return f"\\an{alignment}{face_tags}{size_tag}\\pos({x},{y})\\blur{blur}"

    def _document(self, plan: RenderPlan, events: list[str]) -> str:
        theme = self.theme
        pixel_scale = plan.projection.scale if plan.projection else 1.0
        def style(name: str, color: str, size: int, outline: float) -> str:
            return self._style_line(
                name, color, max(1, round(size * pixel_scale)),
                outline_color=theme.dark_outline,
                outline=outline * pixel_scale,
                shadow=TEXT_SHADOW_PX * pixel_scale,
            )
        styles = [
            style("Keyword", theme.primary, 158, 8.0),
            style("Number", theme.gold, 188, 9.5),
            style("Amount", theme.accent, 188, 9.5),
            style("WarningAmount", theme.warning, 194, 9.8),
            style("Warning", theme.warning, 188, 9.5),
            style("Emphasis", theme.accent, 178, 9.0),
        ]
        return "\n".join([
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {plan.width}",
            f"PlayResY: {plan.height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding",
            *styles,
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
            *events,
            "",
        ])

    def _style_line(
        self,
        name: str,
        color: str,
        size: int,
        *,
        outline_color: str,
        outline: float,
        shadow: float,
    ) -> str:
        return (
            f"Style: {name},{self.theme.font_family},{size},{color},{color},{outline_color},"
            f"{self.theme.shadow},-1,0,0,0,100,100,0,0,1,{outline:.1f},{shadow:.1f},5,50,50,34,1"
        )

    @staticmethod
    def _ass_style_name(style_id: str) -> str:
        return {
            "number": "Number",
            "amount": "Amount",
            "warning_amount": "WarningAmount",
            "warning": "Warning",
            "emphasis": "Emphasis",
        }.get(style_id, "Keyword")

    @staticmethod
    def _contains_arabic(value: str) -> bool:
        return any(
            "\u0600" <= char <= "\u06ff"
            or "\u0750" <= char <= "\u077f"
            or "\u08a0" <= char <= "\u08ff"
            for char in value
        )

    @staticmethod
    def _directional_text(value: str, rtl: bool) -> str:
        # RLI/PDI are standard Unicode bidi isolates supported by FriBidi. They keep
        # mixed Arabic + Western digits inside one stable RTL paragraph without manual
        # character reversal or language-specific hacks.
        return f"{_RLI}{value}{_PDI}" if rtl else value

    def _dialogue(self, start: float, end: float, style_name: str, tags: str, text: str) -> str:
        return self._dialogue_raw(start, end, style_name, tags, self._escape_text(text))

    @staticmethod
    def _dialogue_raw(start: float, end: float, style_name: str, tags: str, text: str) -> str:
        return (
            "Dialogue: 0,"
            f"{TextRenderer._ass_time(start)},{TextRenderer._ass_time(end)},{style_name},,0,0,0,,"
            f"{{{tags}}}{text}"
        )

    @staticmethod
    def _escape_text(value: str) -> str:
        return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")

    @staticmethod
    def _ass_time(value: float) -> str:
        centiseconds = max(0, round(value * 100))
        hours, rem = divmod(centiseconds, 360000)
        minutes, rem = divmod(rem, 6000)
        seconds, cs = divmod(rem, 100)
        return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"

    @staticmethod
    def ass_filter(path: Path, input_label: str, output_label: str) -> str:
        def escape(value: Path) -> str:
            return str(value.resolve()).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")

        return (
            f"[{input_label}]ass=filename='{escape(path)}'"
            f":fontsdir='{escape(PRODUCTION_FONT_DIR)}'[{output_label}]"
        )
