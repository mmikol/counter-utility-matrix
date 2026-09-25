"""The playbook against the owner's recorded matches: does its score say
anything about who won that the heroes alone do not?

Recorded matches are the second input the owner writes, beside the
strategies. Each is one map (facts.matches.Match): both sixes, the bans,
the map, blue's side, blue's result, and the digest of the playbook in
force when it was played. Blue is always the owner's team.

    families    the playbook's scoring strategies in the groups an ablation
                drops together - side bonuses, counters, synergy, the rates,
                the other scored constraints, the rest - each named by the
                ids it holds
    pins        the digests the matches were played under; a playbook is
                judged only on the maps from the first one played under it,
                so it is never judged on the maps it was tuned on
    rescore     each map through engine.evaluate from both seats - blue's six
                against red's on blue's side, red's against blue's on the
                other - with the team and matchup metrics of both sixes
    examples    the decided maps as the models read them, and M4's ablations
    assess      the models fitted and scored out of sample on two splits,
                the ablations, the guard and the verdict -> a Validation
    validate    pins, rescore and assess in one call
    rendered    a Validation as text

The models (M0 a coin flip up to M4, the heroes plus the playbook score
and the matchups) and the splits (older sessions against newer ones, and
whole sessions left out) are inference.predict's; each model is judged by
log loss and Brier on maps it was not fitted on, with a 95% interval from
resampling sessions. Below the decided maps an effect needs - (5.6 / b)^2
for b log-odds per sd - the report says so and gives no verdict. Nothing
here writes; the maps are read, never tuned on.
"""

import datetime
import statistics
from collections.abc import Callable, Iterable, Sequence
from typing import NamedTuple, NotRequired, TypedDict

from db import Log, Refusal
from facts.compute import matchup_metrics
from facts.draft import Draft, opposite
from facts.matches import Match
from facts.model import World
from facts.team import VERSUS_METRICS, numbers, team_metrics
from inference import engine, fit, predict
from inference.fit import Estimate
from inference.strategy import Strategy

BOOTSTRAP = 2000            # resamples of the sessions behind every interval
EFFECT = 0.60              # the win chance the guard's effect moves an even map to
REFERENCE_EFFECTS = (0.60, 0.55)    # the effects the guard always quotes
POOL = 2                    # the field evaluate ranks against: a six's score is the
                            # same at any pool, since the scale is drawn at its own
PROGRESS_EVERY = 10         # maps rescored between progress lines
NO_DIFFERENCE = 1e-9        # a difference in mean log loss this small is none

WIN, LOSS, DRAW = "win", "loss", "draw"


# --- the families ---------------------------------------------------------------

def _keyed(sections: Iterable[str], keys: Iterable[str]) -> frozenset[str]:
    """Every section.key pair, as a strategy names a metric."""
    keys = tuple(keys)
    return frozenset("%s.%s" % (s, k) for s in sections for k in keys)


# the metrics each family is recognised by, as a strategy's metric, confidence
# or expressions name them
SIDE_KEYS = frozenset({"map.side"})
COUNTER_KEYS = _keyed(("team",), VERSUS_METRICS) | {"matchup.exposure_share"}
SYNERGY_KEYS = _keyed(("team", "enemy"), (
    "synergy_edges", "synergy_score", "synergy_density", "isolated_count", "isolated",
    "core_size", "pairs"))
# Blizzard's rates: the meta and map sections of the team metrics, and the map's
# style, which the per-map rates lift
RATE_KEYS = _keyed(("team", "enemy"), (
    "win_mean", "pick_mass", "availability", "map_availability", "max_ban_rate",
    "max_ban_hero", "rank_sensitive_count", "trend_sum", "map_win_mean", "map_pick_mass",
    "map_specialists", "map_offmap", "home_map_hits", "style_fit")) | {
    "map.style_top", "map.style_margin"}


class Family(NamedTuple):
    """Strategies an ablation drops together: the family's name, what it
    is, and the ids of the playbook's strategies in it."""
    name: str
    meaning: str
    ids: tuple[str, ...]


