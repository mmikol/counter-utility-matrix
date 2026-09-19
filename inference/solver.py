"""The solver: the optimal six under the catalog, players playing optimally.

    sample     the REFERENCE: a seeded set of random legal sixes for this
               board (map, side, enemies, bans). Heuristics are normalised
               against it, so infer, evaluate and the current comp share one
               scale and a score means the same thing across calls. The seed
               is a string, so every process draws the same list and any of
               them can prepare a slice of it.
    standing   each hero's mean score across the reference sixes it is in:
               the playbook's own ranking of the roster on this board
    enumerate  every shape the hard limits allow, filled around the locked
               picks from a per-role pool ranked by standing (six per role by
               default)
    sweep      a slice of the enumeration prepared, scored and slimmed. The
               slices partition the field, so the search splits across
               processes.
    score      STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS: limits prune (soft ones
               charge), heuristics normalise and weigh, scored constraints add;
               assumptions are the agent's. A `when` reading only the enemy, the
               map and the world is settled once per board, not once per candidate.
               A heuristic guarded on the six's own state is a need: see score().
    rank       sorted by score, then tie-break, then names - a total order, so
               the answer does not depend on how the sweep was split
    refine     local search from the best six sixes and the best of every shape:
               swap any slot for any same-role hero on the roster, keep improvements
"""

import itertools
import random

from inference.catalog import BOARD_SECTIONS
from inference.expr import scope
from ui.facts import compute
from ui.facts.compute import ROLE_COUNT, TEAM_SIZE

REFERENCE_SIZE = 1200
PARTNER_POINTS = 0.5              # a locked partner's worth when ranking a pool
SEEDS = 6                         # the local search's starts, whatever `top` asks for
NEED_BUDGET = 2.0                 # the most one guarded state can cost
REFERENCE_SEED = 20260913

SHAPE_KEYS = {"team.tanks", "team.damage", "team.supports", "team.size",
              "team.open_slots"}

# the namespaces that do not change across the candidates of one board
STATIC_SECTIONS = BOARD_SECTIONS

_EMPTY = {}


class Candidate:
    __slots__ = (
        "contributions",
        "heroes",
        "key",
        "ns",
        "raw",
        "scope",
        "score",
        "tiebreak",
        "violations",
    )

    def __init__(self, heroes):
        self.heroes = tuple(heroes)
        self.key = frozenset(h.id for h in heroes)
        self.ns = None
        self.scope = None
        self.score = 0.0
        self.tiebreak = 0.0
        self.contributions = []
        self.violations = []
        self.raw = []          # one metric value per heuristic, in catalog order

    @property
    def names(self):
        return [h.name for h in self.heroes]


