"""The search: the optimal six under the catalog, players playing optimally.
A Solver is the board's Objective (inference.scoring) on the board's scale
(inference.scale), searched around the locked picks.

    legal_sixes     every shape the hard limits allow, filled around the locked
                    picks from a per-role pool ranked by standing (six per role
                    by default)
    sweep           a slice of the enumeration prepared, scored and slimmed. The
                    slices partition the field, so the search splits across
                    processes.
    rank            sorted by score, then tie-break, then names - a total order, so
                    the answer does not depend on how the sweep was split
    refine          local search from the best six sixes and the best of every
                    shape: swap any slot for any same-role hero on the roster, keep
                    improvements; bring each of the wiki's synergy pairs into the
                    best sixes two slots at once; then climb from random sixes of
                    the leader's shape and change two seats at once
"""

import heapq
import itertools
import random
from collections.abc import Iterator, Mapping, Sequence
from typing import NamedTuple

from db import Refusal
from inference import scale
from inference.catalog import Strategy
from inference.scoring import Candidate, Objective, Shape, legal_shapes
from ui.facts.model import ROLES, Hero, Map, World

PARTNER_POINTS = 0.5              # a locked partner's worth when ranking a pool
SEEDS = 6                         # the local search's starts, whatever `top` asks for
RESTARTS = 24                     # in-shape random starts: the SEEDS are near-duplicates
SHAPE_REACH = 4.0                 # a shape starts too when its best six is this close
PAIR_TRIES = 800                  # the most new sixes one refine scores bringing pairs in


class Solved(NamedTuple):
    """A board's search: the solver that ran it and its ranked winners, hydrated."""
    solver: "Solver"
    ranked: list[Candidate]


class Swept(NamedTuple):
    """A board's field: the whole enumeration's size and one slice's feasible sixes."""
    solver: "Solver"
    size: int
    feasible: list[Candidate]


class Evaluated(NamedTuple):
    """A full six scored and ranked against the refined field's best five, hydrated."""
    target: Candidate
    field: list[Candidate]
    rank: int
    solver: "Solver"


