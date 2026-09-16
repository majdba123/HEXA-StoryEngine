from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models import RenderPlan, StoryBeat, TextLayoutItem, TextMotionCue, TextMotionToken


@dataclass(frozen=True, slots=True)
class TextRenderTheme:
    """Renderer-level visual tokens for sparse explainer keywords."""

    font_family: str = "Noto Kufi Arabic"
    primary: str = "&H0027261F"      # dark navy/charcoal in ASS BGR order
    accent: str = "&H00F28E20"       # HEXA-like blue
    warning: str = "&H003A3AD9"      # warm red
    outline: str = "&H00FFFFFF"
    shadow: str = "&H30000000"


class TextRenderer:
    """Render shaped RTL/LTR keyword text through libass/HarfBuzz/FriBidi.

    Text stays an independent render layer, but is burned into the same FFmpeg segment
    encode as visual assets. Multi-word cues are emitted as cumulative word stages whose
    starts come from the TextMotion token anchors. This produces storytelling-style
    word-by-word reveals without turning the layer into subtitles or inventing sync offsets.
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
            events.extend(self._cue_events(
                cue_text=cue.text,
                motion=motion,
                item=item,
                style_name=style_name,
                x=x,
                y=y,
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
        segment_start: float,
        duration: float,
    ) -> list[str]:
        del item
        visible_end = float(motion.params.get("visible_end", motion.end))
        tokens = sorted(motion.tokens, key=lambda row: (row.start, row.end))
        if not tokens:
            start = max(0.0, motion.start - segment_start)
            end = min(duration, max(start + 0.12, visible_end - segment_start))
            if end <= start or start >= duration:
                return []
            tags = self._stage_tags(
                kind=motion.kind,
                start=start,
                entrance_end=max(start + 0.05, motion.end - segment_start),
                end=end,
                x=x,
                y=y,
                first=True,
                final=True,
            )
            return [self._dialogue(start, end, style_name, tags, cue_text)]

        events: list[str] = []
        cumulative: list[str] = []
        for index, token in enumerate(tokens):
            cumulative.append(token.text)
            global_start = token.start
            global_end = tokens[index + 1].start if index + 1 < len(tokens) else visible_end
            start = max(0.0, global_start - segment_start)
            end = min(duration, global_end - segment_start)
            if end <= start + 0.035 or start >= duration:
                continue
            entrance_end = min(end, max(start + 0.05, token.end - segment_start))
            tags = self._stage_tags(
                kind=token.kind,
                start=start,
                entrance_end=entrance_end,
                end=end,
                x=x,
                y=y,
                first=index == 0,
                final=index == len(tokens) - 1,
            )
            events.append(self._dialogue(
                start,
                end,
                style_name,
                tags,
                " ".join(cumulative),
            ))
        return events

    def _stage_tags(
        self,
        *,
        kind: str,
        start: float,
        entrance_end: float,
        end: float,
        x: int,
        y: int,
        first: bool,
        final: bool,
    ) -> str:
        entrance_ms = max(90, min(220, round(max(0.05, entrance_end - start) * 1000)))
        fade_out_ms = 120 if final and end > 0.18 else 0

        if first:
            base = ["\\an5", f"\\pos({x},{y})", f"\\fad(100,{fade_out_ms})"]
        else:
            # Subsequent words are added without fading the already-visible phrase away.
            # The compact scale/vertical settle makes the newly expanded phrase feel like
            # one continuous storytelling gesture.
            base = ["\\an5", f"\\pos({x},{y})"]
            if fade_out_ms:
                base.append(f"\\fad(0,{fade_out_ms})")

        if "warning" in kind:
            base.extend(["\\fscx91\\fscy91", f"\\t(0,{entrance_ms},\\fscx104\\fscy104)",
                         f"\\t({entrance_ms},{entrance_ms + 90},\\fscx100\\fscy100)"])
        elif "number" in kind:
            base.extend(["\\fscx92\\fscy92", f"\\t(0,{entrance_ms},\\fscx102\\fscy102)",
                         f"\\t({entrance_ms},{entrance_ms + 80},\\fscx100\\fscy100)"])
        elif first:
            start_y = y + 16
            base = ["\\an5", f"\\move({x},{start_y},{x},{y},0,{entrance_ms})",
                    f"\\fad(100,{fade_out_ms})"]
        else:
            base.extend(["\\fscx95\\fscy95", f"\\t(0,{entrance_ms},\\fscx100\\fscy100)"])
        return "".join(base)

    def _document(self, plan: RenderPlan, events: list[str]) -> str:
        theme = self.theme
        styles = [
            self._style_line("Keyword", theme.primary, 68, outline=4.0, shadow=1.6),
            self._style_line("Number", theme.accent, 84, outline=4.5, shadow=1.8),
            self._style_line("Amount", theme.accent, 82, outline=4.5, shadow=1.8),
            self._style_line("WarningAmount", theme.warning, 84, outline=4.8, shadow=2.0),
            self._style_line("Warning", theme.warning, 76, outline=4.4, shadow=1.9),
            self._style_line("Emphasis", theme.accent, 72, outline=4.2, shadow=1.7),
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
            f"{self.theme.shadow},-1,0,0,0,100,100,0,0,1,{outline:.1f},{shadow:.1f},5,40,40,28,1"
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

    def _dialogue(self, start: float, end: float, style_name: str, tags: str, text: str) -> str:
        return (
            "Dialogue: 0,"
            f"{self._ass_time(start)},{self._ass_time(end)},{style_name},,0,0,0,,"
            f"{{{tags}}}{self._escape_text(text)}"
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
