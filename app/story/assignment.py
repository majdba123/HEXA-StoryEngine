from __future__ import annotations

import math
from dataclasses import dataclass


# Margins are differences of decimal scores; a margin that is exactly the threshold
# must not flip to "ambiguous" through binary floating-point rounding.
_MARGIN_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class GlobalMatch:
    """One accepted or rejected row of a scene-global assignment."""

    row: str
    column: str | None
    score: float
    runner_up_score: float | None
    margin: float | None
    ambiguous: bool = False
    rival: str | None = None


def solve_max_weight(weights: list[list[float]]) -> list[int | None]:
    """Maximum-weight bipartite assignment (Hungarian algorithm, O(n^2 * m)).

    ``weights[row][column]`` must be finite and non-negative; zero means "no edge".
    Returns the chosen column per row, or ``None`` when the row stays unassigned.
    Rows and columns are expected in a canonical order, which makes the result
    deterministic for identical inputs regardless of caller iteration order.
    """
    rows = len(weights)
    columns = len(weights[0]) if rows else 0
    if rows == 0 or columns == 0:
        return [None] * rows
    for line in weights:
        if len(line) != columns or any(not math.isfinite(v) or v < 0.0 for v in line):
            raise ValueError("assignment weights must be a finite non-negative rectangle")
    if rows > columns:
        transposed = [[weights[r][c] for r in range(rows)] for c in range(columns)]
        by_column = solve_max_weight(transposed)
        result: list[int | None] = [None] * rows
        for column, row in enumerate(by_column):
            if row is not None:
                result[row] = column
        return result

    top = max(max(line) for line in weights)
    cost = [[top - value for value in line] for line in weights]
    u = [0.0] * (rows + 1)
    v = [0.0] * (columns + 1)
    match = [0] * (columns + 1)
    way = [0] * (columns + 1)
    for row in range(1, rows + 1):
        match[0] = row
        column0 = 0
        minimum = [math.inf] * (columns + 1)
        used = [False] * (columns + 1)
        while True:
            used[column0] = True
            row0 = match[column0]
            delta = math.inf
            column1 = 0
            for column in range(1, columns + 1):
                if used[column]:
                    continue
                current = cost[row0 - 1][column - 1] - u[row0] - v[column]
                if current < minimum[column]:
                    minimum[column] = current
                    way[column] = column0
                if minimum[column] < delta:
                    delta = minimum[column]
                    column1 = column
            for column in range(columns + 1):
                if used[column]:
                    u[match[column]] += delta
                    v[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = column1
            if match[column0] == 0:
                break
        while column0:
            previous = way[column0]
            match[column0] = match[previous]
            column0 = previous

    result = [None] * rows
    for column in range(1, columns + 1):
        if match[column] and weights[match[column] - 1][column - 1] > 0.0:
            result[match[column] - 1] = column - 1
    return result


def assign_globally(
    scores: dict[str, dict[str, float]],
    *,
    minimum_score: float,
    minimum_margin: float,
    weight_floor: float,
) -> dict[str, GlobalMatch]:
    """Resolve scene-wide ownership between rows (intents) and columns (cutouts).

    An edge exists when its score reaches ``minimum_score``. The objective maximises
    the sum of ``(score - weight_floor)^2`` so one strong match is never traded for
    two weak ones. After solving, a match is *ambiguous* (and withdrawn) when

    * the row has another still-free column within ``minimum_margin``,
    * an unmatched row wants the same column within ``minimum_margin``, or
    * swapping with another matched row is a near-tie for both rows.

    Every row is returned; rows without a usable edge have ``column=None``.
    """
    row_ids = sorted(scores)
    column_ids = sorted({column for row in scores.values() for column in row})
    for row in row_ids:
        for column, value in scores[row].items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"invalid carrier score for {row} -> {column}: {value!r}")

    def edge(row: str, column: str) -> float:
        value = scores[row].get(column, 0.0)
        return value if value >= minimum_score else 0.0

    weights = [
        [max(0.0, edge(row, column) - weight_floor) ** 2 for column in column_ids]
        for row in row_ids
    ]
    solved = solve_max_weight(weights)
    chosen = {
        row: column_ids[index]
        for row, index in zip(row_ids, solved)
        if index is not None
    }
    owner = {column: row for row, column in chosen.items()}

    output: dict[str, GlobalMatch] = {}
    for row in row_ids:
        column = chosen.get(row)
        ranked = sorted(scores[row].items(), key=lambda item: (-item[1], item[0]))
        if column is None:
            best = ranked[0] if ranked else None
            output[row] = GlobalMatch(
                row=row, column=None, score=best[1] if best else 0.0,
                runner_up_score=None, margin=None,
                rival=owner.get(best[0]) if best else None,
            )
            continue
        score = scores[row][column]
        rivals: list[tuple[float, str]] = []
        for other_column, other_score in scores[row].items():
            if other_column == column:
                continue
            other_owner = owner.get(other_column)
            if other_owner is None:
                # Any still-free column competes, even below the acceptance floor:
                # a barely-accepted match with a near-equal free rival is not proof.
                rivals.append((other_score, other_column))
            elif other_score >= minimum_score and edge(other_owner, column) > 0.0 and (
                scores[other_owner][other_column] - scores[other_owner][column]
                < minimum_margin - _MARGIN_EPSILON
            ):
                rivals.append((other_score, other_column))
        for other_row in row_ids:
            if other_row != row and other_row not in chosen and edge(other_row, column) > 0.0:
                rivals.append((scores[other_row][column], other_row))
        runner_up = max(rivals, key=lambda item: (item[0], item[1])) if rivals else None
        margin = score - runner_up[0] if runner_up else score
        output[row] = GlobalMatch(
            row=row, column=column, score=score,
            runner_up_score=runner_up[0] if runner_up else None,
            margin=margin,
            ambiguous=margin < minimum_margin - _MARGIN_EPSILON,
            rival=runner_up[1] if runner_up else None,
        )
    return output
