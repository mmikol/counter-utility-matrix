"""infer(), evaluate() and board(): the API over the solver.

    infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",), side="attack"))

returns the optimal six around the locked picks, each pick with the facts
that justify it (the board the UI layer would show for map + red + the
six), the score broken down per strategy, and the alternatives.
board() does it for both seats - blue's absolute optimal, red around
its revealed ones, on opposite sides of a sided map - and scores the
current blue picks as they stand. The records are result.py's, the prose
plan.py's and the process pool parallel.py's.
"""

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures.process import BrokenProcessPool
from math import comb
from typing import NamedTuple

from db import Refusal
from inference import catalog as catalog_module
from inference import parallel
from inference.catalog import Strategy
from inference.plan import Seats, momentum, plan
from inference.result import Alternative, Board, Pick, Result, ResultKind, Seat
from inference.scoring import Candidate, legal_shapes
from inference.solver import Solved, Solver, Swept, evaluate_comp
from ui.facts import board_facts, compute
from ui.facts.draft import (
    MAX_TANKS,
    TEAM_SIZE,
    Draft,
    check_tanks,
    check_team_size,
    is_sided,
    opposite,
)
from ui.facts.factset import FactSet
from ui.facts.model import ROLES, Hero, Map, World


class SearchBounds(NamedTuple):
    """How wide a search runs: candidates per role, and alternatives kept."""
    pool_size: int
    top: int


# the legal sixes one search may enumerate: a candidate holds about 1 KB while the
# field is ranked, so this is about 540 MB of the inference container's 2 GiB
FIELD_BUDGET = 500_000


def field_size(pool: int) -> int:
    """The legal sixes a search over `pool` candidates per role enumerates
    with nothing locked and no shape limit but the queue's tanks: the sum
    over the queue's shapes of the product of C(pool, need) per role."""
    return sum(
        comb(pool, t) * comb(pool, d) * comb(pool, TEAM_SIZE - t - d)
        for t in range(MAX_TANKS + 1) for d in range(TEAM_SIZE - t + 1))


# the most candidates per role whose field fits the budget: 10, 411,825 sixes
POOL_CEILING = max(p for p in range(2, 13) if field_size(p) <= FIELD_BUDGET)


def clamp_search(pool: str | float | None = None,
                 top: str | float | None = None) -> SearchBounds:
    """Bounds on the search: pool 2..POOL_CEILING candidates per role, top
    1..20 alternatives. The pool is bounded by the field it would enumerate,
    not by a round number: pool 12 is 1,345,960 legal sixes, which ran the
    inference container out of memory. Every door that takes the two from a
    caller - the MCP tools and the HTTP service - passes them through here,
    so the search is bounded by one definition. Junk raises Refusal, which
    every door answers as the caller's error."""
    try:
        return SearchBounds(max(2, min(int(pool or 6), POOL_CEILING)),
                            max(1, min(int(top or 5), 20)))
    except (TypeError, ValueError) as error:
        raise Refusal("pool and top must be numbers: %s" % error) from error


COUNTERED_POOL = 4          # a what-if: a smaller field is enough
BOARD_TOP = 5               # the alternatives each of a board's seats keeps


class Brief(NamedTuple):
    """What a caller asks of one board beyond the draft: the candidates per
    role, the playbook tab's weights ({heuristic id: 0..10}, for this board
    only), whether to solve the countered case - the MCP board prints it, the
    page never reads it - and the check that says a newer request from the
    same client has superseded this one."""
    pool_size: int = 6
    weights: Mapping[str, float] | None = None
    countered: bool = True
    superseded: Callable[[], bool] | None = None


def _order(heroes: Iterable[Hero]) -> list[str]:
    return [h.name for h in sorted(heroes, key=lambda h: (ROLES.index(h.role), h.name))]


def _board_facts(world: World, result: Result, side: str) -> FactSet:
    """The facts of the board a result stands on: its map, both sides as it
    names them, its bans, and the side."""
    return board_facts.generate(world, Draft(
        map_name=result.map_name, red=tuple(result.red), blue=tuple(result.blue),
        bans=tuple(result.bans), side=side))


def _side(m: Map | None, side: str) -> str:
    if side not in ("", "attack", "defense"):
        raise Refusal("side must be attack or defense, got %r" % side)
    return side if is_sided(m) else ""


