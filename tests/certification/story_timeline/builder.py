"""Script-first package builder for the Story/Choreography timeline-boundary certification.

The script is laid out first (tokens + arbitrary separators); scene and event spans are
then cut on that script as half-open ``[start, end)`` ranges, exactly as the Unified 2.0
loader validates them. Transcript words are the canonical ``\\S+`` tokens with
deterministic timing, so every expectation can be derived independently of the planners.
"""

from __future__ import annotations

import random
import re
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
    CanonicalVisualProgression,
)
from app.models import Transcript, TranscriptSegment, TranscriptWord, VisualAsset

WORD_RE = re.compile(r"\S+")
STEP = 0.42
LENGTH = 0.28

ARABIC = (
    "لكن بعد أشهر يكتشف الفريق شيئًا أسوأ معلومات حساسة كانت تخرج بهدوء الهاكر يستخدم "
    "المنفذ ثم يرجع للنظام قوي هنا تبدأ المشكلة كيف دخل كيف بقي الشبكة البوابة الحارس"
).split()
ENGLISH = (
    "the team finds something worse sensitive data was leaving quietly attacker uses the "
    "gateway then returns state-linked group version works differently"
).split()
MIXED = ARABIC[:12] + ["VPN", "API", "Wi-Fi", "2.0", "HTTP", "ID"] + ENGLISH[:10]
POOLS = {"ar": ARABIC, "en": ENGLISH, "mixed": MIXED}
PUNCTUATION = ["", "", "", ".", "،", "؛", "؟", ":", "...", "!", "?", ",", '"', ")"]

SEPARATORS = {
    "space": " ", "newline": "\n", "double_newline": "\n\n", "crlf": "\r\n", "tab": "\t",
    "nbsp": " ", "em_space": " ", "mixed": " \n\t ",
}


@dataclass(frozen=True)
class CaseSpec:
    language: str
    scenes: tuple[tuple[tuple[int, ...], ...], ...]  # scene -> event -> token count
    separator: str = "space"
    event_separator: str = "space"
    punctuation: bool = False
    contiguous_scenes: bool = True  # scene N ends exactly where N+1 starts
    contiguous_events: bool = True
    authored: bool = True  # authored visual_progression vs the default event
    word_gap: float = 0.0  # extra silence before every scene (seconds)
    seed: int = 0
    trailing: str = ""
    leading: str = ""
    scene_end_delta: int = 0  # mutation: move every scene end by this many chars
    next_start_delta: int = 0  # mutation: move every scene start after the first


@dataclass
class Built:
    package: CanonicalPackage
    assets: list[VisualAsset]
    transcript: Transcript
    script: str
    spec: CaseSpec
    scene_spans: list[tuple[int, int]]
    event_spans: list[list[tuple[int, int]]] = field(default_factory=list)
    words: list[TranscriptWord] = field(default_factory=list)


def _layout(spec: CaseSpec):
    """Lay out the script; returns script, scene spans, per-scene event spans."""
    rng = random.Random(spec.seed)
    pool = POOLS[spec.language]
    scene_sep = SEPARATORS[spec.separator]
    event_sep = SEPARATORS[spec.event_separator]
    parts: list[str] = [spec.leading]
    cursor = len(spec.leading)
    scene_spans: list[tuple[int, int]] = []
    event_spans: list[list[tuple[int, int]]] = []
    scene_starts: list[int] = []
    scene_token_ends: list[int] = []
    per_scene_events: list[list[tuple[int, int]]] = []
    for scene_index, events in enumerate(spec.scenes):
        scene_events: list[tuple[int, int]] = []
        scene_start = cursor
        for event_index, count in enumerate(events):
            start = cursor
            for token_index in range(count):
                token = rng.choice(pool)
                if spec.punctuation and token_index == count - 1:
                    token += rng.choice(PUNCTUATION)
                parts.append(token)
                cursor += len(token)
                if token_index < count - 1:
                    parts.append(" ")
                    cursor += 1
            scene_events.append((start, cursor))
            if event_index < len(events) - 1:
                parts.append(event_sep)
                cursor += len(event_sep)
        scene_starts.append(scene_start)
        scene_token_ends.append(cursor)
        per_scene_events.append(scene_events)
        if scene_index < len(spec.scenes) - 1:
            parts.append(scene_sep)
            cursor += len(scene_sep)
    parts.append(spec.trailing)
    script = "".join(parts)
    for index, (start, end) in enumerate(zip(scene_starts, scene_token_ends, strict=True)):
        if spec.contiguous_scenes and index + 1 < len(scene_starts):
            end = scene_starts[index + 1]  # includes the separator: A.end == B.start
        if index > 0:
            start = max(0, min(len(script), start + spec.next_start_delta))
        end = max(start + 1, min(len(script), end + spec.scene_end_delta))
        scene_spans.append((start, end))
    for events in per_scene_events:
        fixed = []
        for index, (start, end) in enumerate(events):
            if spec.contiguous_events and index + 1 < len(events):
                end = events[index + 1][0]
            fixed.append((start, end))
        event_spans.append(fixed)
    return script, scene_spans, event_spans


