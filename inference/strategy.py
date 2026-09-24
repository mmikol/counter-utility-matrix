"""One strategy: the record a playbook file becomes, its kind and form, and
the rules every file keeps, checked against the facts layer's metric
registry.

    STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS

A strategy file, in the frontmatter dialect (inference.frontmatter):

    ---
    name: Answer every revealed enemy
    kind: heuristic           # constraint | heuristic | assumption
    category: matchup
    direction: maximize       # heuristics: maximize | minimize
    metric: team.coverage_share
    weight: 3
    when: enemy.size >= 1     # optional guard, either kind
    ---
    prose: what it means and why

A HEURISTIC names a numeric fact key (`metric`), min-max normalised
against a seeded reference sample of legal sixes for the board and
weighted; `direction` says which end is good. Guarded on the six's own
state it is a need: weight x (norm - 1). A CONSTRAINT takes one of two
forms, read off its frontmatter (`form`):

    limit   `require: <expr>` must hold. Hard by default - a comp that
            fails is discarded; `soft: true` with `penalty: <number>`
            subtracts instead.
    scored  `bonus: <expr>` and/or `penalty: <expr>`: the solver adds
            `weight x (bonus - penalty)` while `when` holds.

An ASSUMPTION is prose: what the solver takes as given and the /comp
session holds a comp to (players play optimally, say). It carries nothing
to score and is never a draft.

A constraint or heuristic with only a name, a kind and prose - no metric,
no expression - is a DRAFT: it loads, it is shown and served, the solver
ignores it, and the `/strategy` skill infers the rest (a heuristic's
metric, direction and weight; a constraint's limit or bonus/penalty and
params) from the prose and writes it through `infer_strategy` - or turns
it into an assumption when nothing measurable captures it.

`params:` (an indented block of NAME: number) are the dials an expression
reads as params.NAME - tuning is editing the file.
"""

from collections.abc import Mapping
from typing import Literal, TypedDict

from facts import compute
from inference.expr import Expr, ExprError, Section, compile_expr
from inference.frontmatter import Frontmatter, Scalar

# a strategy's kind, as its frontmatter names it, and its form, as its fields make it
type Kind = Literal["constraint", "heuristic", "assumption"]
type Form = Literal["limit", "scored", "heuristic", "assumption", "draft"]
KINDS: tuple[Kind, ...] = ("constraint", "heuristic", "assumption")
# load() sorts by this index within a kind, so draft sits last for a
# heuristic draft as well as a constraint one
FORMS: tuple[Form, ...] = ("limit", "scored", "heuristic", "assumption", "draft")

# the namespaces one board settles for every candidate six
BOARD_SECTIONS = ("enemy", "map", "world", "params")


class CatalogError(ValueError):
    """A playbook the catalog refuses: the message names the rule a file
    breaks, and `file` the file, once the catalog knows it."""
    file: str | None = None         # the strategy file at fault, when one is


def _text(value: Scalar | dict[str, Scalar]) -> str | None:
    """A field that names something: None when unset or blank, else its text."""
    return str(value) if value else None


def _weight(hid: str, value: Scalar | dict[str, Scalar]) -> float:
    """A weight: a number within 0..10, where a blank one reads 0."""
    value = value or 0.0
    if not isinstance(value, (int, float, str)):
        raise CatalogError("%s: weight must be a number" % hid)
    try:
        weight = float(value)
    except ValueError:
        raise CatalogError("%s: weight must be a number" % hid) from None
    if not 0.0 <= weight <= 10.0:
        raise CatalogError("%s: weight must be within 0..10" % hid)
    return weight


def _compiled(meta: Frontmatter, key: str) -> Expr | None:
    """The expression the frontmatter sets under key, or None."""
    return compile_expr(str(meta[key])) if key in meta else None


class StrategyRecord(TypedDict):
    """A strategy as the tools, the service and the board serve it."""
    id: str
    name: str
    kind: Kind
    form: Form
    pending: bool
    need: bool
    category: str
    direction: str | None
    metric: str | None
    weight: float
    soft: bool
    confidence: str | None
    when: str | None
    require: str | None
    bonus: str | None
    penalty: str | None
    params: dict[str, Scalar]
    body: str


