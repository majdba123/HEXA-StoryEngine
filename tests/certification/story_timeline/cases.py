"""Deterministic case generation for the timeline-boundary certification."""

from __future__ import annotations

import random

from .builder import SEPARATORS, CaseSpec

SEPARATOR_NAMES = tuple(SEPARATORS)


def make_spec(seed: int, language: str, *, scenes: int | None = None, events: int | None = None,
              authored: bool | None = None, multi_event: bool = False) -> CaseSpec:
    rng = random.Random(seed * 7919 + hash(language) % 1000 * 0 + len(language))
    scene_count = scenes if scenes is not None else rng.choice((1, 2, 2, 3, 4, 5, 6))
    layout = []
    for _ in range(scene_count):
        count = events if events is not None else (
            rng.randint(2, 5) if multi_event else rng.choice((1, 1, 2, 3))
        )
        layout.append(tuple(rng.randint(1, 8) for _ in range(count)))
    use_authored = authored if authored is not None else rng.random() < 0.6
    if not use_authored:
        layout = [(sum(row),) for row in layout]  # default progression: one event per scene
    return CaseSpec(
        language=language,
        scenes=tuple(layout),
        separator=rng.choice(SEPARATOR_NAMES),
        event_separator=rng.choice(SEPARATOR_NAMES),
        punctuation=rng.random() < 0.6,
        contiguous_scenes=rng.random() < 0.5,
        contiguous_events=rng.random() < 0.5,
        authored=use_authored,
        word_gap=rng.choice((0.0, 0.0, 0.35, 1.4)),
        seed=seed,
        leading=rng.choice(("", "", "\n", "  ")),
        trailing=rng.choice(("", "", "\n", ".")),
    )