def _names(strategy: Strategy) -> set[str]:
    """Every metric a strategy reads: its metric, its confidence, and the
    names its expressions read."""
    names = {n for n in (strategy.metric, strategy.confidence) if n}
    for expr in (strategy.when, strategy.require, strategy.bonus, strategy.penalty):
        if expr is not None:
            names |= set(expr.names)
    return names


def scores(strategy: Strategy) -> bool:
    """Whether a strategy moves a six's score: a heuristic, a scored
    constraint or a soft limit. A hard limit prunes and adds nothing."""
    return strategy.form in ("heuristic", "scored") or (
        strategy.form == "limit" and strategy.soft)


# the families in the order a strategy is filed: the first whose test it meets
FAMILY_TESTS: tuple[tuple[str, str, Callable[[Strategy], bool]], ...] = (
    ("side", "the side bonuses: rules that read map.side",
        lambda s: bool(_names(s) & SIDE_KEYS)),
    ("counters", "the counter family: rules on the counters table's edges",
        lambda s: bool(_names(s) & COUNTER_KEYS)),
    ("synergy", "cohesion: rules on the wiki's synergy pairs",
        lambda s: bool(_names(s) & SYNERGY_KEYS)),
    ("rates", "the rate-reading rules: Blizzard's win, pick and ban rates",
        lambda s: bool(_names(s) & RATE_KEYS)),
    ("scored", "the other scored constraints", lambda s: s.form == "scored"),
    ("other", "the rest that scores: kit heuristics and soft limits", lambda s: True),
)


def families(catalog: Sequence[Strategy]) -> list[Family]:
    """The playbook's scoring strategies, each in the first family whose
    test it meets; a family the playbook holds nothing of is left out."""
    filed: dict[str, list[str]] = {}
    for strategy in catalog:
        if not scores(strategy):
            continue
        name = next(name for name, _meaning, test in FAMILY_TESTS if test(strategy))
        filed.setdefault(name, []).append(strategy.id)
    return [Family(name, meaning, tuple(sorted(filed[name])))
            for name, meaning, _test in FAMILY_TESTS if name in filed]


# --- the pin --------------------------------------------------------------------

class Pin(TypedDict):
    """One digest the recorded maps were played under: how many, the first
    and last date, and whether it is the playbook this run judges."""
    digest: str
    maps: int
    first: str
    last: str
    judged: bool


def pins(matches: Sequence[Match], digest: str) -> list[Pin]:
    """Each digest the matches were played under, in the order it first
    appears; the matches are oldest first."""
    table: dict[str, Pin] = {}
    for match in matches:
        day = match.played_on.isoformat()
        pin = table.setdefault(match.playbook_digest, Pin(
            digest=match.playbook_digest, maps=0, first=day, last=day,
            judged=match.playbook_digest == digest))
        pin["maps"] += 1
        pin["last"] = day
    return list(table.values())


def pinned(matches: Sequence[Match], digest: str) -> list[Match]:
    """The maps a playbook may be judged on: from the first one played under
    its digest on, whatever digest the later ones carry. A map before it may
    be one the playbook was tuned on; none, where no map carries it."""
    for i, match in enumerate(matches):
        if match.playbook_digest == digest:
            return list(matches[i:])
    return []


# --- the rescore ----------------------------------------------------------------

class Rescored(NamedTuple):
    """One recorded map through the engine: each seat's playbook score from
    evaluate on its own seat's scale, each seat's term per strategy id, both
    sixes' numeric team metrics (each against the other) and the matchup
    metrics from blue's seat."""
    match: Match
    blue_score: float
    red_score: float
    blue_terms: dict[str, float]
    red_terms: dict[str, float]
    blue_team: dict[str, float]
    red_team: dict[str, float]
    matchup: dict[str, float]


class Refused(NamedTuple):
    """A recorded map the engine would not score, and why."""
    match_id: int
    reason: str