class Strategy:
    """One strategy file, parsed and checked: its fields, its expressions
    compiled, and the form they make it."""

    def __init__(self, hid: str, meta: Frontmatter, body: str, raw: str, path: str) -> None:
        self.id, self.body, self.raw, self.path = hid, body, raw, path
        self.name = str(meta.get("name") or hid.replace("-", " "))
        kind = meta.get("kind")
        if not isinstance(kind, str) or kind not in KINDS:
            raise CatalogError("%s: kind must be one of %s" % (hid, "/".join(KINDS)))
        self.kind: Kind = kind
        self.category = str(meta.get("category") or "general")
        self.direction = _text(meta.get("direction"))
        self.metric = _text(meta.get("metric"))
        self.weight = _weight(hid, meta.get("weight", 1.0))
        self.soft = bool(meta.get("soft", False))
        # A metric that says how strongly this rule's own premise holds. It scales
        # the term through the same reference bounds the metric uses, so a rule
        # whose premise is barely true contributes barely anything. Declared, not
        # coded: nothing here knows which metric any rule names.
        confidence = meta.get("confidence")
        self.confidence = None if confidence is None else str(confidence)
        params = meta.get("params") or {}
        if not isinstance(params, dict):
            raise CatalogError("%s: params is a block of NAME: number" % hid)
        self.params: dict[str, Scalar] = dict(params)
        self.params_section = Section({k: 0 if v is None else v
                                       for k, v in self.params.items()})
        try:
            self.when = _compiled(meta, "when")
            self.require = _compiled(meta, "require")
            self.bonus = _compiled(meta, "bonus")
            self.penalty = _compiled(meta, "penalty")
        except ExprError as error:
            raise CatalogError("%s: %s" % (hid, error)) from error
        self._check()

    def _check(self) -> None:
        """Every rule a file must keep, in order, so its first error is the one
        reported."""
        known = compute.registry()
        self._check_heuristic(known)
        self._check_confidence(known)
        self._check_kind()
        self._check_limit()
        self._check_names(known)

    def _check_heuristic(self, known: Mapping[str, str]) -> None:
        if self.kind != "heuristic" or not (self.metric or self.direction):
            return
        if self.direction not in ("maximize", "minimize"):
            raise CatalogError("%s: a heuristic needs direction maximize|minimize" % self.id)
        if not self.metric or self.metric not in known:
            raise CatalogError("%s: metric %r is not a registered fact key"
                               % (self.id, self.metric))
        if self.metric in compute.TEXT_METRICS:
            raise CatalogError("%s: metric %r is text, not a number" % (self.id, self.metric))

    def _check_confidence(self, known: Mapping[str, str]) -> None:
        if self.confidence is None:
            return
        if self.confidence not in known:
            raise CatalogError("%s: confidence %r is not a metric" % (self.id, self.confidence))
        if self.confidence in compute.TEXT_METRICS:
            raise CatalogError("%s: confidence %r is text, not a number"
                               % (self.id, self.confidence))
        if self.form != "heuristic":
            raise CatalogError("%s: only a heuristic scales by a confidence" % self.id)

    def _check_kind(self) -> None:
        """What each kind may not carry."""
        if self.kind == "assumption" and (self.metric or self.expressions):
            raise CatalogError("%s: an assumption carries nothing to score" % self.id)
        if self.kind == "heuristic" and (self.require is not None or self.bonus is not None):
            raise CatalogError("%s: a heuristic weighs a metric;"
                               " require/bonus belong to a constraint"
                               % self.id)
        if self.kind == "constraint" and self.metric:
            raise CatalogError("%s: a constraint has no metric; that is a heuristic" % self.id)

    def _check_limit(self) -> None:
        """A limit or scored, never both; soft only on a limit, with a penalty."""
        if self.require is not None and self.bonus is not None:
            raise CatalogError("%s: a constraint is a limit (require) or scored (bonus/penalty),"
                               " not both" % self.id)
        if self.require is not None and self.soft and self.penalty is None:
            raise CatalogError("%s: a soft limit needs penalty:" % self.id)
        if self.require is None and self.soft:
            raise CatalogError("%s: soft: needs require:" % self.id)

    def _check_names(self, known: Mapping[str, str]) -> None:
        """Every name an expression reads is a registered key or a declared param."""
        for expr in (self.when, self.require, self.bonus, self.penalty):
            if expr is None:
                continue
            for name in expr.names:
                if name.startswith("params."):
                    if name[7:] not in self.params:
                        raise CatalogError("%s: %s is not declared under params:"
                                           % (self.id, name))
                elif name not in known:
                    raise CatalogError("%s: %r is not a registered fact key"
                                       % (self.id, name))

    @property
    def form(self) -> Form:
        """heuristic, a constraint's form (limit, scored), assumption, or draft
        (name, kind and prose only - awaiting /strategy)."""
        if self.kind == "assumption":
            return "assumption"
        if self.kind == "heuristic" and self.metric:
            return "heuristic"
        if self.require is not None:
            return "limit"
        if self.bonus is not None or self.penalty is not None:
            return "scored"
        return "draft"

    @property
    def solver_reads(self) -> bool:
        """Whether the solver reads this strategy at all (assumptions and drafts it does not)."""
        return self.form in ("heuristic", "limit", "scored")

    @property
    def pending(self) -> bool:
        """A draft: the /strategy skill has not inferred its frontmatter yet."""
        return self.form == "draft"

    @property
    def expressions(self) -> str:
        """Every expression the file sets, labelled: "when: ...; require: ..."."""
        parts = []
        for label, expr in (("when", self.when), ("require", self.require),
                            ("bonus", self.bonus), ("penalty", self.penalty)):
            if expr is not None:
                parts.append("%s: %s" % (label, expr.source))
        return "; ".join(parts)

    @property
    def need(self) -> bool:
        """A heuristic guarded on the six's own state: the solver charges what it
        misses (weight x (norm - 1)) instead of paying what it has. Guards on red
        or the map - red's matchup keys included - leave it a reward."""
        return (self.form == "heuristic" and self.when is not None
                and any(n.split(".", 1)[0] not in BOARD_SECTIONS
                        and n not in compute.RED_MATCHUP
                        for n in self.when.names))

    def to_dict(self) -> StrategyRecord:
        """The record the tools, the service and the board serve."""
        return {"id": self.id, "name": self.name, "kind": self.kind, "form": self.form,
                "pending": self.pending, "need": self.need,
                "category": self.category, "direction": self.direction,
                "metric": self.metric, "weight": self.weight, "soft": self.soft,
                "confidence": self.confidence,
                "when": self.when.source if self.when else None,
                "require": self.require.source if self.require else None,
                "bonus": self.bonus.source if self.bonus else None,
                "penalty": self.penalty.source if self.penalty else None,
                "params": self.params, "body": self.body}