class Solver(Objective):
    """One board's search: the playbook's objective on this board, the scale
    it is normalised on, and the local search around the locked picks."""

    def __init__(self, world: World, m: Map | None, *, red: Sequence[Hero],
                 locked: Sequence[Hero], banned: Sequence[Hero] = (), side: str = "",
                 catalog: list[Strategy], pool_size: int = 6) -> None:
        super().__init__(world, m, red=red, banned=banned, side=side, catalog=catalog)
        self.locked = list(locked)
        self._locked_by_role = {r: [h for h in self.locked if h.role == r] for r in ROLES}
        self.pool_size = pool_size
        self.considered = 0
        self._standing: dict[int, float] = {}   # hero id -> mean reference score, once read

    # --- the scale and the standing ---------------------------------------------

    def freeze_bounds(self) -> None:
        """Bounds per heuristic from the reference sample and the field, then
        each hero's standing in the sample."""
        self.adopt_standing(scale.freeze(self))

    def adopt_bounds(self, bounds: Mapping[str, tuple[float, float]],
                     standing: Mapping[int, Sequence[int]] | None = None) -> None:
        """Bounds (and standing) frozen elsewhere for this same board: another
        process's slice of the search, or an earlier solver on the same map,
        side, enemies and bans. The sample is seeded, so it draws the same
        numbers wherever it runs; taking them saves drawing it again."""
        super().adopt_bounds(bounds)
        if standing is not None:
            self.adopt_standing(standing)

    def adopt_standing(self, tally: Mapping[int, Sequence[int]]) -> None:
        """A hero's standing: the mean score of the reference sixes it is in -
        how the playbook in force rates it on this board, red and the map
        included. It ranks each role's pool, so the heroes searched in full
        are the ones the strategies favour, not the ones a side formula does."""
        self._standing = {hid: total / n for hid, (total, n) in tally.items() if n}

    # --- enumeration ---------------------------------------------------------------

    def shapes(self) -> list[Shape]:
        """(tanks, damage, supports) triples the shape-only hard limits
        allow, that can still seat the locked picks."""
        counts = {r: len(v) for r, v in self._locked_by_role.items()}
        return legal_shapes(self.catalog, counts)

    def prior(self, h: Hero) -> float:
        """The ranking that cut the pools before the playbook ranked them
        itself: still the tie-break, and the whole ranking when nothing scores.
        The board's prior, with a hero's partners among the locked picks."""
        partners = sum(1 for a in self.locked if self.world.synergy(a.id, h.id))
        return scale.board_prior(self, h, partners)

    def pools(self) -> dict[str, list[Hero]]:
        locked_ids = {h.id for h in self.locked} | self.banned
        pools: dict[str, list[Hero]] = {}
        for role in ROLES:
            heroes = [h for h in self.world.heroes.values()      # announced heroes wait
                      if h.role == role and h.released and h.id not in locked_ids]
            heroes.sort(key=self._pool_key)
            pools[role] = heroes[:self.pool_size]
        return pools

    def _pool_key(self, h: Hero) -> tuple[float, float, str]:
        """Standing first, a point for each locked partner; then the old prior,
        then the name."""
        standing = self._standing.get(h.id)
        if standing is not None:
            standing += PARTNER_POINTS * 1e6 * sum(
                1 for a in self.locked if self.world.synergy(a.id, h.id))
        return (-(standing if standing is not None else float("-inf")), -self.prior(h), h.name)

    def legal_sixes(self) -> Iterator[list[Hero]]:
        """Every legal six around the locked picks, as a list of heroes. A six's
        roles fix its shape and the pools hold neither the locked picks nor the
        bans, so no two of these are the same set. Lazy: a slice of the search
        builds candidates for its own positions and walks past the rest."""
        pools = self.pools()
        locked_by_role = self._locked_by_role
        for t, d, s in self.shapes():
            need = {"tank": t - len(locked_by_role["tank"]),
                    "damage": d - len(locked_by_role["damage"]),
                    "support": s - len(locked_by_role["support"])}
            choices = [list(itertools.combinations(pools[r], need[r]))
                       for r in ("tank", "damage", "support")]
            for combo in itertools.product(*choices):
                yield self.locked + [h for part in combo for h in part]

    # --- the search -------------------------------------------------------------------

    def sweep(self, index: int = 0, count: int = 1) -> Swept:
        """Every `count`-th candidate of the enumeration, from `index`:
        prepared, scored and slimmed, so a search of thousands holds only
        verdicts. -> Swept: this solver, the whole field's size and the
        feasible ones of this slice. The slices of one field partition it, so
        any split of the work reaches the same set."""
        feasible: list[Candidate] = []
        size = 0
        for heroes in self.legal_sixes():
            if size % count == index:
                cand = self.prepare(Candidate(heroes))
                if not cand.violations:
                    feasible.append(self.slim(self.score(cand, detail=False)))
            size += 1
        return Swept(self, size, feasible)

    def rank(self, feasible: list[Candidate], top: int = 5,
                refine: bool = True) -> list[Candidate]:
        """The best sixes of a swept field, refined and hydrated. The order is
        the _rank_key's alone, so it does not depend on how the sweep was
        split."""
        if not feasible:
            return []
        feasible.sort(key=self._rank_key)
        if refine:
            feasible = self.refine(feasible)
        return [self.hydrate(c) for c in feasible[:top]]

    def solve(self, top: int = 5, refine: bool = True) -> Solved:
        """The best sixes, in this process."""
        self.freeze_bounds()
        swept = self.sweep()
        self.considered = swept.size
        return Solved(self, self.rank(swept.feasible, top, refine))

    @staticmethod
    def _rank_key(c: Candidate) -> tuple[float, float, list[str]]:
        # sorted: a six's names in seat order are a construction artifact, so the
        # same hero set could key 720 ways and the order would not be a function
        # of the composition
        return (-c.score, -c.tiebreak, sorted(c.names))

    def refine(self, ranked: list[Candidate]) -> list[Candidate]:
        """Local search: swap any open slot for any same-role hero. A swap keeps
        the shape, so the starts are the best SEEDS of the field and the best
        six of every shape in it: an off-shape six can win only if its own
        shape was searched. Then the best SEEDS sixes try each of the wiki's synergy pairs
        brought in two slots at once, and the swaps run on from any that gained:
        partners that pay only together are never met one swap at a time.

        An empty field refines to an empty field: rank() returns before calling
        it, and evaluate_comp refuses a board with no feasible six the way
        infer does."""
        if not ranked:
            return []
        known = {c.key: c for c in ranked}
        starts = list(ranked[:SEEDS])
        shapes: set[tuple[str, ...]] = set()
        floor = ranked[0].score - SHAPE_REACH
        for cand in ranked:                   # sorted: the first of a shape is its best
            if cand.score < floor:
                break                         # a swap or two will not make this up
            shape = tuple(sorted(h.role for h in cand.heroes))
            if shape not in shapes:
                shapes.add(shape)
                if cand not in starts:
                    starts.append(cand)
        roster = [h for h in sorted(self.world.heroes.values(), key=lambda h: h.id)
                  if h.released and h.id not in self.banned]    # announced heroes wait here too
        for seed in starts:
            self._climb(seed, roster, known)
        pairs = self._pairs()
        if pairs:
            for seed in heapq.nsmallest(SEEDS, known.values(), key=self._rank_key):
                spent = self.considered + PAIR_TRIES      # each seed gets its own budget
                paired = self._bring_pair(seed, pairs, known, spent)
                if paired is not seed:
                    self._climb(paired, roster, known)
        # the SEEDS are the top of one pool-restricted sweep and sit within a swap
        # or two of each other, so the climbs above share a basin; and a climb moves
        # one seat at a time, so a six two swaps away is unreachable however many
        # times it is started. These two stages answer those in that order.
        leader = min(known.values(), key=self._rank_key)
        leader = self._restarts(leader, roster, known)
        self._two_swap(leader, roster, known)
        out = list(known.values())
        out.sort(key=self._rank_key)
        return out

    def _try(self, heroes: Sequence[Hero],
                known: dict[frozenset[int], Candidate]) -> Candidate | None:
        """The six prepared, scored and slimmed once; None where a hard limit
        refuses it."""
        cand = Candidate(heroes)
        if cand.key in known:
            return known[cand.key]
        self.prepare(cand)
        self.considered += 1
        if cand.violations:
            return None
        known[cand.key] = self.slim(self.score(cand, detail=False))
        return cand

    def _climb(self, seed: Candidate, roster: Sequence[Hero],
                known: dict[frozenset[int], Candidate]) -> Candidate:
        """Single-slot swaps from one six until none ranks above it."""
        locked_ids = {h.id for h in self.locked}
        current = seed
        while True:
            best = current
            for index, hero in enumerate(current.heroes):
                if hero.id in locked_ids:
                    continue
                for other in roster:
                    if other.role != hero.role or other.id in current.key:
                        continue
                    heroes = list(current.heroes)
                    heroes[index] = other
                    cand = self._try(heroes, known)
                    if cand is not None and _beats(cand, best):
                        best = cand
            if best is current:
                return current
            current = best

    def _restarts(self, leader: Candidate, roster: Sequence[Hero],
                  known: dict[frozenset[int], Candidate], n: int = RESTARTS) -> Candidate:
        """Climbs from random sixes of the leader's own shape. A climb preserves
        the shape, so a start off it can only report on a shape already searched;
        confining the draw is what makes a couple of dozen starts enough."""
        locked_ids = {h.id for h in self.locked}
        by_role = {r: [h for h in roster if h.role == r and h.id not in locked_ids]
                   for r in ROLES}
        locked_by_role = self._locked_by_role
        shape = {r: sum(1 for h in leader.heroes if h.role == r) for r in ROLES}
        seed = "restart|%s|%s" % (self.m.id if self.m else 0, self.side)
        rng = random.Random(seed)  # nosec B311  # a str seed, stable across processes
        best = leader
        for _ in range(n):
            heroes: list[Hero] = []
            short = False                     # a role with too few heroes for the shape
            for role in ROLES:
                need = shape[role] - len(locked_by_role[role])
                if not 0 <= need <= len(by_role[role]):
                    short = True
                    break
                heroes += locked_by_role[role] + rng.sample(by_role[role], need)
            if short:
                continue
            cand = self._try(heroes, known)
            if cand is None:
                continue
            cand = self._climb(cand, roster, known)
            if _beats(cand, best):
                best = cand
        return best

    def _two_swap(self, leader: Candidate, roster: Sequence[Hero],
                  known: dict[frozenset[int], Candidate]) -> Candidate:
        """Two open seats changed at once, to convergence. Two picks that pay
        only together are a saddle a one-slot climb cannot cross."""
        locked_ids = {h.id for h in self.locked}
        current = leader
        while True:
            best = current
            for heroes in _two_swaps(current, roster, locked_ids):
                cand = self._try(heroes, known)
                if cand is not None and _beats(cand, best):
                    best = cand
            if best is current:
                return current
            current = self._climb(best, roster, known)

    def _pairs(self) -> list[tuple[Hero, Hero]]:
        """The wiki's synergy pairs this board can field, in id order."""
        heroes = self.world.heroes
        out = []
        ids = sorted(tuple(sorted(pair)) for pair in self.world.synergies if len(pair) == 2)
        for a_id, b_id in ids:
            a, b = heroes.get(a_id), heroes.get(b_id)
            if (a is not None and b is not None and a.released and b.released
                    and a.id not in self.banned and b.id not in self.banned):
                out.append((a, b))
        return out

    def _bring_pair(self, seed: Candidate, pairs: Sequence[tuple[Hero, Hero]],
                    known: dict[frozenset[int], Candidate], spent: int) -> Candidate:
        """Each pair with neither partner in the six, seated in two open slots of
        their own roles, until `considered` reaches `spent`. -> the best six met,
        the seed itself where none beat it."""
        locked_ids = {h.id for h in self.locked}
        open_slots: dict[str, list[int]] = {}
        for index, hero in enumerate(seed.heroes):
            if hero.id not in locked_ids:
                open_slots.setdefault(hero.role, []).append(index)
        best = seed
        for a, b in pairs:
            if a.id in seed.key or b.id in seed.key:
                continue                      # one swap reaches these
            if self.considered >= spent:
                break
            for i, j in _seatings(open_slots, a, b):
                heroes = list(seed.heroes)
                heroes[i], heroes[j] = a, b
                cand = self._try(heroes, known)
                if cand is not None and _beats(cand, best):
                    best = cand
        return best


