from __future__ import annotations

from dataclasses import dataclass


BLACK_HAT_PROFILE = {
    "scenes": 40,
    "objects": 129,
    "semantic_groups": 40,
    "semantic_events": 55,
    "relations": 15,
}

STRUCTURAL_SEEDS = tuple(range(37500, 37564))
ENCODED_SEEDS = tuple(range(37600, 37608))
FULL_RENDER_SEEDS = (37700, 37701, 37702, 37703)
# Opening-coverage failure class (production diagnostic 570a01cb): narration starts
# before the first exact visual phrase by more than Story's bounded 0.42 s lead.
OPENING_COVERAGE_SEEDS = (37800, 37801, 37802)
# test_opening_coverage.py: fixture-shape proof, two covered openings, fail-closed opening.
OPENING_COVERAGE_TESTS = 4


@dataclass(frozen=True, slots=True)
class HoldoutCase:
    seed: int
    scene_count: int
    family: str
    image_mode: str = "exact"


FAMILIES = (
    "sparse",
    "dense",
    "relations",
    "no_relations",
    "progression",
    "no_progression",
    "edge_locators",
    "close_locators",
    "persistent",
    "delayed_reveal",
    "cause_action_result",
    "short_beats",
)


def structural_cases() -> tuple[HoldoutCase, ...]:
    rows = []
    for index, seed in enumerate(STRUCTURAL_SEEDS):
        # Eight cases equal or exceed Black Hat scene density. The remainder keep
        # package creation cheap while varying per-scene topology.
        scene_count = (40, 44, 48, 52)[index % 4] if index < 8 else (2 + index % 5)
        rows.append(HoldoutCase(seed, scene_count, FAMILIES[index % len(FAMILIES)]))
    return tuple(rows)


def encoded_cases() -> tuple[HoldoutCase, ...]:
    modes = ("exact", "same_aspect", "fit_pad", "one_mismatch")
    return tuple(
        HoldoutCase(seed, 2, FAMILIES[index % len(FAMILIES)], modes[index % len(modes)])
        for index, seed in enumerate(ENCODED_SEEDS)
    )


def opening_coverage_cases() -> tuple[HoldoutCase, ...]:
    return (
        HoldoutCase(OPENING_COVERAGE_SEEDS[0], 2, "opening_lead"),
        HoldoutCase(OPENING_COVERAGE_SEEDS[1], 2, "opening_prelude"),
        HoldoutCase(OPENING_COVERAGE_SEEDS[2], 2, "opening_result_first"),
    )


def full_render_cases() -> tuple[HoldoutCase, ...]:
    families = ("relations", "no_relations", "cause_action_result", "edge_locators")
    modes = ("exact", "same_aspect", "fit_pad", "one_mismatch")
    return tuple(HoldoutCase(seed, 2, families[index], modes[index]) for index, seed in enumerate(FULL_RENDER_SEEDS))
