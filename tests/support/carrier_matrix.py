"""Deterministic package-shaped case generator for semantic-carrier certification."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from tests.support.carrier_scene import CANVAS, Cutout, Event, SceneSpec, Unit, locator_for

POSITIVE_FAMILIES = (
    "single",
    "few",
    "many",
    "decorative_leader",
    "compound_split",
    "dotted",
    "approximate",
    "no_locators",
    "boundary",
    "overlap",
    "result_tail",
    "long_window",
)
NEGATIVE_FAMILIES = {
    "neg_unresolved": "SEMANTIC_CARRIER_UNRESOLVED",
    "neg_misbound": "SEMANTIC_CARRIER_UNRESOLVED",
    "neg_hidden_art": "AUTHORED_CONTENT_HIDDEN",
}


@dataclass(frozen=True)
class CarrierCase:
    seed: int
    families: tuple[str, ...]
    scenes: tuple[SceneSpec, ...]
    expected_code: str | None

    @property
    def label(self) -> str:
        return f"{self.seed}-" + "+".join(self.families)


def _grid(count: int, rng: random.Random, *, touch_edges: bool = False) -> list[tuple[int, int, int, int]]:
    columns = max(1, math.ceil(math.sqrt(count)))
    rows = max(1, math.ceil(count / columns))
    cell_w, cell_h = CANVAS // columns, CANVAS // rows
    boxes = []
    for index in range(count):
        col, row = index % columns, index // columns
        pad_x = 0 if touch_edges else max(8, int(cell_w * rng.uniform(0.08, 0.16)))
        pad_y = 0 if touch_edges else max(8, int(cell_h * rng.uniform(0.08, 0.16)))
        width = cell_w - 2 * pad_x if touch_edges else int((cell_w - 2 * pad_x) * rng.uniform(0.80, 1.0))
        height = cell_h - 2 * pad_y if touch_edges else int((cell_h - 2 * pad_y) * rng.uniform(0.80, 1.0))
        boxes.append((col * cell_w + pad_x, row * cell_h + pad_y, max(40, width), max(40, height)))
    return boxes


def _shrink(box: tuple[int, int, int, int], ratio: float) -> tuple[float, float, float, float]:
    x, y, w, h = box
    return ((x + w / 2) / CANVAS, (y + h / 2) / CANVAS, w * ratio / CANVAS, h * ratio / CANVAS)


def _events(
    names: list[str], rng: random.Random, words: int, *, each_own: bool, result_tail: bool,
) -> tuple[Event, ...]:
    if each_own:
        groups = [[name] for name in names]
    else:
        groups, index = [], 0
        while index < len(names):
            size = rng.randint(1, 3)
            groups.append(names[index:index + size])
            index += size
    events = []
    for order, members in enumerate(groups):
        first = min(order, words - 1)
        last = min(words - 1, first + rng.randint(0, 1))
        results: tuple[str, ...] = ()
        if result_tail and order == len(groups) - 1 and len(members) > 1:
            results = (members[-1],)
            first, last = words - 2, words - 1
        events.append(Event(
            name=f"E{order + 1:02d}",
            leader=members[0],
            words=(first, last),
            participants=tuple(members[1:]),
            results=results,
            depends_on=(f"E{order:02d}",) if order and rng.random() < 0.5 else (),
        ))
    return tuple(events)


def _positive_scene(family: str, rng: random.Random) -> SceneSpec:
    count = {
        "single": 1, "few": rng.randint(2, 5), "many": rng.randint(10, 12),
    }.get(family, rng.randint(2, 5))
    words = max(6, count + 2)
    phrase = tuple(f"kalima{index}" for index in range(words))
    boxes = _grid(count, rng, touch_edges=family == "boundary")
    if family == "overlap" and count > 1:
        boxes = [
            (max(0, x - int(w * 0.10)) if i % 2 else x, y, min(CANVAS - x, int(w * 1.10)), h)
            for i, (x, y, w, h) in enumerate(boxes)
        ]
    names = [f"U{index:02d}" for index in range(count)]
    roles = ["primary"] + ["supporting"] * (count - 1)
    leader_decorative = family == "decorative_leader"
    events = _events(
        names, rng, words,
        each_own=family == "approximate",
        result_tail=family == "result_tail",
    )
    if leader_decorative:
        target = events[rng.randrange(len(events))].leader
        roles[names.index(target)] = "decorative"

    cutouts: list[Cutout] = []
    units: list[Unit] = []
    for index, (name, box, role) in enumerate(zip(names, boxes, roles)):
        span = (0, words - 1) if family == "long_window" else (min(index, words - 1),) * 2
        if family == "compound_split" and index == 0:
            x, y, w, h = box
            pieces = rng.randint(2, 8)
            columns = math.ceil(math.sqrt(pieces))
            piece_w, piece_h = w // columns, h // math.ceil(pieces / columns)
            fragments = [
                (x + (p % columns) * piece_w + 4, y + (p // columns) * piece_h + 4,
                 max(50, piece_w - 8), max(50, piece_h - 8))
                for p in range(pieces)
            ]
            cutouts.extend(
                Cutout(f"asset-{len(cutouts) + 1:02d}", fragment, role=role) for fragment in fragments
            )
            units.append(Unit(name, span, role=role, locator=locator_for(*fragments)))
            continue
        cutouts.append(Cutout(f"asset-{len(cutouts) + 1:02d}", box, role=role))
        if family == "no_locators":
            locator = None
        elif family == "approximate":
            locator = _shrink(box, rng.uniform(0.30, 0.45))
        else:
            locator = locator_for(box)
        units.append(Unit(name, span, role=role, locator=locator))
    policy = "SEQUENTIAL_WITHIN_PHRASE"
    if family == "dotted":
        policy = "SIMULTANEOUS_VISUAL_UNIT"
        for dot in range(rng.randint(3, 9)):
            cutouts.append(Cutout(
                f"asset-{len(cutouts) + 1:02d}", (8 + 20 * dot, CANVAS - 20, 10, 10),
            ))
    return SceneSpec(
        phrase=phrase, units=tuple(units), cutouts=tuple(cutouts), events=events,
        group_policy=policy,
    )


def _negative_scene(family: str, rng: random.Random) -> SceneSpec:
    phrase = tuple(f"kalima{index}" for index in range(6))
    left, middle, right = (40, 200, 280, 600), (380, 300, 240, 400), (680, 220, 280, 560)
    if family == "neg_unresolved":
        return SceneSpec(
            phrase=phrase,
            units=(
                Unit("SIGNED", (0, 3), role="primary", locator=locator_for(left)),
                Unit("AAA", (4, 4), binding="AMBIGUOUS"),
                Unit("BBB", (5, 5), binding="AMBIGUOUS"),
                Unit("ZMISSING", (0, 3)),
            ),
            cutouts=(Cutout("asset-01", left, role="primary"), Cutout("asset-02", middle),
                     Cutout("asset-03", right)),
            events=(Event("E01", "SIGNED", (0, 3), participants=("ZMISSING",)),),
            group_policy="SIMULTANEOUS_VISUAL_UNIT",
        )
    if family == "neg_misbound":
        return SceneSpec(
            phrase=phrase,
            units=(Unit("FIRST", (0, 1), role="primary", locator=locator_for(left)),
                   Unit("NOWHERE", (2, 3), locator=(rng.uniform(0.75, 0.85), 0.12, 0.18, 0.10))),
            cutouts=(Cutout("asset-01", left, role="primary"),),
            events=(Event("E01", "FIRST", (0, 1)),
                    Event("E02", "NOWHERE", (2, 3), depends_on=("E01",))),
        )
    big = (rng.randint(520, 600), rng.randint(150, 300), rng.randint(200, 300), rng.randint(200, 400))
    return SceneSpec(
        phrase=phrase,
        units=(Unit("MAIN", (0, 1), role="primary", locator=locator_for(left)),),
        cutouts=(Cutout("asset-01", left, role="primary"), Cutout("asset-02", big)),
        events=(Event("E01", "MAIN", (0, 1)),),
        group_policy="SIMULTANEOUS_VISUAL_UNIT",
    )


def family_case(family: str, seed: int) -> CarrierCase:
    """One-scene case of a named family (positive or negative)."""
    rng = random.Random(seed)
    if family in NEGATIVE_FAMILIES:
        return CarrierCase(seed, (family,), (_negative_scene(family, rng),), NEGATIVE_FAMILIES[family])
    return CarrierCase(seed, (family,), (_positive_scene(family, rng),), None)


def generate_case(seed: int, *, negative: bool = False) -> CarrierCase:
    rng = random.Random(seed)
    scene_count = rng.randint(1, 4)
    families = [rng.choice(POSITIVE_FAMILIES) for _ in range(scene_count)]
    scenes = [_positive_scene(family, rng) for family in families]
    expected = None
    if negative:
        family = rng.choice(sorted(NEGATIVE_FAMILIES))
        position = rng.randint(0, scene_count)
        families.insert(position, family)
        scenes.insert(position, _negative_scene(family, rng))
        expected = NEGATIVE_FAMILIES[family]
    return CarrierCase(seed=seed, families=tuple(families), scenes=tuple(scenes), expected_code=expected)
