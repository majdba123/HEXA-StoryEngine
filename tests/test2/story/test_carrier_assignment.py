"""Scene-global carrier assignment: optimal, order-independent, never guessing ties."""

from __future__ import annotations

import itertools
import math
import random

import pytest

from app.story.assignment import assign_globally, solve_max_weight

MIN_SCORE, MIN_MARGIN, FLOOR = 0.60, 0.065, 0.50


def _assign(scores: dict[str, dict[str, float]]):
    return assign_globally(
        scores, minimum_score=MIN_SCORE, minimum_margin=MIN_MARGIN, weight_floor=FLOOR,
    )


def _owners(scores) -> dict[str, str | None]:
    return {
        row: (match.column if not match.ambiguous else None)
        for row, match in _assign(scores).items()
    }


def _brute_force(weights: list[list[float]]) -> float:
    rows, columns = len(weights), len(weights[0]) if weights else 0
    best = 0.0
    slots = list(range(columns)) + [None] * rows
    for pick in itertools.permutations(slots, rows):
        best = max(best, sum(weights[r][c] for r, c in enumerate(pick) if c is not None))
    return best


@pytest.mark.parametrize("seed", range(60))
def test_hungarian_matches_brute_force_optimum(seed: int) -> None:
    rng = random.Random(seed)
    rows, columns = rng.randint(1, 5), rng.randint(1, 5)
    weights = [
        [rng.choice([0.0, round(rng.random(), 3)]) for _ in range(columns)] for _ in range(rows)
    ]
    solved = solve_max_weight(weights)
    assert len({c for c in solved if c is not None}) == len([c for c in solved if c is not None])
    total = sum(weights[r][c] for r, c in enumerate(solved) if c is not None)
    assert total == pytest.approx(_brute_force(weights), abs=1e-9)


@pytest.mark.parametrize("shape", [(0, 0), (0, 3), (3, 0)])
def test_empty_matrices_assign_nothing(shape) -> None:
    rows, columns = shape
    assert solve_max_weight([[0.0] * columns for _ in range(rows)]) == [None] * rows


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.1])
def test_invalid_weights_are_rejected_not_clamped(bad: float) -> None:
    with pytest.raises(ValueError):
        solve_max_weight([[0.5, bad]])
    if not (isinstance(bad, float) and bad < 0):
        with pytest.raises(ValueError):
            _assign({"A": {"c1": bad}})


def test_global_solution_beats_order_dependent_greedy() -> None:
    """A is nearly indifferent; B only fits cutout1: the scene solution is A->2, B->1."""
    scores = {"A": {"c1": 0.90, "c2": 0.89}, "B": {"c1": 0.88, "c2": 0.20}}
    assert _owners(scores) == {"A": "c2", "B": "c1"}


def test_three_by_three_chain_keeps_every_intent() -> None:
    scores = {
        "A": {"c1": 0.94, "c2": 0.10, "c3": 0.04},
        "B": {"c1": 0.81, "c2": 0.88, "c3": 0.05},
        "C": {"c1": 0.03, "c2": 0.07, "c3": 0.91},
    }
    assert _owners(scores) == {"A": "c1", "B": "c2", "C": "c3"}


def test_strong_owner_is_not_traded_for_two_weak_matches() -> None:
    """Sum-of-scores would give A->c2, B->c1 (1.22 > 0.99); the strong owner must win."""
    scores = {"A": {"c1": 0.99, "c2": 0.61}, "B": {"c1": 0.61}}
    assert _owners(scores) == {"A": "c1", "B": None}


def test_single_candidate_intent_cannot_steal_from_a_stronger_owner() -> None:
    scores = {"A": {"c1": 0.95, "c2": 0.65}, "B": {"c1": 0.80}, "C": {"c2": 0.70}}
    assert _owners(scores) == {"A": "c1", "B": None, "C": "c2"}


