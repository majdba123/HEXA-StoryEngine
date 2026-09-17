from __future__ import annotations

from app.models import StoryBeat


class SequenceGrouper:
    """Group consecutive narration beats into short visual mini-stories.

    Grouping is timeline/continuity based, never scene-ID based. A sequence is kept short
    enough to preserve momentum while long enough to support setup -> action -> consequence.
    """

    MIN_BEATS = 2
    MAX_BEATS = 4
    MAX_SECONDS = 8.5
    HARD_GAP_SECONDS = 1.15

    def group(self, beats: list[StoryBeat]) -> list[list[StoryBeat]]:
        if not beats:
            return []
        groups: list[list[StoryBeat]] = []
        current: list[StoryBeat] = []
        sequence_start = 0.0
        previous_audio_end: float | None = None

        for beat in beats:
            audio_start = beat.audio_start if beat.audio_start is not None else beat.start
            audio_end = beat.audio_end if beat.audio_end is not None else beat.end
            if not current:
                current = [beat]
                sequence_start = audio_start
                previous_audio_end = audio_end
                continue

            gap = max(0.0, audio_start - (previous_audio_end or audio_start))
            duration = audio_end - sequence_start
            hard_break = gap > self.HARD_GAP_SECONDS
            full = len(current) >= self.MAX_BEATS
            too_long = duration > self.MAX_SECONDS and len(current) >= self.MIN_BEATS

            if hard_break or full or too_long:
                groups.append(current)
                current = [beat]
                sequence_start = audio_start
            else:
                current.append(beat)
            previous_audio_end = audio_end

        if current:
            if len(current) == 1 and groups and len(groups[-1]) < self.MAX_BEATS:
                groups[-1].extend(current)
            else:
                groups.append(current)
        return groups
