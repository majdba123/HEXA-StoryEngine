from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models import RenderPlan, StoryBeat, TextLayoutItem, TextMotionCue


@dataclass(frozen=True, slots=True)
class TextRenderTheme:
    """High-contrast explainer-title tokens for sparse keyword storytelling."""

    font_family: str = "Noto Kufi Arabic"
    primary: str = "&H00452B16"      # dark navy, ASS AABBGGRR
    accent: str = "&H00EB6E0A"       # saturated HEXA-style blue
    gold: str = "&H001AA4F2"         # warm gold for numbers
    warning: str = "&H003F4BE3"      # warm red
    outline: str = "&H00FFFFFF"       # white separation from detailed artwork
    shadow: str = "&H500D1826"        # translucent navy depth


class TextRenderer:
    """Render shaped RTL/LTR sparse keywords through libass/HarfBuzz/FriBidi.

    A multi-word cue is one stable ASS line, not a sequence of recentered subtitle
    fragments. Future words are laid out invisibly from the cue's first frame and each
    word reveals at its exact forced-alignment timestamp. This keeps the final phrase
    geometry stable while producing authored word-by-word storytelling motion.
    """

    def __init__(self, *, font_family: str = "Noto Kufi Arabic") -> None:
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
            x = round(plan.width * item.x)
            y = round(plan.height * item.y)
            event = self._cue_event(
                cue_text=cue.text,
                motion=motion,
                item=item,
                style_name=style_name,
                x=x,
                y=y,
                segment_start=segment_start,
                duration=duration,
            )
            if event is not None:
                events.append(event)
        return events

    def _cue_event(
        self,
        *,
        cue_text: str,
        motion: TextMotionCue,
        item: TextLayoutItem,
        style_name: str,
        x: int,
        y: int,
        segment_start: float,
        duration: float,
    ) -> str | None:
        del item
        visible_end = float(motion.params.get("visible_end", motion.end))
        event_global_start = max(motion.start, segment_start)
        start = max(0.0, event_global_start - segment_start)
        end = min(duration, visible_end - segment_start)
        if end <= start + 0.06 or start >= duration:
            return None

        tokens = sorted(motion.tokens, key=lambda row: (row.start, row.end))
        entrance_ms = max(120, min(220, round((motion.end - motion.start) * 1000)))
        start_y = y + (18 if "warning" not in motion.kind else 12)
        line_tags = (
            f"\\an5\\move({x},{start_y},{x},{y},0,{entrance_ms})"
            "\\fad(75,140)"
        )

        if not tokens:
            return self._dialogue(start, end, style_name, line_tags, cue_text)

        base_color = self._style_color(style_name)
        token_fragments: list[str] = []
        for index, token in enumerate(tokens):
            rel_start_ms = max(0, round((token.start - event_global_start) * 1000))
            settle_ms = max(
                rel_start_ms + 90,
                min(rel_start_ms + 230, round((token.end - event_global_start) * 1000)),
            )
            # Every token reserves its final layout space from frame one but remains
            # invisible until its real spoken timestamp. Blur + alpha + colour settle
            # creates motion without changing glyph metrics, so earlier words never jump.
            initial_color = self._token_flash_color(token.kind, base_color, index)
            tags = (
                f"\\1c{initial_color}\\alpha&HFF&\\blur3.8"
                f"\\t({rel_start_ms},{settle_ms},\\1c{base_color}\\alpha&H00&\\blur0.25)"
            )
            token_fragments.append(f"{{{tags}}}{self._escape_text(token.text)}")

        # If a transformed display phrase has no one-to-one token text, fall back to the
        # canonical cue text rather than producing a malformed line. Current semantic
        # planning preserves token display provenance, so this is a defensive guard.
        text = " ".join(token_fragments) if token_fragments else self._escape_text(cue_text)
        return self._dialogue_raw(start, end, style_name, line_tags, text)

    def _document(self, plan: RenderPlan, events: list[str]) -> str:
        theme = self.theme
        styles = [
            self._style_line("Keyword", theme.primary, 88, outline=5.2, shadow=2.2),
            self._style_line("Number", theme.gold, 116, outline=6.2, shadow=2.8),
            self._style_line("Amount", theme.accent, 108, outline=5.8, shadow=2.6),
            self._style_line("WarningAmount", theme.warning, 114, outline=6.2, shadow=2.9),
            self._style_line("Warning", theme.warning, 104, outline=5.9, shadow=2.7),
            self._style_line("Emphasis", theme.accent, 98, outline=5.6, shadow=2.5),
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

    def _style_line(self, name: str, color: str, size: int, *, outline: float, shadow: float) -> str:
        return (
            f"Style: {name},{self.theme.font_family},{size},{color},{color},{self.theme.outline},"
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

    def _style_color(self, style_name: str) -> str:
        return {
            "Number": self.theme.gold,
            "Amount": self.theme.accent,
            "WarningAmount": self.theme.warning,
            "Warning": self.theme.warning,
            "Emphasis": self.theme.accent,
        }.get(style_name, self.theme.primary)

    def _token_flash_color(self, kind: str, base_color: str, index: int) -> str:
        # A brief role-aware colour arrival gives each word a visual beat without scale
        # changes that would disturb Arabic shaping or re-center the phrase.
        if "warning" in kind:
            return self.theme.gold if index == 0 else self.theme.warning
        if "number" in kind:
            return self.theme.gold
        if index == 0:
            return self.theme.accent
        return base_color

    def _dialogue(self, start: float, end: float, style_name: str, tags: str, text: str) -> str:
        return self._dialogue_raw(start, end, style_name, tags, self._escape_text(text))

    def _dialogue_raw(self, start: float, end: float, style_name: str, tags: str, text: str) -> str:
        return (
            "Dialogue: 0,"
            f"{self._ass_time(start)},{self._ass_time(end)},{style_name},,0,0,0,,"
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