class Rescoring(NamedTuple):
    """What the rescore made of the maps: the scored ones and the refused."""
    scored: list[Rescored]
    refused: list[Refused]


def seats(match: Match) -> tuple[Draft, Draft]:
    """The map from each seat: blue's six against red's on blue's side, and
    red's against blue's on the other side."""
    return (Draft(map_name=match.map_name, red=match.red, blue=match.blue, bans=match.bans,
                  side=match.side),
            Draft(map_name=match.map_name, red=match.blue, blue=match.red, bans=match.bans,
                  side=opposite(match.side)))


def rescored(
        world: World, match: Match, catalog: list[Strategy],
        pool_size: int = POOL) -> Rescored:
    """One map rescored: engine.evaluate from both seats, then the team and
    matchup metrics. A board the engine refuses raises its Refusal."""
    blue_seat, red_seat = seats(match)
    blue = engine.evaluate(world, blue_seat, catalog=catalog, pool_size=pool_size)
    red = engine.evaluate(world, red_seat, catalog=catalog, pool_size=pool_size)
    m, red_h, blue_h, _bans = world.resolve(match.map_name, match.red, match.blue, match.bans)
    blue_team = team_metrics(world, blue_h, m, red_h, lean=True)
    red_team = team_metrics(world, red_h, m, blue_h, lean=True)
    return Rescored(
        match=match, blue_score=blue.score, red_score=red.score,
        blue_terms={c["id"]: c["weighted"] for c in blue.contributions},
        red_terms={c["id"]: c["weighted"] for c in red.contributions},
        blue_team=numbers(blue_team), red_team=numbers(red_team),
        matchup=numbers(matchup_metrics(blue_team, red_team)))


def rescore(world: World, matches: Sequence[Match], catalog: list[Strategy], *,
            pool_size: int = POOL, log: Log | None = None) -> Rescoring:
    """Every map rescored, in order; a map the engine refuses - a hero the
    database no longer holds, a board no six satisfies - is listed with the
    reason instead. A progress line every PROGRESS_EVERY maps goes to `log`."""
    done, refused = [], []
    for i, match in enumerate(matches, 1):
        try:
            done.append(rescored(world, match, catalog, pool_size))
        except Refusal as error:
            refused.append(Refused(match.match_id, str(error)))
        if log is not None and (i % PROGRESS_EVERY == 0 or i == len(matches)):
            log("validate: %d of %d maps rescored" % (i, len(matches)))
    return Rescoring(done, refused)


def without(row: Rescored, ids: Iterable[str]) -> float:
    """Blue's score minus red's, less every term of the strategies named:
    the playbook score difference with a family dropped. The scale each
    heuristic is normalised on stays the full playbook's."""
    dropped = set(ids)
    blue = row.blue_score - sum(v for k, v in row.blue_terms.items() if k in dropped)
    red = row.red_score - sum(v for k, v in row.red_terms.items() if k in dropped)
    return blue - red


# --- the guard ------------------------------------------------------------------

class Guard(TypedDict):
    """Whether the decided maps are enough for the effect asked about: the
    maps, the effect as a win chance and in log-odds, the maps it needs,
    the maps each reference effect needs, and the verdict's first words."""
    decided: int
    effect: float
    log_odds: float
    needed: int
    reference: dict[str, int]
    enough: bool
    text: str


def check_effect(effect: float) -> float:
    """An effect as the guard takes it: a win chance above one half and
    below 1, else a Refusal."""
    if not 0.5 < effect < 1.0:
        raise Refusal("effect is a win chance above 0.5 and below 1, got %r" % effect)
    return effect