def infer(
        world: World, draft: Draft, *, catalog: list[Strategy] | None = None,
        pool_size: int = 6, top: int = 5) -> Result:
    """Blue's optimal six around its locked picks (`draft.blue`) against red's
    revealed ones, on the draft's side of a sided map."""
    return _optimal(world, draft, catalog=catalog or catalog_module.load(),
                    pool_size=pool_size, top=top, seat="blue", kind="infer",
                    solved=None, began=None).result


def evaluate(
        world: World, draft: Draft, *, catalog: list[Strategy] | None = None,
        pool_size: int = 6) -> Result:
    """Blue's full six (`draft.blue`), scored and ranked against the field the
    solver would have searched."""
    return _evaluated(world, draft, catalog=catalog or catalog_module.load(),
                      pool_size=pool_size, seat="blue", kind="evaluate", swept=None)


class _Optimal(NamedTuple):
    """A seat's optimal six and the Solver that found it: the seat's current
    comp is scored under the bounds that search froze."""
    result: Result
    solver: Solver


def _optimal(
        world: World, draft: Draft, *, catalog: list[Strategy], pool_size: int,
        top: int, seat: Seat, kind: ResultKind, solved: Solved | None,
        began: float | None) -> _Optimal:
    """The optimal six for `seat` around its locked picks (`draft.blue`)
    against the other seat's revealed ones (`draft.red`), labelled `kind`.
    `solved` takes a Solved the caller already has - a board's search, run
    across the worker pool - in place of searching here, and `began` the
    time that search started, which the result's seconds run from; None
    times the search this call makes."""
    started = time.time() if began is None else began
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    side = _side(m, draft.side)
    check_team_size(blue_h, seat)
    check_tanks(blue_h, seat)
    result = Result(kind=kind, map_name=m.name if m else None, red=[h.name for h in red_h],
                    blue=[], locked=[h.name for h in blue_h], catalog=catalog,
                    bans=[h.name for h in bans_h], side=side, seat=seat)
    if solved is None:
        solved = Solver(world, m, red=red_h, locked=blue_h, banned=bans_h, side=side,
                        catalog=catalog, pool_size=pool_size).solve(top=max(top, 1) + 1)
    if not solved.ranked:
        raise Refusal("no composition satisfies the limits around the"
                         " locked %s picks - relax a constraint in inference/strategies/"
                         % seat)
    best = solved.ranked[0]
    result.blue = _order(best.heroes)
    fs = _board_facts(world, result, side)
    result.record_candidate(best, fs, solved.solver.considered)
    result.alternatives = [Alternative(blue=_order(c.heroes), score=round(c.score, 3),
                                       normalized=None)
                           for c in solved.ranked[1:top + 1]]
    result.scale_to(result.score)
    result.seconds = time.time() - started
    return _Optimal(result, solved.solver)


def _evaluated(
        world: World, draft: Draft, *, catalog: list[Strategy], pool_size: int,
        seat: Seat, kind: ResultKind, swept: Swept | None) -> Result:
    """`seat`'s full six (`draft.blue`), scored and ranked against the field
    the solver would have searched, labelled `kind`. `swept` takes that field
    from a search the caller already ran on this board."""
    started = time.time()
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    side = _side(m, draft.side)
    if len(blue_h) != TEAM_SIZE:
        raise Refusal("evaluate needs exactly %d %s picks (got %d)"
                         % (TEAM_SIZE, seat, len(blue_h)))
    check_tanks(blue_h, seat)
    result = Result(kind=kind, map_name=m.name if m else None, red=[h.name for h in red_h],
                    blue=[h.name for h in blue_h], locked=[], catalog=catalog,
                    bans=[h.name for h in bans_h], side=side, seat=seat)
    evaluated = evaluate_comp(world, m, blue_h, red=red_h, banned=bans_h, side=side,
                              catalog=catalog, pool_size=pool_size, swept=swept)
    fs = _board_facts(world, result, side)
    result.record_candidate(evaluated.target, fs, evaluated.solver.considered)
    result.rank = evaluated.rank
    result.alternatives = [Alternative(blue=_order(c.heroes), score=round(c.score, 3),
                                       normalized=None)
                           for c in evaluated.field[:3]]
    result.seconds = time.time() - started
    # the board's best known six is the 100, not this comp's own best rival: a
    # beaten six must not read 100 because nothing it was compared against beat it
    result.scale_to(max([result.score] + [a["score"] for a in result.alternatives]))
    return result


