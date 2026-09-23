from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models import RenderPlan, StoryBeat, TextLayoutItem, TextMotionCue


_RLI = "\u2067"
_PDI = "\u2069"


@dataclass(frozen=True, slots=True)
class TextRenderTheme:
    """Premium high-contrast tokens for sparse keyword storytelling."""

    font_family: str = "Noto Kufi Arabic Extra Bold"
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

    def __init__(self, *, font_family: str = "Noto Kufi Arabic Extra Bold") -> None:
        self.theme = TextRenderTheme(font_family=font_family)

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
            y = round(plan.height * item.y)
            rtl = self._contains_arabic(cue.text)
            if rtl:
                # Right-edge anchoring makes cumulative Arabic phrases expand leftward
                # while keeping the final lane fixed. This is stable for mixed numbers.
                x = round(plan.width * min(0.97, item.x + item.max_width / 2))
            else:
                x = round(plan.width * max(0.03, item.x - item.max_width / 2))
            events.extend(self._cue_events(
                cue_text=cue.text,
                motion=motion,
                item=item,
                style_name=style_name,
                x=x,
                y=y,
                rtl=rtl,
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
        x: int,
        y: int,
        rtl: bool,
        segment_start: float,
        duration: float,
    ) -> list[str]:
        font_scale = max(0.55, min(1.0, float(item.font_scale)))
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
            tags = self._line_tags(x=x, y=y, rtl=rtl, first=True, font_scale=font_scale)
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
            tags = self._line_tags(x=x, y=y, rtl=rtl, first=index == 0, font_scale=font_scale)
            events.append(self._dialogue(
                start,
                end,
                style_name,
                tags,
                self._directional_text(state_text, rtl),
            ))
        return events

    @staticmethod
    def _line_tags(*, x: int, y: int, rtl: bool, first: bool, font_scale: float = 1.0) -> str:
        alignment = 6 if rtl else 4  # middle-right for RTL, middle-left for LTR
        scale = max(55, min(100, round(font_scale * 100)))
        size_tag = f"\\fscx{scale}\\fscy{scale}"
        if first:
            # One restrained entry gesture for the phrase. Later word states hold the
            # exact anchor so the line does not bounce or re-center.
            direction = 14 if rtl else -14
            return (
                f"\\an{alignment}{size_tag}\\move({x + direction},{y + 10},{x},{y},0,165)"
                "\\fad(65,0)\\blur0.35"
            )
        return f"\\an{alignment}{size_tag}\\pos({x},{y})\\blur0.25"

    def _document(self, plan: RenderPlan, events: list[str]) -> str:
        theme = self.theme
        styles = [
            self._style_line(
                "Keyword", theme.primary, 158, outline_color=theme.dark_outline,
                outline=8.0, shadow=1.2,
            ),
            self._style_line(
                "Number", theme.gold, 188, outline_color=theme.dark_outline,
                outline=9.5, shadow=1.2,
            ),
            self._style_line(
                "Amount", theme.accent, 188, outline_color=theme.dark_outline,
                outline=9.5, shadow=1.2,
            ),
            self._style_line(
                "WarningAmount", theme.warning, 194, outline_color=theme.dark_outline,
                outline=9.8, shadow=1.2,
            ),
            self._style_line(
                "Warning", theme.warning, 188, outline_color=theme.dark_outline,
                outline=9.5, shadow=1.2,
            ),
            self._style_line(
                "Emphasis", theme.accent, 178, outline_color=theme.dark_outline,
                outline=9.0, shadow=1.2,
            ),
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
        escaped = str(path.resolve()).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")
        return f"[{input_label}]ass=filename='{escaped}'[{output_label}]"
