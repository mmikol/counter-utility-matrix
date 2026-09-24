"""The objective: what one six scores on one board under the playbook.

    score           STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS: limits prune
                    (soft ones charge), heuristics normalise and weigh, scored
                    constraints add; assumptions are the agent's. A `when` reading
                    only the enemy, the map and the world is settled once per board,
                    not once per candidate. A heuristic guarded on the six's own
                    state is a need: see Objective.score().
    legal_shapes    the (tanks, damage, supports) triples the queue and the hard
                    shape limits allow, around whatever picks are locked
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal, NamedTuple, NotRequired, TypedDict

from inference.expr import Expr, Scope, Value, scope
from inference.strategy import BOARD_SECTIONS, Strategy
from ui.facts import compute
from ui.facts.draft import MAX_TANKS, TEAM_SIZE
from ui.facts.model import ROLES, Hero, Map, World
from ui.facts.team import NUMBER_TYPES, MetricBag, MetricValue, number, team_metrics

CONFIDENCE_KEY = "\x00confidence"   # a rule's scale bounds, beside its own
NEED_BUDGET = 2.0                 # the most one guarded state can cost

SHAPE_KEYS = {"team.tanks", "team.damage", "team.supports", "team.size", "team.open_slots"}

# the namespaces that do not change across the candidates of one board
STATIC_SECTIONS = BOARD_SECTIONS

# The records the objective passes around. A namespace is the metric bags by
# section.
Bounds = dict[str, tuple[float, float]]         # id, or id + CONFIDENCE_KEY -> low, high
Namespace = dict[str, MetricBag]


class Shape(NamedTuple):
    """A six's count per role."""
    tanks: int
    damage: int
    supports: int


class MetricKey(NamedTuple):
    """A dotted metric key split: the namespace, and the key within it."""
    section: str
    key: str


class Norm(NamedTuple):
    """One heuristic's frozen scale for the scoring loop: the strategy, its
    reference low and spread (None where the sample never moved), its weight,
    whether it minimises, whether it is a need, and its confidence metric's
    bounds where it names one."""
    strategy: Strategy
    low: float
    span: float | None
    weight: float
    minimize: bool
    need: bool
    scale: tuple[float, float] | None


_EMPTY: MetricBag = {}


def _split_key(key: str | None) -> MetricKey:
    """A dotted metric key -> (namespace, key)."""
    section, _, name = (key or "").partition(".")
    return MetricKey(section, name)


def _not_a_number(value: MetricValue | None) -> float:
    """A metric read as a number that holds none: 0 when it is unset or empty,
    as the score has always read one. A name or a list is refused - the
    catalog keeps text metrics out of every place the solver reads a number,
    and a number itself never reaches here, so the loop pays no call for it."""
    if value:
        raise TypeError("a metric read as a number holds %r" % (value,))
    return 0.0


def _amount(value: Value) -> float:
    """A bonus or penalty expression's value, as the score adds it."""
    if isinstance(value, (int, float, str)):          # a bool is an int
        return float(value)
    raise TypeError("a bonus or penalty reads a number, got %r" % (value,))


def _slot_gate(held: list[bool | None], slot: int, h: Strategy, sc: Scope) -> bool:
    """A gate the candidate decides, read once per slot: the answer a strategy
    guarded the same way already left in `held`, else h's `when` evaluated on
    this scope with h's params and kept there."""
    gate = held[slot]
    if gate is None:
        sc["params"] = h.params_section
        when = h.when                  # set: a gate the candidate decides has one
        gate = held[slot] = when is None or bool(when.evaluate(sc))
    return gate


def _norm(raw: float, lo: float, span: float | None, minimize: bool, need: bool) -> float:
    """A heuristic's raw value on its reference scale, clamped to [0, 1] and
    flipped where it minimises; with no spread, the middle."""
    if span is None:
        return 1.0 if need else 0.5    # a need nothing here can miss costs nothing
    norm = (raw - lo) / span
    if norm > 1.0:                     # the candidate sits outside the sample
        norm = 1.0
    elif norm < 0.0:
        norm = 0.0
    return 1.0 - norm if minimize else norm