def _current(
        world: World, draft: Draft, *, solver: Solver, best: float,
        catalog: list[Strategy], pool_size: int, seat: Seat, kind: ResultKind,
        swept: Swept | None) -> Result:
    """`seat`'s picks (`draft.blue`, from that seat's perspective) as they
    stand against the other seat's (`draft.red`), on the scale of the seat's
    optimal: `solver` is the Solver its search ran and `best` its score, the
    100. A full six is evaluated against the field - `swept`, when the caller
    already has it - and reads "evaluate" where `kind` is "current", any other
    kind staying as given; a partial team is scored under the bounds `solver`
    froze, and says so."""
    if len(draft.blue) == TEAM_SIZE:
        result = _evaluated(world, draft, catalog=catalog, pool_size=pool_size, seat=seat,
                            kind="evaluate" if kind == "current" else kind, swept=swept)
        result.scale_to(best)
        return result
    started = time.time()
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    side = _side(m, draft.side)
    result = Result(kind=kind, map_name=m.name if m else None, red=[h.name for h in red_h],
                    blue=[h.name for h in blue_h], locked=[h.name for h in blue_h],
                    catalog=catalog, bans=[h.name for h in bans_h], side=side, seat=seat,
                    partial=True)
    if blue_h:
        cand = solver.prepare(Candidate(blue_h))
        solver.score(cand)
        result.record_candidate(cand, _board_facts(world, result, side), solver.considered)
    result.scale_to(best)
    result.seconds = time.time() - started
    return result


def board(
        world: World, draft: Draft, *, catalog: list[Strategy] | None = None,
        brief: Brief | None = None) -> Board:
    """The whole board in one pass, at whatever stage the draft is - no map
    (the meta's best six), a map, a map and a side, bans, red's picks as
    they reveal:

        blue         blue's optimal six: the best counter to red's selection
                     as revealed - or, before they reveal a pick, to their
                     likely six - on this map, side and bans; blue's own
                     picks never constrain it
        red          red's optimal six: their best counter to blue's
                     selection, on the other side - the scale red's current
                     comp is measured on
        current      blue's picks as they stand, scored against red's
                     selection on blue's optimal's scale
        red_current  red's picks as they stand, scored against blue's
                     selection on red's optimal's scale
        countered    blue's picks against red's optimal six - how you hold
                     if they answer you perfectly: a full six as it stands, a
                     half-drafted one filled, on the scale of blue's best
                     counter to that six (None without blue picks, or when
                     the brief does not ask for it)
        fill         blue's locked picks with the empty slots filled by the
                     solver - the best six that keeps what you hold, on
                     blue's optimal's scale (None unless one to five are locked)
        momentum     the verdict from the two current comps, each
                     half-drafted seat read through its fill; red's fill is
                     solved for the verdict and not kept
        plan         the game plan in prose, from the same facts, for the six
                     the comps tab shows for blue: its optimal before any
                     blue pick, the fill around one to five, the picks
                     themselves at six
        shapes       the (tanks, damage, supports) triples the queue and the
                     playbook's shape limits allow - what the roster enforces
                     as you pick; a team past six picks or two tanks is refused
        expected     red's likely six from the data alone - a two-two-two from
                     the map's pick rates and the wiki's synergies, past the
                     bans - static for the board, no strategy read; what the
                     comps tab shows for red and what blue counters until red
                     reveals a pick

    The brief's weights override the files' for this board only - the
    playbook tab's sliders; the files stay as they are and every result says
    the weights it was scored under.

    Across the pool the searches are split and walked through their rounds
    together; in this process each seat searches for itself. A worker dying
    anywhere in the pooled pass drops the pool and runs the same pass here. A
    board the brief's check reports superseded stops at its next round, its
    unstarted tasks cancelled, and raises parallel.Superseded.
    """
    brief = brief or Brief()
    pooled = parallel.available(catalog)
    catalog = catalog_module.weighted(catalog or catalog_module.load(), brief.weights)
    if not pooled:
        return _board_once(world, draft, catalog=catalog, brief=brief, workers=None)
    try:
        return _board_once(world, draft, catalog=catalog, brief=brief,
                           workers=parallel.POOL.executor())
    except BrokenProcessPool:
        parallel.POOL.drop()                   # a worker died: this board, in this process
    return _board_once(world, draft, catalog=catalog, brief=brief, workers=None)