def _beats(cand: Candidate, best: Candidate) -> bool:
    """Whether a six ranks above another in the order rank() sorts by: score,
    then tie-break, then names. A search that moved on score alone stood still
    wherever sixes tie - everywhere, under a playbook that scores nothing - and
    never met the better tie-break a swap away, so a fill that kept the
    optimal's own picks came back a different six."""
    if cand.score != best.score:
        return cand.score > best.score
    return Solver._rank_key(cand) < Solver._rank_key(best)


def _two_swaps(current: Candidate, roster: Sequence[Hero],
                locked_ids: set[int]) -> Iterator[list[Hero]]:
    """Every six two open seats from `current`: each pair of open seats, in
    seat order, refilled with two other heroes of their roles."""
    open_seats = [i for i, h in enumerate(current.heroes) if h.id not in locked_ids]
    for i, j in itertools.combinations(open_seats, 2):
        role_i, role_j = current.heroes[i].role, current.heroes[j].role
        for x in roster:
            if x.role != role_i or x.id in current.key:
                continue
            for y in roster:
                if y.role != role_j or y.id in current.key or y.id == x.id:
                    continue
                heroes = list(current.heroes)
                heroes[i], heroes[j] = x, y
                yield heroes


def _seatings(open_slots: Mapping[str, Sequence[int]], a: Hero,
                b: Hero) -> Iterator[tuple[int, int]]:
    """The seats a pair can take: a in an open slot of its role, b in another
    of its own."""
    for i in open_slots.get(a.role, ()):
        for j in open_slots.get(b.role, ()):
            # the same six, seated the other way round, is met once
            if i != j and not (a.role == b.role and i > j):
                yield i, j