class Solver:
    def __init__(self, world, m, red, locked, catalog, pool_size=6, bans=(), side=""):
        self.world, self.m, self.red = world, m, list(red)
        self.locked = list(locked)
        self.banned = {h.id for h in bans}
        self.side = side
        self.catalog = catalog
        self.pool_size = pool_size
        self.limits = [h for h in catalog if h.form == "limit"]
        self.heuristics = [h for h in catalog if h.form == "heuristic"]
        self.scored_constraints = [h for h in catalog if h.form == "scored"]
        # the red side's metrics do not change across candidates
        self.red_t = compute.team_metrics(world, self.red, m, ())
        self.static = {"enemy": self.red_t, "map": compute.map_metrics(m, side, len(self.banned)),
                       "world": compute.world_metrics(world)}
        self.bounds = {}                     # heuristic id -> (min, max)
        self.considered = 0
        self._reference = None               # the sample, once drawn
        self._standing = {}                  # hero id -> mean reference score, once read
        # each strategy paired with its gate - True or False where `when` is
        # settled for the whole board, None where the candidate decides it -
        # and with the slot it shares with every strategy guarded the same way
        gates, slots, self.gate_slots = self._gates()
        self._limits = [(h, gates[h.id], slots.get(h.id, 0)) for h in self.limits]
        self._scored = [(r, gates[r.id], slots.get(r.id, 0))
                        for r in self.scored_constraints]
        self._heuristics = [(g, gates[g.id], slots.get(g.id, 0), *g.metric.split(".", 1))
                            for g in self.heuristics]
        # a heuristic guarded on the six's own state is a need: see score().
        # Needs that share a guard share NEED_BUDGET: the state costs at most
        # that much however many rules the playbook writes about it
        needs = [g for g in self.heuristics if gates[g.id] is None]
        written = {}
        for g in needs:
            written[g.when.source] = written.get(g.when.source, 0.0) + g.weight
        self._needs = {g.id: min(1.0, NEED_BUDGET / written[g.when.source])
                       if written[g.when.source] else 1.0 for g in needs}
        self._freeze_norms()

    def _gates(self):
        """Every strategy's `when`, read once per board: True where there is
        none, True or False where it touches only the static sections, None
        where the candidate decides it. -> (gate per id, slot per undecided
        id, how many slots). Strategies whose `when` and params are the same
        answer together, so they share a slot: a guard a dozen strategies
        write is evaluated once per candidate."""
        sc = scope(dict(self.static, matchup=compute.red_matchup(self.red_t)))
        gates, slots, groups = {}, {}, {}
        for h in self.catalog:
            if h.when is None:
                gates[h.id] = True
            elif all(n.split(".", 1)[0] in STATIC_SECTIONS or n in compute.RED_MATCHUP
                     for n in h.when.names):
                sc["params"] = h.params_section
                gates[h.id] = bool(h.when.eval(sc))
            else:
                gates[h.id] = None
                try:
                    key = (h.when.source, tuple(sorted(h.params.items())))
                    hash(key)
                except TypeError:          # a param the dialect read as a list
                    key = h.id
                slots[h.id] = groups.setdefault(key, len(groups))
        return gates, slots, len(groups)

    # --- namespace and scoring -----------------------------------------------

    def namespace(self, heroes, lean=True):
        team = compute.team_metrics(self.world, heroes, self.m, self.red, lean=lean)
        ns = dict(self.static)
        ns["team"] = team
        ns["matchup"] = compute.matchup_metrics(team, self.red_t)
        return ns

    @staticmethod
    def _holds(h, sc):
        """`when` on a Scope whose params slot is already h's."""
        if h.when is None:
            return True
        return bool(h.when.eval(sc))

    def prepare(self, cand):
        """Namespace, hard-limit check, raw heuristic values."""
        ns = cand.ns = self.namespace(cand.heroes)
        sc = cand.scope = scope(ns)
        held = [None] * self.gate_slots
        violations = []
        for h, gate, slot in self._limits:
            if gate is None:
                gate = held[slot]
                if gate is None:
                    sc["params"] = h.params_section
                    gate = held[slot] = bool(h.when.eval(sc))
            if gate:
                sc["params"] = h.params_section
                if not bool(h.require.eval(sc)) and not h.soft:
                    violations.append(h.id)
        cand.violations = violations
        raw = []
        keep = raw.append
        for g, gate, slot, section, key in self._heuristics:
            if gate is None:
                gate = held[slot]
                if gate is None:
                    sc["params"] = g.params_section
                    gate = held[slot] = bool(g.when.eval(sc))
            if gate:
                value = ns.get(section, _EMPTY).get(key)
                keep(float(value) if value else 0.0)
            else:
                keep(None)
        cand.raw = raw
        cand.tiebreak = ns["team"]["map_win_mean"]
        return cand

    @staticmethod
    def slim(cand):
        """Keep the verdict, drop the working: the namespace, the scope, the raw
        values and the breakdown. A search holds thousands of candidates at
        once and reads only their score, tie-break and picks; the winners are
        hydrated again before they are shown."""
        cand.ns = cand.scope = cand.raw = None
        cand.contributions = []
        return cand

    def hydrate(self, cand):
        """A slim candidate prepared and scored again, with its breakdown."""
        if cand.ns is None:
            self.prepare(cand)
        return self.score(cand)

    # --- the reference: one scale per board -------------------------------------

    def sample(self, size=REFERENCE_SIZE):
        """A seeded sample of random legal sixes for this board, unprepared.
        Deterministic for a given map, side, enemies and bans, and independent
        of the locked picks and the pool, so every call on one board shares a
        scale - and any process draws the same list and can take a slice."""
        rng = random.Random("%d|%s|%s|%s|%s" % (        # a str seed is stable across processes
            REFERENCE_SEED, self.m.id if self.m else 0, self.side,
            ",".join(str(i) for i in sorted(h.id for h in self.red)),
            ",".join(str(i) for i in sorted(self.banned))))
        by_role = {r: sorted((h for h in self.world.heroes.values()    # by id: the draw must
                              if h.role == r and h.released           # not hang on a
                              and h.id not in self.banned),           # query's row order
                             key=lambda h: h.id)
                   for r in ROLE_COUNT}
        shapes = legal_shapes(self.catalog)
        out, seen = [], set()
        if shapes:
            while len(out) < size:
                t, d, s = rng.choice(shapes)
                heroes = (rng.sample(by_role["tank"], t) + rng.sample(by_role["damage"], d)
                          + rng.sample(by_role["support"], s))
                cand = Candidate(heroes)
                if cand.key in seen:
                    continue
                seen.add(cand.key)
                out.append(cand)
        return out

    def reference(self, size=REFERENCE_SIZE):
        """The sample prepared, minus what the hard limits refuse: what every
        heuristic is normalised against."""
        if self._reference is None:
            self._reference = [c for c in (self.prepare(c) for c in self.sample(size))
                               if not c.violations]
        return self._reference

    def reference_bounds(self, index=0, count=1):
        """{heuristic id: (min, max)} over one slice of the sample, leaving out
        the heuristics the slice never valued. The slices partition the
        sample, so merging their lows and highs gives what one process
        freezes."""
        prepared = [c for c in (self.prepare(c) for c in self.sample()[index::count])
                    if not c.violations]
        out = {}
        for i, g in enumerate(self.heuristics):
            values = [c.raw[i] for c in prepared if c.raw[i] is not None]
            if values:
                out[g.id] = (min(values), max(values))
        return out

    def freeze_bounds(self):
        """Bounds per heuristic from the reference sample, then each hero's
        standing in it."""
        reference = self.reference()
        for i, g in enumerate(self.heuristics):
            values = [c.raw[i] for c in reference if c.raw[i] is not None]
            self.bounds[g.id] = (min(values), max(values)) if values else (0.0, 0.0)
        self._freeze_norms()
        self.adopt_standing(self._tally(reference))

    def adopt_bounds(self, bounds, standing=None):
        """Bounds (and standing) frozen elsewhere for this same board: another
        process's slice of the search, or an earlier solver on the same map,
        side, enemies and bans. The sample is seeded, so it draws the same
        numbers wherever it runs; taking them saves drawing it again."""
        self.bounds = dict(bounds)
        self._freeze_norms()
        if standing is not None:
            self.adopt_standing(standing)

    # --- standing: the playbook's own ranking of the roster --------------------

    def _tally(self, prepared):
        """{hero id: [summed score in millionths, sixes]} over prepared reference
        sixes. Whole numbers, so slices add up the same in any order."""
        tally = {}
        for cand in prepared:
            points = round(self.score(cand, detail=False).score * 1e6)
            for h in cand.heroes:
                seen = tally.setdefault(h.id, [0, 0])
                seen[0] += points
                seen[1] += 1
        return tally

    def reference_standing(self, index=0, count=1):
        """One slice of the sample scored under the frozen bounds -> its tally."""
        return self._tally([c for c in (self.prepare(c) for c in self.sample()[index::count])
                            if not c.violations])

    def adopt_standing(self, tally):
        """A hero's standing: the mean score of the reference sixes it is in -
        how the playbook in force rates it on this board, red and the map
        included. It ranks each role's pool, so the heroes searched in full
        are the ones the strategies favour, not the ones a side formula does."""
        self._standing = {hid: total / n for hid, (total, n) in tally.items() if n}

    def _freeze_norms(self):
        """One tuple per heuristic for the scoring loop: the strategy, the
        reference low, the reference spread (None where the sample never
        moved: everything then normalises to 0.5), its weight, whether it
        minimises and whether it is a need."""
        self._norm = [(g, lo, hi - lo if hi > lo else None,
                       g.weight * self._needs.get(g.id, 1.0),
                       g.direction == "minimize", g.id in self._needs)
                      for g, (lo, hi) in ((g, self.bounds.get(g.id, (0.0, 0.0)))
                                          for g in self.heuristics)]

    def score(self, cand, detail=True):
        """Score with the frozen bounds; with detail, fill the breakdown too.

        A heuristic with no guard, or a guard on the board (enemy, map), adds
        weight x norm. A heuristic guarded on the six's own state (team.*,
        matchup.*) is a need - "a solo healer needs an escape" - and adds
        weight x (norm - 1): met in full it costs nothing, unmet it costs the
        weight, and entering the guarded state never pays. Needs written on
        one guard are scaled to sum to NEED_BUDGET at most."""
        total, contributions = 0.0, []
        sc = cand.scope
        held = [None] * self.gate_slots
        for h, applies, slot in self._limits:
            if applies is None:
                applies = held[slot]
                if applies is None:
                    sc["params"] = h.params_section
                    applies = held[slot] = bool(h.when.eval(sc))
            ok, penalty = True, 0.0
            if applies:
                sc["params"] = h.params_section
                ok = bool(h.require.eval(sc))
                if h.soft and not ok:
                    penalty = float(h.penalty.eval(sc))
            total -= penalty
            if detail:
                contributions.append({"id": h.id, "kind": "constraint", "form": "limit",
                                      "applies": applies, "ok": ok, "weighted": -penalty,
                                      "metric": h.require.source})
        for raw, (g, lo, span, weight, minimize, need) in zip(cand.raw, self._norm,
                                                               strict=True):
            if raw is None:
                if detail:
                    contributions.append({"id": g.id, "kind": "heuristic",
                                          "form": "heuristic", "applies": False, "raw": None,
                                          "norm": 0.0, "weighted": 0.0, "metric": g.metric})
                continue
            if span is not None:
                norm = (raw - lo) / span
                if norm > 1.0:            # the candidate sits outside the sample
                    norm = 1.0
                elif norm < 0.0:
                    norm = 0.0
            else:
                norm = 1.0 if need else 0.5     # a need nothing here can miss costs nothing
            if minimize and span is not None:
                norm = 1.0 - norm
            weighted = weight * (norm - 1.0) if need else weight * norm
            total += weighted
            if detail:
                contributions.append({"id": g.id, "kind": "heuristic", "form": "heuristic",
                                      "applies": True, "raw": raw, "norm": norm,
                                      "weighted": weighted, "metric": g.metric,
                                      "spread": span is not None, "need": need})
        for r, applies, slot in self._scored:
            if applies is None:
                applies = held[slot]
                if applies is None:
                    sc["params"] = r.params_section
                    applies = held[slot] = bool(r.when.eval(sc))
            bonus = penalty = 0.0
            if applies:
                sc["params"] = r.params_section
                if r.bonus is not None:
                    bonus = float(r.bonus.eval(sc))
                if r.penalty is not None:
                    penalty = float(r.penalty.eval(sc))
            weighted = r.weight * (bonus - penalty)
            total += weighted
            if detail:
                contributions.append({"id": r.id, "kind": "constraint", "form": "scored",
                                      "applies": applies, "bonus": bonus, "penalty": penalty,
                                      "weighted": weighted, "metric": r.expressions})
        cand.score = total
        cand.contributions = contributions
        return cand

    # --- enumeration ---------------------------------------------------------------

    def shapes(self):
        """(tanks, damage, supports) triples the shape-only hard limits
        allow, that can still seat the locked picks."""
        return legal_shapes(self.catalog, {r: sum(1 for h in self.locked if h.role == r)
                                           for r in ROLE_COUNT})

    def prior(self, h):
        """The ranking that cut the pools before the playbook ranked them
        itself: still the tie-break, and the whole ranking when nothing scores."""
        base = h.map_win(self.m.id) if self.m is not None and h.map_win(self.m.id) \
            is not None else (h.win if h.win is not None else 50.0)
        answers = sum(1 for e in self.red if self.world.counters_of(e.id, h.id))
        exposed = sum(1 for e in self.red if self.world.counters_of(h.id, e.id))
        partners = sum(1 for a in self.locked if self.world.synergy(a.id, h.id))
        style = 1 if (self.m is not None and self.m.style_top in h.styles) else 0
        listed = 1 if (self.m is not None and self.m.id in h.best_maps) else 0
        return base + 3.0 * answers - 3.0 * exposed + 2.0 * partners + style + listed

    def pools(self):
        locked_ids = {h.id for h in self.locked} | self.banned
        pools = {}
        for role in ROLE_COUNT:
            heroes = [h for h in self.world.heroes.values()      # announced heroes wait
                      if h.role == role and h.released and h.id not in locked_ids]
            heroes.sort(key=self._pool_key)
            pools[role] = heroes[:self.pool_size]
        return pools

    def _pool_key(self, h):
        """Standing first, a point for each locked partner; then the old prior,
        then the name."""
        standing = self._standing.get(h.id)
        if standing is not None:
            standing += PARTNER_POINTS * 1e6 * sum(
                1 for a in self.locked if self.world.synergy(a.id, h.id))
        return (-(standing if standing is not None else float("-inf")), -self.prior(h), h.name)

    def enumerate(self):
        """Every legal six around the locked picks, as a list of heroes. A six's
        roles fix its shape and the pools hold neither the locked picks nor the
        bans, so no two of these are the same set. Lazy: a slice of the search
        builds candidates for its own positions and walks past the rest."""
        pools = self.pools()
        locked_by_role = {r: [h for h in self.locked if h.role == r] for r in ROLE_COUNT}
        for t, d, s in self.shapes():
            need = {"tank": t - len(locked_by_role["tank"]),
                    "damage": d - len(locked_by_role["damage"]),
                    "support": s - len(locked_by_role["support"])}
            choices = [list(itertools.combinations(pools[r], need[r]))
                       for r in ("tank", "damage", "support")]
            for combo in itertools.product(*choices):
                yield self.locked + [h for part in combo for h in part]

    # --- the search -------------------------------------------------------------------

    def sweep(self, index=0, count=1):
        """Every `count`-th candidate of the enumeration, from `index`:
        prepared, scored and slimmed, so a search of thousands holds only
        verdicts. -> (the whole field's size, the feasible ones of this
        slice). The slices of one field partition it, so any split of the
        work reaches the same set."""
        feasible, size = [], 0
        for heroes in self.enumerate():
            if size % count == index:
                cand = self.prepare(Candidate(heroes))
                if not cand.violations:
                    feasible.append(self.slim(self.score(cand, detail=False)))
            size += 1
        return size, feasible

    def rank(self, feasible, top=5, refine=True):
        """The best sixes of a swept field, refined and hydrated. The order is
        the _rank_key's alone, so it does not depend on how the sweep was
        split."""
        if not feasible:
            return []
        feasible.sort(key=self._rank_key)
        if refine:
            feasible = self.refine(feasible)
        return [self.hydrate(c) for c in feasible[:top]]

    def solve(self, top=5, refine=True):
        """The best sixes, in this process."""
        self.freeze_bounds()
        self.considered, feasible = self.sweep()
        return self.rank(feasible, top, refine)

    @staticmethod
    def _rank_key(c):
        return (-c.score, -c.tiebreak, c.names)

    def refine(self, ranked):
        """Local search: swap any open slot for any same-role hero. A swap keeps
        the shape, so the starts are the best SEEDS of the field and the best
        six of every shape in it: an off-shape six can win only if its own
        shape was searched."""
        known = {c.key: c for c in ranked}
        locked_ids = {h.id for h in self.locked}
        roster = sorted(self.world.heroes.values(), key=lambda h: h.id)
        starts, shapes = list(ranked[:SEEDS]), set()
        for cand in ranked:
            shape = tuple(sorted(h.role for h in cand.heroes))
            if shape not in shapes:
                shapes.add(shape)
                if cand not in starts:
                    starts.append(cand)
        for seed in starts:
            current = seed
            while True:
                best = current
                for index, hero in enumerate(current.heroes):
                    if hero.id in locked_ids:
                        continue
                    for other in roster:
                        if (other.role != hero.role or other.id in current.key
                                or other.id in self.banned or not other.released):
                            continue                  # announced heroes wait here too
                        heroes = list(current.heroes)
                        heroes[index] = other
                        cand = Candidate(heroes)
                        if cand.key in known:
                            cand = known[cand.key]
                        else:
                            self.prepare(cand)
                            self.considered += 1
                            if cand.violations:
                                continue
                            self.slim(self.score(cand, detail=False))
                            known[cand.key] = cand
                        if cand.score > best.score + 1e-9:
                            best = cand
                if best is current:
                    break
                current = best
        out = list(known.values())
        out.sort(key=self._rank_key)
        return out


