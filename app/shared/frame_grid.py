from __future__ import annotations

import math
from dataclasses import dataclass

from app.models import StoryBeat


@dataclass(frozen=True, slots=True)
class BeatSegment:
    """One beat's slot on the encoded frame grid (the render authority for time)."""

    index: int
    beat: StoryBeat
    previous_beat: StoryBeat | None
    start_frame: int
    frame_count: int


def time_to_frame(value: float, fps: int, total_frames: int) -> int:
    return max(0, min(total_frames, round(max(0.0, value) * fps)))


def first_visible_frame(start: float, fps: int) -> int:
    """Encoded frame n (timestamp n/fps) that first satisfies ``t >= start``.

    ``1e-9`` only absorbs the float error of a start computed to sit exactly on a frame;
    it is far below one frame.
    """
    return max(0, math.ceil(max(0.0, float(start)) * int(fps) - 1e-9))


def beat_segments(story: list[StoryBeat], *, duration: float, fps: int) -> list[BeatSegment]:
    """Frame slots of every beat: each beat runs until the next beat's first frame."""
    ordered = sorted(story, key=lambda beat: (beat.start, beat.end, beat.id))
    if not ordered:
        return []
    total_frames = max(1, round(duration * fps))
    start_frame = time_to_frame(ordered[0].start, fps, total_frames)
    segments: list[BeatSegment] = []
    for index, beat in enumerate(ordered, start=1):
        if index < len(ordered):
            end_frame = time_to_frame(ordered[index].start, fps, total_frames)
        else:
            end_frame = total_frames
        end_frame = max(start_frame + 1, min(total_frames, end_frame))
        segments.append(BeatSegment(
            index=index,
            beat=beat,
            previous_beat=ordered[index - 2] if index > 1 else None,
            start_frame=start_frame,
            frame_count=end_frame - start_frame,
        ))
        start_frame = end_frame
    return segments
