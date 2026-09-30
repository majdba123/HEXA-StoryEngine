"""Oracle-backed case generator for Semantic Carrier Resolver acceptance.

Every generated scene knows the *true* cutout(s) of each authored unit, so a resolver
decision is compared with ground truth instead of merely "did not raise". All
randomness is seeded; ``case(family, seed)`` is fully reproducible.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace

from tests.support.carrier_scene import CANVAS, Cutout, Event, SceneSpec, Unit, locator_for

Box = tuple[int, int, int, int]

CLEAN_FAMILIES = (
    "A_precise", "B_jitter", "C_loose", "G_two_overlapping", "I_repeated_icons",
    "J_similar_sized", "K_tiny", "L_large", "N_border", "O_corner",
    "P_partially_outside", "R_sparse",
)
COMPLEX_FAMILIES = (
    "D_broad_group", "E_missing_locator", "H_three_overlapping", "M_nested", "Q_dense",
    "S_extra_cutout", "T_decorative_optional", "U_decorative_leader", "W_one_to_many",
    "X_many_to_one", "Y_repeated_fragments", "Z_dotted_path",
)
FAILURE_FAMILIES = {
    "F_wrong_locator": "SEMANTIC_CARRIER_UNRESOLVED",
    "ambiguous_participant": "SEMANTIC_CARRIER_AMBIGUOUS",
    "ambiguous_result": "SEMANTIC_CARRIER_AMBIGUOUS",
    "ambiguous_leader": "FINAL_PACKAGE_SEMANTIC_EVENT_COVERAGE",
    "no_required_carrier": "SEMANTIC_CARRIER_UNRESOLVED",
    "locator_on_nothing": "SEMANTIC_CARRIER_UNRESOLVED",
    "dependency_outside_locator": "SEMANTIC_CARRIER_UNRESOLVED",
    "hidden_authored_art": "AUTHORED_CONTENT_HIDDEN",
}
MUTATIONS = (
    "delete_locator", "shift_locator_small", "shift_locator_far", "overlap_locators",
    "cutout_role_decorative", "make_other_leader", "rename_cutouts", "merge_cutouts",
    "split_cutout", "add_confusing_cutout", "add_far_cutout", "remove_cutout",
    "reverse_unit_order", "equal_score_candidates",
)


@dataclass(frozen=True)
class Case:
    family: str
    seed: int
    spec: SceneSpec
    # unit name -> cutout keys that are truly its pixels
    truth: dict[str, frozenset[str]] = field(default_factory=dict)
    shared: dict[str, str] = field(default_factory=dict)   # unit -> compound cutout key
    unowned: frozenset[str] = frozenset()                  # units expected without members
    expected_code: str | None = None

    @property
    def label(self) -> str:
        return f"{self.family}:{self.seed}"


def _cells(count: int, rng: random.Random, *, fill: tuple[float, float] = (0.55, 0.8)) -> list[Box]:
    columns = max(1, math.ceil(math.sqrt(count)))
    rows = max(1, math.ceil(count / columns))
    cell_w, cell_h = CANVAS // columns, CANVAS // rows
    order = list(range(columns * rows))
    rng.shuffle(order)
    boxes = []
    for slot in order[:count]:
        col, row = slot % columns, slot // columns
        w = max(36, int(cell_w * rng.uniform(*fill)))
        h = max(36, int(cell_h * rng.uniform(*fill)))
        x = col * cell_w + rng.randint(4, max(4, cell_w - w - 4))
        y = row * cell_h + rng.randint(4, max(4, cell_h - h - 4))
        boxes.append((x, y, w, h))
    return boxes


def _expand(box: Box, ratio: float) -> tuple[float, float, float, float]:
    x, y, w, h = box
    nw, nh = w * ratio, h * ratio
    nx, ny = max(0.0, x - (nw - w) / 2), max(0.0, y - (nh - h) / 2)
    nw, nh = min(CANVAS - nx, nw), min(CANVAS - ny, nh)
    return ((nx + nw / 2) / CANVAS, (ny + nh / 2) / CANVAS, nw / CANVAS, nh / CANVAS)


def _shift(box: Box, fx: float, fy: float) -> tuple[float, float, float, float]:
    x, y, w, h = box
    nx = min(max(0, x + int(w * fx)), CANVAS - w)
    ny = min(max(0, y + int(h * fy)), CANVAS - h)
    return locator_for((nx, ny, w, h))


def _phrase(count: int) -> tuple[str, ...]:
    return tuple(f"kalima{i}" for i in range(max(6, count + 2)))


def _simple(
    boxes: list[Box], locators: list, *, roles: list[str] | None = None,
    leader: int = 0, policy: str = "SEQUENTIAL_WITHIN_PHRASE", each_own: bool = False,
    extra: tuple[Cutout, ...] = (),
) -> tuple[SceneSpec, dict[str, frozenset[str]]]:
    count = len(boxes)
    names = [f"U{i:02d}" for i in range(count)]
    roles = roles or (["primary"] + ["supporting"] * (count - 1))
    words = len(_phrase(count))
    units = tuple(
        Unit(name, (min(i, words - 1),) * 2, role=roles[i], locator=locators[i])
        for i, name in enumerate(names)
    )
    cutouts = tuple(Cutout(f"asset-{i + 1:02d}", box, role=roles[i]) for i, box in enumerate(boxes))
    if each_own:
        events = tuple(
            Event(f"E{i + 1:02d}", name, (min(i, words - 1),) * 2,
                  depends_on=(f"E{i:02d}",) if i else ())
            for i, name in enumerate(names)
        )
    else:
        events = (Event("E01", names[leader], (0, words - 1),
                        participants=tuple(n for n in names if n != names[leader])),)
    spec = SceneSpec(phrase=_phrase(count), units=units, cutouts=(*cutouts, *extra),
                     events=events, group_policy=policy)
    truth = {name: frozenset({f"asset-{i + 1:02d}"}) for i, name in enumerate(names)}
    return spec, truth


def positive(family: str, seed: int) -> Case:
    rng = random.Random(f"{family}:{seed}")
    key = family.split("_", 1)[0]
    count = rng.randint(2, 5)

    if key in {"A", "B", "C", "P", "J", "R", "G", "H", "Q", "L", "K"}:
        if key == "R":
            count = 2
        if key == "Q":
            count = rng.randint(12, 18)
        if key == "H":
            count = 3
        if key == "G":
            count = 2
        fill = {"L": (0.85, 0.95), "K": (0.08, 0.14), "J": (0.62, 0.64)}.get(key, (0.55, 0.8))
        boxes = _cells(count, rng, fill=fill)
        if key in {"G", "H"}:
            y, w, h = 300, 240, 300
            boxes = [(60 + i * 270, y, w, h) for i in range(count)]
        locators = []
        for box in boxes:
            if key == "B":
                locators.append(_shift(box, rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03)))
            elif key == "C":
                locators.append(_expand(box, rng.uniform(1.10, 1.22)))
            elif key == "P":
                locators.append(_shift(box, rng.choice([-1, 1]) * rng.uniform(0.10, 0.16), 0.0))
            elif key in {"G", "H"}:
                locators.append(_expand(box, 1.20))
            else:
                locators.append(locator_for(box))
        spec, truth = _simple(boxes, locators)
        return Case(family, seed, spec, truth)

    if key == "I":
        count = rng.randint(3, 8)
        side = min(140, 900 // count - 24)
        y = rng.randint(200, 700)
        boxes = [(30 + i * (900 // count), y, side, side) for i in range(count)]
        spec, truth = _simple(boxes, [locator_for(b) for b in boxes])
        return Case(family, seed, spec, truth)

    if key in {"N", "O"}:
        w, h = rng.randint(120, 220), rng.randint(120, 220)
        edge = {
            "N": [(0, 400, w, h), (CANVAS - w, 300, w, h), (400, 0, w, h), (350, CANVAS - h, w, h)],
            "O": [(0, 0, w, h), (CANVAS - w, 0, w, h), (0, CANVAS - h, w, h),
                  (CANVAS - w, CANVAS - h, w, h)],
        }[key]
        boxes = [edge[rng.randrange(4)], (400, 400, 180, 180)]
        spec, truth = _simple(boxes, [locator_for(b) for b in boxes])
        return Case(family, seed, spec, truth)

    if key == "M":
        outer = (rng.randint(80, 200), rng.randint(80, 200), 560, 620)
        inner = (outer[0] + rng.randint(150, 260), outer[1] + rng.randint(180, 300), 120, 130)
        far = (760, 760, 160, 160)
        boxes = [outer, inner, far]
        spec, truth = _simple(boxes, [locator_for(b) for b in boxes])
        return Case(family, seed, spec, truth)

    if key == "E":
        boxes = _cells(count, rng)
        missing = rng.randrange(1, count)
        locators = [None if i == missing else locator_for(b) for i, b in enumerate(boxes)]
        spec, truth = _simple(boxes, locators)
        return Case(family, seed, spec, truth)

    if key == "S":
        boxes = _cells(count, rng)
        extras = tuple(
            Cutout(f"asset-{count + 1 + i:02d}", (6 + 20 * i, CANVAS - 14, 9, 9))
            for i in range(rng.randint(1, 6))
        )
        spec, truth = _simple(boxes, [locator_for(b) for b in boxes],
                              policy="SIMULTANEOUS_VISUAL_UNIT", extra=extras)
        return Case(family, seed, spec, truth)

    if key == "T":
        boxes = _cells(count, rng)
        spec, truth = _simple(boxes, [locator_for(b) for b in boxes],
                              policy="SIMULTANEOUS_VISUAL_UNIT")
        ornament = Cutout(f"asset-{count + 1:02d}", (960, 960, 30, 30), role="decorative")
        spec = replace(
            spec,
            units=(*spec.units, Unit("ZORNAMENT", (0, 0), role="decorative")),
            cutouts=(*spec.cutouts, ornament),
        )
        return Case(family, seed, spec, truth, unowned=frozenset({"ZORNAMENT"}))

    if key == "U":
        boxes = _cells(count, rng)
        leader = rng.randrange(count)
        roles = ["primary"] + ["supporting"] * (count - 1)
        roles[leader] = "decorative"
        spec, truth = _simple(boxes, [locator_for(b) for b in boxes], roles=roles, leader=leader)
        return Case(family, seed, spec, truth)

    if key in {"D", "W", "Y", "Z"}:
        pieces = {"D": 2, "W": rng.choice([2, 3, 5]), "Y": rng.choice([10, 20]),
                  "Z": rng.randint(5, 9)}[key]
        anchor = (560, 80, 380, 420)
        if key == "Z":
            fragments = [(40 + 58 * i, 820 + (14 if i % 2 else 0), 44, 28) for i in range(pieces)]
        else:
            columns = math.ceil(math.sqrt(pieces))
            fragments = [
                (40 + (i % columns) * (440 // columns), 100 + (i // columns) * (700 // columns),
                 max(40, 440 // columns - 14), max(40, 700 // columns - 14))
                for i in range(pieces)
            ]
        units = (
            Unit("ANCHOR", (0, 0), role="primary", locator=locator_for(anchor)),
            Unit("GROUPED", (1, 2), locator=locator_for(*fragments)),
        )
        cutouts = (
            Cutout("asset-01", anchor, role="primary"),
            *(Cutout(f"asset-{i + 2:02d}", box) for i, box in enumerate(fragments)),
        )
        spec = SceneSpec(
            phrase=_phrase(2), units=units, cutouts=cutouts,
            events=(Event("E01", "ANCHOR", (0, 0)),
                    Event("E02", "GROUPED", (1, 2), depends_on=("E01",))),
        )
        truth = {
            "ANCHOR": frozenset({"asset-01"}),
            "GROUPED": frozenset(f"asset-{i + 2:02d}" for i in range(pieces)),
        }
        return Case(family, seed, spec, truth)

    if key == "X":
        intents = rng.choice([2, 3])
        anchor = (40, 100, 240, 320)
        merged = (360, 250, 200 * intents + 20, 400)
        halves = [(360 + 200 * i + 10, 250, 190, 400) for i in range(intents)]
        units = (
            Unit("ANCHOR", (0, 0), role="primary", locator=locator_for(anchor)),
            *(Unit(f"PART{i}", (i + 1, i + 1), locator=_expand(halves[i], 0.8))
              for i in range(intents)),
        )
        events = (
            Event("E01", "ANCHOR", (0, 0)),
            *(Event(f"E{i + 2:02d}", f"PART{i}", (i + 1, i + 1), depends_on=(f"E{i + 1:02d}",))
              for i in range(intents)),
        )
        spec = SceneSpec(
            phrase=_phrase(intents + 1), units=units,
            cutouts=(Cutout("asset-01", anchor, role="primary"), Cutout("asset-02", merged)),
            events=events,
        )
        return Case(
            family, seed, spec, {"ANCHOR": frozenset({"asset-01"})},
            shared={f"PART{i}": "asset-02" for i in range(intents)},
        )
    raise ValueError(family)


def failure(family: str, seed: int) -> Case:
    rng = random.Random(f"{family}:{seed}")
    code = FAILURE_FAMILIES[family]
    lead = (rng.randint(20, 60), rng.randint(80, 160), rng.randint(180, 240), rng.randint(260, 340))
    lead_unit = Unit("LEAD", (0, 1), role="primary", locator=locator_for(lead))
    lead_cutout = Cutout("asset-01", lead, role="primary")
    simultaneous = "SIMULTANEOUS_VISUAL_UNIT"

    def near_tied() -> tuple[tuple, tuple[Cutout, Cutout]]:
        x, y, side = rng.randint(480, 520), rng.randint(90, 130), rng.randint(280, 320)
        grow = rng.randint(100, 130)
        first = (x - grow // 2, y - grow // 2, side + grow, side + grow)
        second = (first[0] + rng.randint(14, 22), first[1] + rng.randint(14, 22), first[2], first[3])
        return locator_for((x, y, side, side)), (Cutout("asset-02", first), Cutout("asset-03", second))

    if family in {"ambiguous_participant", "ambiguous_result", "ambiguous_leader"}:
        locator, pair = near_tied()
        target = Unit("TARGET", (2, 3), locator=locator)
        if family == "ambiguous_leader":
            events = (Event("E01", "LEAD", (0, 1)), Event("E02", "TARGET", (2, 3), depends_on=("E01",)))
        elif family == "ambiguous_result":
            events = (Event("E01", "LEAD", (0, 3), results=("TARGET",)),)
        else:
            events = (Event("E01", "LEAD", (0, 3), participants=("TARGET",)),)
        spec = SceneSpec(_phrase(2), (lead_unit, target), (lead_cutout, *pair), events, simultaneous)
    elif family in {"F_wrong_locator", "locator_on_nothing"}:
        stray = (rng.randint(520, 640), rng.randint(450, 560), rng.randint(200, 280), rng.randint(220, 300))
        locator = (rng.uniform(0.82, 0.9), rng.uniform(0.08, 0.14), 0.16, 0.12)
        if family == "F_wrong_locator":
            # The authored region is elsewhere; the true cutout is hidden under it.
            locator = locator_for((stray[0] + 40, stray[1] + 40, 60, 60))
        spec = SceneSpec(
            _phrase(2), (lead_unit, Unit("TARGET", (2, 3), locator=locator)),
            (lead_cutout, Cutout("asset-02", stray)),
            (Event("E01", "LEAD", (0, 3), participants=("TARGET",)),), simultaneous,
        )
    elif family == "no_required_carrier":
        boxes = [(rng.randint(340, 400), 300, 220, 360), (rng.randint(660, 720), 240, 240, 480)]
        spec = SceneSpec(
            _phrase(4),
            (lead_unit, Unit("AAA", (4, 4), binding="AMBIGUOUS"),
             Unit("BBB", (5, 5), binding="AMBIGUOUS"), Unit("ZMISSING", (0, 3))),
            (lead_cutout, Cutout("asset-02", boxes[0]), Cutout("asset-03", boxes[1])),
            (Event("E01", "LEAD", (0, 3), participants=("ZMISSING",)),), simultaneous,
        )
    elif family == "dependency_outside_locator":
        spec = SceneSpec(
            _phrase(2),
            (lead_unit, Unit("NOWHERE", (2, 3), locator=(rng.uniform(0.75, 0.88), 0.12, 0.18, 0.1))),
            (lead_cutout,),
            (Event("E01", "LEAD", (0, 1)), Event("E02", "NOWHERE", (2, 3), depends_on=("E01",))),
        )
    else:
        big = (rng.randint(520, 600), rng.randint(150, 300), rng.randint(200, 300), rng.randint(200, 400))
        spec = SceneSpec(_phrase(1), (lead_unit,), (lead_cutout, Cutout("asset-02", big)),
                         (Event("E01", "LEAD", (0, 1)),), simultaneous)
    return Case(family, seed, spec, expected_code=code)


def mutate(mutation: str, seed: int) -> Case:
    """Start from a valid precise scene (A->1, B->2, ...) and change exactly one thing."""
    rng = random.Random(f"{mutation}:{seed}")
    count = rng.randint(3, 5)
    boxes = _cells(count, rng)
    spec, truth = _simple(boxes, [locator_for(b) for b in boxes])
    units, cutouts = list(spec.units), list(spec.cutouts)
    target = rng.randrange(1, count)
    name = units[target].name
    shared: dict[str, str] = {}

    if mutation == "delete_locator":
        units[target] = replace(units[target], locator=None)
    elif mutation == "shift_locator_small":
        units[target] = replace(units[target], locator=_shift(boxes[target], 0.06, -0.05))
    elif mutation == "shift_locator_far":
        units[target] = replace(units[target], locator=(0.97, 0.97, 0.05, 0.05))
    elif mutation == "overlap_locators":
        units[target] = replace(units[target], locator=_expand(boxes[target], 1.25))
        units[0] = replace(units[0], locator=_expand(boxes[0], 1.25))
    elif mutation == "cutout_role_decorative":
        cutouts[target] = replace(cutouts[target], role="decorative")
    elif mutation == "make_other_leader":
        others = tuple(u.name for u in units if u.name != name)
        spec = replace(spec, events=(Event("E01", name, spec.events[0].words, participants=others),))
    elif mutation == "rename_cutouts":
        renamed = {c.key: f"asset-{90 - i:02d}" for i, c in enumerate(cutouts)}
        cutouts = [replace(c, key=renamed[c.key]) for c in cutouts]
        truth = {unit: frozenset(renamed[k] for k in keys) for unit, keys in truth.items()}
    elif mutation == "merge_cutouts":
        other = 0 if target != 0 else 1
        a, b = boxes[target], boxes[other]
        x0, y0 = min(a[0], b[0]), min(a[1], b[1])
        x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
        merged_key = cutouts[other].key
        cutouts = [c for i, c in enumerate(cutouts) if i not in {target, other}]
        cutouts.append(Cutout(merged_key, (x0, y0, x1 - x0, y1 - y0), role="primary"))
        for index in (target, other):
            truth[units[index].name] = frozenset({merged_key})
            shared[units[index].name] = merged_key
    elif mutation == "split_cutout":
        x, y, w, h = boxes[target]
        halves = [(x, y, w // 2 - 2, h), (x + w // 2 + 2, y, w - w // 2 - 2, h)]
        key = cutouts[target].key
        cutouts[target] = Cutout(key, halves[0])
        cutouts.append(Cutout("asset-77", halves[1]))
        truth[name] = frozenset({key, "asset-77"})
    elif mutation == "add_confusing_cutout":
        x, y, w, h = boxes[target]
        cutouts.append(Cutout("asset-78", (min(CANVAS - w, x + 8), min(CANVAS - h, y + 8), w, h)))
        truth[name] = frozenset({cutouts[target].key, "asset-78"})
    elif mutation == "add_far_cutout":
        cutouts.append(Cutout("asset-79", (985, 985, 10, 10), role="decorative"))
    elif mutation == "remove_cutout":
        removed = cutouts.pop(target).key
        truth[name] = frozenset()
        del removed
    elif mutation == "reverse_unit_order":
        units.reverse()
        cutouts.reverse()
    elif mutation == "equal_score_candidates":
        x, y, w, h = boxes[target]
        grow = 110
        first = (max(0, x - grow // 2), max(0, y - grow // 2), w + grow, h + grow)
        second = (min(CANVAS - first[2], first[0] + 16), min(CANVAS - first[3], first[1] + 16),
                  first[2], first[3])
        key = cutouts[target].key
        cutouts[target] = Cutout(key, first)
        cutouts.append(Cutout("asset-76", second))
        truth[name] = frozenset({key, "asset-76"})
    else:
        raise ValueError(mutation)
    spec = replace(spec, units=tuple(units), cutouts=tuple(cutouts))
    return Case(f"mutation_{mutation}", seed, spec, truth, shared=shared)