def _certainty(scale: tuple[float, float], scale_raw: float) -> float:
    """How far a rule's confidence metric sits between its reference low and
    high, in [0, 1]. A rule that names one is worth its weight only where that
    metric is at its high, and nothing where it is at the low: a premise that
    barely holds barely counts."""
    scale_lo, scale_hi = scale
    # anchor at zero where the metric never goes below it: the least certain
    # board seen is not the same as no certainty at all, and taking it as the
    # floor would pay that board nothing
    if scale_lo >= 0.0:
        scale_lo = 0.0
    width = scale_hi - scale_lo
    sure = 1.0 if width <= 0 else (scale_raw - scale_lo) / width
    return 0.0 if sure < 0.0 else 1.0 if sure > 1.0 else sure


class Contribution(TypedDict):
    """One strategy's term in a six's score: the `contributions` array of the
    public payload. Every term carries the required keys; the rest belong to
    the form that has them, and no term is padded with the others."""
    id: str
    kind: Literal["constraint", "heuristic"]
    form: Literal["limit", "heuristic", "scored"]
    applies: bool
    weighted: float
    metric: str | None                 # a heuristic's metric, a constraint's expressions
    ok: NotRequired[bool]              # a limit: whether its require holds
    raw: NotRequired[float | None]     # a heuristic
    norm: NotRequired[float]
    when: NotRequired[str | None]      # a heuristic, and a scored constraint
    spread: NotRequired[bool]          # an applying heuristic
    need: NotRequired[bool]
    confidence: NotRequired[str | None]
    confidence_raw: NotRequired[float | None]
    bonus: NotRequired[float]          # a scored constraint
    penalty: NotRequired[float]
    fact: NotRequired[str]             # the board fact that states the metric, if any
    text: NotRequired[str]


class Candidate:
    """One six on its way through the search: its heroes, and once prepared
    and scored its namespace, limit breaches, raw values, score, tie-break and
    breakdown. A slim one keeps only the verdict."""

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

    def __init__(self, heroes: Iterable[Hero]) -> None:
        self.heroes = tuple(heroes)
        self.key = frozenset(h.id for h in self.heroes)
        self.ns: Namespace | None = None
        self.scope: Scope | None = None
        self.score = 0.0
        self.tiebreak = 0.0
        self.contributions: list[Contribution] = []
        self.violations: list[str] = []
        # one metric value per heuristic, in catalog order, and its confidence
        # metric where it names one, else None; empty on a slim candidate
        self.raw: Sequence[float | None] = []
        self.confidence: Sequence[float | None] = []

    @property
    def names(self) -> list[str]:
        return [h.name for h in self.heroes]


