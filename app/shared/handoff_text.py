from __future__ import annotations

from math import isfinite

from app.models import (
    StoryBeat,
    TextCompositionBeat,
    TextMotionCue,
    TextPlan,
    Transcript,
    VisualAsset,
)
from app.text.metrics import TextTypographyMetrics

from .handoff_core import _EPS, _HandoffCore

_PRODUCTION_TYPOGRAPHY = TextTypographyMetrics()


class TextHandoffMixin(_HandoffCore):
    @classmethod
    def require_text_for_composition(
        cls,
        *,
        transcript: Transcript,
        story: list[StoryBeat],
        assets: list[VisualAsset],
        text: TextPlan,
    ) -> None:
        violations: list[dict[str, object]] = []
        beat_by_id = {beat.id: beat for beat in story}
        asset_by_id = {asset.id: asset for asset in assets}
        cls._duplicates(
            (style.id for style in text.styles),
            kind="duplicate_text_style_id",
            field="style_id",
            violations=violations,
        )
        style_ids = {style.id for style in text.styles}
        cls._duplicates(
            (cue.id for cue in text.cues),
            kind="duplicate_text_cue_id",
            field="text_cue_id",
            violations=violations,
        )
        for cue in text.cues:
            beat = beat_by_id.get(cue.beat_id)
            if beat is None:
                cls._add(
                    violations,
                    "text_unknown_beat",
                    text_cue_id=cue.id,
                    beat_id=cue.beat_id,
                )
                continue
            if not cls._window(
                cue.spoken_start,
                cue.spoken_end,
                lower=beat.start,
                upper=min(beat.end, transcript.duration),
            ):
                cls._add(
                    violations,
                    "text_spoken_window_outside_beat",
                    text_cue_id=cue.id,
                    beat_id=cue.beat_id,
                    spoken_start=cue.spoken_start,
                    spoken_end=cue.spoken_end,
                    beat_start=beat.start,
                    beat_end=beat.end,
                )
            if cue.style_id not in style_ids:
                cls._add(
                    violations,
                    "text_cue_unknown_style",
                    text_cue_id=cue.id,
                    style_id=cue.style_id,
                )
            if not (cue.spoken_start - _EPS <= cue.emphasis_time <= cue.spoken_end + _EPS):
                cls._add(
                    violations,
                    "text_emphasis_outside_cue",
                    text_cue_id=cue.id,
                    emphasis_time=cue.emphasis_time,
                    spoken_start=cue.spoken_start,
                    spoken_end=cue.spoken_end,
                )
            if cue.anchor_asset_id:
                cls._require_asset_scene(
                    violations,
                    asset_by_id=asset_by_id,
                    asset_id=cue.anchor_asset_id,
                    scene_id=beat.scene_id,
                    kind="text_anchor_reference",
                    beat_id=beat.id,
                    text_cue_id=cue.id,
                )
            for token in cue.tokens:
                if not (
                    cue.source_char_start <= token.source_char_start
                    < token.source_char_end <= cue.source_char_end
                ):
                    cls._add(
                        violations,
                        "text_token_char_span_outside_cue",
                        text_cue_id=cue.id,
                        token=token.text,
                        source_char_start=token.source_char_start,
                        source_char_end=token.source_char_end,
                        cue_char_start=cue.source_char_start,
                        cue_char_end=cue.source_char_end,
                    )
                if not cls._window(
                    token.spoken_start,
                    token.spoken_end,
                    lower=cue.spoken_start,
                    upper=cue.spoken_end,
                ):
                    cls._add(
                        violations,
                        "text_token_window_outside_cue",
                        text_cue_id=cue.id,
                        token=token.text,
                        spoken_start=token.spoken_start,
                        spoken_end=token.spoken_end,
                    )

        cls._raise(
            "text->text-composition",
            "TEXT_HANDOFF_CONTRACT_VIOLATIONS",
            violations,
        )

    @classmethod
    def require_text_render_contract(
        cls,
        *,
        story: list[StoryBeat],
        assets: list[VisualAsset],
        text: TextPlan,
        text_composition: list[TextCompositionBeat],
        text_motion: list[TextMotionCue],
    ) -> None:
        violations: list[dict[str, object]] = []
        beat_by_id = {beat.id: beat for beat in story}
        asset_by_id = {asset.id: asset for asset in assets}
        cue_by_id = {cue.id: cue for cue in text.cues}

        layout_ids = [
            item.text_cue_id
            for beat in text_composition
            for item in beat.items
        ]
        motion_ids = [cue.text_cue_id for cue in text_motion]
        cls._duplicates(
            layout_ids,
            kind="duplicate_text_layout",
            field="text_cue_id",
            violations=violations,
        )
        cls._duplicates(
            motion_ids,
            kind="duplicate_text_motion",
            field="text_cue_id",
            violations=violations,
        )
        expected_ids = set(cue_by_id)
        if set(layout_ids) != expected_ids:
            cls._add(
                violations,
                "text_layout_coverage_mismatch",
                missing=sorted(expected_ids - set(layout_ids)),
                foreign=sorted(set(layout_ids) - expected_ids),
            )
        if set(motion_ids) != expected_ids:
            cls._add(
                violations,
                "text_motion_coverage_mismatch",
                missing=sorted(expected_ids - set(motion_ids)),
                foreign=sorted(set(motion_ids) - expected_ids),
            )

        for layout in text_composition:
            beat = beat_by_id.get(layout.beat_id)
            if beat is None:
                cls._add(
                    violations,
                    "text_layout_unknown_beat",
                    beat_id=layout.beat_id,
                )
                continue
            for item in layout.items:
                cue = cue_by_id.get(item.text_cue_id)
                if cue is None:
                    cls._add(
                        violations,
                        "text_layout_unknown_cue",
                        beat_id=layout.beat_id,
                        text_cue_id=item.text_cue_id,
                    )
                    continue
                if cue.beat_id != layout.beat_id:
                    cls._add(
                        violations,
                        "text_layout_cross_beat_cue",
                        beat_id=layout.beat_id,
                        text_cue_id=cue.id,
                        cue_beat_id=cue.beat_id,
                    )
                if not _PRODUCTION_TYPOGRAPHY.covers(cue.text):
                    # libass would substitute a machine-local font for missing glyphs.
                    cls._add(
                        violations,
                        "text_glyphs_outside_production_font",
                        beat_id=layout.beat_id,
                        text_cue_id=cue.id,
                    )
                layout_values = (item.x, item.y, item.max_width, item.font_scale)
                if not all(isfinite(value) for value in layout_values):
                    cls._add(
                        violations,
                        "nonfinite_text_layout_geometry",
                        beat_id=layout.beat_id,
                        text_cue_id=cue.id,
                    )
                elif item.max_width <= 0.0 or item.font_scale <= 0.0:
                    cls._add(
                        violations,
                        "nonpositive_text_layout_geometry",
                        beat_id=layout.beat_id,
                        text_cue_id=cue.id,
                        max_width=item.max_width,
                        font_scale=item.font_scale,
                    )
                if item.anchor_asset_id:
                    cls._require_asset_scene(
                        violations,
                        asset_by_id=asset_by_id,
                        asset_id=item.anchor_asset_id,
                        scene_id=beat.scene_id,
                        kind="text_layout_anchor_reference",
                        beat_id=beat.id,
                        text_cue_id=item.text_cue_id,
                    )

        for motion in text_motion:
            beat = beat_by_id.get(motion.beat_id)
            cue = cue_by_id.get(motion.text_cue_id)
            if beat is None or cue is None:
                cls._add(
                    violations,
                    "text_motion_unknown_reference",
                    beat_id=motion.beat_id,
                    text_cue_id=motion.text_cue_id,
                )
                continue
            if cue.beat_id != motion.beat_id:
                cls._add(
                    violations,
                    "text_motion_cross_beat_cue",
                    beat_id=motion.beat_id,
                    text_cue_id=cue.id,
                    cue_beat_id=cue.beat_id,
                )
            if not cls._window(
                motion.start,
                motion.end,
                lower=beat.start,
                upper=beat.end,
                allow_equal=True,
            ):
                cls._add(
                    violations,
                    "text_motion_window_outside_beat",
                    beat_id=beat.id,
                    text_cue_id=cue.id,
                    start=motion.start,
                    end=motion.end,
                    beat_start=beat.start,
                    beat_end=beat.end,
                )
            for token in motion.tokens:
                if not (
                    isfinite(token.start)
                    and isfinite(token.end)
                    and isfinite(token.visible_end)
                    and beat.start - _EPS <= token.start
                    <= token.end <= token.visible_end <= beat.end + _EPS
                ):
                    cls._add(
                        violations,
                        "text_motion_token_window_outside_beat",
                        beat_id=beat.id,
                        text_cue_id=cue.id,
                        token=token.text,
                        start=token.start,
                        end=token.end,
                        visible_end=token.visible_end,
                        beat_start=beat.start,
                        beat_end=beat.end,
                    )

        cls._raise(
            "text-motion->render",
            "TEXT_HANDOFF_CONTRACT_VIOLATIONS",
            violations,
        )