def guard(decided: int, effect: float = EFFECT) -> Guard:
    """The data guard: (5.6 / b)^2 decided maps for an effect b in log-odds
    per sd, b the log-odds of `effect` - the win chance the effect moves an
    even map to. Below it, the text says so plainly."""
    b = fit.log_odds(check_effect(effect))
    needed = fit.maps_needed(b)
    reference = {"%.2f" % p: fit.maps_needed(fit.log_odds(p)) for p in REFERENCE_EFFECTS}
    enough = decided >= needed
    quoted = "; ".join("50%% -> %d%% needs %d" % (round(100 * float(p)), n)
                       for p, n in reference.items())
    if enough:
        text = ("%d decided maps: enough to tell an even map from one won %d%% of the time"
                " (%d needed)." % (decided, round(100 * effect), needed))
    else:
        text = ("%d decided maps, and telling an even map from one won %d%% of the time"
                " needs %d (%s): too few for a verdict. The scores below are what the"
                " maps say so far, not a finding."
                % (decided, round(100 * effect), needed, quoted))
    return Guard(decided=decided, effect=effect, log_odds=b, needed=needed,
                 reference=reference, enough=enough, text=text)


# --- the examples ---------------------------------------------------------------

def examples(rows: Sequence[Rescored], kin: Sequence[Family]) -> list[predict.Example]:
    """The decided maps among the rescored ones, as the models read them."""
    out = []
    for row in rows:
        if row.match.result not in (WIN, LOSS):
            continue
        heroes: dict[str, float] = {}
        for names, sign in ((row.match.blue, 1.0), (row.match.red, -1.0)):
            for name in names:
                key = predict.HERO + name
                heroes[key] = heroes.get(key, 0.0) + sign
        score = {"": row.blue_score - row.red_score}
        score.update((f.name, without(row, f.ids)) for f in kin)
        out.append(predict.Example(
            match=row.match, won=1 if row.match.result == WIN else 0,
            heroes={k: v for k, v in heroes.items() if v},
            map_win=row.blue_team.get("map_win_mean", 0.0) - row.red_team.get(
                "map_win_mean", 0.0),
            matchup={"matchup." + k: v for k, v in sorted(row.matchup.items())},
            score=score))
    return out


def ablations(kin: Sequence[Family]) -> list[predict.Model]:
    """M4 with one family dropped from the playbook score, then with the
    score dropped whole: each named by the family and its ids."""
    out = [predict.Model(
        "M4-%s" % f.name, "M4 without %s (%s)" % (f.name, ", ".join(f.ids)), False,
        predict.logistic(predict.playbook(f.name))) for f in kin]
    if kin:
        out.append(predict.Model("M4-playbook", "M4 without the playbook score", False,
                                 predict.logistic(predict.playbook(None))))
    return out


# --- the report -----------------------------------------------------------------

class ModelScore(TypedDict):
    """One model on one split: log loss and Brier with their intervals, and
    its log loss minus the coin flip's on the same maps."""
    id: str
    label: str
    rate_derived: bool
    log_loss: Estimate
    brier: Estimate
    vs_coin: Estimate


class Ablation(TypedDict):
    """M4 with one family dropped: its log loss, and that minus M4's on the
    same maps - above 0, the family was carrying weight."""
    id: str
    family: str
    ids: list[str]
    log_loss: Estimate
    vs_full: Estimate


class SplitReport(TypedDict):
    """One split: its folds, the maps and sessions it scored, each model,
    M4 minus M3 (what the playbook and the matchups add to the heroes), the
    ablations, and the verdict - None while the guard holds it back."""
    name: str
    meaning: str
    folds: int
    scored: int
    sessions: int
    models: list[ModelScore]
    playbook_adds: Estimate | None
    ablations: list[Ablation]
    verdict: str | None


class HeroEffect(TypedDict):
    """A hero's effect in M3 fitted on every decided map, in log-odds, and
    the maps it was on either side."""
    hero: str
    effect: float
    maps: int


class ScoreEffect(TypedDict):
    """The playbook score difference's effect in M4 fitted on every decided
    map, in log-odds per sd, and the decided maps an effect that size needs."""
    log_odds: float
    needed: int


