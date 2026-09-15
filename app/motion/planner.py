from __future__ import annotations

from app.models import CompositionBeat, MotionCue, StoryBeat


class MotionPlanner:
    """Narration-led pacing with readable holds and non-frantic short beats.

    The primary visual is already legible when the narrated idea begins. Long beats
    receive a strong handoff; very short beats use restrained movement so rapid speech
    does not become a sequence of aggressive pops.
    """

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
            support_window_end = min(
                beat.end - 0.08,
                audio_start + max(0.18, spoken_duration * 0.55),
            )
            if support_count:
                available = max(0.0, support_window_end - max(primary_end, audio_start + 0.06))
                support_step = min(0.38, max(0.16, available / max(1, support_count)))
            else:
                support_step = 0.0

            for index, item in enumerate(layout.items):
                if index == 0:
                    cue_start = primary_start
                    cue_end = primary_end
                    kind = primary_kind
                else:
                    support_duration = min(0.36, max(0.24, entrance_duration * 0.82))
                    cue_start = max(primary_end + 0.10, audio_start + 0.05 + (index - 1) * support_step)
                    latest_start = max(beat.start, beat.end - support_duration - 0.08)
                    cue_start = min(cue_start, latest_start)
                    cue_end = min(beat.end - 0.04, cue_start + support_duration)
                    cue_end = max(cue_end, cue_start + 0.10)
                    kind = "soft_in" if visual_duration < 1.10 else "reveal_in"

                cues.append(MotionCue(
                    beat_id=beat.id,
                    asset_id=item.asset_id,
                    kind=kind,
                    start=cue_start,
                    end=cue_end,
                    params={
                        "overshoot": 0.025 if index == 0 else 0.012,
                        "sequence_index": index,
                        "sequence_count": len(layout.items),
                        "audio_anchor": audio_start,
                        "spoken_duration": spoken_duration,
                    },
                ))
        return cues
