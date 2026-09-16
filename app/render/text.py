from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models import RenderPlan, StoryBeat, TextLayoutItem, TextMotionCue


@dataclass(frozen=True, slots=True)
class TextRenderTheme:
    """Renderer-level visual tokens for sparse Arabic explainer keywords."""

    font_family: str = "Noto Kufi Arabic"
    primary: str = "&H0027261F"      # dark navy/charcoal in ASS BGR order
    accent: str = "&H00F28E20"       # HEXA-like blue
    warning: str = "&H003A3AD9"      # warm red
    outline: str = "&H00FFFFFF"
    shadow: str = "&H30000000"


class TextRenderer:
    """Generate libass overlays for shaped RTL text without rasterizing text in Python.

    libass delegates shaping/bidi to HarfBuzz/FriBidi when available in FFmpeg, which is
    substantially safer for Arabic than hand-reversing strings or per-glyph placement.
    The produced ASS script is deterministic and can be burned into the same FFmpeg encode
    used for visual assets, avoiding an additional video generation pass.
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
            start = max(0.0, motion.start - segment_start)
            visible_end = float(motion.params.get("visible_end", cue.spoken_end))
            end = min(duration, max(start + 0.12, visible_end - segment_start))
            if end <= 0 or start >= duration:
                continue
            start = max(0.0, start)
            end = min(duration, end)
            if end <= start:
                continue
            x = round(plan.width * item.x)
            y = round(plan.height * item.y)
            tags = self._motion_tags(motion, item, start=start, end=end, x=x, y=y)
            text = self._escape_text(cue.text)
            events.append(
                "Dialogue: 0,"
                f"{self._ass_time(start)},{self._ass_time(end)},{style_name},,0,0,0,,"
                f"{{{tags}}}{text}"
            )
        return events

    def _motion_tags(
        self,
        motion: TextMotionCue,
        item: TextLayoutItem,
        *,
        start: float,
        end: float,
        x: int,
        y: int,
    ) -> str:
        del item
        entrance_ms = max(80, min(260, round(max(0.05, motion.end - motion.start) * 1000)))
        fade_out_ms = max(80, min(180, round(max(0.08, end - start) * 120)))
        base = ["\\an5", f"\\pos({x},{y})", f"\\fad({min(140, entrance_ms)},{fade_out_ms})"]

        if motion.kind == "text_number_in":
            base.extend(["\\fscx92\\fscy92", f"\\t(0,{entrance_ms},\\fscx100\\fscy100)"])
        elif motion.kind == "text_warning_in":
            base.extend(["\\fscx90\\fscy90", f"\\t(0,{entrance_ms},\\fscx104\\fscy104)",
                         f"\\t({entrance_ms},{entrance_ms + 110},\\fscx100\\fscy100)"])
        elif motion.kind == "text_emphasis_in":
            base.extend(["\\fscx94\\fscy94", f"\\t(0,{entrance_ms},\\fscx100\\fscy100)"])
        else:
            # A restrained vertical settle keeps keywords alive without competing with imagery.
            start_y = y + 14
            base = ["\\an5", f"\\move({x},{start_y},{x},{y},0,{entrance_ms})",
                    f"\\fad({min(140, entrance_ms)},{fade_out_ms})"]
        return "".join(base)

    def _document(self, plan: RenderPlan, events: list[str]) -> str:
        theme = self.theme
        styles = [
            self._style_line("Keyword", theme.primary, 50, outline=3.2, shadow=1.6),
            self._style_line("Number", theme.accent, 62, outline=3.6, shadow=1.8),
            self._style_line("Amount", theme.accent, 62, outline=3.6, shadow=1.8),
            self._style_line("WarningAmount", theme.warning, 62, outline=3.8, shadow=1.9),
            self._style_line("Emphasis", theme.primary, 54, outline=3.4, shadow=1.7),
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
            "emphasis": "Emphasis",
        }.get(style_id, "Keyword")

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