def _board_once(
        world: World, draft: Draft, *, catalog: list[Strategy], brief: Brief,
        workers: parallel.Workers | None) -> Board:
    """The board, its searches split across `workers`, or each run in this
    process where there are none. The rounds go in the order that keeps the
    pool full: the two optimal seats rank their rosters and sweep, the fills
    sweep on their seats' scales, the seats merge and are solved, and the
    countered case, which needs red's six, sweeps while the fills merge."""
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    draft = draft._replace(side=_side(m, draft.side))
    _check_teams(red_h, blue_h)
    expected = _expected(world, m, bans_h, draft, catalog)
    enemy = draft.red or tuple(expected.blue)
    # each seat's draft, from that seat's perspective: its own picks are `blue`
    blue_seat = draft._replace(red=enemy, blue=())
    red_seat = Draft(map_name=draft.map_name, red=draft.blue, blue=(), bans=draft.bans,
                     side=opposite(draft.side))
    ours = draft._replace(red=enemy)                   # blue's current comp and fill
    theirs = Draft(map_name=draft.map_name, red=draft.blue, blue=draft.red, bans=draft.bans,
                   side=opposite(draft.side))
    solve = _Pass(world, catalog, brief, workers)
    blue_split, red_split = solve.split(blue_seat, solve.half), solve.split(red_seat, solve.rest)
    blue_split.rank_roster()
    red_split.rank_roster()
    blue_split.sweep()
    red_split.sweep()
    # a fill is its seat's board, so it takes the seat's scale and draws none
    fill_split = solve.split(ours, solve.half, wanted=_drafting(ours), scale=blue_split)
    red_fill_split = solve.split(theirs, solve.rest, wanted=_drafting(theirs), scale=red_split)
    fill_split.sweep()
    red_fill_split.sweep()
    blue_split.merge()
    red_split.merge()
    blue = solve.optimal(blue_seat, blue_split, seat="blue")
    red = solve.optimal(red_seat, red_split, seat="red")
    countered_seat = draft._replace(red=tuple(red.result.blue))
    against_split, answer_split = solve.countering(countered_seat)
    for split in (fill_split, red_fill_split, against_split, answer_split):
        split.merge()
    # a full six is ranked against the field its seat's search just swept;
    # 100 is the seat's optimal, whatever it holds
    cur = solve.current(ours, blue, blue_split, seat="blue")
    red_cur = solve.current(theirs, red, red_split, seat="red")
    fill = solve.filled(ours, fill_split, seat="blue", best=blue.result.score)
    red_fill = solve.filled(theirs, red_fill_split, seat="red", best=red.result.score)
    countered = solve.countered(countered_seat, against_split, answer_split)
    seats = Seats(current=cur, red_current=red_cur, blue=blue.result, red=red.result,
                  fill=fill, red_fill=red_fill, countered=countered)
    # the six the comps tab shows for blue, which the plan describes
    shown = fill if fill is not None else cur if len(draft.blue) == TEAM_SIZE else blue.result
    return Board(map_name=expected.map_name, side=draft.side, bans=list(draft.bans),
                 blue=blue.result, red=red.result, current=cur, red_current=red_cur,
                 fill=fill, countered=countered, momentum=momentum(seats),
                 plan=plan(world, m, draft.side, list(draft.bans), red_h, shown),
                 shapes=[list(s) for s in legal_shapes(catalog)], expected=expected)


def _drafting(seat: Draft) -> bool:
    """Whether a seat is half-drafted - one to five picks, which a fill completes."""
    return 0 < len(seat.blue) < TEAM_SIZE


# a search sent across the pool, or one each seat runs for itself
Searching = parallel.Split | parallel.NullSplit