def test_more_intents_than_cutouts_and_more_cutouts_than_intents() -> None:
    assert _owners({"A": {"c1": 0.9}, "B": {"c1": 0.7}, "C": {"c1": 0.62}}) == {
        "A": "c1", "B": None, "C": None,
    }
    assert _owners({"A": {"c1": 0.9, "c2": 0.1, "c3": 0.2, "c4": 0.3}}) == {"A": "c1"}


def test_scores_below_the_acceptance_floor_never_assign() -> None:
    result = _assign({"A": {"c1": 0.59}, "B": {}})
    assert result["A"].column is None and result["B"].column is None


def test_two_free_near_equal_candidates_are_ambiguous() -> None:
    result = _assign({"A": {"c1": 0.90, "c2": 0.88}})
    assert result["A"].ambiguous and result["A"].rival == "c2"
    assert _owners({"A": {"c1": 0.90, "c2": 0.80}}) == {"A": "c1"}


def test_two_intents_near_tied_for_one_cutout_are_ambiguous() -> None:
    result = _assign({"A": {"c1": 0.90}, "B": {"c1": 0.88}})
    assert result["A"].ambiguous and result["A"].rival == "B"
    assert result["B"].column is None
    assert _owners({"A": {"c1": 0.90}, "B": {"c1": 0.70}}) == {"A": "c1", "B": None}


def test_exact_symmetric_tie_is_ambiguous_for_both_intents() -> None:
    scores = {"A": {"c1": 0.85, "c2": 0.85}, "B": {"c1": 0.85, "c2": 0.85}}
    assert _owners(scores) == {"A": None, "B": None}


def test_a_near_equal_rival_owned_firmly_by_another_intent_is_not_ambiguity() -> None:
    scores = {"A": {"c1": 0.90, "c2": 0.88}, "B": {"c2": 0.95}}
    assert _owners(scores) == {"A": "c1", "B": "c2"}


@pytest.mark.parametrize("seed", range(40))
def test_assignment_is_independent_of_input_order(seed: int) -> None:
    rng = random.Random(1000 + seed)
    rows = [f"A{i}" for i in range(rng.randint(1, 7))]
    columns = [f"c{i}" for i in range(rng.randint(1, 7))]
    scores = {
        row: {c: round(rng.random(), 2) for c in columns if rng.random() < 0.8} for row in rows
    }
    reference = _assign(scores)
    for _ in range(5):
        shuffled_rows = rows[:]
        rng.shuffle(shuffled_rows)
        shuffled = {}
        for row in shuffled_rows:
            items = list(scores[row].items())
            rng.shuffle(items)
            shuffled[row] = dict(items)
        assert _assign(shuffled) == reference


@pytest.mark.parametrize("seed", range(40))
def test_accepted_matches_are_exclusive_real_and_above_the_floor(seed: int) -> None:
    rng = random.Random(2000 + seed)
    rows = [f"A{i}" for i in range(rng.randint(1, 8))]
    columns = [f"c{i}" for i in range(rng.randint(1, 8))]
    scores = {row: {c: round(rng.random(), 3) for c in columns} for row in rows}
    result = _assign(scores)
    accepted = [m for m in result.values() if m.column is not None and not m.ambiguous]
    assert set(result) == set(rows)
    assert len({m.column for m in accepted}) == len(accepted)
    for match in accepted:
        assert match.column in columns
        assert match.score == scores[match.row][match.column] >= MIN_SCORE
        assert match.margin is not None and match.margin >= MIN_MARGIN


@pytest.mark.parametrize("top", [0.70, 0.80, 0.99])
def test_margin_exactly_at_the_threshold_is_not_ambiguous(top: float) -> None:
    """Regression: 0.70 - 0.635 is 0.06499999 in binary floats; the boundary is inclusive."""
    at_threshold = _assign({"A": {"c1": top, "c2": round(top - MIN_MARGIN, 6)}})["A"]
    just_below = _assign({"A": {"c1": top, "c2": round(top - MIN_MARGIN + 0.001, 6)}})["A"]
    assert not at_threshold.ambiguous and at_threshold.column == "c1"
    assert just_below.ambiguous