class MatchRow(TypedDict):
    """One judged map: what was recorded, each seat's playbook score, the
    rate-derived map win difference, the matchup metrics, and the chance
    each model gave blue on each split, where the split scored it."""
    match_id: int
    played_on: str
    map: str
    side: str
    result: str
    digest: str
    note: str
    blue: list[str]
    red: list[str]
    blue_score: float
    red_score: float
    map_win_diff: float
    matchup: dict[str, float]
    predictions: dict[str, dict[str, float]]
    blue_team: NotRequired[dict[str, float]]
    red_team: NotRequired[dict[str, float]]


class FamilyRecord(TypedDict):
    """A family as the report lists it."""
    name: str
    meaning: str
    ids: list[str]


class Playbook(TypedDict):
    """The playbook judged: its folder, its digest, whether anything in it
    scores, and its families."""
    name: str
    digest: str
    scoring: bool
    families: list[FamilyRecord]


class Counts(TypedDict):
    """The maps: recorded, set aside by the pin, refused by the engine,
    judged, and of those decided, won, lost and drawn, over how many
    sessions."""
    recorded: int
    set_aside: int
    refused: int
    judged: int
    decided: int
    won: int
    lost: int
    drawn: int
    sessions: int


class RefusedRecord(TypedDict):
    """A map the engine refused, and why."""
    match_id: int
    reason: str


class Validation(TypedDict):
    """The whole run, JSON-ready: the playbook, whether the pin held, the
    digests, the counts, the refused maps, the guard, each split, the hero
    and score effects fitted on every decided map, each judged map, and the
    verdict in words."""
    playbook: Playbook
    pinned: bool
    pins: list[Pin]
    counts: Counts
    refused: list[RefusedRecord]
    guard: Guard
    splits: list[SplitReport]
    heroes: list[HeroEffect]
    score_effect: ScoreEffect | None
    matches: list[MatchRow]
    verdict: str


def reading(diff: Estimate) -> int:
    """-1 where a difference's interval lies wholly below 0, 1 wholly above,
    0 across it - or within NO_DIFFERENCE of it, where two models that read
    the same features differ only in their last bits."""
    if diff["high"] < -NO_DIFFERENCE:
        return -1
    return 1 if diff["low"] > NO_DIFFERENCE else 0


class _Scores(NamedTuple):
    """A split's predictions: model id -> match id -> blue's chance, and
    the scored maps grouped by session."""
    predictions: dict[str, dict[int, float]]
    sessions: list[list[predict.Example]]


def _predict(folds: Sequence[predict.Fold], models: Sequence[predict.Model]) -> _Scores:
    """Every model fitted on each fold's training maps and read on its test
    maps: each scored map once."""
    predictions: dict[str, dict[int, float]] = {m.id: {} for m in models}
    tested: dict[datetime.date, list[predict.Example]] = {}
    for fold in folds:
        for ex in fold.test:
            tested.setdefault(ex.match.played_on, []).append(ex)
        for model in models:
            predictor = model.fit(fold.train)
            out = predictions[model.id]
            for ex in fold.test:
                out[ex.match.match_id] = predictor(ex)
    return _Scores(predictions, [tested[day] for day in sorted(tested)])


class _Judge:
    """One split's scores: every interval bootstrapped over the same
    resamples of its sessions, so two models' intervals are paired."""

    def __init__(self, name: str, scored: _Scores) -> None:
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

    def model(self, spec: predict.Model) -> ModelScore:
        return ModelScore(
            id=spec.id, label=spec.label, rate_derived=spec.rate_derived,
            log_loss=self.estimate(spec.id), brier=self.estimate(spec.id, loss=fit.brier),
            vs_coin=self.estimate(spec.id, "M0"))


