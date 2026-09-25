"""The playbook against the owner's recorded matches: does its score say
anything about who won that the heroes alone do not?

Recorded matches are the second input the owner writes, beside the
strategies. Each is one map (facts.matches.Match): both sixes, the bans,
the map, blue's side, blue's result, and the digest of the playbook in
force when it was played. Blue is always the owner's team.

    guard       the decided maps an effect needs, and the plain words when
                there are fewer
    examples    the decided maps as the models read them, and M4's ablations
    assess      the models fitted and scored out of sample on two splits,
                the ablations, the guard and the verdict -> a Validation
    validate    the pin, the rescore and assess in one call

inference.rescore picks the maps a playbook is judged on and rescores them
through the engine; inference.predict holds the models (M0 a coin flip up
to M4, the heroes plus the playbook score and the matchups), the splits
(older sessions against newer ones, and whole sessions left out) and each
model's log loss and Brier on maps it was not fitted on, with a 95%
interval from resampling sessions. Below the decided maps an effect needs
- (5.6 / b)^2 for b log-odds per sd - the report says so and gives no
verdict. Nothing here writes; the maps are read, never tuned on.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple, Self

from db import Log, Refusal
from facts.matches import Match
from facts.model import World
from inference import catalog as catalog_module
from inference import fit, predict, report, rescore
from inference.fit import Estimate
from inference.strategy import CatalogError, Strategy

EFFECT = 0.60               # the win chance the guard's effect moves an even map to
REFERENCE_EFFECTS = (0.60, 0.55)    # the effects the guard always quotes

WIN, LOSS, DRAW = "win", "loss", "draw"


# --- the guard ------------------------------------------------------------------

def check_effect(effect: float) -> float:
    """An effect as the guard takes it: a win chance above one half and
    below 1, else a Refusal."""
    if not 0.5 < effect < 1.0:
        raise Refusal("effect is a win chance above 0.5 and below 1, got %r" % effect)
    return effect


def guard(decided: int, effect: float = EFFECT) -> report.Guard:
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
    return report.Guard(decided=decided, effect=effect, log_odds=b, needed=needed,
                        reference=reference, enough=enough, text=text)


# --- the examples ---------------------------------------------------------------

def examples(
        rows: Sequence[rescore.Rescored], kin: Sequence[rescore.Family]) -> list[predict.Example]:
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
        score.update((f.name, rescore.without(row, f.ids)) for f in kin)
        out.append(predict.Example(
            match=row.match, won=1 if row.match.result == WIN else 0,
            heroes={k: v for k, v in heroes.items() if v},
            map_win=row.blue_team.get("map_win_mean", 0.0) - row.red_team.get(
                "map_win_mean", 0.0),
            matchup={"matchup." + k: v for k, v in sorted(row.matchup.items())},
            score=score))
    return out


def ablations(kin: Sequence[rescore.Family]) -> list[predict.Model]:
    """M4 with one family dropped from the playbook score, then with the
    score dropped whole: each named by the family and its ids."""
    out = [predict.Model(
        "M4-%s" % f.name, "M4 without %s (%s)" % (f.name, ", ".join(f.ids)), False,
        predict.Logistic(predict.playbook(f.name))) for f in kin]
    if kin:
        whole = predict.Logistic(predict.playbook(None))
        out.append(predict.Model("M4-playbook", "M4 without the playbook score", False, whole))
    return out


def _split(
        name: str, meaning: str, folds: list[predict.Fold], kin: Sequence[rescore.Family],
        enough: bool) -> tuple[report.SplitReport, predict.Scores]:
    """One split scored: the five models, M4 against M3, the ablations
    against M4, and the verdict where the guard allows one."""
    cut = ablations(kin)
    scored = predict.predictions(folds, [*predict.MODELS, *cut])
    judge = predict.Judge(name, scored)
    sessions = len(scored.sessions)
    maps = sum(len(s) for s in scored.sessions)
    if not maps:
        return report.SplitReport(
            name=name, meaning=meaning, folds=len(folds), scored=0, sessions=0, models=[],
            playbook_adds=None, ablations=[], verdict=None), scored
    models = [judge.model(m) for m in predict.MODELS]
    adds = judge.estimate("M4", "M3")
    cuts = [report.Ablation(
        id=m.id, family=m.id[len("M4-"):], ids=list(_ids(kin, m.id)),
        log_loss=judge.estimate(m.id), vs_full=judge.estimate(m.id, "M4")) for m in cut]
    return report.SplitReport(
        name=name, meaning=meaning, folds=len(folds), scored=maps, sessions=sessions,
        models=models, playbook_adds=adds, ablations=cuts,
        verdict=_verdict(models, adds, cuts) if enough else None), scored


def _ids(kin: Sequence[rescore.Family], model_id: str) -> tuple[str, ...]:
    """The strategy ids an ablation drops: its family's, or every family's."""
    name = model_id[len("M4-"):]
    if name == "playbook":
        return tuple(sorted(i for f in kin for i in f.ids))
    return next(f.ids for f in kin if f.name == name)


def _verdict(
        models: Sequence[predict.ModelScore], adds: Estimate,
        cuts: Sequence[report.Ablation]) -> str:
    """A split's verdict in words: the best model, the models that beat the
    coin flip, what the playbook adds to the heroes, and the families that
    carry weight or cost more than they give."""
    best = min(models, key=lambda m: m["log_loss"]["value"])
    beating = [m["id"] for m in models if m["id"] != "M0" and predict.reading(m["vs_coin"]) < 0]
    lines = ["%s scores best (log loss %.3f); beating the coin flip: %s." % (
        best["id"], best["log_loss"]["value"], ", ".join(beating) or "none")]
    lines.append({
        -1: "The playbook score and the matchups add to the heroes",
        1: "The playbook score and the matchups do worse than the heroes alone",
        0: "The playbook score and the matchups add nothing the maps can tell"}[
        predict.reading(adds)] + " (M4 - M3 %+.3f [%+.3f, %+.3f])." % (
        adds["value"], adds["low"], adds["high"]))
    carry = [a["family"] for a in cuts if predict.reading(a["vs_full"]) > 0]
    cost = [a["family"] for a in cuts if predict.reading(a["vs_full"]) < 0]
    if cuts:
        lines.append("Carrying weight: %s. Costing more than they give: %s." % (
            ", ".join(carry) or "none", ", ".join(cost) or "none"))
    return " ".join(lines)


def _hero_effects(rows: Sequence[predict.Example]) -> list[report.HeroEffect]:
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
        out.append(report.HeroEffect(hero=hero, effect=coef[index[key]], maps=maps))
    return sorted(out, key=lambda h: (-h["effect"], h["hero"]))


def _score_effect(rows: Sequence[predict.Example]) -> report.ScoreEffect | None:
    """The playbook score difference alone, fitted on every decided map, in
    log-odds per sd, and the maps an effect that size needs; None where the
    difference never varies or no map is decided."""
    diffs = [ex.score[""] for ex in rows]
    if len(diffs) < 2 or statistics.pstdev(diffs) == 0:
        return None
    mean, sd = statistics.fmean(diffs), statistics.pstdev(diffs)
    coef = fit.fit([{1: (d - mean) / sd} for d in diffs], [ex.won for ex in rows], 1, predict.RIDGE)
    b = coef[1]
    return report.ScoreEffect(log_odds=b, needed=fit.maps_needed(b) if b else 0)


def _match_row(
        row: rescore.Rescored, split_scores: dict[str, predict.Scores],
        detail: bool) -> report.MatchRow:
    """One judged map as the report lists it."""
    match = row.match
    predictions = {
        split: {m.id: scored.predictions[m.id][match.match_id] for m in predict.MODELS
                if match.match_id in scored.predictions[m.id]}
        for split, scored in split_scores.items()}
    out = report.MatchRow(
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


class Subject(NamedTuple):
    """The playbook a run judges: its strategies, its folder as the database
    names it (catalog.playbook_name) and its digest."""
    catalog: list[Strategy]
    name: str
    digest: str

    @classmethod
    def of(cls, directory: str) -> Self:
        """The playbook in a folder. One that does not load is a Refusal
        naming the folder: the caller named it."""
        name = catalog_module.playbook_name(directory)
        try:
            strategies = catalog_module.load(directory)
        except CatalogError as error:
            raise Refusal("the playbook at %s does not load: %s" % (name, error)) from error
        return cls(strategies, name, catalog_module.playbook_digest(directory))


@dataclass(frozen=True)
class Options:
    """How a run judges: with the pin or every map, the win chance the
    guard sizes the sample for, whether each map carries both seats' team
    metrics, and where the rescore's progress lines go."""
    pin: bool = True
    effect: float = EFFECT
    detail: bool = False
    log: Log | None = None


