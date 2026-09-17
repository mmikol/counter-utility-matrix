"""The solver: the optimal six under the catalog, players playing optimally.

    enumerate  every shape the hard limits allow, filled around the
               locked picks from a per-role pool ranked by a cheap prior
               (six per role by default)
    score      STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS: limits prune (soft ones charge),
               heuristics normalise and weigh, scored constraints add; assumptions are
               the agent's. Heuristics are normalised against a REFERENCE:
               a seeded sample of random legal sixes for this board (map,
               side, enemies, bans), so infer, evaluate and the current
               comp share one scale and a score means the same thing
               across calls.
    refine     local search from the best few: swap any slot for any
               same-role hero on the roster, keep improvements
"""

import itertools
import random

from inference.expr import scope
from ui.facts import compute
from ui.facts.compute import ROLE_COUNT, TEAM_SIZE

REFERENCE_SIZE = 1200
REFERENCE_SEED = 20260913

SHAPE_KEYS = {"team.tanks", "team.damage", "team.supports", "team.size",
              "team.open_slots"}


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
        self.raw = {}

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
        self.heuristics = [h for h in catalog if h.kind == "heuristic"]
        self.scored_constraints = [h for h in catalog if h.form == "scored"]
        self.heuristic_keys = {g.id: tuple(g.metric.split(".", 1)) for g in self.heuristics}
        # the red side's metrics do not change across candidates
        self.red_t = compute.team_metrics(world, self.red, m, ())
        self.static = {"enemy": self.red_t, "map": compute.map_metrics(m, side),
                       "world": compute.world_metrics(world)}
        self.bounds = {}                     # heuristic id -> (min, max)
        self.considered = 0
        self._reference = None               # the sample, once drawn

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
        cand.ns = self.namespace(cand.heroes)
        cand.scope = scope(cand.ns)
        sc = cand.scope
        cand.violations = []
        for h in self.limits:
            sc["params"] = h.params_section
            if self._holds(h, sc) and not bool(h.require.eval(sc)) and not h.soft:
                cand.violations.append(h.id)
        raw = {}
        for g in self.heuristics:
            sc["params"] = g.params_section
            if self._holds(g, sc):
                section, key = self.heuristic_keys[g.id]
                value = cand.ns.get(section, {}).get(key)
                raw[g.id] = float(value or 0)
            else:
                raw[g.id] = None
        cand.raw = raw
        cand.tiebreak = cand.ns["team"]["map_win_mean"]
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

    def reference(self, size=REFERENCE_SIZE):
        """A seeded sample of random legal sixes for this board, prepared:
        what every heuristic is normalised against. Deterministic for a given
        map, side, enemies and bans, and independent of the locked picks
        and the pool, so every call on one board shares a scale."""
        if self._reference is not None:
            return self._reference
        rng = random.Random("%d|%s|%s|%s|%s" % (        # a str seed is stable across processes
            REFERENCE_SEED, self.m.id if self.m else 0, self.side,
            ",".join(str(i) for i in sorted(h.id for h in self.red)),
            ",".join(str(i) for i in sorted(self.banned))))
        by_role = {r: [h for h in self.world.heroes.values()
                       if h.role == r and h.released and h.id not in self.banned]
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
                out.append(self.prepare(cand))
        self._reference = [c for c in out if not c.violations]
        return self._reference

    def freeze_bounds(self):
        """Bounds per heuristic from the reference sample."""
        for g in self.heuristics:
            values = [c.raw[g.id] for c in self.reference() if c.raw.get(g.id) is not None]
            self.bounds[g.id] = (min(values), max(values)) if values else (0.0, 0.0)

    def score(self, cand, detail=True):
        """Score with the frozen bounds; with detail, fill the breakdown too."""
        total, contributions = 0.0, []
        sc = cand.scope
        for h in self.limits:
            sc["params"] = h.params_section
            applies = self._holds(h, sc)
            ok = bool(h.require.eval(sc)) if applies else True
            penalty = float(h.penalty.eval(sc)) if (h.soft and applies and not ok) else 0.0
            total -= penalty
            if detail:
                contributions.append({"id": h.id, "kind": "constraint", "form": "limit",
                                      "applies": applies, "ok": ok, "weighted": -penalty,
                                      "metric": h.require.source})
        for g in self.heuristics:
            raw = cand.raw.get(g.id)
            if raw is None:
                if detail:
                    contributions.append({"id": g.id, "kind": "heuristic",
                                          "form": "heuristic", "applies": False, "raw": None,
                                          "norm": 0.0, "weighted": 0.0, "metric": g.metric})
                continue
            lo, hi = self.bounds.get(g.id, (raw, raw))
            if hi > lo:
                norm = (raw - lo) / (hi - lo)
                norm = min(1.0, max(0.0, norm))
            else:
                norm = 0.5
            if g.direction == "minimize":
                norm = 1.0 - norm
            weighted = g.weight * norm
            total += weighted
            if detail:
                contributions.append({"id": g.id, "kind": "heuristic", "form": "heuristic",
                                      "applies": True, "raw": raw, "norm": norm,
                                      "weighted": weighted, "metric": g.metric,
                                      "spread": hi > lo})
        for r in self.scored_constraints:
            sc["params"] = r.params_section
            applies = self._holds(r, sc)
            bonus = float(r.bonus.eval(sc)) if (applies and r.bonus is not None) else 0.0
            penalty = float(r.penalty.eval(sc)) if (applies and r.penalty is not None) else 0.0
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
        """A cheap ranking to cut each role's pool before enumeration."""
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
            heroes.sort(key=self.prior, reverse=True)
            pools[role] = heroes[:self.pool_size]
        return pools

    def enumerate(self):
        pools = self.pools()
        locked_by_role = {r: [h for h in self.locked if h.role == r] for r in ROLE_COUNT}
        seen, out = set(), []
        for t, d, s in self.shapes():
            need = {"tank": t - len(locked_by_role["tank"]),
                    "damage": d - len(locked_by_role["damage"]),
                    "support": s - len(locked_by_role["support"])}
            choices = [list(itertools.combinations(pools[r], need[r]))
                       for r in ("tank", "damage", "support")]
            for combo in itertools.product(*choices):
                heroes = list(self.locked) + [h for part in combo for h in part]
                cand = Candidate(heroes)
                if cand.key in seen:
                    continue
                seen.add(cand.key)
                out.append(cand)
        return out

    # --- the search -------------------------------------------------------------------

    def solve(self, top=5, refine=True):
        """The best sixes, each prepared, scored and slimmed in one pass so a
        search of thousands holds only verdicts; the top are hydrated."""
        self.freeze_bounds()
        candidates = self.enumerate()
        self.considered = len(candidates)
        feasible = []
        for c in candidates:
            self.prepare(c)
            if not c.violations:
                feasible.append(self.slim(self.score(c, detail=False)))
        if not feasible:
            return []
        feasible.sort(key=self._rank_key)
        if refine:
            feasible = self.refine(feasible, max(top, 3))
        return [self.hydrate(c) for c in feasible[:top]]

    @staticmethod
    def _rank_key(c):
        return (-c.score, -c.tiebreak, c.names)

    def refine(self, ranked, seeds):
        """Local search: swap any open slot for any same-role hero."""
        known = {c.key: c for c in ranked}
        locked_ids = {h.id for h in self.locked}
        improved_any = False
        for seed in list(ranked[:seeds]):
            current = seed
            while True:
                best = current
                for index, hero in enumerate(current.heroes):
                    if hero.id in locked_ids:
                        continue
                    for other in self.world.heroes.values():
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
                current, improved_any = best, True
        out = list(known.values())
        out.sort(key=self._rank_key)
        return out if improved_any else ranked


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


def evaluate_comp(world, m, red, heroes, catalog, pool_size=6, bans=(), side=""):
    """Score one full six against the field the solver would search."""
    solver = Solver(world, m, red, [], catalog, pool_size, bans, side)
    solver.freeze_bounds()                    # the same reference scale as infer
    field = solver.enumerate()
    solver.considered = len(field)
    feasible = []
    for c in field:
        solver.prepare(c)
        if not c.violations:
            feasible.append(solver.slim(solver.score(c, detail=False)))
    target = solver.score(solver.prepare(Candidate(heroes)))
    feasible.sort(key=Solver._rank_key)
    rank = 1 + sum(1 for c in feasible if c.score > target.score + 1e-9)
    return target, [solver.hydrate(c) for c in feasible[:5]], rank, solver