class Objective:
    """The part of a board's search that scores a six: the playbook's
    objective against this enemy, on this map, side and bans, with every
    `when` the board settles read once and each heuristic's bounds, once
    frozen, turned into the norms the scoring loop reads."""

    def __init__(self, world: World, m: Map | None, *, red: Sequence[Hero],
                 banned: Sequence[Hero] = (), side: str = "",
                 catalog: list[Strategy]) -> None:
        self.world, self.m, self.red = world, m, list(red)
        self.banned = {h.id for h in banned}
        self.side = side
        self.catalog = catalog
        self.limits = [h for h in catalog if h.form == "limit"]
        self.heuristics = [h for h in catalog if h.form == "heuristic"]
        self.scored_constraints = [h for h in catalog if h.form == "scored"]
        # the red side's metrics do not change across candidates
        self.red_t = team_metrics(world, self.red, m, ())
        self.static: Namespace = {
            "enemy": self.red_t,
            "map": compute.map_metrics(m, side, ban_count=len(self.banned)),
            "world": compute.world_metrics(world)}
        self.bounds: Bounds = {}             # heuristic id -> (min, max)
        self._norms: list[Norm] = []
        # each strategy paired with its gate - True or False where `when` is
        # settled for the whole board, None where the candidate decides it -
        # and with the slot it shares with every strategy guarded the same way;
        # a limit with its require:, which every limit has
        gates, slots, self.gate_slots = self._gates()
        self._limits: list[tuple[Strategy, Expr, bool | None, int]] = [
            (h, h.require, gates[h.id], slots.get(h.id, 0)) for h in self.limits
            if h.require is not None]
        self._scored = [(r, gates[r.id], slots.get(r.id, 0))
                        for r in self.scored_constraints]
        self._heuristics = [(g, gates[g.id], slots.get(g.id, 0), *_split_key(g.metric))
                            for g in self.heuristics]
        # the same, for whatever metric a rule scales itself by; None where none
        self.confidence_metrics = [_split_key(g.confidence) if g.confidence else None
                                   for g in self.heuristics]
        # a heuristic guarded on the six's own state is a need: see score().
        # Needs that share a guard share NEED_BUDGET: the state costs at most
        # that much however many rules the playbook writes about it
        guards = {g.id: g.when.source for g in self.heuristics
                  if gates[g.id] is None and g.when is not None}
        written: dict[str, float] = {}
        for g in self.heuristics:
            if g.id in guards:
                written[guards[g.id]] = written.get(guards[g.id], 0.0) + g.weight
        self._needs = {hid: min(1.0, NEED_BUDGET / written[source])
                       if written[source] else 1.0 for hid, source in guards.items()}
        self._freeze_norms()

    def _gates(self) -> tuple[dict[str, bool | None], dict[str, int], int]:
        """Every strategy's `when`, read once per board: True where there is
        none, True or False where it touches only the static sections, None
        where the candidate decides it. -> (gate per id, slot per undecided
        id, how many slots). Strategies whose `when` and params are the same
        answer together, so they share a slot: a guard a dozen strategies
        write is evaluated once per candidate."""
        sc = scope(dict(self.static, matchup=compute.red_matchup(self.red_t)))
        gates: dict[str, bool | None] = {}
        slots: dict[str, int] = {}
        groups: dict[object, int] = {}
        for h in self.catalog:
            if h.when is None:
                gates[h.id] = True
            elif all(n.split(".", 1)[0] in STATIC_SECTIONS or n in compute.RED_MATCHUP
                     for n in h.when.names):
                sc["params"] = h.params_section
                gates[h.id] = bool(h.when.evaluate(sc))
            else:
                gates[h.id] = None
                key: object
                try:
                    key = (h.when.source, tuple(sorted(h.params.items())))
                    hash(key)
                except TypeError:          # a param the dialect read as a list
                    key = h.id
                slots[h.id] = groups.setdefault(key, len(groups))
        return gates, slots, len(groups)

    # --- namespace and preparation -------------------------------------------

    def namespace(self, heroes: Sequence[Hero]) -> Namespace:
        team = team_metrics(self.world, heroes, self.m, self.red, lean=True)
        ns = dict(self.static)
        ns["team"] = team
        ns["matchup"] = compute.matchup_metrics(team, self.red_t)
        return ns

    def prepare(self, cand: Candidate) -> Candidate:
        """Namespace, hard-limit check, raw heuristic values."""
        ns = cand.ns = self.namespace(cand.heroes)
        sc = cand.scope = scope(ns)
        held: list[bool | None] = [None] * self.gate_slots
        violations = []
        for h, require, gate, slot in self._limits:
            if gate is None:
                gate = _slot_gate(held, slot, h, sc)
            if gate:
                sc["params"] = h.params_section
                if not bool(require.evaluate(sc)) and not h.soft:
                    violations.append(h.id)
        cand.violations = violations
        raw: list[float | None] = []
        keep = raw.append
        for g, gate, slot, section, key in self._heuristics:
            if gate is None:
                gate = _slot_gate(held, slot, g, sc)
            if gate:
                value = ns.get(section, _EMPTY).get(key)
                keep(float(value) if isinstance(value, NUMBER_TYPES) else _not_a_number(value))
            else:
                keep(None)
        cand.raw = raw
        cand.confidence = self._confidence_values(ns, raw)
        cand.tiebreak = number(ns["team"]["map_win_mean"])
        return cand

    def _confidence_values(self, ns: Namespace,
                           raw: Sequence[float | None]) -> list[float | None]:
        """Each heuristic's confidence metric on this six, where it names one
        and applies; None elsewhere."""
        confidence: list[float | None] = []
        for i, spec in enumerate(self.confidence_metrics):
            if spec is None or raw[i] is None:
                confidence.append(None)
                continue
            value = ns.get(spec.section, _EMPTY).get(spec.key)
            confidence.append(float(value) if isinstance(value, NUMBER_TYPES)
                              else _not_a_number(value))
        return confidence

    @staticmethod
    def slim(cand: Candidate) -> Candidate:
        """Keep the verdict, drop the working: the namespace, the scope, the raw
        values and the breakdown. A search holds thousands of candidates at
        once and reads only their score, tie-break and picks; the winners are
        hydrated again before they are shown."""
        cand.ns = cand.scope = None
        cand.raw = cand.confidence = ()
        cand.contributions = []
        return cand

    def hydrate(self, cand: Candidate) -> Candidate:
        """A slim candidate prepared and scored again, with its breakdown."""
        if cand.ns is None:
            self.prepare(cand)
        return self.score(cand)

    # --- the frozen scale ------------------------------------------------------

    def adopt_bounds(self, bounds: Mapping[str, tuple[float, float]]) -> None:
        """Each heuristic's low and high on this board, frozen here or
        elsewhere: inference.scale draws them, and a board split across
        processes merges its slices' lows and highs before any scores."""
        self.bounds = dict(bounds)
        self._freeze_norms()

    def _freeze_norms(self) -> None:
        """One Norm per heuristic for the scoring loop. A spread of None -
        the sample never moved - normalises everything to 0.5."""
        self._norms = []
        for g in self.heuristics:
            lo, hi = self.bounds.get(g.id, (0.0, 0.0))
            self._norms.append(Norm(
                strategy=g, low=lo, span=hi - lo if hi > lo else None,
                weight=g.weight * self._needs.get(g.id, 1.0),
                minimize=g.direction == "minimize", need=g.id in self._needs,
                scale=self.bounds.get(g.id + CONFIDENCE_KEY) if g.confidence else None))

    # --- the score -------------------------------------------------------------

    def score(self, cand: Candidate, detail: bool = True) -> Candidate:
        """Score with the frozen bounds; with detail, fill the breakdown too.

        A heuristic with no guard, or a guard on the board (enemy, map), adds
        weight x norm. A heuristic guarded on the six's own state (team.*,
        matchup.*) is a need - "a solo healer needs an escape" - and adds
        weight x (norm - 1): met in full it costs nothing, unmet it costs the
        weight, and entering the guarded state never pays. Needs written on
        one guard are scaled to sum to NEED_BUDGET at most.

        With `detail`, every term is a Contribution: its optional keys belong
        to the form that has them, so a reader asks for those with .get()."""
        sc = cand.scope
        if sc is None:
            raise RuntimeError("score() takes a prepared candidate: hydrate() a slim one")
        held: list[bool | None] = [None] * self.gate_slots
        contributions: list[Contribution] = []
        out = contributions if detail else None
        total = self._score_limits(sc, held, 0.0, out)
        total = self._score_heuristics(cand, total, out)
        total = self._score_scored(sc, held, total, out)
        cand.score = total
        cand.contributions = contributions
        return cand

    # Each form's terms take the running total and return it: subtotals summed
    # at the end would reassociate the additions and move a score in its last bit.

    def _score_limits(self, sc: Scope, held: list[bool | None], total: float,
                      out: list[Contribution] | None) -> float:
        """The limits' terms: a hard limit costs nothing here (prepare() has
        pruned what breaks it), a soft one charges its penalty where it fails."""
        for h, require, applies, slot in self._limits:
            if applies is None:
                applies = _slot_gate(held, slot, h, sc)
            ok, penalty = True, 0.0
            if applies:
                sc["params"] = h.params_section
                ok = bool(require.evaluate(sc))
                if h.soft and not ok and h.penalty is not None:     # a soft limit has one
                    penalty = _amount(h.penalty.evaluate(sc))
            total -= penalty
            if out is not None:
                out.append({"id": h.id, "kind": "constraint", "form": "limit",
                            "applies": applies, "ok": ok, "weighted": -penalty,
                            "metric": require.source})
        return total

    def _score_heuristics(self, cand: Candidate, total: float,
                          out: list[Contribution] | None) -> float:
        """The heuristics' terms: weight x norm, a need weight x (norm - 1),
        each scaled by its confidence metric where it names one."""
        for raw, scale_raw, (g, lo, span, weight, minimize, need, scale) in zip(
                cand.raw, cand.confidence, self._norms, strict=True):
            if raw is None:
                if out is not None:
                    out.append({
                        "id": g.id, "kind": "heuristic", "form": "heuristic",
                        "applies": False, "raw": None, "norm": 0.0, "weighted": 0.0,
                        "metric": g.metric, "when": g.when.source if g.when else None})
                continue
            norm = _norm(raw, lo, span, minimize, need)
            if scale is not None and scale_raw is not None:
                weight = weight * _certainty(scale, scale_raw)
            weighted = weight * (norm - 1.0) if need else weight * norm
            total += weighted
            if out is not None:
                out.append({"id": g.id, "kind": "heuristic", "form": "heuristic",
                            "applies": True, "raw": raw, "norm": norm,
                            "weighted": weighted, "metric": g.metric,
                            "when": g.when.source if g.when else None,
                            "spread": span is not None, "need": need,
                            "confidence": g.confidence, "confidence_raw": scale_raw})
        return total

    def _score_scored(self, sc: Scope, held: list[bool | None], total: float,
                      out: list[Contribution] | None) -> float:
        """The scored constraints' terms: weight x (bonus - penalty) while
        `when` holds."""
        for r, applies, slot in self._scored:
            if applies is None:
                applies = _slot_gate(held, slot, r, sc)
            bonus = penalty = 0.0
            if applies:
                sc["params"] = r.params_section
                if r.bonus is not None:
                    bonus = _amount(r.bonus.evaluate(sc))
                if r.penalty is not None:
                    penalty = _amount(r.penalty.evaluate(sc))
            weighted = r.weight * (bonus - penalty)
            total += weighted
            if out is not None:
                out.append({"id": r.id, "kind": "constraint", "form": "scored",
                            "applies": applies, "bonus": bonus, "penalty": penalty,
                            "weighted": weighted, "metric": r.expressions,
                            "when": r.when.source if r.when else None})
        return total