def build(spec: CaseSpec, image_root: Path = Path("timeline-scenes")) -> Built:
    script, scene_spans, event_spans = _layout(spec)
    namespace = f"TL{spec.seed:04d}"

    def span(start: int, end: int) -> CanonicalScriptSpan:
        return CanonicalScriptSpan(
            text=script[start:end], global_char_start=start, global_char_end=end,
        )

    scenes: list[CanonicalScene] = []
    assets: list[VisualAsset] = []
    for order, ((start, end), events) in enumerate(zip(scene_spans, event_spans, strict=True)):
        scene_id = f"{namespace}_SCENE_{order + 1:03d}"
        columns = max(1, int(len(events) ** 0.5 + 0.999))
        cell = 900 // columns
        boxes = [
            (((i % columns) * cell) + 40, ((i // columns) * cell) + 40, cell - 80, cell - 80)
            for i in range(max(1, len(events)))
        ]
        units = []
        for index, box in enumerate(boxes):
            x0, y0, w, h = box
            locator = CanonicalVisualLocator(
                coordinate_space="normalized_scene",
                cx=(x0 + w / 2) / 1000, cy=(y0 + h / 2) / 1000, width=w / 1000, height=h / 1000,
            )
            ev_start, ev_end = events[min(index, len(events) - 1)]
            units.append(CanonicalAsset(
                unit_id=f"{scene_id}_unit{index}", asset_id=f"{scene_id}_unit{index}",
                scene_id=scene_id, role="primary", semantic_role="PRIMARY",
                binding_type=BindingType("SEMANTIC"),
                script_text=script[ev_start:ev_end],
                script_span=span(ev_start, ev_end),
                sequence_order=index + 1, visual_locator=locator,
                semantic_group_id=f"{scene_id}_G01", semantic_event_id=f"{scene_id}_E{index}",
            ))
            assets.append(VisualAsset(
                id=f"{scene_id}:asset-{index + 1:02d}", scene_id=scene_id, role="primary",
                image_path=image_root / f"{scene_id}-{index}.png",
                extraction_method="timeline-cert", source_bbox=box,
                source_canvas_width=1000, source_canvas_height=1000,
                source_area_ratio=(w * h) / 1_000_000, can_animate_independently=True,
                confidence=1.0,
            ))
        progression = ()
        if spec.authored:
            progression = tuple(
                CanonicalVisualProgression(
                    action="EXPLAIN", order=index + 1,
                    targets=(units[min(index, len(units) - 1)].unit_id,),
                    trigger=span(*events[index]),
                )
                for index in range(len(events))
            )
        semantic_events = tuple(
            CanonicalSemanticEvent(
                semantic_event_id=f"{scene_id}_E{index}", scene_id=scene_id,
                script_text=script[ev_start:ev_end],
                script_span=span(ev_start, ev_end), sequence_order=index + 1,
                visual_leader_asset_id=unit.unit_id, text_anchor_asset_id=unit.unit_id,
            )
            for index, (unit, (ev_start, ev_end)) in enumerate(
                zip(units, [events[min(i, len(events) - 1)] for i in range(len(units))], strict=True)
            )
        )
        scenes.append(CanonicalScene(
            id=scene_id, image_path=image_root / f"{scene_id}.png", order=order,
            narration_hint=script[start:end].strip() or None,
            script_char_start=start, script_char_end=end,
            units=tuple(units), visual_progression=progression,
            semantic_events=semantic_events,
            semantic_groups=(CanonicalSemanticGroup(
                semantic_group_id=f"{scene_id}_G01",
                script_text=script[start:end].strip() or None,
                animation_policy="SEQUENTIAL_WITHIN_PHRASE",
                asset_ids=tuple(unit.asset_id for unit in units),
            ),),
        ))

    words: list[TranscriptWord] = []
    scene_of_word: list[int] = []
    for match in WORD_RE.finditer(script):
        scene_index = max(
            (i for i, (s, _e) in enumerate(scene_spans) if s <= match.start()), default=0,
        )
        at = 0.30 + len(words) * STEP + spec.word_gap * scene_index
        words.append(TranscriptWord(
            text=match.group(), start=round(at, 4), end=round(at + LENGTH, 4),
            char_start=match.start(), char_end=match.end(),
        ))
        scene_of_word.append(scene_index)
    segments = [TranscriptSegment(
        start=words[0].start, end=words[-1].end, text=script.strip(),
        char_start=words[0].char_start, char_end=words[-1].char_end, words=words,
    )]
    transcript = Transcript(
        language="ar" if spec.language != "en" else "en", duration=words[-1].end + 0.30,
        segments=segments, words=words, timing_source="forced_alignment",
    )
    package = CanonicalPackage(
        root=image_root, package_id=f"{namespace.lower()}-timeline", script=script,
        scenes=tuple(scenes), has_authoritative_semantics=True,
    )
    return Built(package, assets, transcript, script, spec, scene_spans, event_spans, words)


def words_in(built: Built, start: int, end: int) -> list[TranscriptWord]:
    """Reference rule, independent of the planners: half-open overlap."""
    return [w for w in built.words if w.char_end > start and w.char_start < end]
