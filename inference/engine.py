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
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures.process import BrokenProcessPool
from typing import NamedTuple

from db import Refusal
from inference import catalog as catalog_module
from inference import parallel
from inference.catalog import Strategy
from inference.plan import momentum, plan
from inference.result import Alternative, Board, Pick, Result
from inference.scale import Tally
from inference.scoring import Bounds, Candidate, legal_shapes
from inference.solver import Solved, Solver, Swept, evaluate_comp
from ui.facts import board_facts, compute
from ui.facts.draft import TEAM_SIZE, Draft, check_tanks, check_team_size, is_sided, opposite
from ui.facts.factset import FactSet
from ui.facts.model import ROLES, Hero, Map, World


class SearchBounds(NamedTuple):
    """How wide a search runs: candidates per role, and alternatives kept."""
    pool_size: int
    top: int


def clamp_search(pool: str | float | None = None,
                 top: str | float | None = None) -> SearchBounds:
    """Bounds on the search: pool 2..12 candidates per role, top 1..20
    alternatives. Every door that takes the two from a caller - the MCP tools
    and the HTTP service - passes them through here, so the search is bounded
    by one definition. Junk raises Refusal, which every door answers as the
    caller's error."""
    try:
        return SearchBounds(max(2, min(int(pool or 6), 12)), max(1, min(int(top or 5), 20)))
    except (TypeError, ValueError) as error:
        raise Refusal("pool and top must be numbers: %s" % error) from error


COUNTERED_POOL = 4          # a what-if: a smaller field is enough
BOARD_TOP = 5               # the alternatives each of a board's seats keeps


def _order(heroes: Iterable[Hero]) -> list[str]:
    return [h.name for h in sorted(heroes, key=lambda h: (ROLES.index(h.role), h.name))]


def _board_facts(world: World, result: Result, side: str) -> FactSet:
    """The facts of the board a result stands on: its map, both sides as it
    names them, its bans, and the side."""
    return board_facts.generate(world, Draft(result.map_name, tuple(result.red),
                                             tuple(result.blue), tuple(result.bans), side))


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
                    solved=None).result


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
        top: int, seat: str, kind: str, solved: Solved | None) -> _Optimal:
    """The optimal six for `seat` around its locked picks (`draft.blue`)
    against the other seat's revealed ones (`draft.red`), labelled `kind`.
    `solved` takes a Solved the caller already has - a board's search, run
    across the worker pool - in place of searching here."""
    started = time.time()
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
        seat: str, kind: str, swept: Swept | None) -> Result:
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
        catalog: list[Strategy], pool_size: int, seat: str, kind: str,
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


def _countered(
        world: World, draft: Draft, *, catalog: list[Strategy], pool_size: int,
        top: int, solved: Solved | None, swept: Swept | None) -> Result:
    """Blue's picks (`draft.blue`) against red's optimal six (`draft.red`):
    how they hold if red answers perfectly, on the scale of blue's best
    counter to that six."""
    hypothetical = min(pool_size, COUNTERED_POOL)
    against = _optimal(world, draft._replace(blue=()), catalog=catalog, pool_size=hypothetical,
                       top=top, seat="blue", kind="infer", solved=solved)
    return _current(world, draft, solver=against.solver, best=against.result.score,
                    catalog=catalog, pool_size=hypothetical, seat="blue", kind="countered",
                    swept=swept)