def _split(
        name: str, meaning: str, folds: list[predict.Fold], kin: Sequence[Family],
        enough: bool) -> tuple[SplitReport, _Scores]:
    """One split scored: the five models, M4 against M3, the ablations
    against M4, and the verdict where the guard allows one."""
    cut = ablations(kin)
    scored = _predict(folds, [*predict.MODELS, *cut])
    judge = _Judge(name, scored)
    sessions = len(scored.sessions)
    maps = sum(len(s) for s in scored.sessions)
    if not maps:
        return SplitReport(name=name, meaning=meaning, folds=len(folds), scored=0,
                           sessions=0, models=[], playbook_adds=None, ablations=[],
                           verdict=None), scored
    models = [judge.model(m) for m in predict.MODELS]
    adds = judge.estimate("M4", "M3")
    cuts = [Ablation(id=m.id, family=m.id[len("M4-"):], ids=list(_ids(kin, m.id)),
                     log_loss=judge.estimate(m.id), vs_full=judge.estimate(m.id, "M4"))
            for m in cut]
    report = SplitReport(name=name, meaning=meaning, folds=len(folds), scored=maps,
                         sessions=sessions, models=models, playbook_adds=adds, ablations=cuts,
                         verdict=_verdict(models, adds, cuts) if enough else None)
    return report, scored


def _ids(kin: Sequence[Family], model_id: str) -> tuple[str, ...]:
    """The strategy ids an ablation drops: its family's, or every family's."""
    name = model_id[len("M4-"):]
    if name == "playbook":
        return tuple(sorted(i for f in kin for i in f.ids))
    return next(f.ids for f in kin if f.name == name)


def _verdict(
        models: Sequence[ModelScore], adds: Estimate, cuts: Sequence[Ablation]) -> str:
    """A split's verdict in words: the best model, the models that beat the
    coin flip, what the playbook adds to the heroes, and the families that
    carry weight or cost more than they give."""
    best = min(models, key=lambda m: m["log_loss"]["value"])
    beating = [m["id"] for m in models if m["id"] != "M0" and reading(m["vs_coin"]) < 0]
    lines = ["%s scores best (log loss %.3f); beating the coin flip: %s." % (
        best["id"], best["log_loss"]["value"], ", ".join(beating) or "none")]
    lines.append({
        -1: "The playbook score and the matchups add to the heroes",
        1: "The playbook score and the matchups do worse than the heroes alone",
        0: "The playbook score and the matchups add nothing the maps can tell"}[
        reading(adds)] + " (M4 - M3 %+.3f [%+.3f, %+.3f])." % (
        adds["value"], adds["low"], adds["high"]))
    carry = [a["family"] for a in cuts if reading(a["vs_full"]) > 0]
    cost = [a["family"] for a in cuts if reading(a["vs_full"]) < 0]
    if cuts:
        lines.append("Carrying weight: %s. Costing more than they give: %s." % (
            ", ".join(carry) or "none", ", ".join(cost) or "none"))
    return " ".join(lines)


def _hero_effects(rows: Sequence[predict.Example]) -> list[HeroEffect]:
    """M3 fitted on every decided map: each hero's effect, largest first."""
    if not rows:
        return []
    keys = sorted({k for ex in rows for k in ex.heroes})
    index = {k: i for i, k in enumerate(keys, 1)}
    coef = fit.fit([{index[k]: v for k, v in ex.heroes.items()} for ex in rows],
                   [ex.won for ex in rows], len(keys), predict.RIDGE)
    out = []
    for key in keys:
        hero = key[len(predict.HERO):]
        maps = sum(1 for ex in rows if hero in ex.match.blue or hero in ex.match.red)
        out.append(HeroEffect(hero=hero, effect=coef[index[key]], maps=maps))
    return sorted(out, key=lambda h: (-h["effect"], h["hero"]))


def _score_effect(rows: Sequence[predict.Example]) -> ScoreEffect | None:
    """The playbook score difference alone, fitted on every decided map, in
    log-odds per sd, and the maps an effect that size needs; None where the
    difference never varies or no map is decided."""
    diffs = [ex.score[""] for ex in rows]
    if len(diffs) < 2 or statistics.pstdev(diffs) == 0:
        return None
    mean, sd = statistics.fmean(diffs), statistics.pstdev(diffs)
    coef = fit.fit([{1: (d - mean) / sd} for d in diffs], [ex.won for ex in rows], 1, predict.RIDGE)
    b = coef[1]
    return ScoreEffect(log_odds=b, needed=fit.maps_needed(b) if b else 0)