class _Pass:
    """One pass of a board: the world, the weighted playbook and the brief it
    is solved under, and the searches it sends out - blue's and its fill's
    over half the pool's workers, red's, its fill's and the countered case's
    over the rest - or each seat searching for itself where there are none."""

    def __init__(self, world: World, catalog: list[Strategy], brief: Brief,
                 workers: parallel.Workers | None) -> None:
        self.world, self.catalog, self.brief = world, catalog, brief
        self.watch = parallel.Watch(brief.superseded)
        size = workers.size if workers is not None else 0
        self.half = max(1, size // 2)
        self.rest = max(1, size - self.half)
        self.run = None if workers is None else parallel.Run(
            workers.executor, world, catalog, brief.weights, BOARD_TOP + 1, self.watch)
        self.countered_pool = min(brief.pool_size, COUNTERED_POOL)

    def split(
            self, draft: Draft, slices: int, *, wanted: bool = True,
            pool_size: int | None = None, scale: Searching | None = None) -> Searching:
        """One search sent out, unless there are no workers or it is not
        wanted. With `scale`, a search on the same board, it takes that
        search's bounds and standing and draws no sample of its own."""
        if self.run is None or not wanted:
            return parallel.NullSplit(self.watch)
        spec = parallel.Spec(draft, pool_size or self.brief.pool_size)
        if scale is None:
            return parallel.Split(self.run, spec, slices)
        return parallel.Split(self.run, spec, slices, scale.bounds, scale.standing)

    def optimal(
            self, draft: Draft, search: Searching, *, seat: Seat, kind: ResultKind = "infer",
            pool_size: int | None = None) -> _Optimal:
        """`seat`'s optimal six on `draft`, taken from `search` where it ran
        across the pool and timed from when it was sent out."""
        return _optimal(self.world, draft, catalog=self.catalog,
                        pool_size=pool_size or self.brief.pool_size, top=BOARD_TOP, seat=seat,
                        kind=kind, solved=search.solved(), began=search.started)

    def current(self, draft: Draft, optimal: _Optimal, search: Searching, *, seat: Seat) -> Result:
        """`seat`'s picks as they stand, on its optimal's scale; a full six is
        ranked against the field `search` swept."""
        swept = search.swept() if len(draft.blue) == TEAM_SIZE else None
        return _current(self.world, draft, solver=optimal.solver, best=optimal.result.score,
                        catalog=self.catalog, pool_size=self.brief.pool_size, seat=seat,
                        kind="current", swept=swept)

    def filled(
            self, draft: Draft, search: Searching, *, seat: Seat, best: float,
            kind: ResultKind = "fill", pool_size: int | None = None) -> Result | None:
        """`seat`'s picks (`draft.blue`) with the empty slots filled by the
        solver, on the scale whose 100 is `best`: how close the best
        completion comes. None unless the seat is half-drafted."""
        if not _drafting(draft):
            return None
        fill = self.optimal(draft, search, seat=seat, kind=kind, pool_size=pool_size).result
        fill.scale_to(best)
        return fill

    def _countering(self, draft: Draft) -> bool:
        """Whether the countered case is solved: blue has picks, red a six,
        and the brief asks for it."""
        return bool(self.brief.countered and draft.blue and draft.red)

    def countering(self, draft: Draft) -> tuple[Searching, Searching]:
        """The countered case's two searches, swept: blue's best counter to
        red's optimal six (`draft.red`), which is its 100, and blue's picks
        filled against that six on the same scale - the second only while
        blue is half-drafted."""
        wanted = self._countering(draft)
        against = self.split(draft._replace(blue=()), self.rest, wanted=wanted,
                             pool_size=self.countered_pool)
        against.sweep()
        answer = self.split(draft, self.rest, wanted=wanted and _drafting(draft),
                            pool_size=self.countered_pool, scale=against)
        answer.sweep()
        return against, answer

    def countered(self, draft: Draft, against: Searching, answer: Searching) -> Result | None:
        """Blue's picks (`draft.blue`) against red's optimal six (`draft.red`):
        how they hold if red answers perfectly, on the scale of blue's best
        counter to that six. A full six is ranked against that counter's
        field; a half-drafted one is filled, as the fill reads blue's picks.
        None where the countered case is not solved."""
        if not self._countering(draft):
            return None
        top = self.optimal(draft._replace(blue=()), against, seat="blue",
                           pool_size=self.countered_pool)
        if _drafting(draft):
            return self.filled(draft, answer, seat="blue", best=top.result.score,
                               kind="countered", pool_size=self.countered_pool)
        return _current(self.world, draft, solver=top.solver, best=top.result.score,
                        catalog=self.catalog, pool_size=self.countered_pool, seat="blue",
                        kind="countered", swept=against.swept())


def _check_teams(red_h: Sequence[Hero], blue_h: Sequence[Hero]) -> None:
    """Refuse a team no lobby seats: past six picks, or past the queue's
    tanks."""
    for team, seat in ((red_h, "red"), (blue_h, "blue")):
        check_team_size(team, seat)
        check_tanks(team, seat)


def _expected(
        world: World, m: Map | None, bans_h: Sequence[Hero], draft: Draft,
        catalog: list[Strategy]) -> Result:
    """Red's likely six - the map and the meta alone, past the bans - static
    for the board; until red reveals a pick it is what blue's seat counters.
    A Result like every other seat: its picks carry the reason each rests on."""
    likely = compute.expected_picks(world, m, banned=bans_h)
    return Result(kind="expected", map_name=m.name if m else None, red=[],
                  blue=[p["hero"] for p in likely], locked=[], catalog=catalog,
                  bans=list(draft.bans), side=draft.side, seat="red",
                  picks=[Pick(hero=p["hero"], role=p["role"], rate=p["rate"],
                              locked=p["locked"], why=p["why"], evidence=[])
                         for p in likely])
