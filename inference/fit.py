"""The statistics the validation reads, in pure Python: a ridge-penalised
logistic model fitted by Newton's method over sparse rows, the two scores a
win chance is judged by, the bootstrap over sessions that puts an interval
on a mean score, and the sample an effect needs.

    fit            the coefficients of a ridge-penalised logistic model: the
                   intercept free, every other coefficient pulled toward 0
    predict        a row's win chance under them
    log_loss       -ln of the chance given to what happened: ln 2 (0.693) is
                   the coin flip
    brier          the squared miss: 0.25 is the coin flip
    bootstrap      a mean over maps and its 95% interval, resampling whole
                   sessions, since maps played the same day are not independent
    maps_needed    the decided maps an effect of b log-odds per sd needs:
                   (5.6 / b)^2, 80% power at a two-sided 5% level
"""

import math
import random
from collections.abc import Mapping, Sequence
from typing import TypedDict

# a row of a design: feature index -> value, the intercept (index 0) implied
type Row = Mapping[int, float]

CLIP = 1e-6                 # the least chance a prediction gives either outcome
NEWTON_STEPS = 50           # a fit that has not settled by then keeps its last step
SETTLED = 1e-8              # a Newton step this small in every coefficient ends the fit
Z_POWER = 5.6               # (1.96 + 0.84) / 0.5: a two-sided 5% test at 80% power, over
                            # the sd of an even map's result


class Estimate(TypedDict):
    """A mean and its 95% bootstrap interval."""
    value: float
    low: float
    high: float


def sigmoid(z: float) -> float:
    """The logistic function, safe at either extreme."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def log_odds(p: float) -> float:
    """ln(p / (1 - p)): a win chance as the logistic model reads it."""
    return math.log(p / (1.0 - p))


def maps_needed(effect: float) -> int:
    """The decided maps that tell an effect of `effect` log-odds per sd from
    none: (Z_POWER / b)^2, rounded up. 50% -> 60% is 0.405 and needs 191
    maps; 50% -> 55% is 0.201 and needs 779."""
    return math.ceil((Z_POWER / abs(effect)) ** 2)


def predict(coef: Sequence[float], row: Row) -> float:
    """The win chance a fitted model gives a row."""
    return sigmoid(coef[0] + sum(coef[j] * v for j, v in row.items()))


def log_loss(p: float, won: int) -> float:
    """-ln of the chance p gave the outcome, p clipped to [CLIP, 1 - CLIP]."""
    p = min(1.0 - CLIP, max(CLIP, p))
    return -math.log(p if won else 1.0 - p)


def brier(p: float, won: int) -> float:
    """The squared distance between the chance and the outcome."""
    return (p - won) ** 2


# a row as the fit walks it: (index, value) pairs by index, the intercept's first
type Items = tuple[tuple[int, float], ...]


def _items(row: Row) -> Items:
    """A row as the fit walks it."""
    return ((0, 1.0), *sorted(row.items()))


def _objective(
        coef: Sequence[float], rows: Sequence[Items], wins: Sequence[int],
        penalty: float) -> float:
    """The penalised negative log-likelihood the fit minimises."""
    total = 0.5 * penalty * sum(c * c for c in coef[1:])
    for items, won in zip(rows, wins, strict=True):
        z = sum(coef[j] * v for j, v in items)
        # ln(1 + e^z) - won * z, written so neither extreme overflows
        total += (z if z > 0 else 0.0) + math.log1p(math.exp(-abs(z))) - won * z
    return total


def _newton_step(coef: Sequence[float], rows: Sequence[Items], wins: Sequence[int],
                 penalty: float) -> list[float]:
    """The Newton step from coef: the Hessian's solve against the gradient.
    Each row touches only its own features, so a row costs the square of
    what it holds, not of the design's width; the Hessian's upper triangle
    is summed and mirrored."""
    width = len(coef)
    grad = [0.0] * width
    hess = [[0.0] * width for _ in range(width)]
    for items, won in zip(rows, wins, strict=True):
        p = sigmoid(sum(coef[j] * v for j, v in items))
        weight, miss = p * (1.0 - p), p - won
        for a, (j, vj) in enumerate(items):
            grad[j] += miss * vj
            line, scaled = hess[j], weight * vj
            for k, vk in items[a:]:
                line[k] += scaled * vk
    for j in range(width):
        for k in range(j):
            hess[j][k] = hess[k][j]
    for j in range(1, width):
        grad[j] += penalty * coef[j]
        hess[j][j] += penalty
    hess[0][0] += 1e-9                  # an intercept the rows barely move stays solvable
    return _solve(hess, grad)


def _solve(matrix: list[list[float]], vector: Sequence[float]) -> list[float]:
    """x with matrix x = vector, matrix symmetric positive definite, by
    Cholesky: L L' = matrix, then two triangular solves."""
    n = len(vector)
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                lower[i][i] = math.sqrt(max(s, 1e-12))
            else:
                lower[i][j] = s / lower[j][j]
    y = [0.0] * n
    for i in range(n):
        y[i] = (vector[i] - sum(lower[i][k] * y[k] for k in range(i))) / lower[i][i]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (y[i] - sum(lower[k][i] * x[k] for k in range(i + 1, n))) / lower[i][i]
    return x


def fit(rows: Sequence[Row], wins: Sequence[int], width: int, penalty: float) -> list[float]:
    """The coefficients - the intercept, then one per feature index 1..width
    - that minimise the negative log-likelihood plus penalty/2 x the sum of
    the squared non-intercept coefficients. Newton's method, halving a step
    that would raise the objective; the penalty keeps it finite where the
    rows separate the outcomes. No rows fits the intercept 0."""
    coef = [0.0] * (width + 1)
    if not rows:
        return coef
    walked = [_items(row) for row in rows]
    current = _objective(coef, walked, wins, penalty)
    for _ in range(NEWTON_STEPS):
        step = _newton_step(coef, walked, wins, penalty)
        scale = 1.0
        while True:
            trial = [c - scale * s for c, s in zip(coef, step, strict=True)]
            value = _objective(trial, walked, wins, penalty)
            if value <= current + 1e-12 or scale < 1e-6:
                break
            scale /= 2.0
        coef, current = trial, value
        if max(abs(scale * s) for s in step) < SETTLED:
            break
    return coef


def bootstrap(groups: Sequence[Sequence[float]], *, draws: int, seed: str) -> Estimate:
    """The mean of every value in `groups` and its 95% interval: `draws`
    resamples of whole groups (sessions) with replacement, each read as the
    mean over the maps it holds. The seed is a string, so the same groups
    draw the same resamples and two scores bootstrapped on one split are
    paired."""
    sums = [sum(group) for group in groups]
    counts = [len(group) for group in groups]
    total = sum(counts)
    if not total:
        return Estimate(value=0.0, low=0.0, high=0.0)
    value = sum(sums) / total
    rng = random.Random(seed)       # nosec B311  # a seeded resample, not a secret
    means = []
    for _ in range(draws):
        s = c = 0.0
        for _ in groups:
            i = rng.randrange(len(groups))
            s += sums[i]
            c += counts[i]
        means.append(s / c if c else value)
    means.sort()
    return Estimate(value=value, low=means[int(0.025 * (draws - 1))],
                    high=means[math.ceil(0.975 * (draws - 1))])
