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
               swap any slot for any same-role hero on the roster, keep improvements;
               then bring each of the wiki's synergy pairs into the best sixes two slots at once
"""

import heapq
import itertools
import random

from inference.catalog import BOARD_SECTIONS
from inference.expr import scope
from ui.facts import compute
from ui.facts.compute import ROLE_COUNT, TEAM_SIZE

REFERENCE_SIZE = 1200
PARTNER_POINTS = 0.5              # a locked partner's worth when ranking a pool
SEEDS = 6                         # the local search's starts, whatever `top` asks for
RESTARTS = 24                     # in-shape random starts: the SEEDS are near-duplicates
SCALE_POOL = 6                    # the field that fixes a board's scale, whatever pool is searched
SHAPE_REACH = 4.0                 # a shape starts too when its best six is this close
PAIR_TRIES = 800                  # the most new sixes one refine scores bringing pairs in
CONFIDENCE_KEY = "\x00confidence"   # a rule's scale bounds, beside its own
NEED_BUDGET = 2.0                 # the most one guarded state can cost
REFERENCE_SEED = 20260913

SHAPE_KEYS = {"team.tanks", "team.damage", "team.supports", "team.size",
              "team.open_slots"}

# the namespaces that do not change across the candidates of one board
STATIC_SECTIONS = BOARD_SECTIONS

_EMPTY = {}


class Candidate:
    __slots__ = (
        "confidence",
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
        self.confidence = []   # its confidence metric where it names one, else None

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
        # the same, for whatever metric a rule scales itself by; None where none
        self._confidence = [tuple(g.confidence.split(".", 1)) if g.confidence else None
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
        confidence = []
        for i, spec in enumerate(self._confidence):
            if spec is None or raw[i] is None:
                confidence.append(None)
                continue
            value = ns.get(spec[0], _EMPTY).get(spec[1])
            confidence.append(float(value) if value else 0.0)
        cand.confidence = confidence
        cand.tiebreak = ns["team"]["map_win_mean"]
        return cand

    @staticmethod
    def slim(cand):
        """Keep the verdict, drop the working: the namespace, the scope, the raw
        values and the breakdown. A search holds thousands of candidates at
        once and reads only their score, tie-break and picks; the winners are
        hydrated again before they are shown."""
        cand.ns = cand.scope = cand.raw = cand.confidence = None
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
        Deterministic for a given map and side, and independent of the locked
        picks, the pool, the enemies and the bans, so every call on one board
        shares a scale - and any process draws the same list and can take a
        slice.

        It must not depend on red or the bans. The sample fixes every
        heuristic's [lo, hi], so drawing it differently rescales the whole
        objective: a hero banned out of neither team would move the score of
        an unchanged six, banning could raise the reported maximum over a
        smaller feasible set, and `the optimal comp for this board` would
        stop being a function of the composition. Bans still screen the
        candidate field, in pools(), refine() and _pairs() - it is only the
        measuring stick that has to hold still."""
        rng = random.Random("%d|%s|%s" % (              # a str seed is stable across processes
            REFERENCE_SEED, self.m.id if self.m else 0, self.side))
        by_role = {r: sorted((h for h in self.world.heroes.values()    # by id: the draw must
                              if h.role == r and h.released),          # not hang on a
                             key=lambda h: h.id)                       # query's row order
                   for r in ROLE_COUNT}
        shapes = legal_shapes(self.catalog)
        # bans can empty a role past what a shape needs; drawing one then raises
        shapes = [(t, d, s) for t, d, s in shapes
                  if t <= len(by_role["tank"]) and d <= len(by_role["damage"])
                  and s <= len(by_role["support"])]
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

    def _confidence_bounds(self, index, prepared):
        """The low and high a rule's confidence metric is read against.

        A metric of the six varies across the reference sixes, so the reference
        is its population. A metric of the board - the map, the world - is one
        number here however the six changes, and normalising it against a sample
        that cannot move it would call every board equally certain. Its
        population is the other boards: the same metric over every map.
        """
        section, key = self._confidence[index]
        if section == "map":
            over = [compute.map_metrics(m, self.side).get(key)
                    for m in self.world.maps.values()]
            over = [float(v) for v in over if v is not None]
            return (min(over), max(over)) if over else (0.0, 0.0)
        seen = [c.confidence[index] for c in prepared if c.confidence[index] is not None]
        return (min(seen), max(seen)) if seen else (0.0, 0.0)

    def reference(self, size=REFERENCE_SIZE):
        """The sample prepared, minus what the hard limits refuse: what every
        heuristic is normalised against."""
        if self._reference is None:
            self._reference = [c for c in (self.prepare(c) for c in self.sample(size))
                               if not c.violations]
        return self._reference

    def reference_bounds(self, index=0, count=1):
        """{heuristic id: (min, max)} over one slice of the sample AND of the
        field, leaving out the heuristics the slice never valued. The slices
        partition both, so merging their lows and highs gives what one process
        freezes."""
        prepared = [c for c in (self.prepare(c) for c in self.sample()[index::count])
                    if not c.violations]
        prepared += self._field_sample(index, count)
        out = {}
        for i, g in enumerate(self.heuristics):
            values = [c.raw[i] for c in prepared if c.raw[i] is not None]
            if values:
                out[g.id] = (min(values), max(values))
            if self._confidence[i] is not None:
                out[g.id + CONFIDENCE_KEY] = self._confidence_bounds(i, prepared)
        return out

    def _board_prior(self, h):
        """`prior` without the locked-partner points: the board's own ranking.

        prior() pays a hero for each locked pick it partners, which is right
        when ranking a pool to search and wrong when choosing the field that
        fixes the scale - that field has to be the same for every seat and
        every set of locks on this board."""
        base = h.map_win(self.m.id) if self.m is not None and h.map_win(self.m.id) \
            is not None else (h.win if h.win is not None else 50.0)
        answers = sum(1 for e in self.red if self.world.counters_of(e.id, h.id))
        exposed = sum(1 for e in self.red if self.world.counters_of(h.id, e.id))
        style = 1 if (self.m is not None and self.m.style_top in h.styles) else 0
        best = 1 if (self.m is not None and self.m.id in h.best_maps) else 0
        return base + 3.0 * answers - 3.0 * exposed + style + best

    def _board_field(self):
        """The field this board would search with nothing locked: each role's
        top `pool_size` by standing alone, over every legal shape.

        It must not read the locked picks, and it takes SCALE_POOL rather than
        the pool this search happens to use. The bounds it feeds are the
        board's one scale: `infer`, `evaluate`, `current` and the countered
        what-if run with different locks and different pool sizes on the same
        board, and a scale that moved with either would make a current comp and
        the optimal it is a share of two different numbers."""
        ranked = {}
        for role in ROLE_COUNT:
            # not filtered by the bans, on purpose, exactly as sample() is not:
            # this field is half the population that fixes the scale, and a ban
            # that moved it would move the score of an unchanged six. Bans keep
            # banned heroes out of the CANDIDATE field in pools(); the measuring
            # stick has to hold still
            heroes = [h for h in self.world.heroes.values()
                      if h.role == role and h.released]
            heroes.sort(key=lambda h: (-self._board_prior(h), h.name))
            ranked[role] = heroes[:SCALE_POOL]
        for t, d, s in legal_shapes(self.catalog):
            if t > len(ranked["tank"]) or d > len(ranked["damage"]) or s > len(ranked["support"]):
                continue
            for a in itertools.combinations(ranked["tank"], t):
                for b in itertools.combinations(ranked["damage"], d):
                    for c in itertools.combinations(ranked["support"], s):
                        yield list(a) + list(b) + list(c)

    def _field_sample(self, index=0, count=1):
        """The board's field, prepared but unscored.

        The sample alone is 1,200 random legal sixes, and the search picks from
        comps far better than random, so a good six sat above the sample's high
        on most metrics and every one of them normalised to the same 1.0: the
        rule stopped telling them apart, and a weight raised past that bought
        nothing. The field belongs in the population that sets the scale."""
        out = []
        for size, heroes in enumerate(self._board_field()):
            if size % count == index:
                cand = self.prepare(Candidate(heroes))
                if not cand.violations:
                    out.append(cand)
        return out

    def freeze_bounds(self):
        """Bounds per heuristic from the reference sample and the field, then
        each hero's standing in the sample."""
        reference = self.reference()
        over = reference + self._field_sample()
        for i, g in enumerate(self.heuristics):
            values = [c.raw[i] for c in over if c.raw[i] is not None]
            self.bounds[g.id] = (min(values), max(values)) if values else (0.0, 0.0)
            if self._confidence[i] is not None:
                self.bounds[g.id + CONFIDENCE_KEY] = self._confidence_bounds(i, over)
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
        self._norm = []
        for g in self.heuristics:
            lo, hi = self.bounds.get(g.id, (0.0, 0.0))
            scale = self.bounds.get(g.id + CONFIDENCE_KEY) if g.confidence else None
            self._norm.append((g, lo, hi - lo if hi > lo else None,
                               g.weight * self._needs.get(g.id, 1.0),
                               g.direction == "minimize", g.id in self._needs, scale))

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
        for raw, scale_raw, (g, lo, span, weight, minimize, need, scale) in zip(
                cand.raw, cand.confidence, self._norm, strict=True):
            if raw is None:
                if detail:
                    contributions.append({"id": g.id, "kind": "heuristic",
                                          "form": "heuristic", "applies": False, "raw": None,
                                          "norm": 0.0, "weighted": 0.0, "metric": g.metric,
                                          "when": g.when.source if g.when else None})
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
            # a rule that names a confidence metric is worth its weight only where
            # that metric is at its reference high, and nothing where it is at the
            # low: a premise that barely holds barely counts
            if scale is not None and scale_raw is not None:
                scale_lo, scale_hi = scale
                # anchor at zero where the metric never goes below it: the least
                # certain board seen is not the same as no certainty at all, and
                # taking it as the floor would pay that board nothing
                if scale_lo >= 0.0:
                    scale_lo = 0.0
                width = scale_hi - scale_lo
                sure = 1.0 if width <= 0 else (scale_raw - scale_lo) / width
                sure = 0.0 if sure < 0.0 else 1.0 if sure > 1.0 else sure
                weight = weight * sure
            weighted = weight * (norm - 1.0) if need else weight * norm
            total += weighted
            if detail:
                contributions.append({"id": g.id, "kind": "heuristic", "form": "heuristic",
                                      "applies": True, "raw": raw, "norm": norm,
                                      "weighted": weighted, "metric": g.metric,
                                      "when": g.when.source if g.when else None,
                                      "spread": span is not None, "need": need,
                                      "confidence": g.confidence,
                                      "confidence_raw": scale_raw})
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
                                      "weighted": weighted, "metric": r.expressions,
                                      "when": r.when.source if r.when else None})
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
        best = 1 if (self.m is not None and self.m.id in h.best_maps) else 0
        return base + 3.0 * answers - 3.0 * exposed + 2.0 * partners + style + best

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
        # sorted: a six's names in seat order are a construction artifact, so the
        # same hero set could key 720 ways and the order would not be a function
        # of the composition
        return (-c.score, -c.tiebreak, sorted(c.names))

    def refine(self, ranked):
        """Local search: swap any open slot for any same-role hero. A swap keeps
        the shape, so the starts are the best SEEDS of the field and the best
        six of every shape in it: an off-shape six can win only if its own
        shape was searched. Then the best SEEDS sixes try each of the wiki's synergy pairs
        brought in two slots at once, and the swaps run on from any that gained:
        partners that pay only together are never met one swap at a time."""
        known = {c.key: c for c in ranked}
        starts, shapes = list(ranked[:SEEDS]), set()
        floor = ranked[0].score - SHAPE_REACH if ranked else 0.0
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

    def _try(self, heroes, known):
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

    def _climb(self, seed, roster, known):
        """Single-slot swaps from one six until none improves it."""
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
                    if cand is not None and cand.score > best.score + 1e-9:
                        best = cand
            if best is current:
                return current
            current = best

    def _restarts(self, leader, roster, known, n=RESTARTS):
        """Climbs from random sixes of the leader's own shape. A climb preserves
        the shape, so a start off it can only report on a shape already searched;
        confining the draw is what makes a couple of dozen starts enough."""
        locked_ids = {h.id for h in self.locked}
        by_role = {r: [h for h in roster if h.role == r and h.id not in locked_ids]
                   for r in ROLE_COUNT}
        locked_by_role = {r: [h for h in self.locked if h.role == r] for r in ROLE_COUNT}
        shape = {r: sum(1 for h in leader.heroes if h.role == r) for r in ROLE_COUNT}
        rng = random.Random("restart|%s|%s" % (self.m.id if self.m else 0, self.side))
        best = leader
        for _ in range(n):
            heroes = []
            for role in ROLE_COUNT:
                need = shape[role] - len(locked_by_role[role])
                if not 0 <= need <= len(by_role[role]):
                    heroes = None
                    break
                heroes += locked_by_role[role] + rng.sample(by_role[role], need)
            if heroes is None:
                continue
            cand = self._try(heroes, known)
            if cand is None:
                continue
            cand = self._climb(cand, roster, known)
            if cand.score > best.score + 1e-9:
                best = cand
        return best

    def _two_swap(self, leader, roster, known):
        """Two open seats changed at once, to convergence. Two picks that pay
        only together are a saddle a one-slot climb cannot cross."""
        locked_ids = {h.id for h in self.locked}
        current = leader
        while True:
            best = current
            open_seats = [i for i, h in enumerate(current.heroes) if h.id not in locked_ids]
            for a_at in range(len(open_seats)):
                for b_at in range(a_at + 1, len(open_seats)):
                    i, j = open_seats[a_at], open_seats[b_at]
                    role_i, role_j = current.heroes[i].role, current.heroes[j].role
                    for x in roster:
                        if x.role != role_i or x.id in current.key:
                            continue
                        for y in roster:
                            if y.role != role_j or y.id in current.key or y.id == x.id:
                                continue
                            heroes = list(current.heroes)
                            heroes[i], heroes[j] = x, y
                            cand = self._try(heroes, known)
                            if cand is not None and cand.score > best.score + 1e-9:
                                best = cand
            if best is current:
                return current
            current = self._climb(best, roster, known)

    def _pairs(self):
        """The wiki's synergy pairs this board can field, in id order."""
        heroes = self.world.heroes
        out = []
        for a, b in sorted(tuple(sorted(pair)) for pair in self.world.synergies
                           if len(pair) == 2):
            a, b = heroes.get(a), heroes.get(b)
            if (a is not None and b is not None and a.released and b.released
                    and a.id not in self.banned and b.id not in self.banned):
                out.append((a, b))
        return out

    def _bring_pair(self, seed, pairs, known, spent):
        """Each pair with neither partner in the six, seated in two open slots of
        their own roles, until `considered` reaches `spent`. -> the best six met,
        the seed itself where none beat it."""
        locked_ids = {h.id for h in self.locked}
        open_slots = {}
        for index, hero in enumerate(seed.heroes):
            if hero.id not in locked_ids:
                open_slots.setdefault(hero.role, []).append(index)
        best = seed
        for a, b in pairs:
            if a.id in seed.key or b.id in seed.key:
                continue                      # one swap reaches these
            if self.considered >= spent:
                break
            for i in open_slots.get(a.role, ()):
                for j in open_slots.get(b.role, ()):
                    if i == j or (a.role == b.role and i > j):
                        continue              # the same six, seated the other way round
                    heroes = list(seed.heroes)
                    heroes[i], heroes[j] = a, b
                    cand = self._try(heroes, known)
                    if cand is not None and cand.score > best.score + 1e-9:
                        best = cand
        return best


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
    # rank against the field the search actually ends on. Ranking against the raw
    # sweep alone called a six first that the refinement had already beaten, so a
    # comp and a strictly better one both read rank 1.
    feasible = solver.refine(sorted(feasible, key=Solver._rank_key))
    rank = 1 + sum(1 for c in feasible if c.score > target.score + 1e-9)
    return target, [solver.hydrate(c) for c in feasible[:5]], rank, solver
