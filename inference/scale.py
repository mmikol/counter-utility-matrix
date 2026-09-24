"""One scale per board: what every heuristic on it is normalised against, as
functions of an Objective.

    sample              the REFERENCE: a seeded set of random legal sixes for this
                        map and side. Heuristics are normalised against it, so infer,
                        evaluate and the current comp share one scale and a score
                        means the same thing across calls. The seed is a string, so
                        every process draws the same list and any of them can prepare
                        a slice of it.
    reference_bounds    each heuristic's low and high over one slice of the sample
                        and of the board's field; the slices merge into the bounds
                        freeze draws in one process
    reference_standing  each hero's summed score across one slice of the reference
                        sixes it is in: its mean is the playbook's own ranking of the
                        roster on this board
"""

import itertools
import math
import random
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from inference.scoring import CONFIDENCE_KEY, Bounds, Candidate, Interval, MetricKey, Objective
from inference.shapes import legal_shapes
from ui.facts import compute
from ui.facts.model import ROLES, Hero
from ui.facts.team import number

REFERENCE_SIZE = 1200
REFERENCE_SEED = 20260913
SCALE_POOL = 6                    # the field that fixes a board's scale, whatever pool is searched


@dataclass(slots=True)
class Standing:
    """One hero's tally over reference sixes: its summed score in millionths
    and the sixes it is in. Whole numbers, so slices add up the same in any
    order; the mean is total / sixes."""
    total: int = 0
    sixes: int = 0


Tally = dict[int, Standing]                     # hero id -> its standing


def sample(objective: Objective, size: int = REFERENCE_SIZE) -> list[Candidate]:
    """A seeded sample of `size` random legal sixes for this board,
    unprepared; every legal six, in the seeded order, on a roster that holds
    fewer. Deterministic for a given map and side, and independent of the
    locked picks, the pool, the enemies and the bans, so every call on one
    board shares a scale - and any process draws the same list and can take
    a slice.

    It must not depend on red or the bans. The sample fixes every
    heuristic's [lo, hi], so drawing it differently rescales the whole
    objective: a hero banned out of neither team would move the score of
    an unchanged six, banning could raise the reported maximum over a
    smaller feasible set, and `the optimal comp for this board` would
    stop being a function of the composition. Bans still screen the
    candidate field, in pools(), refine() and _pairs() - it is only the
    measuring stick that has to hold still."""
    m = objective.m
    rng = random.Random("%d|%s|%s" % (  # nosec B311  # a str seed, stable across processes
        REFERENCE_SEED, m.id if m else 0, objective.side))
    by_role = {r: sorted((h for h in objective.world.heroes.values()   # by id: the draw
                          if h.role == r and h.released),              # must not hang on
                         key=lambda h: h.id)                           # a query's row order
                for r in ROLES}
    # a role short of released heroes for a shape: drawing one would raise
    shapes = [(t, d, s) for t, d, s in legal_shapes(objective.catalog)
                if t <= len(by_role["tank"]) and d <= len(by_role["damage"])
                and s <= len(by_role["support"])]
    # the legal sixes there are: a draw for more than that never ends
    space = sum(
        math.comb(len(by_role["tank"]), t) * math.comb(len(by_role["damage"]), d)
        * math.comb(len(by_role["support"]), s) for t, d, s in shapes)
    out: list[Candidate] = []
    seen: set[frozenset[int]] = set()
    if shapes:
        while len(out) < min(size, space):
            t, d, s = rng.choice(shapes)
            heroes = (rng.sample(by_role["tank"], t) + rng.sample(by_role["damage"], d)
                      + rng.sample(by_role["support"], s))
            cand = Candidate(heroes)
            if cand.key in seen:
                continue
            seen.add(cand.key)
            out.append(cand)
    return out


def _prepared(objective: Objective, index: int = 0, count: int = 1) -> list[Candidate]:
    """One slice of the sample prepared, minus what the hard limits refuse:
    what every heuristic is normalised against."""
    return [c for c in (objective.prepare(c) for c in sample(objective)[index::count])
            if not c.violations]


def _spanning(values: Sequence[float]) -> Interval:
    """The lowest and highest of values; 0.0 and 0.0 when there are none."""
    return Interval(low=min(values), high=max(values)) if values else Interval(low=0.0, high=0.0)


def _confidence_bounds(objective: Objective, spec: MetricKey, index: int,
                       prepared: Sequence[Candidate]) -> Interval:
    """The low and high a rule's confidence metric (`spec`, its namespace and
    key) is read against.

    A metric of the six varies across the reference sixes, so the reference
    is its population. A metric of the board - the map, the world - is one
    number here however the six changes, and normalising it against a sample
    that cannot move it would call every board equally certain. Its
    population is the other boards: the same metric over every map.
    """
    if spec.section == "map":
        ban_count = len(objective.banned)
        readings = [compute.map_metrics(m, objective.side, ban_count=ban_count).get(spec.key)
                    for m in objective.world.maps.values()]
        over = [float(number(v)) for v in readings if v is not None]
        return _spanning(over)
    seen = [value for c in prepared if (value := c.confidence[index]) is not None]
    return _spanning(seen)


