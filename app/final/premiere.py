"""Editable Premiere Pro timeline of a final RenderPlan (FCP7 XML, ``xmeml`` version 4).

User direction 2026-10-21: "generate as a Premiere file, with layers I can edit". Premiere
Pro imports Final Cut Pro 7 XML (File > Import) as a sequence with real tracks. The edit
comes from the renderer itself: ``FFmpegRenderer.capture_layers`` authors every beat
segment exactly as it would for the video and records each drawn layer (position and
scale expressions, visibility window, opacity clock) instead of encoding. Every element
becomes its own clip:

* each artwork cutout is its original PNG on its own track, with Basic Motion (Position,
  Scale) and Opacity keyframes sampled frame by frame from the renderer's expressions
  and reduced to the keyframes a straight line between them cannot replace;
* keywords are transparent QuickTime Animation clips rendered from the same ASS
  documents (word timing and style unchanged); arrows are their write-on frames as
  transparent clips; the grey wash is a full-frame tint clip with its opacity clock;
* V1 is the white canvas, A1 the narration.

Consecutive beats that keep an element continuous become one clip. Clips are stacked so
that the compositing order of every beat is kept (higher track = drawn on top). Layer
effects without an FCP7 equivalent (motion blur, the wash's background blur, landing
defocus, the path write-on mask) are left out; their timing is kept as opacity. The
narration timing is the narration's own: nothing is retimed.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image

from app.models import RenderPlan
from app.final import sound
from app.render.expression import compile_expression
from app.render.renderer import CapturedLayer, FFmpegRenderer
from app.render.text import PRODUCTION_FONT_DIR
from app.shared.errors import StageFailedError
from app.shared.process import run_hidden

# Keyframe reduction tolerances: what a straight line between two kept keyframes may
# miss by (position px, scale percentage points, opacity percentage points).
POSITION_TOLERANCE_PX = 0.35
SCALE_TOLERANCE = 0.05
OPACITY_TOLERANCE = 0.5
# Continuity accepted when one element's clips of consecutive beats become one clip.
_JOIN_PX = 1.5
_JOIN_SCALE = 0.5
_JOIN_OPACITY = 3.0
_YCBCR = re.compile(r"^YCbCr Matrix:.*$", re.MULTILINE)
_ASS_TIME = re.compile(r"^Dialogue:\s*[^,]*,(\d+):(\d\d):(\d\d)[.](\d\d),(\d+):(\d\d):(\d\d)[.](\d\d),")


@dataclass(slots=True)
class PremiereClip:
    kind: str  # still | movie
    name: str
    media: Path
    media_size: tuple[int, int]
    start: int  # sequence frame of the first drawn frame
    asset_id: str | None = None
    # Per drawn frame, from ``start``: centre x/y (sequence px), scale (%), opacity (%).
    cx: list[float] = field(default_factory=list)
    cy: list[float] = field(default_factory=list)
    scale: list[float] = field(default_factory=list)
    opacity: list[float] = field(default_factory=list)
    length: int = 0  # frames (movie clips carry no per-frame samples)
    joinable: bool = True

    @property
    def end(self) -> int:
        return self.start + (len(self.cx) if self.cx else self.length)

    def joins(self, other: PremiereClip) -> bool:
        return (self.joinable and other.joinable and self.kind == other.kind == "still"
                and self.media == other.media and self.end == other.start and bool(self.cx) and bool(other.cx)
                and abs(self.cx[-1] - other.cx[0]) <= _JOIN_PX and abs(self.cy[-1] - other.cy[0]) <= _JOIN_PX
                and abs(self.scale[-1] - other.scale[0]) <= _JOIN_SCALE
                and abs(self.opacity[-1] - other.opacity[0]) <= _JOIN_OPACITY)

    def extend(self, other: PremiereClip) -> None:
        self.cx += other.cx
        self.cy += other.cy
        self.scale += other.scale
        self.opacity += other.opacity


@dataclass(frozen=True, slots=True)
class PremiereProject:
    path: Path
    media_dir: Path
    tracks: int
    clips: int
    warnings: tuple[dict[str, Any], ...] = ()


class PremiereExporter:
    """RenderPlan -> ``<name>.xml`` + ``media/`` (copied cutouts, rendered text/arrow clips)."""

    def __init__(self, renderer: FFmpegRenderer, *, ffmpeg_bin: str = "ffmpeg") -> None:
        self.renderer = renderer
        self.ffmpeg_bin = ffmpeg_bin

    def export(self, plan: RenderPlan, *, audio: Path, xml_path: Path, media_dir: Path,
               name: str, reference_video: Path | None = None, work_dir: Path | None = None,
               effects: bool = True) -> PremiereProject:
        """``work_dir`` holds the renderer's authoring files (arrow frames, ASS documents)
        while the clips are made; a short path (the job workspace) keeps every file inside
        the Windows path limit. Default: a fresh system temporary folder."""
        media_dir.mkdir(parents=True, exist_ok=True)
        if work_dir is None:
            capture_root = Path(tempfile.mkdtemp(prefix="hexa-premiere-"))
        else:
            capture_root = work_dir / f"capture-{uuid.uuid4().hex[:8]}"
        warnings: list[dict[str, Any]] = []
        try:
            layers, problems = self.renderer.capture_layers(plan, capture_root)
            if problems and not layers:
                # A broken beat is skipped and reported; nothing authored at all is a broken
                # export, never a published empty project.
                raise StageFailedError(
                    "no beat of the plan could be authored for the Premiere project",
                    details={"code": "PREMIERE_EXPORT_FAILED", "first_error": problems[0]},
                )
            warnings.extend({"code": "PREMIERE_SEGMENT_SKIPPED", **row} for row in problems)
            segments = self._segments(plan, layers, media_dir, warnings)
        finally:
            shutil.rmtree(capture_root, ignore_errors=True)
        tracks = self._stack(segments)
        background = self._solid(media_dir / "canvas_white.png", (plan.width, plan.height), (255, 255, 255, 255))
        audio_copy = media_dir / f"narration{audio.suffix.lower()}"
        shutil.copyfile(audio, audio_copy)
        effects_track = None
        if effects and sound.SOUND_EFFECTS:
            try:  # the sound effects as their own editable track (A2)
                effects_track = media_dir / "sound_effects.wav"
                sound.mix(plan, audio, effects_track, ffmpeg_bin=self.ffmpeg_bin, include_voice=False)
            except Exception as exc:  # noqa: BLE001 - the project never depends on its effects
                effects_track = None
                warnings.append({"code": "PREMIERE_SOUND_EFFECTS_SKIPPED", "error": str(exc)[:300]})
        total = max(1, round(plan.duration * plan.fps))
        document = _XmemlWriter(plan, name=name, total=total).build(
            background=background, tracks=tracks, audio=audio_copy, reference=reference_video,
            effects=effects_track)
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_bytes(document)
        (media_dir / "README.txt").write_text(_README.format(xml=xml_path.name), encoding="utf-8")
        return PremiereProject(path=xml_path, media_dir=media_dir, tracks=len(tracks) + 1,
                               clips=sum(len(row) for row in tracks) + 1, warnings=tuple(warnings))

    # -- layers -> clips ---------------------------------------------------------------
    def _segments(self, plan: RenderPlan, layers: list[CapturedLayer], media_dir: Path,
                  warnings: list[dict[str, Any]]) -> list[list[PremiereClip]]:
        grouped: dict[float, list[CapturedLayer]] = {}
        for layer in layers:
            grouped.setdefault(layer.segment_start, []).append(layer)
        copies: dict[Path, tuple[Path, tuple[int, int]]] = {}
        output: list[list[PremiereClip]] = []
        counter = 0
        for segment_start in sorted(grouped):
            clips: list[PremiereClip] = []
            for layer in grouped[segment_start]:
                counter += 1
                try:
                    clip = self._clip(plan, layer, media_dir, copies, counter)
                except Exception as exc:  # noqa: BLE001 - one layer never stops the project
                    warnings.append({"code": "PREMIERE_LAYER_SKIPPED", "beat_id": layer.beat_id,
                                     "kind": layer.kind, "asset_id": layer.asset_id, "error": str(exc)[:300]})
                    continue
                if clip is not None:
                    clips.append(clip)
            output.append(clips)
        return output

    def _clip(self, plan: RenderPlan, layer: CapturedLayer, media_dir: Path,
              copies: dict[Path, tuple[Path, tuple[int, int]]], counter: int) -> PremiereClip | None:
        fps = plan.fps
        first_frame = round(layer.segment_start * fps)
        frame_count = max(1, round(layer.duration * fps))
        if layer.kind == "asset":
            return self._asset_clip(plan, layer, media_dir, copies, first_frame, frame_count)
        if layer.kind == "text":
            return self._text_clip(plan, layer, media_dir, first_frame, frame_count, counter)
        if layer.kind == "connection":
            return self._connection_clip(plan, layer, media_dir, first_frame, frame_count, counter)
        if layer.kind == "wash":
            return self._wash_clip(plan, layer, media_dir, first_frame, frame_count)
        return None

    def _asset_clip(self, plan, layer, media_dir, copies, first_frame, frame_count) -> PremiereClip | None:
        fps = plan.fps
        k0 = max(0, math.ceil(layer.visible[0] * fps - 1e-6))
        k1 = min(frame_count - 1, math.floor(layer.visible[1] * fps + 1e-6))
        if k1 < k0 or layer.image is None:
            return None
        source = Path(layer.image)
        if source not in copies:
            target = media_dir / f"{_safe(layer.asset_id or source.stem)}{source.suffix.lower() or '.png'}"
            if target.exists() and target.resolve() != source.resolve():
                target = target.with_name(f"{target.stem}-{len(copies)}{target.suffix}")
            shutil.copyfile(source, target)
            with Image.open(target) as image:
                copies[source] = (target, image.size)
        media, (iw, ih) = copies[source]
        box_w, box_h = layer.box
        fit = min(box_w / max(1, iw), box_h / max(1, ih))
        x_of, y_of, s_of = (compile_expression(layer.x_expr), compile_expression(layer.y_expr),
                            compile_expression(layer.scale_expr))
        clip = PremiereClip(kind="still", name=layer.asset_id or source.stem, media=media, media_size=(iw, ih),
                            start=first_frame + k0, asset_id=layer.asset_id)
        for k in range(k0, k1 + 1):
            t = k / fps
            s = s_of(t)
            if not math.isfinite(s):
                s = 1.0
            ow, oh = max(2.0, box_w * s), max(2.0, box_h * s)
            x, y = x_of(t, ow, oh), y_of(t, ow, oh)
            cx, cy = x + ow / 2.0, y + oh / 2.0
            if not (math.isfinite(cx) and math.isfinite(cy)):  # never write "nan" into the XML
                cx, cy = (clip.cx[-1], clip.cy[-1]) if clip.cx else (plan.width / 2.0, plan.height / 2.0)
            clip.cx.append(cx)
            clip.cy.append(cy)
            clip.scale.append(100.0 * fit * s)
            clip.opacity.append(100.0 * _opacity(layer.fades, t))
        return clip

    def _text_clip(self, plan, layer, media_dir, first_frame, frame_count, counter) -> PremiereClip | None:
        window = _ass_window(Path(layer.source))
        if window is None:
            return None
        k0 = max(0, math.floor(window[0] * plan.fps))
        k1 = min(frame_count - 1, math.ceil(window[1] * plan.fps))
        if k1 < k0:
            return None
        media = media_dir / f"text_{counter:04d}_{_safe(layer.beat_id)}.mov"
        # The video draws keywords on YUV frames, where the document's "YCbCr Matrix: TV.709"
        # keeps white white. On the RGBA canvas of a transparent clip libass would apply the
        # TV range to every colour (white -> 235 grey), so the clip uses an RGB copy.
        source = Path(layer.source)
        rgb = source.with_name(f"{source.stem}.rgb.ass")
        rgb.write_text(_YCBCR.sub("YCbCr Matrix: None", source.read_text(encoding="utf-8")), encoding="utf-8")
        self._encode([
            "-f", "lavfi", "-i",
            f"color=c=black@0.0:s={plan.width}x{plan.height}:r={plan.fps}:d={layer.duration:.6f},format=rgba",
            "-vf", (f"ass=filename='{_filter_path(rgb)}':fontsdir='{_filter_path(PRODUCTION_FONT_DIR)}':alpha=1,"
                    f"trim=start_frame={k0}:end_frame={k1 + 1},setpts=PTS-STARTPTS"),
        ], media)
        return PremiereClip(kind="movie", name=f"Text {layer.beat_id}", media=media,
                            media_size=(plan.width, plan.height), start=first_frame + k0,
                            length=k1 - k0 + 1, joinable=False)

    def _connection_clip(self, plan, layer, media_dir, first_frame, frame_count, counter) -> PremiereClip | None:
        fps = plan.fps
        k0 = max(0, math.ceil(layer.visible[0] * fps - 1e-6))
        k1 = min(frame_count - 1, math.floor(layer.visible[1] * fps + 1e-6))
        if k1 < k0 or layer.frames <= 0:
            return None
        length = k1 - k0 + 1
        hold = max(0, length - layer.frames) / fps
        media = media_dir / f"arrow_{counter:04d}_{_safe(layer.beat_id)}.mov"
        self._encode([
            "-framerate", str(fps), "-start_number", "0", "-i", str(layer.source),
            "-vf", f"format=rgba,tpad=stop_mode=clone:stop_duration={hold:.6f},trim=end_frame={length}",
        ], media)
        return PremiereClip(kind="movie", name=f"Arrow {layer.beat_id}", media=media,
                            media_size=(plan.width, plan.height), start=first_frame + k0, length=length,
                            joinable=False)

    def _wash_clip(self, plan, layer, media_dir, first_frame, frame_count) -> PremiereClip | None:
        wash = layer.wash or {}
        fps = plan.fps
        start, end, ramp = float(wash.get("start", 0.0)), float(wash.get("end", 0.0)), float(wash.get("ramp", 0.1))
        k0 = max(0, math.floor(start * fps))
        k1 = min(frame_count - 1, math.ceil(end * fps))
        if k1 < k0:
            return None
        tint = str(wash.get("tint", "FFFFFF"))
        color = tuple(int(tint[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
        media = self._solid(media_dir / f"wash_{tint.lower()}.png", (plan.width, plan.height), color)
        peak = 100.0 * float(wash.get("tint_alpha", 0.5))
        releases = end < layer.duration - 0.5 / fps
        clip = PremiereClip(kind="still", name=f"Wash {layer.beat_id}", media=media,
                            media_size=(plan.width, plan.height), start=first_frame + k0, joinable=False)
        for k in range(k0, k1 + 1):
            t = k / fps
            level = min(1.0, max(0.0, (t - start) / max(1e-6, ramp)))
            if releases:
                level *= 1.0 - min(1.0, max(0.0, (t - (end - ramp)) / max(1e-6, ramp)))
            clip.cx.append(plan.width / 2.0)
            clip.cy.append(plan.height / 2.0)
            clip.scale.append(100.0)
            clip.opacity.append(peak * level)
        return clip

    # -- tracks --------------------------------------------------------------------------
    @staticmethod
    def _stack(segments: list[list[PremiereClip]]) -> list[list[PremiereClip]]:
        """Clips on tracks (index 0 = V2). Inside a beat a clip drawn later sits on a higher
        track; an element continuing from the previous beat continues its own clip."""
        tracks: list[list[PremiereClip]] = []
        for clips in segments:
            floor = 0
            for clip in clips:
                chosen = next((index for index in range(floor, len(tracks))
                               if tracks[index] and tracks[index][-1].joins(clip)), None)
                if chosen is not None:
                    tracks[chosen][-1].extend(clip)
                else:
                    chosen = floor
                    while chosen < len(tracks) and tracks[chosen] and tracks[chosen][-1].end > clip.start:
                        chosen += 1
                    if chosen == len(tracks):
                        tracks.append([])
                    tracks[chosen].append(clip)
                floor = chosen + 1
        return [row for row in tracks if row]

    # -- media ---------------------------------------------------------------------------
    def _encode(self, arguments: list[str], output: Path) -> None:
        command = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", *arguments,
                   "-c:v", "qtrle", "-pix_fmt", "argb", "-an", str(output)]
        try:
            run_hidden(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"ffmpeg failed for {output.name}: {(exc.stderr or '')[-300:]}") from exc

    @staticmethod
    def _solid(path: Path, size: tuple[int, int], color: tuple[int, ...]) -> Path:
        if not path.exists():
            Image.new("RGBA", size, color).save(path)
        return path


def _opacity(fades: tuple[tuple[str, float, float], ...], t: float) -> float:
    level = 1.0
    for kind, start, length in fades:
        ramp = 1.0 if length <= 0 else min(1.0, max(0.0, (t - start) / length))
        level *= ramp if kind == "in" else 1.0 - ramp
    return level


def _ass_window(path: Path) -> tuple[float, float] | None:
    starts, ends = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ASS_TIME.match(line)
        if match:
            h1, m1, s1, c1, h2, m2, s2, c2 = (int(value) for value in match.groups())
            starts.append(h1 * 3600 + m1 * 60 + s1 + c1 / 100.0)
            ends.append(h2 * 3600 + m2 * 60 + s2 + c2 / 100.0)
    return (min(starts), max(ends)) if starts else None


def _filter_path(path: Path) -> str:
    return str(Path(path).resolve()).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def _safe(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "layer").strip("_")[:80] or "layer"


def _keyframes(series: list[tuple[float, ...]], tolerance: tuple[float, ...]) -> list[int]:
    """Indices that must stay keyframes so straight lines between them stay within
    ``tolerance`` of every sample (iterative Ramer-Douglas-Peucker per dimension)."""
    count = len(series)
    if count <= 2:
        return list(range(count))
    keep = {0, count - 1}
    pending = [(0, count - 1)]
    dims = range(len(tolerance))
    while pending:
        left, right = pending.pop()
        worst, worst_index = 1.0, None
        span = right - left
        for index in range(left + 1, right):
            u = (index - left) / span
            error = max(abs(series[index][d] - (series[left][d] + (series[right][d] - series[left][d]) * u))
                        / tolerance[d] for d in dims)
            if error > worst:
                worst, worst_index = error, index
        if worst_index is not None:
            keep.add(worst_index)
            pending += [(left, worst_index), (worst_index, right)]
    return sorted(keep)


def _url(path: Path) -> str:
    posix = Path(path).resolve().as_posix()
    if re.match(r"^[A-Za-z]:", posix):
        posix = posix[0] + "%3a" + quote(posix[2:], safe="/")
    else:
        posix = quote(posix, safe="/")
    return "file://localhost/" + posix.lstrip("/")


class _XmemlWriter:
    def __init__(self, plan: RenderPlan, *, name: str, total: int) -> None:
        self.plan = plan
        self.name = name
        self.total = total
        self.files: dict[Path, str] = {}
        self.file_lengths: dict[Path, int] = {}
        self.clip_ids = 0

    def build(self, *, background: Path, tracks: list[list[PremiereClip]], audio: Path,
              reference: Path | None, effects: Path | None = None) -> bytes:
        for row in tracks:
            for clip in row:
                self.file_lengths[clip.media] = max(self.file_lengths.get(clip.media, 0), clip.end - clip.start)
        self.file_lengths[background] = self.total
        root = ET.Element("xmeml", version="4")
        sequence = ET.SubElement(root, "sequence", id="sequence-1")
        ET.SubElement(sequence, "uuid").text = str(uuid.uuid4())
        ET.SubElement(sequence, "name").text = self.name
        ET.SubElement(sequence, "duration").text = str(self.total)
        self._rate(sequence)
        timecode = ET.SubElement(sequence, "timecode")
        self._rate(timecode)
        ET.SubElement(timecode, "string").text = "00:00:00:00"
        ET.SubElement(timecode, "frame").text = "0"
        ET.SubElement(timecode, "displayformat").text = "NDF"
        media = ET.SubElement(sequence, "media")
        video = ET.SubElement(media, "video")
        fmt = ET.SubElement(video, "format")
        self._characteristics(fmt, self.plan.width, self.plan.height)
        canvas = PremiereClip(kind="still", name="Canvas", media=background,
                              media_size=(self.plan.width, self.plan.height), start=0, length=self.total)
        self._track(video, [canvas])
        for row in tracks:
            self._track(video, row)
        if reference is not None and reference.is_file():
            ref = PremiereClip(kind="movie", name="Rendered reference (disabled)", media=reference,
                               media_size=(self.plan.width, self.plan.height), start=0, length=self.total)
            self.file_lengths[reference] = self.total
            self._track(video, [ref], enabled=False)
        audio_root = ET.SubElement(media, "audio")
        ET.SubElement(audio_root, "numOutputChannels").text = "2"
        audio_format = ET.SubElement(audio_root, "format")
        samples = ET.SubElement(audio_format, "samplecharacteristics")
        ET.SubElement(samples, "depth").text = "16"
        ET.SubElement(samples, "samplerate").text = "48000"
        for index, (label, path) in enumerate(
                (row for row in (("Narration", audio), ("Sound effects", effects)) if row[1] is not None), start=1):
            track = ET.SubElement(audio_root, "track")
            item = self._clipitem(track, name=label, start=0, length=self.total)
            file = ET.SubElement(item, "file", id=f"file-audio-{index}")
            ET.SubElement(file, "name").text = path.name
            ET.SubElement(file, "pathurl").text = _url(path)
            self._rate(file)
            ET.SubElement(file, "duration").text = str(self.total)
            file_media = ET.SubElement(ET.SubElement(file, "media"), "audio")
            file_samples = ET.SubElement(file_media, "samplecharacteristics")
            ET.SubElement(file_samples, "depth").text = "16"
            ET.SubElement(file_samples, "samplerate").text = "48000"
            ET.SubElement(file_media, "channelcount").text = "2"
            source = ET.SubElement(item, "sourcetrack")
            ET.SubElement(source, "mediatype").text = "audio"
            ET.SubElement(source, "trackindex").text = "1"
        ET.indent(root, space="  ")
        return b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="utf-8")

    def _track(self, video: ET.Element, clips: list[PremiereClip], *, enabled: bool = True) -> None:
        track = ET.SubElement(video, "track")
        for clip in clips:
            length = clip.end - clip.start
            item = self._clipitem(track, name=clip.name, start=clip.start, length=length)
            ET.SubElement(item, "alphatype").text = "straight"
            self._file(item, clip)
            if clip.cx:
                self._motion(item, clip)
                self._opacity(item, clip)
        ET.SubElement(track, "enabled").text = "TRUE" if enabled else "FALSE"
        ET.SubElement(track, "locked").text = "FALSE"

    def _clipitem(self, track: ET.Element, *, name: str, start: int, length: int) -> ET.Element:
        self.clip_ids += 1
        item = ET.SubElement(track, "clipitem", id=f"clipitem-{self.clip_ids}")
        ET.SubElement(item, "name").text = name
        ET.SubElement(item, "enabled").text = "TRUE"
        ET.SubElement(item, "duration").text = str(length)
        self._rate(item)
        ET.SubElement(item, "start").text = str(start)
        ET.SubElement(item, "end").text = str(start + length)
        ET.SubElement(item, "in").text = "0"
        ET.SubElement(item, "out").text = str(length)
        return item

    def _file(self, item: ET.Element, clip: PremiereClip) -> None:
        known = self.files.get(clip.media)
        if known is not None:
            ET.SubElement(item, "file", id=known)
            return
        file_id = f"file-{len(self.files) + 1}"
        self.files[clip.media] = file_id
        file = ET.SubElement(item, "file", id=file_id)
        ET.SubElement(file, "name").text = clip.media.name
        ET.SubElement(file, "pathurl").text = _url(clip.media)
        self._rate(file)
        ET.SubElement(file, "duration").text = str(self.file_lengths.get(clip.media, clip.end - clip.start))
        video = ET.SubElement(ET.SubElement(file, "media"), "video")
        self._characteristics(video, *clip.media_size)

    def _motion(self, item: ET.Element, clip: PremiereClip) -> None:
        effect = self._effect(item, "Basic Motion", "basic")
        width, height = self.plan.width, self.plan.height
        scale = self._parameter(effect, "scale", "Scale", 0, 1000)
        self._keys(scale, [(value,) for value in clip.scale], (SCALE_TOLERANCE,),
                   lambda row, element: setattr(element, "text", _num(row[0])))
        rotation = self._parameter(effect, "rotation", "Rotation", -8640, 8640)
        ET.SubElement(rotation, "value").text = "0"
        center = self._parameter(effect, "center", "Center")
        centres = [((x - width / 2.0) / width, (y - height / 2.0) / height) for x, y in zip(clip.cx, clip.cy)]
        tolerance = (POSITION_TOLERANCE_PX / width, POSITION_TOLERANCE_PX / height)
        self._keys(center, centres, tolerance, self._point)
        anchor = self._parameter(effect, "centerOffset", "Anchor Point")
        self._point((0.0, 0.0), ET.SubElement(anchor, "value"))

    def _opacity(self, item: ET.Element, clip: PremiereClip) -> None:
        effect = self._effect(item, "Opacity", "opacity")
        parameter = self._parameter(effect, "opacity", "opacity", 0, 100)
        self._keys(parameter, [(value,) for value in clip.opacity], (OPACITY_TOLERANCE,),
                   lambda row, element: setattr(element, "text", _num(row[0])))

    @staticmethod
    def _keys(parameter: ET.Element, series: list[tuple[float, ...]], tolerance: tuple[float, ...],
              write) -> None:
        if all(all(abs(row[d] - series[0][d]) <= tolerance[d] for d in range(len(tolerance))) for row in series):
            write(series[0], ET.SubElement(parameter, "value"))
            return
        for index in _keyframes(series, tolerance):
            keyframe = ET.SubElement(parameter, "keyframe")
            ET.SubElement(keyframe, "when").text = str(index)
            write(series[index], ET.SubElement(keyframe, "value"))

    @staticmethod
    def _point(row: tuple[float, ...], element: ET.Element) -> None:
        ET.SubElement(element, "horiz").text = _num(row[0], 6)
        ET.SubElement(element, "vert").text = _num(row[1], 6)

    @staticmethod
    def _effect(item: ET.Element, name: str, effect_id: str) -> ET.Element:
        effect = ET.SubElement(ET.SubElement(item, "filter"), "effect")
        ET.SubElement(effect, "name").text = name
        ET.SubElement(effect, "effectid").text = effect_id
        ET.SubElement(effect, "effectcategory").text = "motion"
        ET.SubElement(effect, "effecttype").text = "motion"
        ET.SubElement(effect, "mediatype").text = "video"
        return effect

    @staticmethod
    def _parameter(effect: ET.Element, parameter_id: str, name: str, low: float | None = None,
                   high: float | None = None) -> ET.Element:
        parameter = ET.SubElement(effect, "parameter", authoringApp="PremierePro")
        ET.SubElement(parameter, "parameterid").text = parameter_id
        ET.SubElement(parameter, "name").text = name
        if low is not None:
            ET.SubElement(parameter, "valuemin").text = _num(low)
            ET.SubElement(parameter, "valuemax").text = _num(high)
        return parameter

    def _rate(self, parent: ET.Element) -> None:
        rate = ET.SubElement(parent, "rate")
        ET.SubElement(rate, "timebase").text = str(self.plan.fps)
        ET.SubElement(rate, "ntsc").text = "FALSE"

    def _characteristics(self, parent: ET.Element, width: int, height: int) -> None:
        samples = ET.SubElement(parent, "samplecharacteristics")
        self._rate(samples)
        ET.SubElement(samples, "width").text = str(width)
        ET.SubElement(samples, "height").text = str(height)
        ET.SubElement(samples, "anamorphic").text = "FALSE"
        ET.SubElement(samples, "pixelaspectratio").text = "square"
        ET.SubElement(samples, "fielddominance").text = "none"


def _num(value: float, digits: int = 4) -> str:
    text = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def manifest_row(project: PremiereProject, target_id: str, plan: RenderPlan) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "filename": project.path.name,
        "kind": "premiere_fcp7_xml",
        "media_dir": project.media_dir.name,
        "width": plan.width,
        "height": plan.height,
        "fps": plan.fps,
        "duration": round(plan.duration, 6),
        "tracks": project.tracks,
        "clips": project.clips,
        "warnings": list(project.warnings),
    }


_README = """HEXA StoryEngine - Premiere Pro project
=======================================

Open Premiere Pro, then File > Import and choose {xml}
(keep this media folder next to it). Premiere builds one sequence with:

  V1        white canvas
  V2 ...    one clip per drawn element (artwork cutouts, keywords, arrows, grey wash),
            stacked in the video's drawing order; higher track = in front
  A1        narration
  A2        sound effects (whoosh, pop, tick, swell) - adjust or mute freely

Every artwork clip is the original cutout with its exact Position, Scale and Opacity
keyframes (Effect Controls > Motion / Opacity). Keywords and arrows are transparent
QuickTime Animation clips. Motion blur, the wash's background blur and landing defocus are
video-only effects and are not part of the editable timeline.

If Premiere asks for media, point it to this folder. Preferences > Media >
Default Media Scaling should stay "None" so cutouts keep their exact size.

----

افتح Premiere Pro ثم File > Import واختر الملف {xml} (خلي مجلد media جنبه).
كل عنصر بالفيديو طبقة لحالها: الرسومات مع حركة الموقع والحجم والشفافية كـ keyframes،
الكلمات والأسهم ملفات شفافة، والصوت على A1. أعلى طبقة = قدام.
"""