def legal_shapes(catalog, locked_counts=None):
    """(tanks, damage, supports) triples the catalog's shape-only hard limits
    allow - the playbook's rule of the game's form (at most two tanks; or
    2-2-2) - optionally only those that can still seat the picks counted per
    role. The board carries the full list so the roster can refuse a pick no
    legal six could seat."""
    locked_counts = locked_counts or dict.fromkeys(ROLE_COUNT, 0)
    shape_constraints = [h for h in catalog if h.form == "limit" and not h.soft and h.require
                         and set(h.require.names) <= SHAPE_KEYS
                         and (h.when is None or set(h.when.names) <= SHAPE_KEYS)]
    out = []
    for t in range(TEAM_SIZE + 1):
        for d in range(TEAM_SIZE + 1 - t):
            s = TEAM_SIZE - t - d
            if (t < locked_counts["tank"] or d < locked_counts["damage"]
                    or s < locked_counts["support"]):
                continue
            stub = scope({"team": {"tanks": t, "damage": d, "supports": s,
                                   "size": TEAM_SIZE, "open_slots": 0}})
            ok = True
            for h in shape_constraints:
                stub["params"] = h.params_section
                if Solver._holds(h, stub) and not bool(h.require.eval(stub)):
                    ok = False
                    break
            if ok:
                out.append((t, d, s))
    return out


def evaluate_comp(world, m, red, heroes, catalog, pool_size=6, bans=(), side="",
                  swept=None):
    """Score one full six against the field the solver would search. `swept`
    takes a (solver, field size, feasible) swept elsewhere - the same board's
    optimal search, which sweeps the same field."""
    if swept is None:
        solver = Solver(world, m, red, [], catalog, pool_size, bans, side)
        solver.freeze_bounds()                # the same reference scale as infer
        solver.considered, feasible = solver.sweep()
    else:
        solver, size, feasible = swept
        solver.considered = size
    target = solver.score(solver.prepare(Candidate(heroes)))
    feasible.sort(key=Solver._rank_key)
    rank = 1 + sum(1 for c in feasible if c.score > target.score + 1e-9)
    return target, [solver.hydrate(c) for c in feasible[:5]], rank, solver