class Judged(NamedTuple):
    """What assess() is told beside the rescored maps: the playbook, the
    digests of every recorded map, how many were recorded and set aside,
    and whether the pin held."""
    subject: Subject
    pins: list[rescore.Pin]
    recorded: int
    set_aside: int
    pinned: bool


def _playbook(subject: Subject, kin: Sequence[rescore.Family]) -> report.Playbook:
    """The playbook as the report names it."""
    families = [report.FamilyRecord(name=f.name, meaning=f.meaning, ids=list(f.ids))
                for f in kin]
    return report.Playbook(
        name=subject.name, digest=subject.digest,
        scoring=any(rescore.scores(s) for s in subject.catalog), families=families)


def _counts(
        rescoring: rescore.Rescoring, judged: Judged,
        rows: Sequence[predict.Example]) -> report.Counts:
    """The maps: recorded, set aside, refused, judged and decided."""
    results = [r.match.result for r in rescoring.scored]
    return report.Counts(
        recorded=judged.recorded, set_aside=judged.set_aside, refused=len(rescoring.refused),
        judged=len(rescoring.scored), decided=len(rows), won=results.count(WIN),
        lost=results.count(LOSS), drawn=results.count(DRAW),
        sessions=len(predict.sessions(rows)))


def assess(
        rescoring: rescore.Rescoring, judged: Judged,
        options: Options | None = None) -> report.Validation:
    """The rescored maps judged: the guard, each split's models and
    ablations, the effects fitted on every decided map, and the verdict.
    No options is the pin, the default effect and no team metrics."""
    options = Options() if options is None else options
    kin = rescore.families(judged.subject.catalog)
    rows = examples(rescoring.scored, kin)
    held = guard(len(rows), options.effect)
    splits, split_scores = [], {}
    for name, meaning, folds in predict.SPLITS:
        split, scored = _split(name, meaning, folds(rows), kin, held["enough"])
        splits.append(split)
        split_scores[name] = scored
    return report.Validation(
        playbook=_playbook(judged.subject, kin), pinned=judged.pinned, pins=judged.pins,
        counts=_counts(rescoring, judged, rows),
        refused=[report.RefusedRecord(match_id=r.match_id, reason=r.reason)
                 for r in rescoring.refused],
        guard=held, splits=splits, heroes=_hero_effects(rows), score_effect=_score_effect(rows),
        matches=[_match_row(r, split_scores, options.detail) for r in rescoring.scored],
        verdict=_overall(held, splits, len(rows), judged))


