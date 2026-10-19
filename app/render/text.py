from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.models import RenderPlan, StoryBeat, TextCue, TextLayoutItem, TextMotionCue
from app.render.connection import LabelAnchor
from app.text.metrics import (
    MAX_FONT_SCALE,
    MIN_FONT_SCALE,
    PRODUCTION_FONT_DIR,
    PRODUCTION_FONT_FAMILY,
    TEXT_SHADOW_PX,
    TextTypographyMetrics,
    _bidi_runs,
)


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
    shadow: str = "&H70000000"        # soft grey drop shadow (reference keyword style)


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
        include: Callable[[TextCue], bool] | None = None,
    ) -> Path | None:
        events = self._events_for_beat(
            plan,
            beat,
            segment_start=segment_start,
            duration=duration,
            include=include,
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
        include: Callable[[TextCue], bool] | None = None,
    ) -> list[str]:
        cue_by_id = {
            cue.id: cue for cue in plan.text.cues
            if cue.beat_id == beat.id and (include is None or include(cue))
        }
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
                face=face,
            ) -> tuple[int, int]:
                # Left-anchored (an4) lines place shaped ink exactly where HarfBuzz
                # does, so each reveal state is positioned from its own measurement and
                # the reading-start edge (right for RTL) never moves between states.
                layout = self.metrics.layout(
                    state_text, style_id=style_id, semantic_type=semantic_type,
                    font_scale=scale, rtl=rtl, face=face,
                )
                x = edge_x - (layout.ink_right if rtl else layout.ink_left)
                y = ink_center_y - (layout.ink_top + layout.ink_bottom) / 2.0
                if projection is not None:
                    x = projection.offset_x + x * projection.scale
                    y = projection.offset_y + y * projection.scale
                return round(x), round(y)

            def ink_span(
                state_text: str,
                *,
                anchor=anchor,
                scale: float = safe_scale,
                semantic_type: str = cue.semantic_type,
                style_id: str = style_id,
                rtl: bool = rtl,
                face=face,
            ) -> tuple[float, float]:
                """Left/right ink edge (output pixels) of a reveal state drawn at its anchor."""
                layout = self.metrics.layout(
                    state_text, style_id=style_id, semantic_type=semantic_type,
                    font_scale=scale, rtl=rtl, face=face,
                )
                x, _y = anchor(state_text)
                pixel = projection.scale if projection is not None else 1.0
                return x + layout.ink_left * pixel, x + layout.ink_right * pixel

            events.extend(self._cue_events(
                cue_text=cue.text,
                motion=motion,
                item=item,
                style_name=style_name,
                anchor=anchor,
                ink_span=ink_span,
                canvas=(plan.width, plan.height),
                face_tags=face_tags,
                rtl=rtl,
                font_scale=safe_scale,
                pixel_scale=projection.scale if projection else 1.0,
                segment_start=segment_start,
                duration=duration,
                frame=1.0 / max(1, int(plan.fps)),
            ))
        return events

    def label_anchors(self, plan: RenderPlan, beat: StoryBeat) -> list[LabelAnchor]:
        """Resting ink box (output pixels) and visible window of every placed keyword that
        names an asset: the same geometry ``_events_for_beat`` draws (G17 label arrows)."""
        layout_beat = next((row for row in plan.text_composition if row.beat_id == beat.id), None)
        if layout_beat is None:
            return []
        cues = {cue.id: cue for cue in plan.text.cues if cue.beat_id == beat.id}
        motions = {cue.text_cue_id: cue for cue in plan.text_motion if cue.beat_id == beat.id}
        styles = {style.id: style for style in plan.text.styles}
        projection = plan.projection
        anchors: list[LabelAnchor] = []
        for item in layout_beat.items:
            cue, motion = cues.get(item.text_cue_id), motions.get(item.text_cue_id)
            if cue is None or motion is None or not item.anchor_asset_id:
                continue
            face = self.metrics.face_for(cue.text)
            if face is None:
                continue
            style = styles.get(cue.style_id)
            style_id = style.id if style else cue.style_id
            rtl = self._contains_arabic(cue.text)
            geometry_plan, geometry_item = plan, item
            if projection is not None:
                geometry_plan = plan.model_copy(update={
                    "width": projection.reference_width, "height": projection.reference_height,
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
            edge_x, ink_center_y, scale = self._safe_text_geometry(
                plan=geometry_plan, cue_text=cue.text, semantic_type=cue.semantic_type,
                style_id=style_id, item=geometry_item, rtl=rtl,
                entry_strength=float(motion.params.get("entry_strength", 0.0)),
            )
            layout = self.metrics.layout(cue.text, style_id=style_id, semantic_type=cue.semantic_type,
                                         font_scale=scale, rtl=rtl, face=face)
            if layout is None:
                continue
            left = edge_x - layout.width if rtl else edge_x
            box = (left, ink_center_y - layout.height / 2.0,
                   left + layout.width, ink_center_y + layout.height / 2.0)
            if projection is not None:
                box = tuple(
                    (projection.offset_x if index % 2 == 0 else projection.offset_y) + value * projection.scale
                    for index, value in enumerate(box)
                )
            anchors.append(LabelAnchor(
                asset_id=item.anchor_asset_id, box=box, start=float(motion.start),
                end=float(motion.params.get("visible_end", motion.end)),
            ))
        return anchors

    def _cue_events(
        self,
        *,
        cue_text: str,
        motion: TextMotionCue,
        item: TextLayoutItem,
        style_name: str,
        anchor,
        rtl: bool,
        ink_span=None,
        canvas: tuple[int, int],
        face_tags: str = "",
        font_scale: float,
        pixel_scale: float = 1.0,
        segment_start: float,
        duration: float,
        frame: float = 1.0 / 30.0,
    ) -> list[str]:
        font_scale = max(MIN_FONT_SCALE, min(MAX_FONT_SCALE, float(font_scale)))
        params = motion.params
        visible_end = float(params.get("visible_end", motion.end))
        event_global_start = max(motion.start, segment_start)
        local_end = min(duration, visible_end - segment_start)
        if local_end <= 0.06 or event_global_start >= segment_start + duration:
            return []
        entry_strength = float(params.get("entry_strength", 0.0))
        entry_ms = int(params.get("entry_duration_ms", 165))
        # Appearance and disappearance are planned by Text Motion; plans without these
        # fields keep the earlier entry fade and a cut at visible_end.
        planned_entry_fade = params.get("entry_fade_ms")
        entry_fade_ms = None if planned_entry_fade is None else int(planned_entry_fade)
        word_fade = max(0.0, float(params.get("word_fade_ms", 0))) / 1000.0
        exit_fade = max(0.0, float(params.get("exit_fade_ms", 0))) / 1000.0

        def tags_for(x: int, y: int, *, first: bool, elapsed: float | None, fade_in_ms=None,
                     fade_out: float = 0.0, clip: str = "") -> str:
            return self._line_tags(
                x=x, y=y, rtl=rtl, first=first, font_scale=font_scale, pixel_scale=pixel_scale,
                entry_strength=entry_strength, entry_duration_ms=entry_ms, face_tags=face_tags,
                entry_elapsed_ms=None if elapsed is None else max(0, round(elapsed * 1000)),
                fade_in_ms=fade_in_ms, fade_out_ms=round(fade_out * 1000), clip=clip,
            )

        tokens = list(motion.tokens)
        if not tokens:
            start = max(0.0, event_global_start - segment_start)
            if local_end <= start + 0.04:
                return []
            x, y = anchor(cue_text)
            tags = tags_for(x, y, first=True, elapsed=0.0, fade_in_ms=entry_fade_ms,
                            fade_out=min(exit_fade, (local_end - start) / 2.0))
            return [self._dialogue(start, local_end, style_name, tags, self._directional_text(cue_text, rtl))]

        # Reveal states follow the planned reading order (Text Motion keeps the cue's
        # logical word order); they are never re-sorted by time, which shaped tied words
        # in the wrong order. Words that begin within one frame of each other appear
        # together as one state: a shorter state cannot be seen and would overlap the next.
        states: list[tuple[float, int]] = []  # (state start, number of words shown)
        for index, token in enumerate(tokens):
            state_start = max(float(token.start), states[-1][0] if states else float("-inf"))
            if states and state_start - states[-1][0] < frame - 1e-9:
                states[-1] = (states[-1][0], index + 1)
            else:
                states.append((state_start, index + 1))

        windows: list[tuple[float, float, int, int]] = []  # (local start, local end, words, state)
        for index, (state_start, words) in enumerate(states):
            state_global_start = max(event_global_start, state_start)
            if state_global_start >= visible_end:
                continue
            next_start = states[index + 1][0] if index + 1 < len(states) else visible_end
            state_global_end = min(visible_end, next_start)
            start = max(0.0, state_global_start - segment_start)
            end = min(duration, state_global_end - segment_start)
            if end <= start + 0.02 or start >= duration:
                continue
            windows.append((start, end, words, index))
        if not windows:
            return []

        # The entry gesture starts with the first state; later states inside it continue it.
        origin = windows[0][0] if windows[0][3] == 0 else None
        gesture_dx, _gesture_dy, gesture_ms = self._entry_gesture(
            rtl=rtl, pixel_scale=pixel_scale, entry_strength=entry_strength, entry_duration_ms=entry_ms,
        )
        # A new word fades in only where adding it moves no earlier word: one bidi
        # direction for the whole line (mixed runs may reorder, so they stay a cut).
        soft_words = word_fade > 0 and ink_span is not None and all(
            is_rtl == rtl for _run, is_rtl in _bidi_runs(cue_text, rtl)
        )
        width, height = canvas
        specs: list[dict] = []
        previous_words = 0
        for start, end, words, index in windows:
            # Full logical phrase prefix -> one FriBidi/HarfBuzz shaping run. No inline
            # alpha tags are inserted between Arabic tokens, which eliminates temporary
            # reverse ordering during reveal.
            state_text = " ".join(row.text for row in tokens[:words]).strip()
            if not state_text:
                continue
            x, y = anchor(state_text)
            main_start = start
            if soft_words and specs and previous_words:
                fade = min(word_fade, (end - start) / 2.0)
                clip = self._added_word_clip(
                    ink_span,
                    " ".join(row.text for row in tokens[:previous_words]).strip(),
                    state_text,
                    " ".join(row.text for row in tokens[previous_words:words]).strip(),
                    rtl=rtl, width=width, height=height,
                    elapsed=None if origin is None else start - origin,
                    gesture_ms=gesture_ms, gesture_dx=gesture_dx,
                )
                if fade >= frame - 1e-9 and clip:
                    specs[-1]["end"] = start + fade  # earlier words stay exactly where they are
                    specs.append({"start": start, "end": start + fade, "text": state_text, "x": x, "y": y,
                                  "first": False, "fade_in": round(fade * 1000), "clip": clip})
                    main_start = start + fade
            specs.append({"start": main_start, "end": end, "text": state_text, "x": x, "y": y,
                          "first": index == 0, "fade_in": entry_fade_ms if index == 0 else None, "clip": ""})
            previous_words = words
        if specs and exit_fade > 0:
            last = specs[-1]
            last["fade_out"] = min(exit_fade, (last["end"] - last["start"]) / 2.0)

        events: list[str] = []
        for spec in specs:
            elapsed = None if origin is None else spec["start"] - origin
            tags = tags_for(spec["x"], spec["y"], first=spec["first"], elapsed=elapsed,
                            fade_in_ms=spec["fade_in"], fade_out=spec.get("fade_out", 0.0), clip=spec["clip"])
            events.append(self._dialogue(
                spec["start"],
                spec["end"],
                style_name,
                tags,
                self._directional_text(spec["text"], rtl),
            ))
        return events

    @staticmethod
    def _added_word_clip(
        ink_span, previous_text: str, state_text: str, added: str, *, rtl: bool, width: int, height: int,
        elapsed: float | None, gesture_ms: int, gesture_dx: int,
    ) -> str:
        """Rectangle that shows only the newly added words of a reveal state.

        The boundary sits in the middle of the gap between the earlier words' ink and the
        new words' ink (outline and shadow included). Word gaps are tight (a median of
        about a tenth of the line height), so one output pixel is enough; with less, or overlapping
        ink, the word keeps a cut (""). While the entry gesture still runs, the boundary
        travels with the line.
        """
        if not added:
            return ""
        previous_left, previous_right = ink_span(previous_text)
        state_left, state_right = ink_span(state_text)
        added_left, added_right = ink_span(added)
        added_width = added_right - added_left
        if rtl:
            new_edge = state_left + added_width  # the new words occupy the left end
            gap = previous_left - new_edge
            boundary = (previous_left + new_edge) / 2.0
        else:
            new_edge = state_right - added_width
            gap = new_edge - previous_right
            boundary = (previous_right + new_edge) / 2.0
        if gap < 1.0:
            return ""

        def rect(edge: float) -> str:
            edge = round(edge)
            return f"\\clip(0,0,{edge},{height})" if rtl else f"\\clip({edge},0,{width},{height})"

        if elapsed is not None and elapsed * 1000 < gesture_ms:
            remaining_ms = gesture_ms - round(elapsed * 1000)
            offset = gesture_dx * remaining_ms / gesture_ms
            return f"{rect(boundary + offset)}\\t(0,{remaining_ms},{rect(boundary)})"
        return rect(boundary)

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
        scale = max(MIN_FONT_SCALE, min(MAX_FONT_SCALE, float(item.font_scale)))
        available_width = max(1.0, width - margin_x * 2.0 - entry_x)

        def layout_at(value: float):
            return self.metrics.layout(
                cue_text, style_id=style_id, semantic_type=semantic_type, font_scale=value,
            )

        layout = layout_at(scale)
        for _ in range(3):
            if layout is None or layout.width <= available_width + 0.5:
                break
            scale = max(MIN_FONT_SCALE, scale * available_width / max(1.0, layout.width) * 0.985)
            layout = layout_at(scale)
        if layout is None:
            return width * item.x, height * item.y, scale

        # Vertical: centre the resting ink plus the downward entry offset on the box.
        path_height = layout.height + entry_y
        top = height * item.y - path_height / 2.0
        top = max(margin_y, min(height - margin_y - path_height, top))
        ink_center_y = top + layout.height / 2.0

        # Horizontal: the entry starts outward of the reading-start edge by ``entry_x``.
        # The completed phrase is centred on its planned box (the box is centred on the
        # semantic anchor and has a minimum label width, so a short word aligned to the
        # box edge drifted off its anchor); when the box is too tight for the centred
        # path, the path stays inside the box from its reading-start side.
        box_left = width * (item.x - item.max_width / 2.0)
        box_right = width * (item.x + item.max_width / 2.0)
        box_center = width * item.x
        if rtl:
            edge_x = min(box_center + layout.width / 2.0, box_right - entry_x)
            edge_x = max(margin_x + layout.width, min(width - margin_x - entry_x, edge_x))
        else:
            edge_x = max(box_center - layout.width / 2.0, box_left + entry_x)
            edge_x = max(margin_x + entry_x, min(width - margin_x - layout.width, edge_x))
        return edge_x, ink_center_y, scale

    @staticmethod
    def _entry_gesture(
        *, rtl: bool, pixel_scale: float, entry_strength: float, entry_duration_ms: int,
    ) -> tuple[int, int, int]:
        """The phrase's one entry path: (x offset, y offset, duration ms) towards rest."""
        strength = max(0.0, min(1.0, float(entry_strength)))
        horizontal = round((14 + round(10 * strength)) * pixel_scale)
        vertical = round((10 + round(5 * strength)) * pixel_scale)
        return (horizontal if rtl else -horizontal), vertical, max(130, min(240, int(entry_duration_ms)))

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
        entry_elapsed_ms: int | None = None,
        fade_in_ms: int | None = None,
        fade_out_ms: int = 0,
        clip: str = "",
    ) -> str:
        """ASS tags of one reveal event.

        ``first`` starts the phrase's entry gesture. A later state that begins while the
        gesture is still running (``entry_elapsed_ms``) continues the same linear path
        from where the phrase is, so adding a word never makes the line jump.
        """
        alignment = 4  # middle-left: ink lands exactly where the shared measurement puts it
        scale = max(round(MIN_FONT_SCALE * 100), min(round(MAX_FONT_SCALE * 100), round(font_scale * 100)))
        size_tag = f"\\fscx{scale}\\fscy{scale}"
        dx, dy, duration = TextRenderer._entry_gesture(
            rtl=rtl, pixel_scale=pixel_scale, entry_strength=entry_strength,
            entry_duration_ms=entry_duration_ms,
        )
        elapsed = 0 if first else entry_elapsed_ms
        moving = elapsed is not None and elapsed < duration
        if first and fade_in_ms is None:
            strength = max(0.0, min(1.0, float(entry_strength)))
            fade_in_ms = max(45, min(65, round(65 - 15 * strength)))
        fade = f"\\fad({int(fade_in_ms or 0)},{int(fade_out_ms)})" if (fade_in_ms or fade_out_ms) else ""
        if moving:
            # One bounded entry gesture for the phrase. Semantic focus may make the
            # gesture more decisive, but the final anchor/font/style stay unchanged and
            # there is never a post-arrival bounce.
            remaining = 1.0 - elapsed / duration
            place = (f"\\move({x + round(dx * remaining)},{y + round(dy * remaining)},{x},{y},"
                     f"0,{duration - elapsed})")
        else:
            place = f"\\pos({x},{y})"
        rest_blur = 0.25 if pixel_scale == 1.0 else round(0.25 * pixel_scale, 3)
        blur = f"\\blur{rest_blur}"
        if moving:
            # Slightly softer only while travelling and sharp at rest, so every reveal
            # state at rest draws identical pixels: adding a word never re-sharpens the line.
            moving_blur = 0.35 if pixel_scale == 1.0 else round(0.35 * pixel_scale, 3)
            settle = duration - elapsed
            blur = f"\\blur{moving_blur}\\t({settle},{settle},\\blur{rest_blur})"
        return f"\\an{alignment}{face_tags}{size_tag}{place}{fade}{clip}{blur}"

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
