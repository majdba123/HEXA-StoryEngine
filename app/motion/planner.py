from __future__ import annotations

from app.models import CompositionBeat, MotionCue, StoryBeat


class MotionPlanner:
    """Build a semantic motion envelope around verified narration anchors.

    One cue remains the stable contract per asset/beat, while ``params`` carries the
    authored phases that the renderer can execute: entrance, in-frame travel/scale,
    and the outgoing handoff. Timing is derived from Story/audio anchors; no arbitrary
    post-speech cascade is introduced.
    """

    MOTION_VERSION = 2

    def plan(self, beats: list[StoryBeat], composition: list[CompositionBeat]) -> list[MotionCue]:
        by_beat = {item.beat_id: item for item in composition}
        cues: list[MotionCue] = []
        for beat in beats:
            layout = by_beat.get(beat.id)
            if not layout or not layout.items:
                continue

            visual_duration = max(0.12, beat.end - beat.start)
            audio_start = beat.audio_start if beat.audio_start is not None else beat.start
            audio_end = beat.audio_end if beat.audio_end is not None else beat.end
            spoken_duration = max(0.12, audio_end - audio_start)

            if visual_duration < 0.78:
                entrance_duration = min(0.28, max(0.20, visual_duration * 0.42))
                primary_kind = "soft_in"
            elif visual_duration < 1.25:
                entrance_duration = min(0.36, max(0.28, visual_duration * 0.30))
                primary_kind = "soft_in" if beat.action not in {"EMPHASIZE", "RESULT"} else "emphasis_in"
            else:
                entrance_duration = min(0.50, max(0.36, visual_duration * 0.22))
                if beat.action == "HANDOFF":
                    primary_kind = "handoff_in"
                elif beat.action in {"EMPHASIZE", "RESULT"}:
                    primary_kind = "emphasis_in"
                else:
                    primary_kind = "reveal_in"

            primary_end = min(beat.end - 0.04, max(beat.start + 0.08, audio_start - 0.055))
            primary_start = max(beat.start, primary_end - entrance_duration)

            support_count = max(0, len(layout.items) - 1)
            support_step = 0.0 if support_count <= 1 else min(0.035, 0.11 / (support_count - 1))

            for index, item in enumerate(layout.items):
                if index == 0:
                    cue_start = primary_start
                    cue_end = primary_end
                    kind = primary_kind
                else:
                    support_duration = min(0.36, max(0.24, entrance_duration * 0.82))
                    support_offset = min(0.11, (index - 1) * support_step)
                    settle_at = min(beat.end - 0.04, audio_start + 0.02 + support_offset)
                    cue_end = max(beat.start + 0.10, settle_at)
                    cue_start = max(beat.start, cue_end - support_duration)
                    if cue_end <= cue_start:
                        cue_end = min(beat.end - 0.04, cue_start + 0.10)
                    kind = "soft_in" if visual_duration < 1.10 else "reveal_in"

                params = self._motion_params(
                    beat=beat,
                    index=index,
                    item_count=len(layout.items),
                    cue_end=cue_end,
                    audio_start=audio_start,
                    audio_end=audio_end,
                    spoken_duration=spoken_duration,
                    visual_duration=visual_duration,
                )
                cues.append(
                    MotionCue(
                        beat_id=beat.id,
                        asset_id=item.asset_id,
                        kind=kind,
                        start=cue_start,
                        end=cue_end,
                        params=params,
                    )
                )
        return cues

    def _motion_params(
        self,
        *,
        beat: StoryBeat,
        index: int,
        item_count: int,
        cue_end: float,
        audio_start: float,
        audio_end: float,
        spoken_duration: float,
        visual_duration: float,
    ) -> dict[str, float | int | str | bool]:
        is_primary = index == 0
        emphasis = beat.action in {"EMPHASIZE", "RESULT"}
        handoff = beat.action == "HANDOFF"

        if is_primary:
            if handoff:
                entry_dx, entry_dy = 0.18, 0.0
                travel_dx, travel_dy = 0.045, -0.012
                exit_dx, exit_dy = -0.16, 0.0
                entry_scale, travel_scale, exit_scale = 0.90, 1.025, 0.96
            elif emphasis:
                entry_dx, entry_dy = 0.0, 0.075
                travel_dx, travel_dy = 0.0, -0.025
                exit_dx, exit_dy = 0.0, -0.10
                entry_scale, travel_scale, exit_scale = 0.86, 1.055, 0.94
            else:
                entry_dx, entry_dy = 0.0, 0.10
                travel_dx, travel_dy = 0.025, -0.022
                exit_dx, exit_dy = -0.08, -0.055
                entry_scale, travel_scale, exit_scale = 0.91, 1.025, 0.96
        else:
            side = -1.0 if index % 2 else 1.0
            entry_dx, entry_dy = 0.085 * side, 0.045
            travel_dx, travel_dy = -0.018 * side, -0.012
            exit_dx, exit_dy = 0.10 * side, -0.035
            entry_scale, travel_scale, exit_scale = 0.93, 1.018, 0.97

        # Rapid narration still gets a semantic entrance, but not a constant stream of
        # micro-motion. Sustained travel is reserved for beats with a readable hold.
        travel_start = max(cue_end + 0.04, audio_start + 0.08)
        travel_end = min(beat.end - 0.05, audio_end - 0.02)
        travel_enabled = visual_duration >= 0.90 and travel_end - travel_start >= 0.20
        if not travel_enabled:
            travel_start = cue_end
            travel_end = cue_end
            travel_dx = 0.0
            travel_dy = 0.0
            travel_scale = 1.0

        return {
            "motion_version": self.MOTION_VERSION,
            "semantic_action": beat.action,
            "sequence_index": index,
            "sequence_count": item_count,
            "audio_anchor": audio_start,
            "audio_end": audio_end,
            "spoken_duration": spoken_duration,
            "entry_easing": "ease_out_cubic",
            "entry_dx_ratio": entry_dx,
            "entry_dy_ratio": entry_dy,
            "entry_scale": entry_scale,
            "travel_enabled": travel_enabled,
            "travel_start": travel_start,
            "travel_end": travel_end,
            "travel_easing": "smoothstep",
            "travel_dx_ratio": travel_dx,
            "travel_dy_ratio": travel_dy,
            "travel_scale": travel_scale,
            "exit_easing": "ease_in_cubic",
            "exit_dx_ratio": exit_dx,
            "exit_dy_ratio": exit_dy,
            "exit_scale": exit_scale,
        }
