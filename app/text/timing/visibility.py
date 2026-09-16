from __future__ import annotations

from app.models import StoryBeat, TextCue


class TextVisibilityPolicy:
    """Single source of truth for text readability windows.

    Spoken starts remain exact Forced Alignment anchors. This policy only decides how
    long a keyword remains readable after it has been spoken, and is shared by
    composition and motion so spatial collision checks match the rendered lifetime.
    """

    @staticmethod
    def visible_end(cue: TextCue, beat: StoryBeat, siblings: list[TextCue]) -> float:
        min_read = min(1.90, max(0.86, 0.52 + len(cue.text) * 0.060))
        target = max(cue.spoken_end + 0.24, cue.spoken_start + min_read)
        later = [
            row.spoken_start
            for row in siblings
            if row.spoken_start > cue.spoken_start + 0.04
        ]
        if later:
            target = min(target, max(cue.spoken_end, min(later) - 0.08))
        return min(beat.end, max(cue.spoken_end, target))

    @staticmethod
    def overlaps(
        left_start: float,
        left_end: float,
        right_start: float,
        right_end: float,
    ) -> bool:
        return left_start < right_end - 0.01 and right_start < left_end - 0.01
