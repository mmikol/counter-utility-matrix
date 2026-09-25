"""The models inference.validate scores and the splits it scores them on.
A model is fitted on some recorded maps and gives each other map blue's
win chance; a split says which maps each fit trains on and which it is
scored on.

    Example        a decided map as the models read it
    MODELS         M0 a coin flip; M1 the map and side's base rate; M2 blue's
                   team.map_win_mean minus red's (rate-derived: personal use);
                   M3 one effect per hero in a ridge-penalised logistic model;
                   M4 M3 plus the playbook score difference and the matchup
                   metrics
    logistic       the ridge-penalised logistic model over any features, which
                   M2, M3, M4 and M4's ablations are
    time_folds     train on older sessions, score newer ones
    session_folds  leave whole sessions out

A session is one played_on date. Maps played the same evening are not
independent of each other, so a split never parts them.
"""

import datetime
import statistics
from collections.abc import Callable, Sequence
from typing import NamedTuple

from facts.matches import Match
from inference import fit

RIDGE = 16.0                # the pull toward 0 on every coefficient but the intercept: a
                            # prior sd of 0.25 log-odds (1 / 0.25^2), so an effect past
                            # 50% -> 56% per hero or per sd is earned from the maps
TIME_BLOCKS = 5             # the time split's blocks of sessions: the first only trains
SESSION_FOLDS = 10          # the sessions split's folds; fewer where there are fewer sessions
SHRINK = 4.0                # M1: the maps' worth of the overall rate a cell is pulled toward
HERO = "hero:"              # the prefix of a hero's feature; the rest are standardised


# --- the models -----------------------------------------------------------------

class Example(NamedTuple):
    """A decided map as the models read it: the map, whether blue won, and
    its features - each hero's +1 or -1 (a hero on both sides nets out),
    the rate-derived map win difference, the matchup metrics, and the
    playbook score difference in full and with each family dropped."""
    match: Match
    won: int
    heroes: dict[str, float]
    map_win: float
    matchup: dict[str, float]
    score: dict[str, float]         # "" -> the full difference, family -> without it


# a fitted model: a decided map's win chance
type Predictor = Callable[[Example], float]
# how a model reads a map: its features by name
type Reader = Callable[[Example], dict[str, float]]


class Model(NamedTuple):
    """A model or an ablation of M4: its id, what it is, whether it reads the
    rates (personal use), and how it is fitted on the training maps."""
    id: str
    label: str
    rate_derived: bool
    fit: Callable[[Sequence[Example]], Predictor]


def coin(train: Sequence[Example]) -> Predictor:
    """M0: every map an even chance."""
    return lambda ex: 0.5


def _cell(ex: Example) -> tuple[str, str]:
    return ex.match.map_name, ex.match.side


def base_rate(train: Sequence[Example]) -> Predictor:
    """M1: the map and side's win rate over the training maps, pulled toward
    the overall rate by SHRINK maps' worth of it; the overall rate is itself
    pulled toward an even chance by one win and one loss."""
    overall = (sum(ex.won for ex in train) + 1.0) / (len(train) + 2.0)
    wins: dict[tuple[str, str], int] = {}
    maps: dict[tuple[str, str], int] = {}
    for ex in train:
        cell = _cell(ex)
        wins[cell] = wins.get(cell, 0) + ex.won
        maps[cell] = maps.get(cell, 0) + 1

    def predict(ex: Example) -> float:
        cell = _cell(ex)
        return (wins.get(cell, 0) + SHRINK * overall) / (maps.get(cell, 0) + SHRINK)
    return predict


class _Scale(NamedTuple):
    """A standardised feature's training mean and sd."""
    mean: float
    sd: float


