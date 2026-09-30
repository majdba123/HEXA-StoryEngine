"""Frame-grid oracle for handoff coverage, independent of FFmpeg.

The encoded frame grid is the render authority: frame ``n`` has timestamp ``n / fps``.
FFmpeg's filtergraph text carries six decimals, so a bound written as ``k/fps`` can land
either side of frame k. The oracle applies the same rounding and is deliberately
conservative (an overlay bound is treated as exclusive at the rounded value).
"""

from __future__ import annotations

import math


def rounded(value: float) -> float:
    """What the filtergraph actually contains (``:.6f``)."""
    return float(f"{value:.6f}")


def frame_time(frame: int, fps: int) -> float:
    return frame / fps


def visible_frames_from(threshold: float, frame_count: int, fps: int) -> set[int]:
    """Frames on which an overlay enabled with ``between(t, threshold, end)`` is visible."""
    bound = rounded(threshold)
    return {n for n in range(frame_count) if frame_time(n, fps) >= bound}


def covered_frames_until(end: float, frame_count: int, fps: int) -> set[int]:
    """Frames owned by an outgoing layer trimmed/enabled up to ``end`` (exclusive, rounded)."""
    bound = rounded(end)
    return {n for n in range(frame_count) if frame_time(n, fps) < bound}


def first_frame_at_or_after(start: float, fps: int) -> int:
    """Reference first-visible frame of a continuous reveal time."""
    return max(0, math.ceil(start * fps - 1e-9))