def board(
        world: World, draft: Draft, *, catalog: list[Strategy] | None = None,
        pool_size: int = 6, weights: dict[str, float] | None = None) -> Board:
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
                     if they answer you perfectly (None without blue picks)
        fill         blue's locked picks with the empty slots filled by the
                     solver - the best six that keeps what you hold, on
                     blue's optimal's scale (None unless one to five are locked)
        momentum     the verdict from the two current comps
        plan         the game plan in prose, from the same facts
        shapes       the (tanks, damage, supports) triples the queue and the
                     playbook's shape limits allow - what the roster enforces
                     as you pick; a team past six picks or two tanks is refused
        expected     red's likely six from the data alone - a two-two-two from
                     the map's pick rates and the wiki's synergies, past the
                     bans - static for the board, no strategy read; what the
                     comps tab shows for red and what blue counters until red
                     reveals a pick

    `weights` ({heuristic id: 0..10}) overrides the files' weights for this
    board only - the playbook tab's sliders; the files stay as they are and
    every result says the weights it was scored under.

    Across the pool the four searches are split and walked through their
    rounds together; in this process each seat searches for itself. A worker
    dying anywhere in the pooled pass drops the pool and runs the same pass
    here.
    """
    pooled = parallel.available(catalog)
    catalog = catalog_module.weighted(catalog or catalog_module.load(), weights)
    if not pooled:
        return _board_once(world, draft, catalog=catalog, pool_size=pool_size, weights=weights,
                           workers=None)
    try:
        return _board_once(world, draft, catalog=catalog, pool_size=pool_size, weights=weights,
                           workers=parallel.POOL.executor())
    except BrokenProcessPool:
        parallel.POOL.drop()                   # a worker died: this board, in this process
    return _board_once(world, draft, catalog=catalog, pool_size=pool_size, weights=weights,
                       workers=None)


def _board_once(world: World, draft: Draft, *, catalog: list[Strategy], pool_size: int,
                weights: Mapping[str, float] | None, workers: parallel.Workers | None) -> Board:
    """The board, its searches split across `workers`, or each run in this
    process where there are none."""
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    draft = draft._replace(side=_side(m, draft.side))
    _check_teams(red_h, blue_h)
    expected = _expected(world, m, bans_h, draft, catalog)
    enemy = draft.red or tuple(expected.blue)
    # each seat's draft, from that seat's perspective: its own picks are `blue`
    blue_seat = draft._replace(red=enemy, blue=())
    red_seat = Draft(draft.map_name, draft.blue, (), draft.bans, opposite(draft.side))
    ours = draft._replace(red=enemy)                   # the current comp and the fill
    theirs = Draft(draft.map_name, draft.blue, draft.red, draft.bans, opposite(draft.side))
    want = BOARD_TOP + 1
    half, rest = _slices(workers)
    full, wants_fill = len(draft.blue) == TEAM_SIZE, 0 < len(draft.blue) < TEAM_SIZE

    def split(
            seat: Draft, slices: int, *, pool_size: int = pool_size, bounds: Bounds | None = None,
            standing: Tally | None = None) -> parallel.Split | parallel.NullSplit:
        if workers is None:
            return parallel.NullSplit()
        return parallel.Split(workers.executor, world, catalog, parallel.Spec(seat, pool_size),
                              weights, want, slices, bounds, standing)

    blue_split, red_split = split(blue_seat, half), split(red_seat, rest)
    blue_split.rank_roster()
    red_split.rank_roster()
    blue_split.sweep()
    red_split.sweep()
    # the fill is blue's board, so it takes blue's scale and draws none
    fill_split = (split(ours, half, bounds=blue_split.bounds, standing=blue_split.standing)
                  if wants_fill else parallel.NullSplit())
    fill_split.sweep()
    blue_split.merge()
    red_split.merge()
    blue = _optimal(world, blue_seat, catalog=catalog, pool_size=pool_size, top=BOARD_TOP,
                    seat="blue", kind="infer", solved=blue_split.solved())
    red = _optimal(world, red_seat, catalog=catalog, pool_size=pool_size, top=BOARD_TOP,
                   seat="red", kind="infer", solved=red_split.solved())
    countering = bool(draft.blue and red.result.blue)
    countered_seat = draft._replace(red=tuple(red.result.blue))
    countered_split = (split(countered_seat._replace(blue=()), rest,
                             pool_size=min(pool_size, COUNTERED_POOL))
                       if countering else parallel.NullSplit())
    countered_split.sweep()
    fill_split.merge()
    countered_split.merge()
    # a full six is ranked against the field its seat's search just swept;
    # 100 is the seat's optimal, whatever it holds
    cur = _current(world, ours, solver=blue.solver, best=blue.result.score, catalog=catalog,
                   pool_size=pool_size, seat="blue", kind="current",
                   swept=blue_split.swept() if full else None)
    red_cur = _current(world, theirs, solver=red.solver, best=red.result.score, catalog=catalog,
                       pool_size=pool_size, seat="red", kind="current",
                       swept=red_split.swept() if len(draft.red) == TEAM_SIZE else None)
    fill = (_filled(world, ours, catalog=catalog, pool_size=pool_size, top=BOARD_TOP,
                    solved=fill_split.solved(), best=blue.result.score)
            if wants_fill else None)
    countered = (_countered(world, countered_seat, catalog=catalog, pool_size=pool_size,
                            top=BOARD_TOP, solved=countered_split.solved(),
                            swept=countered_split.swept() if full else None)
                 if countering else None)
    return Board(map_name=expected.map_name, side=draft.side, bans=list(draft.bans),
                 blue=blue.result, red=red.result, current=cur, red_current=red_cur,
                 fill=fill, countered=countered,
                 momentum=momentum(cur, red_cur, countered, blue.result, red.result, fill),
                 plan=plan(world, m, draft.side, list(draft.bans), red_h, blue.result),
                 shapes=[list(s) for s in legal_shapes(catalog)], expected=expected)


def _check_teams(red_h: Sequence[Hero], blue_h: Sequence[Hero]) -> None:
    """Refuse a team no lobby seats: past six picks, or past the queue's
    tanks."""
    for team, seat in ((red_h, "red"), (blue_h, "blue")):
        check_team_size(team, seat)
        check_tanks(team, seat)


def _slices(workers: parallel.Workers | None) -> tuple[int, int]:
    """How a board's searches share the pool: blue's and the fill's slices,
    and red's and the countered case's. In this process nothing is sliced."""
    size = workers.size if workers is not None else 0
    half = max(1, size // 2)
    return half, max(1, size - half)


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


def _filled(world: World, draft: Draft, *, catalog: list[Strategy], pool_size: int, top: int,
            solved: Solved | None, best: float) -> Result:
    """Blue's locked picks (`draft.blue`) with the empty slots filled by the
    solver, on the scale of blue's optimal, whose score is `best`: how close
    the best completion comes."""
    fill = _optimal(world, draft, catalog=catalog, pool_size=pool_size, top=top, seat="blue",
                    kind="fill", solved=solved).result
    fill.scale_to(best)
    return fill
