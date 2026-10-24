"""Independent reading of a Premiere FCP7 XML for tests.

Composites one sequence frame from the XML alone, the way Premiere reads it: tracks bottom
to top, linear keyframes, Center normalized to the frame with its origin at the frame
centre, Scale in percent of the source pixels, Opacity in percent, transparent QuickTime
clips decoded with ffmpeg. Tests compare the result with the encoded video.
"""
from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

import numpy as np
from PIL import Image


def local_path(url: str) -> Path:
    path = unquote(urlsplit(url).path)
    if re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return Path(path)


def sequence_size(root: ET.Element) -> tuple[int, int]:
    fmt = root.find("sequence/media/video/format/samplecharacteristics")
    return int(fmt.findtext("width")), int(fmt.findtext("height"))


def _value(node: ET.Element, dims: int) -> np.ndarray:
    value = node.find("value")
    if dims == 2:
        return np.array([float(value.findtext("horiz")), float(value.findtext("vert"))])
    return np.array([float(value.text)])


def parameter_at(parameter: ET.Element | None, frame: int, dims: int) -> np.ndarray | None:
    if parameter is None:
        return None
    keys = [(int(key.findtext("when")), _value(key, dims)) for key in parameter.findall("keyframe")]
    if not keys:
        return _value(parameter, dims)
    if frame <= keys[0][0]:
        return keys[0][1]
    for (w0, v0), (w1, v1) in zip(keys, keys[1:]):
        if w0 <= frame <= w1:
            return v0 + (v1 - v0) * ((frame - w0) / max(1, w1 - w0))
    return keys[-1][1]


def _parameters(item: ET.Element) -> dict[str, ET.Element]:
    return {parameter.findtext("parameterid"): parameter
            for effect in item.iter("effect") for parameter in effect.findall("parameter")}


def _movie_frame(path: Path, index: int, size: tuple[int, int]) -> Image.Image:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{index})", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True, check=True)
    return Image.frombytes("RGBA", size, out.stdout[: size[0] * size[1] * 4])


def composite(xml: Path, frame: int) -> Image.Image:
    root = ET.parse(xml).getroot()
    width, height = sequence_size(root)
    files = {node.get("id"): local_path(node.findtext("pathurl"))
             for node in root.iter("file") if node.find("pathurl") is not None}
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    for track in root.find("sequence/media/video").findall("track"):
        if track.findtext("enabled") == "FALSE":
            continue
        for item in track.findall("clipitem"):
            start, end = int(item.findtext("start")), int(item.findtext("end"))
            if not start <= frame < end:
                continue
            path = files[item.find("file").get("id")]
            offset = frame - start + int(item.findtext("in"))
            if path.suffix.lower() == ".mov":
                canvas.alpha_composite(_movie_frame(path, offset, (width, height)))
                continue
            found = _parameters(item)
            image = Image.open(path).convert("RGBA")
            scale = parameter_at(found.get("scale"), offset, 1)
            centre = parameter_at(found.get("center"), offset, 2)
            opacity = parameter_at(found.get("opacity"), offset, 1)
            s = float(scale[0]) / 100 if scale is not None else 1.0
            cx = width / 2 + (float(centre[0]) * width if centre is not None else 0.0)
            cy = height / 2 + (float(centre[1]) * height if centre is not None else 0.0)
            w, h = max(1, round(image.width * s)), max(1, round(image.height * s))
            layer = image.resize((w, h), Image.LANCZOS)
            if opacity is not None and float(opacity[0]) < 100:
                alpha = np.asarray(layer.getchannel("A"), dtype=np.float32) * float(opacity[0]) / 100
                layer.putalpha(Image.fromarray(alpha.clip(0, 255).astype(np.uint8)))
            placed = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            placed.paste(layer, (round(cx - w / 2), round(cy - h / 2)), layer)
            canvas.alpha_composite(placed)
    return canvas.convert("RGB")


def video_frame(video: Path, frame: int, size: tuple[int, int]) -> Image.Image:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"select=eq(n\\,{frame})", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    return Image.frombytes("RGB", size, out.stdout[: size[0] * size[1] * 3])


def frame_difference(xml: Path, video: Path, frame: int) -> tuple[float, float]:
    """(mean absolute difference 0..255, share of pixels off by more than 40)."""
    root = ET.parse(xml).getroot()
    ours = np.asarray(composite(xml, frame), dtype=np.float32)
    theirs = np.asarray(video_frame(video, frame, sequence_size(root)), dtype=np.float32)
    diff = np.abs(ours - theirs).mean(axis=2)
    return float(diff.mean()), float((diff > 40).mean())
