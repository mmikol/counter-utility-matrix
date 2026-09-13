"""The solver: the optimal five under the catalog, players playing optimally.

    enumerate  every shape the hard constraints allow, filled around the
               locked picks from a per-role pool ranked by a cheap prior
    score      constraints prune, goals normalise and weigh, scored
               strategies add
    refine     local search from the best few: swap any slot for any
               same-role hero on the roster, keep improvements
"""

import itertools

from user.facts import compute
from inference.expr import lookup

SHAPE_KEYS = {"team.tanks", "team.damage", "team.supports", "team.size",
              "team.open_slots"}
ROLE_KEY = {"tank": "tanks", "damage": "damage", "support": "supports"}


class Candidate:
    __slots__ = ("heroes", "key", "ns", "score", "contributions", "violations",
                 "raw")

    def __init__(self, heroes):
        self.heroes = tuple(heroes)
        self.key = frozenset(h.id for h in heroes)
        self.ns = None
        self.score = 0.0
        self.contributions = []
        self.violations = []
        self.raw = {}

    @property
    def names(self):
        return [h.name for h in self.heroes]


class Solver:
    def __init__(self, world, m, red, locked, catalog, pool_size=8):
        self.world, self.m, self.red = world, m, list(red)
        self.locked = list(locked)
        self.catalog = catalog
        self.pool_size = pool_size
        self.constraints = [h for h in catalog if h.kind == "constraint"]
        self.goals = [h for h in catalog if h.kind == "goal"]
        self.strategies = [h for h in catalog if h.kind == "strategy" and h.scored]
        # the red side's metrics do not change across candidates
        self.red_t = compute.team_metrics(world, self.red, m, ())
        self.static = {"enemy": self.red_t, "map": compute.map_metrics(m),
                       "world": compute.world_metrics(world)}
        self.bounds = {}                     # goal id -> (min, max)
        self.considered = 0

    # --- namespace and scoring -----------------------------------------------

    def namespace(self, heroes):
        team = compute.team_metrics(self.world, heroes, self.m, self.red)
        ns = dict(self.static)
        ns["team"] = team
        ns["matchup"] = compute.matchup_metrics(team, self.red_t)
        return ns

    @staticmethod
    def _holds(h, ns):
        if h.when is None:
            return True
        return bool(h.when.eval(dict(ns, params=h.params)))

    def prepare(self, cand):
        """Namespace, hard-constraint check, raw goal values."""
        cand.ns = self.namespace(cand.heroes)
        cand.violations = []
        for h in self.constraints:
            ns = dict(cand.ns, params=h.params)
            if self._holds(h, ns) and not bool(h.require.eval(ns)) and not h.soft:
                cand.violations.append(h.id)
        cand.raw = {g.id: (float(lookup(cand.ns, g.metric) or 0)
                           if self._holds(g, cand.ns) else None)
                    for g in self.goals}
        return cand

    def freeze_bounds(self, candidates):
        for g in self.goals:
            values = [c.raw[g.id] for c in candidates if c.raw.get(g.id) is not None]
            self.bounds[g.id] = (min(values), max(values)) if values else (0.0, 0.0)

    def score(self, cand):
        """Score with the frozen bounds; fills contributions."""
        total, contributions = 0.0, []
        for h in self.constraints:
            ns = dict(cand.ns, params=h.params)
            applies = self._holds(h, ns)
            ok = bool(h.require.eval(ns)) if applies else True
            penalty = float(h.penalty.eval(ns)) if (h.soft and applies and not ok) else 0.0
            total -= penalty
            contributions.append({"id": h.id, "kind": h.kind, "applies": applies,
                                  "ok": ok, "weighted": -penalty,
                                  "metric": h.require.source})
        for g in self.goals:
            raw = cand.raw.get(g.id)
            if raw is None:
                contributions.append({"id": g.id, "kind": "goal", "applies": False,
                                      "raw": None, "norm": 0.0, "weighted": 0.0,
                                      "metric": g.metric})
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
            contributions.append({"id": g.id, "kind": "goal", "applies": True,
                                  "raw": raw, "norm": norm, "weighted": weighted,
                                  "metric": g.metric, "spread": hi > lo})
        for r in self.strategies:
            ns = dict(cand.ns, params=r.params)
            applies = self._holds(r, ns)
            bonus = float(r.bonus.eval(ns)) if (applies and r.bonus is not None) else 0.0
            penalty = float(r.penalty.eval(ns)) if (applies and r.penalty is not None) else 0.0
            weighted = r.weight * (bonus - penalty)
            total += weighted
            contributions.append({"id": r.id, "kind": "strategy", "applies": applies,
                                  "bonus": bonus, "penalty": penalty,
                                  "weighted": weighted, "metric": r.expressions})
        cand.score = total
        cand.contributions = contributions
        return cand

    # --- enumeration ---------------------------------------------------------------

    def shapes(self):
        """(tanks, damage, supports) triples the shape-only hard constraints
        allow, that can still seat the locked picks."""
        locked_counts = {r: sum(1 for h in self.locked if h.role == r)
                         for r in ROLE_KEY}
        shape_rules = [h for h in self.constraints if not h.soft and h.require
                       and set(h.require.names) <= SHAPE_KEYS
                       and (h.when is None or set(h.when.names) <= SHAPE_KEYS)]
        out = []
        for t in range(6):
            for d in range(6 - t):
                s = 5 - t - d
                if (t < locked_counts["tank"] or d < locked_counts["damage"]
                        or s < locked_counts["support"]):
                    continue
                stub = {"team": {"tanks": t, "damage": d, "supports": s,
                                 "size": 5, "open_slots": 0}}
                if all(not self._holds(h, dict(stub, params=h.params))
                       or bool(h.require.eval(dict(stub, params=h.params)))
                       for h in shape_rules):
                    out.append((t, d, s))
        return out

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
        locked_ids = {h.id for h in self.locked}
        pools = {}
        for role in ROLE_KEY:
            heroes = [h for h in self.world.heroes.values()
                      if h.role == role and h.id not in locked_ids]
            heroes.sort(key=self.prior, reverse=True)
            pools[role] = heroes[:self.pool_size]
        return pools

    def enumerate(self):
        pools = self.pools()
        locked_by_role = {r: [h for h in self.locked if h.role == r] for r in ROLE_KEY}
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
        candidates = [self.prepare(c) for c in self.enumerate()]
        self.considered = len(candidates)
        feasible = [c for c in candidates if not c.violations]
        if not feasible:
            return []
        self.freeze_bounds(feasible)
        for c in feasible:
            self.score(c)
        feasible.sort(key=self._rank_key)
        if refine:
            feasible = self.refine(feasible, max(top, 3))
        return feasible[:top]

    @staticmethod
    def _rank_key(c):
        return (-c.score, -c.ns["team"]["map_win_mean"], c.names)

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
                        if other.role != hero.role or other.id in current.key:
                            continue
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
                            self.score(cand)
                            known[cand.key] = cand
                        if cand.score > best.score + 1e-9:
                            best = cand
                if best is current:
                    break
                current, improved_any = best, True
        out = list(known.values())
        out.sort(key=self._rank_key)
        return out if improved_any else ranked


def evaluate_comp(world, m, red, heroes, catalog, pool_size=8):
    """Score one full five against the field the solver would search."""
    solver = Solver(world, m, red, [], catalog, pool_size)
    field = [solver.prepare(c) for c in solver.enumerate()]
    solver.considered = len(field)
    target = solver.prepare(Candidate(heroes))
    feasible = [c for c in field if not c.violations]
    solver.freeze_bounds(feasible + [target])
    for c in feasible:
        solver.score(c)
    solver.score(target)
    feasible.sort(key=Solver._rank_key)
    rank = 1 + sum(1 for c in feasible if c.score > target.score + 1e-9)
    return target, feasible[:5], rank, solver