def evaluate_comp(world: World, m: Map | None, heroes: Sequence[Hero], *,
                  red: Sequence[Hero], banned: Sequence[Hero] = (), side: str = "",
                  catalog: list[Strategy], pool_size: int = 6,
                  swept: Swept | None = None) -> Evaluated:
    """Score one full six against the field the solver would search. `swept`
    takes a Swept from elsewhere - the same board's optimal search, which
    sweeps the same field. A board with no feasible six is refused, as infer
    refuses it."""
    if swept is None:
        solver = Solver(world, m, red=red, locked=[], banned=banned, side=side,
                        catalog=catalog, pool_size=pool_size)
        solver.freeze_bounds()                # the same reference scale as infer
        swept = solver.sweep()
    solver = swept.solver
    solver.considered = swept.size
    if not swept.feasible:
        raise Refusal("no composition satisfies the limits on this board - relax a"
                      " constraint in inference/strategies/")
    target = solver.score(solver.prepare(Candidate(heroes)))
    # rank against the field the search actually ends on. Ranking against the raw
    # sweep alone called a six first that the refinement had already beaten, so a
    # comp and a strictly better one both read rank 1.
    feasible = solver.refine(sorted(swept.feasible, key=Solver._rank_key))
    rank = 1 + sum(1 for c in feasible if c.score > target.score + 1e-9)
    return Evaluated(target, [solver.hydrate(c) for c in feasible[:5]], rank, solver)
