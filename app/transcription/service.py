from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

from app.models import Transcript, TranscriptSegment, TranscriptWord
from app.transcription.alignment import (
    AlignmentRejectedError,
    ForcedAligner,
    WhisperXForcedAligner,
)
from app.shared.errors import DependencyUnavailableError
from app.shared.media import probe_duration

_WORD_RE = re.compile(r"\S+")
_PHRASE_RE = re.compile(r"[^.!؟?،؛;\n]+[.!؟?،؛;]?|[^\n]+$")
_STRONG_PUNCTUATION = frozenset(".!?؟؛;\n")


class TranscriptionService:
    def __init__(
        self,
        *,
        model_name: str,
        ffprobe_bin: str = "ffprobe",
        forced_aligner: ForcedAligner | None = None,
    ) -> None:
        self.model_name = model_name
        self.ffprobe_bin = ffprobe_bin
        self.forced_aligner = forced_aligner or WhisperXForcedAligner()

    def transcribe(self, audio: Path, script: str | None = None) -> Transcript:
        audio = audio.expanduser().resolve()
        if not audio.exists():
            raise FileNotFoundError(audio)
        if script:
            duration = probe_duration(audio, self.ffprobe_bin)
            try:
                return self.forced_aligner.align(audio, script, duration)
            except (DependencyUnavailableError, AlignmentRejectedError):
                # Preserve the existing runtime as a controlled fallback until the
                # forced-alignment runtime is provisioned everywhere. Production can
                # validate alignment availability before rendering.
                pass

        try:
            return self._faster_whisper(audio, script)
        except (ImportError, ModuleNotFoundError, DependencyUnavailableError):
            if script:
                return self._script_fallback(audio, script)
            raise DependencyUnavailableError(
                "faster-whisper is unavailable and Final Package has no script fallback"
            )

    def _faster_whisper(self, audio: Path, script: str | None) -> Transcript:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise DependencyUnavailableError("faster-whisper is not installed") from exc
        model = WhisperModel(self.model_name, device="auto", compute_type="auto")
        segments_iter, info = model.transcribe(str(audio), vad_filter=True, word_timestamps=True)
        segments: list[TranscriptSegment] = []
        words: list[TranscriptWord] = []
        for seg in segments_iter:
            if not seg.text.strip() or seg.end <= seg.start:
                continue
            seg_words: list[TranscriptWord] = []
            for raw in getattr(seg, "words", None) or []:
                text = str(getattr(raw, "word", "")).strip()
                start = float(getattr(raw, "start", seg.start) or seg.start)
                end = float(getattr(raw, "end", start + 0.05) or start + 0.05)
                if text and end > start:
                    word = TranscriptWord(start=start, end=end, text=text)
                    seg_words.append(word)
                    words.append(word)
            segments.append(TranscriptSegment(
                start=float(seg.start),
                end=float(seg.end),
                text=seg.text.strip(),
                words=seg_words,
            ))
        duration = probe_duration(audio, self.ffprobe_bin)
        if not segments:
            raise DependencyUnavailableError("transcription produced no speech segments")
        transcript = Transcript(
            language=getattr(info, "language", None),
            duration=duration,
            segments=segments,
            words=words,
        )
        if script:
            transcript = self._attach_script_char_spans(transcript, script)
        return transcript

    def _script_fallback(self, audio: Path, script: str) -> Transcript:
        duration = probe_duration(audio, self.ffprobe_bin)
        token_matches = list(_WORD_RE.finditer(script))
        if not token_matches:
            raise DependencyUnavailableError("script fallback contains no words")

        active_intervals = self._speech_intervals(audio, duration)
        token_weights = [self._spoken_weight(match.group()) for match in token_matches]
        positions = self._allocate_script_over_intervals(
            script,
            token_matches,
            token_weights,
            active_intervals,
        )
        words: list[TranscriptWord] = []
        for match, (start, end) in zip(token_matches, positions):
            words.append(TranscriptWord(
                start=start,
                end=max(end, start + 0.035),
                text=match.group(),
                char_start=match.start(),
                char_end=match.end(),
            ))

        phrase_matches = [m for m in _PHRASE_RE.finditer(script) if m.group().strip()]
        segments: list[TranscriptSegment] = []
        for match in phrase_matches:
            overlapping = [
                word for word in words
                if word.char_start is not None
                and word.char_end is not None
                and word.char_end > match.start()
                and word.char_start < match.end()
            ]
            if not overlapping:
                continue
            segments.append(TranscriptSegment(
                start=overlapping[0].start,
                end=overlapping[-1].end,
                text=match.group().strip(),
                char_start=match.start(),
                char_end=match.end(),
                words=overlapping,
            ))
        if not segments:
            segments = [TranscriptSegment(
                start=words[0].start,
                end=words[-1].end,
                text=script.strip(),
                char_start=0,
                char_end=len(script),
                words=words,
            )]
        return Transcript(language=None, duration=duration, segments=segments, words=words)

    def _speech_intervals(self, audio: Path, duration: float) -> list[tuple[float, float]]:
        """Return speech-active intervals from FFmpeg silence detection."""
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(audio),
            "-af",
            "silencedetect=noise=-38dB:d=0.16",
            "-f",
            "null",
            "-",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return [(0.0, duration)]
        log = result.stderr or ""
        events: list[tuple[str, float]] = []
        for line in log.splitlines():
            start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
            if start_match:
                events.append(("start", float(start_match.group(1))))
            end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
            if end_match:
                events.append(("end", float(end_match.group(1))))
        intervals: list[tuple[float, float]] = []
        cursor = 0.0
        silence_start: float | None = None
        for kind, value in events:
            value = min(max(0.0, value), duration)
            if kind == "start":
                silence_start = value
                if value - cursor >= 0.06:
                    intervals.append((cursor, value))
            elif silence_start is not None:
                cursor = max(cursor, value)
                silence_start = None
        if cursor < duration - 0.06:
            intervals.append((cursor, duration))
        cleaned = [(a, b) for a, b in intervals if b - a >= 0.06]
        return cleaned or [(0.0, duration)]

    @staticmethod
    def _spoken_weight(token: str) -> float:
        stripped = re.sub(r"[^\w\u0600-\u06FF]+", "", token, flags=re.UNICODE)
        return float(max(1, len(stripped)))

    def _allocate_script_over_intervals(
        self,
        script: str,
        token_matches: list[re.Match[str]],
        weights: list[float],
        intervals: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Align script timing to real narration pauses before interpolating words.

        The previous fallback spread token weight over the complete active-audio axis.
        It skipped silence, but punctuation could still drift several seconds away from
        the pause actually spoken by the TTS voice. Here punctuation boundaries are
        monotonically matched to measured silence gaps first. Word interpolation then
        happens independently inside each anchored speech region.
        """
        if len(token_matches) <= 1 or len(intervals) <= 1:
            return self._allocate_over_intervals(intervals, weights)

        baseline = self._allocate_over_intervals(intervals, weights)
        boundaries: list[tuple[int, float, bool]] = []
        token_ends = [match.end() for match in token_matches]
        for phrase in [m for m in _PHRASE_RE.finditer(script) if m.group().strip()][:-1]:
            token_index = 0
            while token_index < len(token_ends) and token_ends[token_index] <= phrase.end():
                token_index += 1
            if token_index <= 0 or token_index >= len(token_matches):
                continue
            punctuation = phrase.group().strip()[-1:]
            strong = punctuation in _STRONG_PUNCTUATION
            target = baseline[token_index - 1][1]
            if not boundaries or boundaries[-1][0] != token_index:
                boundaries.append((token_index, target, strong))

        gaps = [
            (intervals[index][1], intervals[index + 1][0])
            for index in range(len(intervals) - 1)
            if intervals[index + 1][0] - intervals[index][1] >= 0.16
        ]
        anchors = self._match_pause_anchors(boundaries, gaps)
        if not anchors:
            return baseline

        output: list[tuple[float, float]] = []
        token_cursor = 0
        window_start = intervals[0][0]
        for token_index, gap_start, gap_end in anchors:
            if token_index <= token_cursor:
                continue
            clipped = self._clip_intervals(intervals, window_start, gap_start)
            if not clipped:
                clipped = [(window_start, max(window_start + 0.05, gap_start))]
            output.extend(self._allocate_over_intervals(
                clipped,
                weights[token_cursor:token_index],
            ))
            token_cursor = token_index
            window_start = gap_end

        if token_cursor < len(weights):
            final_end = intervals[-1][1]
            clipped = self._clip_intervals(intervals, window_start, final_end)
            if not clipped:
                clipped = [(window_start, max(window_start + 0.05, final_end))]
            output.extend(self._allocate_over_intervals(clipped, weights[token_cursor:]))

        if len(output) != len(weights):
            return baseline
        return output

    @staticmethod
    def _match_pause_anchors(
        boundaries: list[tuple[int, float, bool]],
        gaps: list[tuple[float, float]],
    ) -> list[tuple[int, float, float]]:
        if not boundaries or not gaps:
            return []

        @lru_cache(maxsize=None)
        def solve(i: int, j: int) -> tuple[float, tuple[tuple[int, int], ...]]:
            if i >= len(boundaries):
                return 0.0, ()
            if j >= len(gaps):
                remaining = sum(1.45 if boundaries[k][2] else 0.80 for k in range(i, len(boundaries)))
                return remaining, ()

            token_index, target, strong = boundaries[i]
            gap_start, gap_end = gaps[j]
            midpoint = (gap_start + gap_end) / 2.0
            pause = gap_end - gap_start

            skip_boundary_cost, skip_boundary_path = solve(i + 1, j)
            skip_boundary_cost += 1.45 if strong else 0.80

            skip_gap_cost, skip_gap_path = solve(i, j + 1)
            skip_gap_cost += 0.08

            best_cost = skip_boundary_cost
            best_path = skip_boundary_path
            if skip_gap_cost < best_cost:
                best_cost = skip_gap_cost
                best_path = skip_gap_path

            error = abs(midpoint - target)
            tolerance = 4.0 if strong else 2.2
            if error <= tolerance:
                match_cost, match_path = solve(i + 1, j + 1)
                scale = 2.4 if strong else 1.9
                pause_bonus = min(0.8, pause) * (0.28 if strong else 0.12)
                match_cost += error / scale - pause_bonus
                if match_cost < best_cost:
                    best_cost = match_cost
                    best_path = ((i, j),) + match_path
            return best_cost, best_path

        _, matched = solve(0, 0)
        output: list[tuple[int, float, float]] = []
        for boundary_index, gap_index in matched:
            token_index, _, _ = boundaries[boundary_index]
            gap_start, gap_end = gaps[gap_index]
            output.append((token_index, gap_start, gap_end))
        return output

    @staticmethod
    def _clip_intervals(
        intervals: list[tuple[float, float]],
        start: float,
        end: float,
    ) -> list[tuple[float, float]]:
        output: list[tuple[float, float]] = []
        for interval_start, interval_end in intervals:
            clipped_start = max(start, interval_start)
            clipped_end = min(end, interval_end)
            if clipped_end - clipped_start >= 0.035:
                output.append((clipped_start, clipped_end))
        return output

    @staticmethod
    def _allocate_over_intervals(
        intervals: list[tuple[float, float]],
        weights: list[float],
    ) -> list[tuple[float, float]]:
        if not weights:
            return []
        total_active = sum(max(0.0, b - a) for a, b in intervals)
        if total_active <= 0:
            total_active = 0.1
        total_weight = max(1.0, sum(weights))

        def real_time(active_position: float) -> float:
            remaining = min(max(0.0, active_position), total_active)
            for start, end in intervals:
                length = end - start
                if remaining <= length:
                    return start + remaining
                remaining -= length
            return intervals[-1][1]

        output: list[tuple[float, float]] = []
        cursor = 0.0
        for weight in weights:
            next_cursor = cursor + total_active * weight / total_weight
            output.append((real_time(cursor), real_time(next_cursor)))
            cursor = next_cursor
        if output:
            output[-1] = (output[-1][0], intervals[-1][1])
        return output

    def _attach_script_char_spans(self, transcript: Transcript, script: str) -> Transcript:
        script_tokens = list(_WORD_RE.finditer(script))
        if not script_tokens or not transcript.words:
            return transcript
        count = min(len(script_tokens), len(transcript.words))
        words = list(transcript.words)
        for index in range(count):
            raw = words[index]
            match = script_tokens[index]
            words[index] = raw.model_copy(update={"char_start": match.start(), "char_end": match.end()})
        segments: list[TranscriptSegment] = []
        cursor = 0
        for seg in transcript.segments:
            seg_count = len(seg.words)
            seg_words = words[cursor:cursor + seg_count]
            cursor += seg_count
            char_start = seg_words[0].char_start if seg_words else None
            char_end = seg_words[-1].char_end if seg_words else None
            segments.append(seg.model_copy(update={
                "words": seg_words,
                "char_start": char_start,
                "char_end": char_end,
            }))
        return transcript.model_copy(update={"segments": segments, "words": words})