def reference_bounds(objective: Objective, index: int = 0, count: int = 1) -> Bounds:
    """{heuristic id: Interval(low, high)} over one slice of the sample AND of the
    field, leaving out the heuristics the slice never valued. The slices
    partition both, so merging their lows and highs gives what one process
    freezes."""
    prepared = _prepared(objective, index, count) + _field_sample(objective, index, count)
    out: Bounds = {}
    for i, g in enumerate(objective.heuristics):
        values = [value for c in prepared if (value := c.raw[i]) is not None]
        if values:
            out[g.id] = _spanning(values)
        spec = objective.confidence_metrics[i]
        if spec is not None:
            out[g.id + CONFIDENCE_KEY] = _confidence_bounds(objective, spec, i, prepared)
    return out


def board_prior(objective: Objective, h: Hero, partners: int = 0) -> float:
    """The ranking that cut the pools before the playbook ranked them itself:
    the hero's win rate here, three points for each enemy it answers less
    three for each that answers it, two for each locked pick it partners, one
    for the map's style and one for a map it is best on.

    With no partners it is the board's own ranking. A point per partner is
    right when ranking a pool to search and wrong when choosing the field that
    fixes the scale - that field has to be the same for every seat and every
    set of locks on this board."""
    m, world = objective.m, objective.world
    here = h.map_win(m.id) if m is not None else None
    base = here if here is not None else (h.win if h.win is not None else 50.0)
    answers = sum(1 for e in objective.red if world.is_countered_by(e.id, h.id))
    exposed = sum(1 for e in objective.red if world.is_countered_by(h.id, e.id))
    style = 1 if (m is not None and m.style_top in h.styles) else 0
    best = 1 if (m is not None and m.id in h.best_maps) else 0
    return base + 3.0 * answers - 3.0 * exposed + 2.0 * partners + style + best


def _board_pool(objective: Objective, role: str) -> list[Hero]:
    """One role's top SCALE_POOL released heroes by the board's own prior."""
    # not filtered by the bans, on purpose, exactly as sample() is not:
    # this field is half the population that fixes the scale, and a ban
    # that moved it would move the score of an unchanged six. Bans keep
    # banned heroes out of the CANDIDATE field in pools(); the measuring
    # stick has to hold still
    heroes = [h for h in objective.world.heroes.values() if h.role == role and h.released]
    heroes.sort(key=lambda h: (-board_prior(objective, h), h.name))
    return heroes[:SCALE_POOL]


def _board_field(objective: Objective) -> Iterator[list[Hero]]:
    """The field this board would search with nothing locked: each role's
    top SCALE_POOL by the board's own prior, over every legal shape.

    It must not read the locked picks, and it takes SCALE_POOL rather than
    the pool this search happens to use. The bounds it feeds are the
    board's one scale: `infer`, `evaluate`, `current` and the countered
    what-if run with different locks and different pool sizes on the same
    board, and a scale that moved with either would make a current comp and
    the optimal it is a share of two different numbers."""
    tanks, damage, supports = [_board_pool(objective, role) for role in ROLES]
    for t, d, s in legal_shapes(objective.catalog):
        if t > len(tanks) or d > len(damage) or s > len(supports):
            continue
        for a in itertools.combinations(tanks, t):
            for b in itertools.combinations(damage, d):
                for c in itertools.combinations(supports, s):
                    yield list(a) + list(b) + list(c)


def _field_sample(objective: Objective, index: int = 0, count: int = 1) -> list[Candidate]:
    """The board's field, prepared but unscored.

    The sample alone is 1,200 random legal sixes, and the search picks from
    comps far better than random, so a good six sat above the sample's high
    on most metrics and every one of them normalised to the same 1.0: the
    rule stopped telling them apart, and a weight raised past that bought
    nothing. The field belongs in the population that sets the scale."""
    out = []
    for size, heroes in enumerate(_board_field(objective)):
        if size % count == index:
            cand = objective.prepare(Candidate(heroes))
            if not cand.violations:
                out.append(cand)
    return out


def freeze(objective: Objective) -> Tally:
    """Bounds per heuristic from the reference sample and the field, adopted
    by the objective; -> the reference sixes' tally under them, each hero's
    standing. The sample is drawn once here, and nowhere else in one
    process."""
    reference = _prepared(objective)
    over = reference + _field_sample(objective)
    bounds: Bounds = {}
    for i, g in enumerate(objective.heuristics):
        values = [value for c in over if (value := c.raw[i]) is not None]
        bounds[g.id] = _spanning(values)
        spec = objective.confidence_metrics[i]
        if spec is not None:
            bounds[g.id + CONFIDENCE_KEY] = _confidence_bounds(objective, spec, i, over)
    objective.adopt_bounds(bounds)
    return _tally(objective, reference)


def _tally(objective: Objective, prepared: Iterable[Candidate]) -> Tally:
    """Each hero's Standing over prepared reference sixes."""
    tally: Tally = {}
    for cand in prepared:
        points = round(objective.score(cand, detail=False).score * 1e6)
        for h in cand.heroes:
            seen = tally.get(h.id)
            if seen is None:
                seen = tally[h.id] = Standing()
            seen.total += points
            seen.sixes += 1
    return tally


def reference_standing(objective: Objective, index: int = 0, count: int = 1) -> Tally:
    """One slice of the sample scored under the frozen bounds -> its tally."""
    return _tally(objective, _prepared(objective, index, count))