def _match_row(row: Rescored, split_scores: dict[str, _Scores], detail: bool) -> MatchRow:
    """One judged map as the report lists it."""
    match = row.match
    predictions = {
        split: {m.id: scored.predictions[m.id][match.match_id] for m in predict.MODELS
                if match.match_id in scored.predictions[m.id]}
        for split, scored in split_scores.items()}
    out = MatchRow(
        match_id=match.match_id, played_on=match.played_on.isoformat(), map=match.map_name,
        side=match.side, result=match.result, digest=match.playbook_digest, note=match.note,
        blue=list(match.blue), red=list(match.red), blue_score=row.blue_score,
        red_score=row.red_score,
        map_win_diff=row.blue_team.get("map_win_mean", 0.0) - row.red_team.get(
            "map_win_mean", 0.0),
        matchup=dict(row.matchup),
        predictions={k: v for k, v in predictions.items() if v})
    if detail:
        out["blue_team"], out["red_team"] = dict(row.blue_team), dict(row.red_team)
    return out


class Judged(NamedTuple):
    """What assess() is told beside the rescored maps: the playbook, its
    folder and digest, the digests of every recorded map, how many were
    recorded and set aside, and whether the pin held."""
    catalog: list[Strategy]
    name: str
    digest: str
    pins: list[Pin]
    recorded: int
    set_aside: int
    pinned: bool


def assess(
        rescoring: Rescoring, judged: Judged, *, effect: float = EFFECT,
        detail: bool = False) -> Validation:
    """The rescored maps judged: the guard, each split's models and
    ablations, the effects fitted on every decided map, and the verdict."""
    kin = families(judged.catalog)
    rows = examples(rescoring.scored, kin)
    held = guard(len(rows), effect)
    results = [r.match.result for r in rescoring.scored]
    splits, split_scores = [], {}
    for name, meaning, folds in predict.SPLITS:
        report, scored = _split(name, meaning, folds(rows), kin, held["enough"])
        splits.append(report)
        split_scores[name] = scored
    return Validation(
        playbook=Playbook(name=judged.name, digest=judged.digest,
                          scoring=any(scores(s) for s in judged.catalog),
                          families=[FamilyRecord(name=f.name, meaning=f.meaning,
                                                 ids=list(f.ids)) for f in kin]),
        pinned=judged.pinned, pins=judged.pins,
        counts=Counts(recorded=judged.recorded, set_aside=judged.set_aside,
                      refused=len(rescoring.refused), judged=len(rescoring.scored),
                      decided=len(rows), won=results.count(WIN), lost=results.count(LOSS),
                      drawn=results.count(DRAW), sessions=len(predict.sessions(rows))),
        refused=[RefusedRecord(match_id=r.match_id, reason=r.reason)
                 for r in rescoring.refused],
        guard=held, splits=splits, heroes=_hero_effects(rows), score_effect=_score_effect(rows),
        matches=[_match_row(r, split_scores, detail) for r in rescoring.scored],
        verdict=_overall(held, splits, len(rows), judged))


def _overall(held: Guard, splits: Sequence[SplitReport], decided: int, judged: Judged) -> str:
    """The run's verdict: no maps to judge, the guard's words, or each
    split's verdict."""
    if not decided:
        if judged.pinned and not any(p["judged"] for p in judged.pins):
            return ("No recorded map was played under this playbook (%s): it is judged only"
                    " on maps played from its first one on." % judged.digest[:12])
        return "No decided map to judge."
    if not held["enough"]:
        return held["text"]
    return " ".join("%s split: %s" % (s["name"], s["verdict"]) for s in splits
                    if s["verdict"]) or "Nothing scored: the splits need two sessions."


