"""LAYER 1 - mathematical certification of the scene-global assignment.

2,040 deterministic matrices (17 shapes x 12 score patterns x 10 seeds). Every one is
checked against an independent exact optimum (bitmask dynamic programme, exhaustive up
to 10x10) and re-solved after shuffling rows, columns and dict insertion order.
"""

from __future__ import annotations

import random

import pytest

from app.story.assignment import assign_globally, solve_max_weight

MIN_SCORE, MIN_MARGIN, FLOOR = 0.60, 0.065, 0.50
SHAPES = (
    (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (8, 8), (10, 10),
    (2, 1), (3, 2), (5, 3), (8, 5), (10, 6),
    (1, 2), (2, 3), (3, 5), (5, 8), (6, 10),
)
PATTERNS = (
    "strong_owner", "weak_matches", "exact_tie", "near_tie", "zero_edges", "all_invalid",
    "one_column_wanted", "one_row_wants_many", "diagonal", "crossed", "chained",
    "dominant_single_owner",
)
SEEDS_PER_CELL = 10
ASSIGNMENT_CASES = len(SHAPES) * len(PATTERNS) * SEEDS_PER_CELL
PERMUTATION_COMPARISONS = ASSIGNMENT_CASES * 2


def _scores(rows: int, columns: int, pattern: str, rng: random.Random) -> dict[str, dict[str, float]]:
    def cell(r: int, c: int) -> float:
        diagonal = r == c
        if pattern == "strong_owner":
            return rng.uniform(0.88, 0.99) if diagonal else rng.uniform(0.0, 0.3)
        if pattern == "weak_matches":
            return rng.uniform(0.60, 0.70)
        if pattern == "exact_tie":
            return 0.85
        if pattern == "near_tie":
            return 0.85 + rng.uniform(-0.02, 0.02)
        if pattern == "zero_edges":
            return rng.choice([0.0, 0.0, rng.uniform(0.6, 1.0)])
        if pattern == "all_invalid":
            return rng.uniform(0.0, 0.59)
        if pattern == "one_column_wanted":
            return rng.uniform(0.7, 0.99) if c == 0 else rng.uniform(0.0, 0.4)
        if pattern == "one_row_wants_many":
            return rng.uniform(0.7, 0.99) if r == 0 else rng.uniform(0.0, 0.65)
        if pattern == "diagonal":
            return 0.95 - 0.04 * abs(r - c) if abs(r - c) <= 1 else 0.1
        if pattern == "crossed":
            return rng.uniform(0.85, 0.95) if c == columns - 1 - r else rng.uniform(0.6, 0.8)
        if pattern == "chained":
            return 0.9 - 0.01 * r if c == r else (0.88 - 0.01 * r if c == r + 1 else 0.2)
        return 0.99 if (r, c) == (0, 0) else rng.uniform(0.60, 0.64)

    return {
        f"A{r:02d}": {f"c{c:02d}": round(cell(r, c), 6) for c in range(columns)}
        for r in range(rows)
    }


def _weights(scores: dict[str, dict[str, float]]) -> tuple[list[str], list[str], list[list[float]]]:
    rows, columns = sorted(scores), sorted({c for row in scores.values() for c in row})
    return rows, columns, [
        [max(0.0, (scores[r][c] if scores[r].get(c, 0.0) >= MIN_SCORE else 0.0) - FLOOR) ** 2
         if scores[r].get(c, 0.0) >= MIN_SCORE else 0.0 for c in columns]
        for r in rows
    ]


def _exact_optimum(weights: list[list[float]]) -> float:
    """Independent exact optimum: dynamic programme over used-column bitmasks."""
    columns = len(weights[0]) if weights else 0
    best = {0: 0.0}
    for row in weights:
        following = dict(best)
        for mask, value in best.items():
            for column in range(columns):
                if mask & (1 << column) or row[column] <= 0.0:
                    continue
                key = mask | (1 << column)
                if value + row[column] > following.get(key, -1.0):
                    following[key] = value + row[column]
        best = following
    return max(best.values())


def _normalized(result) -> tuple:
    return tuple(
        (row, m.column, m.ambiguous, round(m.score, 9),
         None if m.margin is None else round(m.margin, 9))
        for row, m in sorted(result.items())
    )


def _solve(scores):
    return assign_globally(
        scores, minimum_score=MIN_SCORE, minimum_margin=MIN_MARGIN, weight_floor=FLOOR,
    )


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("pattern", PATTERNS)
def test_global_optimum_structure_and_order_independence(shape, pattern: str) -> None:
    rows, columns = shape
    for seed in range(SEEDS_PER_CELL):
        rng = random.Random(f"{rows}x{columns}:{pattern}:{seed}")
        scores = _scores(rows, columns, pattern, rng)
        row_ids, column_ids, weights = _weights(scores)

        # Global optimum equals the independent exact optimum.
        solved = solve_max_weight(weights)
        used = [c for c in solved if c is not None]
        assert len(used) == len(set(used))
        total = sum(weights[r][c] for r, c in enumerate(solved) if c is not None)
        assert total == pytest.approx(_exact_optimum(weights), abs=1e-9), (shape, pattern, seed)

        result = _solve(scores)
        assert set(result) == set(row_ids)
        accepted = [m for m in result.values() if m.column is not None and not m.ambiguous]
        assert len({m.column for m in accepted}) == len(accepted)
        for match in accepted:
            assert match.column in column_ids
            assert scores[match.row][match.column] >= MIN_SCORE
            assert match.margin is not None and match.margin >= MIN_MARGIN
        if pattern == "all_invalid":
            assert all(m.column is None for m in result.values())
        if pattern == "strong_owner":
            for index in range(min(rows, columns)):
                assert result[row_ids[index]].column == column_ids[index]
        if pattern == "exact_tie" and rows > 1 and columns > 1:
            assert not accepted, "an exact tie is never guessed"
        if pattern == "dominant_single_owner":
            assert result["A00"].column == "c00" and not result["A00"].ambiguous

        # Shuffled rows, columns and insertion order -> identical normalized output.
        reference = _normalized(result)
        for _ in range(2):
            shuffled_rows = list(scores)
            rng.shuffle(shuffled_rows)
            shuffled = {}
            for row in shuffled_rows:
                items = list(scores[row].items())
                rng.shuffle(items)
                shuffled[row] = dict(items)
            assert _normalized(_solve(shuffled)) == reference, (shape, pattern, seed)


def test_greedy_local_order_cannot_steal_the_contested_cutout() -> None:
    scores = {"A": {"c1": 0.90, "c2": 0.89}, "B": {"c1": 0.88, "c2": 0.20}}
    result = _solve(scores)
    assert (result["A"].column, result["B"].column) == ("c2", "c1")
    assert not result["A"].ambiguous and not result["B"].ambiguous


BOUNDARY_DELTAS = (0.000, 0.001, 0.010, 0.030, 0.064, 0.065, 0.066, 0.080, 0.150)


@pytest.mark.parametrize("delta", BOUNDARY_DELTAS)
@pytest.mark.parametrize("top", [0.70, 0.80, 0.90, 0.99])
def test_ambiguity_margin_boundary_is_deterministic(delta: float, top: float) -> None:
    """Scores are exact decimals so the 0.065 boundary never depends on float noise."""
    rival = round(top - delta, 6)
    expected_ambiguous = round(top - rival, 6) < MIN_MARGIN
    free_rival = _solve({"A": {"c1": top, "c2": rival}})["A"]
    assert free_rival.ambiguous is expected_ambiguous, (top, delta, free_rival)
    if rival >= MIN_SCORE:
        contested = _solve({"A": {"c1": top}, "B": {"c1": rival}})
        assert contested["A"].ambiguous is expected_ambiguous
        assert contested["B"].column is None
    for _ in range(3):
        assert _solve({"A": {"c2": rival, "c1": top}})["A"].ambiguous is expected_ambiguous
