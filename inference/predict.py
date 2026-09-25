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
    Logistic       the ridge-penalised logistic model over any features, which
                   M2, M3, M4 and M4's ablations are
    time_folds     train on older sessions, score newer ones
    session_folds  leave whole sessions out
    predictions    every model fitted on each fold and read on its test maps
    Judge          a split's log loss and Brier per model, each with a 95%
                   interval from resampling its sessions, paired across models

A session is one played_on date. Maps played the same evening are not
independent of each other, so a split never parts them.
"""

import datetime
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NamedTuple, Self, TypedDict

from facts.matches import Match
from inference import fit
from inference.fit import Estimate

RIDGE = 16.0                # the pull toward 0 on every coefficient but the intercept: a
                            # prior sd of 0.25 log-odds (1 / 0.25^2), so an effect past
                            # 50% -> 56% per hero or per sd is earned from the maps
TIME_BLOCKS = 5             # the time split's blocks of sessions: the first only trains
SESSION_FOLDS = 10          # the sessions split's folds; fewer where there are fewer sessions
SHRINK = 4.0                # M1: the maps' worth of the overall rate a cell is pulled toward
HERO = "hero:"              # the prefix of a hero's feature; the rest are standardised
BOOTSTRAP = 2000            # resamples of the sessions behind every interval
NO_DIFFERENCE = 1e-9        # a difference in mean log loss this small is none


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


@dataclass(frozen=True)
class Design:
    """The features a fit reads, as the training maps set them: each one's
    column in the coefficients, and a standardised feature's scale. A hero's
    +1 or -1 is read as it is; a feature that never varies on the training
    maps is dropped, and one they never held reads 0."""
    columns: dict[str, int]
    scales: dict[str, _Scale]

    @classmethod
    def over(cls, seen: Sequence[dict[str, float]]) -> Self:
        """The design the training maps' features make."""
        keys = sorted({k for features in seen for k in features})
        scales = {}
        for key in keys:
            if not key.startswith(HERO):
                values = [features.get(key, 0.0) for features in seen]
                sd = statistics.pstdev(values) if len(values) > 1 else 0.0
                scales[key] = _Scale(statistics.fmean(values), sd)
        kept = [k for k in keys if k not in scales or scales[k].sd > 0]
        return cls({k: i for i, k in enumerate(kept, 1)}, scales)

    def row(self, features: dict[str, float]) -> dict[int, float]:
        """A map's features as the fit reads them: index -> value."""
        out = {}
        for key, value in features.items():
            i = self.columns.get(key)
            if i is not None:
                scale = self.scales.get(key)
                out[i] = value if scale is None else (value - scale.mean) / scale.sd
        return out


@dataclass(frozen=True)
class _Fitted:
    """A fitted logistic model: what it reads, its design and coefficients."""
    read: Reader
    design: Design
    coef: list[float]

    def __call__(self, ex: Example) -> float:
        return fit.predict(self.coef, self.design.row(self.read(ex)))


@dataclass(frozen=True)
class Logistic:
    """A ridge-penalised logistic model over the features `read` gives,
    fitted when called on the training maps -> their Predictor."""
    read: Reader

    def __call__(self, train: Sequence[Example]) -> Predictor:
        seen = [self.read(ex) for ex in train]
        design = Design.over(seen)
        coef = fit.fit([design.row(f) for f in seen], [ex.won for ex in train],
                       len(design.columns), RIDGE)
        return _Fitted(self.read, design, coef)


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
        Logistic(map_win)),
    Model("M3", "heroes: one effect per hero", False, Logistic(heroes)),
    Model("M4", "heroes + playbook score + matchup metrics", False, Logistic(playbook(""))),
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


# --- the scores -----------------------------------------------------------------

class ModelScore(TypedDict):
    """One model on one split: log loss and Brier with their intervals, and
    its log loss minus the coin flip's on the same maps."""
    id: str
    label: str
    rate_derived: bool
    log_loss: Estimate
    brier: Estimate
    vs_coin: Estimate


def reading(diff: Estimate) -> int:
    """-1 where a difference's interval lies wholly below 0, 1 wholly above,
    0 across it - or within NO_DIFFERENCE of it, where two models that read
    the same features differ only in their last bits."""
    if diff["high"] < -NO_DIFFERENCE:
        return -1
    return 1 if diff["low"] > NO_DIFFERENCE else 0


class Scores(NamedTuple):
    """A split's predictions: model id -> match id -> blue's chance, and
    the scored maps grouped by session."""
    predictions: dict[str, dict[int, float]]
    sessions: list[list[Example]]


def predictions(folds: Sequence[Fold], models: Sequence[Model]) -> Scores:
    """Every model fitted on each fold's training maps and read on its test
    maps: each scored map once."""
    predictions: dict[str, dict[int, float]] = {m.id: {} for m in models}
    tested: dict[datetime.date, list[Example]] = {}
    for fold in folds:
        for ex in fold.test:
            tested.setdefault(ex.match.played_on, []).append(ex)
        for model in models:
            predictor = model.fit(fold.train)
            out = predictions[model.id]
            for ex in fold.test:
                out[ex.match.match_id] = predictor(ex)
    return Scores(predictions, [tested[day] for day in sorted(tested)])


class Judge:
    """One split's scores: every interval bootstrapped over the same
    resamples of its sessions, so two models' intervals are paired."""

    def __init__(self, name: str, scored: Scores) -> None:
        self.seed = "validate|%s" % name
        self.scored = scored

    def _groups(self, loss: Callable[[float, int], float], model: str,
                baseline: str | None = None) -> list[list[float]]:
        """Each session's per-map losses under `model`, less the baseline's."""
        chance = self.scored.predictions
        out = []
        for session in self.scored.sessions:
            values = []
            for ex in session:
                key = ex.match.match_id
                value = loss(chance[model][key], ex.won)
                if baseline is not None:
                    value -= loss(chance[baseline][key], ex.won)
                values.append(value)
            out.append(values)
        return out

    def estimate(self, model: str, baseline: str | None = None,
                 loss: Callable[[float, int], float] = fit.log_loss) -> Estimate:
        return fit.bootstrap(self._groups(loss, model, baseline), draws=BOOTSTRAP,
                             seed=self.seed)

    def model(self, spec: Model) -> ModelScore:
        return ModelScore(
            id=spec.id, label=spec.label, rate_derived=spec.rate_derived,
            log_loss=self.estimate(spec.id), brier=self.estimate(spec.id, loss=fit.brier),
            vs_coin=self.estimate(spec.id, "M0"))