def _overall(
        held: report.Guard, splits: Sequence[report.SplitReport], decided: int,
        judged: Judged) -> str:
    """The run's verdict: no maps to judge, the guard's words, or each
    split's verdict."""
    if not decided:
        if judged.pinned and not any(p["judged"] for p in judged.pins):
            return ("No recorded map was played under this playbook (%s): it is judged only"
                    " on maps played from its first one on." % judged.subject.digest[:12])
        return "No decided map to judge."
    if not held["enough"]:
        return held["text"]
    return " ".join("%s split: %s" % (s["name"], s["verdict"]) for s in splits
                    if s["verdict"]) or "Nothing scored: the splits need two sessions."


def validate(
        world: World, matches: Sequence[Match], subject: Subject,
        options: Options | None = None) -> report.Validation:
    """The playbook judged on the recorded maps, oldest first: with the pin,
    only the maps from the first one played under its digest on; without
    it, every map, which the playbook may have been tuned on."""
    options = Options() if options is None else options
    check_effect(options.effect)    # a bad effect is refused before minutes of rescoring
    digest = subject.digest
    chosen = rescore.pinned(matches, digest) if options.pin else list(matches)
    rescoring = rescore.rescore(world, chosen, subject.catalog, log=options.log)
    return assess(rescoring, Judged(
        subject=subject, pins=rescore.pins(matches, digest), recorded=len(matches),
        set_aside=len(matches) - len(chosen), pinned=options.pin), options)
