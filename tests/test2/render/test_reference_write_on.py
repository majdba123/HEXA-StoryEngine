"""C3 (reference grammar G5): arrows are drawn from cause to effect, never faded in place."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.models import StoryBeat
from app.render.connection import ConnectionSpec, draw_connection, draw_connection_sequence
from app.render.write_on import (
    MAX_FRAMES,
    MIN_ELONGATION,
    authored_path_directions,
    elongation,
    write_on_filter,
    write_on_frame_count,
)

FIXTURE = Path(__file__).with_name("fixtures") / "black_hat_beat022_path.json"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


def _beat022():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    centers = {key: tuple(value) for key, value in data["centers"].items()}
    return StoryBeat.model_validate(data["beat"]), centers, data["parent_of"]


def _art(path: Path, width: int, height: int, *, diagonal: bool = False, disc: bool = False) -> Path:
    """Stand-in alpha shapes: a long arrow shaft (optionally rising to the right) or a disc."""
    art = np.zeros((height, width, 4), np.uint8)
    yy, xx = np.mgrid[0:height, 0:width]
    if disc:
        inside = (xx - width / 2) ** 2 + (yy - height / 2) ** 2 <= (min(width, height) / 2.2) ** 2
    elif diagonal:
        inside = np.abs((height - yy) - xx * height / width) < height * 0.08
    else:
        inside = np.abs(yy - height / 2) < height * 0.15
    art[inside] = (30, 120, 230, 255)
    Image.fromarray(art).save(path)
    return path


def test_real_black_hat_path_writes_on_from_first_to_second_system(tmp_path) -> None:
    """The authored 'path between the two systems' arrow (asset-04) points up-right in the
    package art; it must be drawn along first_server LEADS_TO second_server."""
    beat, centers, parent_of = _beat022()
    images = {asset_id: _art(tmp_path / f"{index}.png", 300, 200, diagonal=True)
              for index, asset_id in enumerate(centers)}
    directions = authored_path_directions(beat, centers, parent_of=parent_of, images=images)
    dx, dy = directions["SCENE_022:asset-04"]
    assert dx > 0.6 and dy < -0.4  # rightward and upward in frame pixels
    # Narration order (DECLARED_PROGRESSION hexa -> first server) never gives a direction:
    # that relation would have drawn the arrow leftward, against its own head.
    assert "SCENE_022:asset-01" not in directions  # the character is never a path
    # A piece of the first server's family bound to the same unit is not the arrow.
    assert "SCENE_022:asset-03:secondary-01" not in directions


def test_path_without_a_causal_relation_between_its_neighbours_keeps_its_reveal(tmp_path) -> None:
    beat, centers, parent_of = _beat022()
    images = {asset_id: _art(tmp_path / f"{index}.png", 300, 200, diagonal=True)
              for index, asset_id in enumerate(centers)}
    context = beat.semantic_context.model_copy(update={
        "relations": [r for r in beat.semantic_context.relations if not r.causal],
    })
    beat = beat.model_copy(update={"semantic_context": context})
    assert authored_path_directions(beat, centers, parent_of=parent_of, images=images) == {}


def test_badges_and_round_icons_named_as_arrows_are_never_wiped_sideways(tmp_path) -> None:
    """Corpus: a round 'forward arrow badge' and a circular 'update arrow' were wiped across
    their own heads. Only artwork that spans the relation direction is a path."""
    beat, centers, parent_of = _beat022()
    disc = {asset_id: _art(tmp_path / f"d{index}.png", 200, 200, disc=True)
            for index, asset_id in enumerate(centers)}
    assert authored_path_directions(beat, centers, parent_of=parent_of, images=disc) == {}
    assert authored_path_directions(beat, centers, parent_of=parent_of) == {}  # no artwork, no claim
    assert elongation(_art(tmp_path / "bar.png", 300, 60), (1.0, 0.0)) >= MIN_ELONGATION
    assert elongation(_art(tmp_path / "bar.png", 300, 60), (0.0, 1.0)) < 1.0


def test_write_on_lives_inside_the_story_reveal_to_settle_window() -> None:
    assert write_on_frame_count(10, 14) == 4          # the whole window, ends before settle
    assert write_on_frame_count(10, 40) == MAX_FRAMES  # never longer than the reference ~8
    assert write_on_frame_count(10, 12) == 0          # too short to read: keep the reveal


@needs_ffmpeg
def test_encoded_write_on_reveals_along_the_direction_and_ends_on_authored_alpha(tmp_path) -> None:
    width, height, first, frames = 120, 20, 2, 4
    art = np.zeros((height, width, 4), np.uint8)
    art[4:16, 10:110] = (30, 120, 230, 255)
    art[8:12, 50:60, 3] = 128  # a semi-transparent detail must come back exactly
    source = tmp_path / "arrow.png"
    Image.fromarray(art).save(source)
    chain = write_on_filter(image_path=source, box=(width, height), direction=(1.0, 0.0),
                            first_frame=first, frames=frames)
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-loop", "1", "-framerate", "30", "-i", str(source),
         "-vf", f"format=rgba{chain}", "-frames:v", str(first + frames + 2),
         "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        check=True, capture_output=True,
    ).stdout
    alpha = np.frombuffer(raw, np.uint8).reshape(-1, height, width, 4)[..., 3].astype(int)
    assert alpha[:first].max() == 0  # nothing before the Story reveal
    drawn = (alpha[first] > 200).any(axis=0).nonzero()[0]
    assert drawn.min() <= 12 and drawn.max() < 100  # starts at the tail, head still missing
    edges = [int((alpha[k] > 200).any(axis=0).nonzero()[0].max()) for k in range(first, first + frames)]
    assert edges == sorted(edges) and edges[0] < edges[-1]  # the leading edge only advances
    for k in range(first + frames - 1, len(alpha)):
        assert np.abs(alpha[k] - art[..., 3].astype(int)).max() <= 1  # exact authored alpha


def test_connector_writes_on_and_its_last_frame_is_the_complete_arrow(tmp_path) -> None:
    spec = ConnectionSpec(start=0.0, end=2.0, p0=(20.0, 50.0), p1=(180.0, 50.0))
    pattern, frames = draw_connection_sequence(spec, (200, 100), tmp_path / "c", fps=30)
    assert frames == 8
    ink = [np.asarray(Image.open(pattern % k))[..., 3] > 0 for k in range(frames)]
    reach = [int(mask.any(axis=0).nonzero()[0].max()) for mask in ink]
    assert reach == sorted(reach) and reach[0] < 120  # grows from the cause toward the effect
    full = np.asarray(Image.open(draw_connection(spec, (200, 100), tmp_path / "full.png")))
    assert np.array_equal(np.asarray(Image.open(pattern % (frames - 1))), full)