def logistic(read: Reader) -> Callable[[Sequence[Example]], Predictor]:
    """A ridge-penalised logistic model over the features `read` gives: a
    hero's +1 or -1 as it is, every other feature standardised on the
    training maps (one that never varies there is dropped). A feature the
    training maps never held reads 0."""
    def train_on(train: Sequence[Example]) -> Predictor:
        seen = [read(ex) for ex in train]
        keys = sorted({k for features in seen for k in features})
        scales: dict[str, _Scale] = {}
        for key in keys:
            if key.startswith(HERO):
                continue
            values = [features.get(key, 0.0) for features in seen]
            sd = statistics.pstdev(values) if len(values) > 1 else 0.0
            scales[key] = _Scale(statistics.fmean(values), sd)
        keys = [k for k in keys if k.startswith(HERO) or scales[k].sd > 0]
        index = {k: i for i, k in enumerate(keys, 1)}

        def row(features: dict[str, float]) -> dict[int, float]:
            out = {}
            for key, value in features.items():
                i = index.get(key)
                if i is None:
                    continue
                scale = scales.get(key)
                out[i] = value if scale is None else (value - scale.mean) / scale.sd
            return out
        coef = fit.fit([row(f) for f in seen], [ex.won for ex in train], len(keys), RIDGE)
        return lambda ex: fit.predict(coef, row(read(ex)))
    return train_on


def heroes(ex: Example) -> dict[str, float]:
    """M3's features: each hero's +1 or -1."""
    return dict(ex.heroes)


def map_win(ex: Example) -> dict[str, float]:
    """M2's feature: blue's map win rate minus red's."""
    return {"map_win": ex.map_win}


def playbook(family: str | None) -> Reader:
    """M4's features: the heroes, the matchup metrics and the playbook score
    difference - with `family` dropped, or with no score at all where
    family is None."""
    def read(ex: Example) -> dict[str, float]:
        features = {**ex.heroes, **ex.matchup}
        if family is not None:
            features["score"] = ex.score[family]
        return features
    return read


MODELS = (
    Model("M0", "coin flip", False, coin),
    Model("M1", "map and side base rate", False, base_rate),
    Model(
        "M2", "map win rate, blue minus red (rate-derived: personal use)", True,
        logistic(map_win)),
    Model("M3", "heroes: one effect per hero", False, logistic(heroes)),
    Model("M4", "heroes + playbook score + matchup metrics", False, logistic(playbook(""))),
)


# --- the splits -----------------------------------------------------------------

class Fold(NamedTuple):
    """The maps one fit trains on and the maps it is scored on."""
    train: list[Example]
    test: list[Example]


def sessions(rows: Sequence[Example]) -> list[datetime.date]:
    """The days the maps were played on, oldest first."""
    return sorted({ex.match.played_on for ex in rows})


def time_folds(rows: Sequence[Example]) -> list[Fold]:
    """Train on older sessions, score the newer: the sessions in date order
    cut into TIME_BLOCKS blocks of about equal maps, and each block after
    the first scored by a fit on every block before it. A fold never trains
    on a map played on or after a day it scores."""
    total = len(rows)
    block: dict[datetime.date, int] = {}
    before = 0
    for day in sessions(rows):
        block[day] = min(TIME_BLOCKS - 1, TIME_BLOCKS * before // total)
        before += sum(1 for ex in rows if ex.match.played_on == day)
    folds = []
    for k in range(1, TIME_BLOCKS):
        train = [ex for ex in rows if block[ex.match.played_on] < k]
        test = [ex for ex in rows if block[ex.match.played_on] == k]
        if train and test:
            folds.append(Fold(train, test))
    return folds


def session_folds(rows: Sequence[Example]) -> list[Fold]:
    """Leave sessions out: the sessions in date order dealt round into
    SESSION_FOLDS folds (one per session where there are fewer), each
    scored by a fit on the others. Two sessions at least."""
    days = sessions(rows)
    count = min(SESSION_FOLDS, len(days))
    if count < 2:
        return []
    fold_of = {day: i % count for i, day in enumerate(days)}
    return [Fold([ex for ex in rows if fold_of[ex.match.played_on] != k],
                 [ex for ex in rows if fold_of[ex.match.played_on] == k])
            for k in range(count)]


SPLITS: tuple[tuple[str, str, Callable[[Sequence[Example]], list[Fold]]], ...] = (
    ("time", "trained on older sessions, scored on newer ones", time_folds),
    ("sessions", "each session scored by a fit that left it out", session_folds),
)