# --- the legal shapes ------------------------------------------------------------

def legal_shapes(catalog: Iterable[Strategy],
                 locked_counts: Mapping[str, int] | None = None) -> list[Shape]:
    """(tanks, damage, supports) triples the queue allows - at most MAX_TANKS
    tanks, whatever the playbook holds - and the catalog's shape-only hard
    limits allow (a playbook's own rule of form, 2-2-2 say), optionally only
    those that can still seat the picks counted per role. The board carries
    the full list so the roster can refuse a pick no legal six could seat."""
    locked_counts = locked_counts or dict.fromkeys(ROLES, 0)
    limits = _shape_limits(catalog)
    out: list[Shape] = []
    for t in range(MAX_TANKS + 1):
        for d in range(TEAM_SIZE + 1 - t):
            s = TEAM_SIZE - t - d
            if (t < locked_counts["tank"] or d < locked_counts["damage"]
                    or s < locked_counts["support"]):
                continue
            if _shape_allowed(t, d, s, limits):
                out.append(Shape(t, d, s))
    return out


def _shape_limits(catalog: Iterable[Strategy]) -> list[tuple[Strategy, Expr]]:
    """The catalog's hard limits that read only a six's shape, each with its
    require."""
    return [(h, h.require) for h in catalog
            if h.form == "limit" and not h.soft and h.require
            and set(h.require.names) <= SHAPE_KEYS
            and (h.when is None or set(h.when.names) <= SHAPE_KEYS)]


def _shape_allowed(t: int, d: int, s: int, limits: Sequence[tuple[Strategy, Expr]]) -> bool:
    """Whether a (tanks, damage, supports) triple meets every shape limit whose
    `when` holds on it."""
    stub = scope({"team": {"tanks": t, "damage": d, "supports": s,
                           "size": TEAM_SIZE, "open_slots": 0}})
    for h, require in limits:
        stub["params"] = h.params_section
        if (h.when is None or bool(h.when.evaluate(stub))) and not bool(require.evaluate(stub)):
            return False
    return True
