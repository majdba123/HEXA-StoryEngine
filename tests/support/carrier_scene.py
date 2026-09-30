"""Package-shaped scenes with real runtime cutouts for semantic-carrier certification.

Each scene pairs authored Unified 2.0 semantics (units, groups, events, locators) with
runtime cutouts in the exact shape Vision/Pass1/Pass2 produce: ``SCENE:asset-NN`` ids,
source bboxes on a 1000x1000 canvas and roles copied from package units. No runtime
id equals an authored asset id, so identity must be proven through locators, the
locator-less heuristic map, elimination or Story proxies, as in production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.canonical import (
    BindingType,
    CanonicalAsset,
    CanonicalPackage,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
    CanonicalSemanticGroup,
    CanonicalVisualLocator,
)
from app.models import Transcript, TranscriptSegment, TranscriptWord, VisualAsset

CANVAS = 1000
WORD_STEP = 0.42
WORD_LENGTH = 0.28


@dataclass(frozen=True)
class Cutout:
    """A runtime cutout: ``box`` is (x, y, w, h) on a 1000x1000 canvas."""

    key: str
    box: tuple[int, int, int, int]
    role: str = "supporting"
    independent: bool = True


@dataclass(frozen=True)
class Unit:
    """An authored VISUAL_ASSET_INTENT; ``words`` indexes into the scene phrase."""

    name: str
    words: tuple[int, int]
    role: str = "supporting"
    locator: tuple[float, float, float, float] | None = None  # cx, cy, w, h
    binding: str = "SEMANTIC"


@dataclass(frozen=True)
class Event:
    name: str
    leader: str
    words: tuple[int, int]
    participants: tuple[str, ...] = ()
    results: tuple[str, ...] = ()
    context: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneSpec:
    phrase: tuple[str, ...]
    units: tuple[Unit, ...]
    cutouts: tuple[Cutout, ...]
    events: tuple[Event, ...] = ()
    group_policy: str = "SEQUENTIAL_WITHIN_PHRASE"


@dataclass
class BuiltPackage:
    package: CanonicalPackage
    assets: list[VisualAsset]
    transcript: Transcript
    scene_ids: list[str] = field(default_factory=list)

    def runtime_id(self, scene_index: int, key: str) -> str:
        return f"{self.scene_ids[scene_index]}:{key}"

    def semantic_id(self, scene_index: int, name: str) -> str:
        return f"{self.scene_ids[scene_index]}_{name}"


def locator_for(*boxes: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
    """Precise locator (cx, cy, w, h) covering the union of cutout boxes."""
    x0 = min(box[0] for box in boxes) / CANVAS
    y0 = min(box[1] for box in boxes) / CANVAS
    x1 = max(box[0] + box[2] for box in boxes) / CANVAS
    y1 = max(box[1] + box[3] for box in boxes) / CANVAS
    return ((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0)


def _write_images(root: Path, scene_id: str, cutouts: tuple[Cutout, ...]) -> None:
    from PIL import Image, ImageDraw

    root.mkdir(parents=True, exist_ok=True)
    scene = Image.new("RGB", (CANVAS, CANVAS), (255, 255, 255))
    draw = ImageDraw.Draw(scene)
    for index, cutout in enumerate(cutouts):
        x, y, w, h = cutout.box
        colour = ((60 + 47 * index) % 220, (140 + 83 * index) % 220, (200 + 29 * index) % 220)
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=colour, outline=(20, 20, 20), width=3)
        sprite = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sprite).rectangle(
            [0, 0, w - 1, h - 1], fill=(*colour, 255), outline=(20, 20, 20, 255), width=3,
        )
        sprite.save(root / f"{scene_id}-{cutout.key}.png")
    scene.save(root / f"{scene_id}.png")


def build_package(
    scenes: list[SceneSpec],
    *,
    namespace: str = "CARRIER",
    image_root: Path = Path("carrier-scenes"),
    write_images: bool = False,
) -> BuiltPackage:
    script_parts: list[str] = []
    cursor = 0
    word_spans: list[list[tuple[int, int]]] = []
    for spec in scenes:
        spans = []
        for token in spec.phrase:
            if script_parts:
                script_parts.append(" ")
                cursor += 1
            spans.append((cursor, cursor + len(token)))
            script_parts.append(token)
            cursor += len(token)
        word_spans.append(spans)
    script = "".join(script_parts)

    canonical_scenes: list[CanonicalScene] = []
    assets: list[VisualAsset] = []
    scene_ids: list[str] = []
    for order, (spec, spans) in enumerate(zip(scenes, word_spans, strict=True)):
        scene_id = f"{namespace}_SCENE_{order + 1:03d}"
        scene_ids.append(scene_id)
        group_id = f"{scene_id}_G01"

        def span(words: tuple[int, int]) -> CanonicalScriptSpan:
            start, end = spans[words[0]][0], spans[words[1]][1]
            return CanonicalScriptSpan(
                text=script[start:end], global_char_start=start, global_char_end=end,
            )

        event_for_unit = {
            unit_name: event.name
            for event in spec.events
            for unit_name in (event.leader, *event.participants, *event.results)
        }
        units = tuple(
            CanonicalAsset(
                unit_id=f"{scene_id}_{unit.name}",
                asset_id=f"{scene_id}_{unit.name}",
                scene_id=scene_id,
                role=unit.role,
                semantic_role=unit.role.upper(),
                binding_type=BindingType(unit.binding),
                script_text=span(unit.words).text,
                script_span=span(unit.words),
                semantic_group_id=group_id,
                sequence_order=index + 1,
                semantic_event_id=(
                    f"{scene_id}_{event_for_unit[unit.name]}"
                    if unit.name in event_for_unit else None
                ),
                visual_locator=(
                    CanonicalVisualLocator(
                        coordinate_space="normalized_scene",
                        cx=unit.locator[0], cy=unit.locator[1],
                        width=unit.locator[2], height=unit.locator[3],
                    )
                    if unit.locator is not None else None
                ),
            )
            for index, unit in enumerate(spec.units)
        )
        events = tuple(
            CanonicalSemanticEvent(
                semantic_event_id=f"{scene_id}_{event.name}",
                scene_id=scene_id,
                script_text=span(event.words).text,
                script_span=span(event.words),
                sequence_order=index + 1,
                visual_leader_asset_id=f"{scene_id}_{event.leader}",
                participant_asset_ids=tuple(f"{scene_id}_{name}" for name in event.participants),
                result_asset_ids=tuple(f"{scene_id}_{name}" for name in event.results),
                context_asset_ids=tuple(f"{scene_id}_{name}" for name in event.context),
                text_anchor_asset_id=f"{scene_id}_{event.leader}",
                depends_on_event_ids=tuple(f"{scene_id}_{name}" for name in event.depends_on),
            )
            for index, event in enumerate(spec.events)
        )
        canonical_scenes.append(CanonicalScene(
            id=scene_id,
            image_path=image_root / f"{scene_id}.png",
            order=order,
            narration_hint=" ".join(spec.phrase),
            script_char_start=spans[0][0],
            script_char_end=spans[-1][1],
            units=units,
            semantic_events=events,
            semantic_groups=(
                CanonicalSemanticGroup(
                    semantic_group_id=group_id,
                    script_text=" ".join(spec.phrase),
                    animation_policy=spec.group_policy,
                    asset_ids=tuple(unit.asset_id for unit in units),
                ),
            ),
        ))
        if write_images:
            _write_images(image_root, scene_id, spec.cutouts)
        for cutout in spec.cutouts:
            x, y, w, h = cutout.box
            assets.append(VisualAsset(
                id=f"{scene_id}:{cutout.key}",
                scene_id=scene_id,
                role=cutout.role,
                image_path=image_root / f"{scene_id}-{cutout.key}.png",
                extraction_method="carrier-scene",
                source_bbox=(x, y, w, h),
                source_canvas_width=CANVAS,
                source_canvas_height=CANVAS,
                source_area_ratio=(w * h) / (CANVAS * CANVAS),
                can_animate_independently=cutout.independent,
                confidence=1.0,
            ))

    words: list[TranscriptWord] = []
    for spans in word_spans:
        for start, end in spans:
            at = 0.30 + len(words) * WORD_STEP
            words.append(TranscriptWord(
                text=script[start:end], start=at, end=at + WORD_LENGTH,
                char_start=start, char_end=end,
            ))
    segments = []
    offset = 0
    for spans in word_spans:
        scene_words = words[offset:offset + len(spans)]
        offset += len(spans)
        segments.append(TranscriptSegment(
            start=scene_words[0].start, end=scene_words[-1].end,
            text=" ".join(word.text for word in scene_words),
            char_start=spans[0][0], char_end=spans[-1][1], words=scene_words,
        ))
    transcript = Transcript(
        language="ar", duration=words[-1].end + 0.30, segments=segments, words=words,
        timing_source="forced_alignment",
    )
    package = CanonicalPackage(
        root=image_root, package_id=f"{namespace.lower()}-carrier", script=script,
        scenes=tuple(canonical_scenes), has_authoritative_semantics=True,
    )
    return BuiltPackage(package=package, assets=assets, transcript=transcript, scene_ids=scene_ids)