def validate(
        world: World, matches: Sequence[Match], catalog: list[Strategy], *,
        digest: str, name: str, pin: bool = True, effect: float = EFFECT,
        pool_size: int = POOL, detail: bool = False,
        log: Log | None = None) -> Validation:
    """The playbook `catalog` (folder `name`, digest `digest`) judged on the
    recorded maps, oldest first: with the pin, only the maps from the first
    one played under that digest on; without it, every map, which the
    playbook may have been tuned on."""
    check_effect(effect)            # a bad effect is refused before minutes of rescoring
    chosen = pinned(matches, digest) if pin else list(matches)
    rescoring = rescore(world, chosen, catalog, pool_size=pool_size, log=log)
    return assess(rescoring, Judged(
        catalog=catalog, name=name, digest=digest, pins=pins(matches, digest),
        recorded=len(matches), set_aside=len(matches) - len(chosen), pinned=pin),
        effect=effect, detail=detail)


# --- the text -------------------------------------------------------------------

def _interval(e: Estimate) -> str:
    return "%.3f [%.3f, %.3f]" % (e["value"], e["low"], e["high"])


def _signed(e: Estimate) -> str:
    return "%+.3f [%+.3f, %+.3f]" % (e["value"], e["low"], e["high"])


def rendered(v: Validation) -> str:
    """The validation as text: the playbook and the maps, the pin, the
    guard, each split's models and ablations, the effects and the verdict."""
    c, book = v["counts"], v["playbook"]
    lines = ["validation of %s (digest %s): %d recorded maps, %d judged%s" % (
        book["name"], book["digest"][:12], c["recorded"], c["judged"],
        "" if book["scoring"] else "; the playbook scores nothing, so every map reads 0")]
    if v["pinned"]:
        lines.append("  pinned: %d earlier maps set aside - the playbook may have been tuned"
                     " on them" % c["set_aside"])
    else:
        lines.append("  unpinned: every map judged, the ones the playbook was tuned on"
                     " included")
    lines.append("  decided %d (%d won, %d lost), %d drawn, over %d sessions%s" % (
        c["decided"], c["won"], c["lost"], c["drawn"], c["sessions"],
        "; %d refused by the engine" % c["refused"] if c["refused"] else ""))
    lines += ["  refused %d: %s" % (r["match_id"], r["reason"]) for r in v["refused"]]
    lines.append("  guard: " + v["guard"]["text"])
    for split in v["splits"]:
        lines.append("%s split - %s: %d folds, %d maps over %d sessions scored" % (
            split["name"], split["meaning"], split["folds"], split["scored"],
            split["sessions"]))
        for m in split["models"]:
            lines.append("  %-3s log loss %s  Brier %s  vs coin %s  %s" % (
                m["id"], _interval(m["log_loss"]), _interval(m["brier"]),
                _signed(m["vs_coin"]), m["label"]))
        if split["playbook_adds"] is not None:
            lines.append("  M4 - M3 log loss %s" % _signed(split["playbook_adds"]))
        for a in split["ablations"]:
            lines.append("  without %-9s %s vs M4 (%s)" % (
                a["family"], _signed(a["vs_full"]), ", ".join(a["ids"])))
    if v["score_effect"] is not None:
        lines.append("playbook score difference on every decided map: %+.3f log-odds per sd,"
                     " an effect that size needs %d maps" % (
                         v["score_effect"]["log_odds"], v["score_effect"]["needed"]))
    if v["heroes"]:
        ends = v["heroes"][:3] + v["heroes"][-3:] if len(v["heroes"]) > 6 else v["heroes"]
        lines.append("hero effects on every decided map (M3, log-odds): %s" % ", ".join(
            "%s %+.2f" % (h["hero"], h["effect"]) for h in ends))
    lines.append("digests: %s" % ("; ".join(
        "%s %d maps %s..%s%s" % (p["digest"][:12], p["maps"], p["first"], p["last"],
                                 " (judged)" if p["judged"] else "")
        for p in v["pins"]) or "none recorded"))
    lines.append("verdict: " + v["verdict"])
    return "\n".join(lines)
