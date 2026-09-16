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
            # Every support visual in this beat belongs to the same narrated event.
            # It should therefore move *into* the narration anchor instead of waiting
            # for a serial post-speech cascade. Keep only a tiny stagger so grouped
            # elements remain readable without feeling simultaneous or mechanical.
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
