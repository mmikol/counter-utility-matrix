"""The strategies catalog: markdown files with frontmatter, read from
inference/strategies/, validated against the facts layer's metric
registry, and mirrored into the `strategies` table.

    STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS

A strategy file:

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

import copy
import hashlib
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal, NotRequired, TypedDict

import psycopg

from db import ROOT, Refusal, embed
from db.data.authored import AUTHORED
from db.psql import now, register_source
from inference.expr import Expr, ExprError, Section, compile_expr
from ui.facts import compute

SHIPPED_DIR = os.path.join(ROOT, "inference", "strategies")
# the id is the filename, so no id may name a path (docs/security.md)
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")


def strategies_dir() -> str:
    """The playbook in force: the shipped one, unless COUNTRIX_STRATEGIES
    names another folder - a path relative to the repo root or absolute. Read
    where it is needed rather than snapshotted at import, so the setting means
    what it says and no module can freeze it before another reads it."""
    chosen = os.environ.get("COUNTRIX_STRATEGIES", "").strip()
    return os.path.abspath(os.path.join(ROOT, chosen)) if chosen else SHIPPED_DIR


DOCS_PATH = os.path.join(ROOT, "docs", "inference.md")
# a strategy's kind, as its frontmatter names it, and its form, as its fields make it
Kind = Literal["constraint", "heuristic", "assumption"]
Form = Literal["limit", "scored", "heuristic", "assumption", "draft"]
KINDS: tuple[Kind, ...] = ("constraint", "heuristic", "assumption")
# load() sorts by this index within a kind, so draft sits last for a
# heuristic draft as well as a constraint one
FORMS: tuple[Form, ...] = ("limit", "scored", "heuristic", "assumption", "draft")
NOT_STRATEGIES = ("README.md", "tuning-log.md")     # markdown that lives beside the files
KIND_ORDER = {k: i for i, k in enumerate(KINDS)}


# the namespaces one board settles for every candidate six
BOARD_SECTIONS = ("enemy", "map", "world", "params")


class CatalogError(ValueError):
    file: str | None = None         # the strategy file at fault, when one is


# --- the frontmatter dialect --------------------------------------------------

# one value: a string, a number, a boolean, a [list] of values, or null
Scalar = str | int | float | bool | list["Scalar"] | None
# a file's frontmatter: flat keys, and one level of indented mapping (params:)
Frontmatter = dict[str, Scalar | dict[str, Scalar]]

_WORDS: dict[str, bool | None] = {"true": True, "yes": True, "false": False, "no": False,
                                  "null": None, "none": None, "~": None}
_INTEGER = re.compile(r"[-+]?\d+(?:_\d+)*\Z")      # what int() reads


def _number(text: str) -> int | float | str:
    """An int where the text is one, else a float, else the text itself: a
    bare word is a string in this dialect."""
    if _INTEGER.match(text):
        return int(text)
    try:
        return float(text)
    except ValueError:
        return text


def _scalar(text: str) -> Scalar:
    text = text.strip()
    if not text:
        return ""
    if text[0] == text[-1] and text[0] in "\"'" and len(text) >= 2:
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(p) for p in inner.split(",")] if inner else []
    low = text.lower()
    if low in _WORDS:
        return _WORDS[low]
    return _number(text)


def parse_frontmatter(text: str) -> tuple[Frontmatter, str]:
    """'---\\nkey: value\\n---\\nbody' -> (meta, body). Flat keys plus one
    level of indented mapping (params:)."""
    if not text.startswith("---"):
        raise CatalogError("no frontmatter: the file must open with ---")
    end = text.find("\n---", 3)
    if end < 0:
        raise CatalogError("unterminated frontmatter")
    header, body = text[3:end], text[end + 4:]
    meta: Frontmatter = {}
    block: dict[str, Scalar] | None = None      # the mapping indented lines fill
    for raw in header.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[0] in " \t"
        line = raw.strip()
        if ":" not in line:
            raise CatalogError("bad frontmatter line %r" % raw)
        key, _, value = line.partition(":")
        key = key.strip()
        if indented:
            if block is None:
                raise CatalogError("indented line %r under no mapping" % raw)
            block[key] = _scalar(value)
        elif value.strip() == "":
            block = {}
            meta[key] = block
        else:
            meta[key] = _scalar(value)
            block = None
    return meta, body.strip("\n")


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


# --- the strategy --------------------------------------------------------------

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


def _read(directory: str, name: str, ids: set[str]) -> Strategy:
    """One strategy file, validated; any failure is a CatalogError naming the
    file."""
    hid = name[:-3]                       # the id IS the filename; nothing overrides it
    try:
        if not ID_RE.fullmatch(hid):
            raise CatalogError("%s: the filename must be lowercase-kebab" % name)
        path = os.path.join(directory, name)
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        meta, body = parse_frontmatter(raw)
        if "id" in meta and str(meta["id"]) != hid:
            raise CatalogError("%s: id: is the filename; drop it" % name)
        if hid in ids:
            raise CatalogError("%s: duplicate id %r" % (name, hid))
        return Strategy(hid, meta, body, raw, path)
    except CatalogError as error:
        text = str(error)
        wrapped = CatalogError(text if text.startswith((name, hid)) else "%s: %s" % (name, text))
        wrapped.file = name
        raise wrapped from error
    except Exception as error:            # bytes that are not text, a directory, ...
        wrapped = CatalogError("%s: %s: %s" % (name, type(error).__name__, error))
        wrapped.file = name
        raise wrapped from error


def strategy_files(directory: str) -> list[str]:
    """The names of a playbook's strategy files, sorted: its .md files less
    the markdown that lives beside them. Everything that copies, reads or
    fingerprints a playbook takes its files from here."""
    if not os.path.isdir(directory):
        raise CatalogError("no strategies directory at %s" % directory)
    return sorted(name for name in os.listdir(directory)
                  if name.endswith(".md") and name not in NOT_STRATEGIES)


def load(directory: str | None = None) -> list[Strategy]:
    """Every strategy file, validated, ordered constraints (limits, scored) then
    heuristics, then assumptions; drafts sit last within their kind."""
    directory = directory or strategies_dir()
    out: list[Strategy] = []
    ids: set[str] = set()
    for name in strategy_files(directory):
        strategy = _read(directory, name, ids)
        ids.add(strategy.id)
        out.append(strategy)
    if not out:
        raise CatalogError("no strategies in %s" % directory)
    out.sort(key=lambda h: (KIND_ORDER[h.kind], FORMS.index(h.form), h.category, h.id))
    return out


def parse_weights(items: Mapping[str, object] | Iterable[object] | None) -> dict[str, float]:
    """`id:value` strings (a query's repeated `weight` parameter) or a mapping
    -> {id: weight}, each clamped to the file's 0..10. What a board's sliders
    send. An entry that is not id:value, or a value that is not a number, is
    a Refusal, which the board, the service and the board tool answer as the
    caller's error."""
    if isinstance(items, Mapping):
        pairs = [(str(hid), value) for hid, value in items.items()]
    else:
        pairs = [_weight_entry(item) for item in items or []]
    out = {}
    for hid, value in pairs:
        if not isinstance(value, (int, float, str)):
            raise Refusal("weight %r for %r is not a number" % (value, hid))
        try:
            weight = float(value)
        except ValueError:
            raise Refusal("weight %r for %r is not a number" % (value, hid)) from None
        out[hid.strip()] = min(10.0, max(0.0, weight))
    return out


def _weight_entry(item: object) -> tuple[str, object]:
    """One `id:value` string -> (id, value)."""
    hid, colon, value = str(item).partition(":")
    if not colon:
        raise Refusal("a weight is id:value, got %r" % item)
    return hid, value


def weighted(catalog: list[Strategy], weights: Mapping[str, float] | None) -> list[Strategy]:
    """The catalog with the heuristics named in `weights` carrying those
    weights instead of their files' - shallow copies, so the files and the
    loaded catalog stay as they are. Only a heuristic has a weight to set:
    a scored constraint's stays its own, and an unknown id is ignored."""
    if not weights:
        return catalog
    out = []
    for h in catalog:
        if h.kind == "heuristic" and h.id in weights and h.weight != weights[h.id]:
            h = copy.copy(h)
            h.weight = weights[h.id]
        out.append(h)
    return out


def has_scoring_terms(catalog: Iterable[Strategy]) -> bool:
    """Whether the playbook has any term that scores: a heuristic, a scored
    constraint or a soft limit. A playbook of hard limits and prose alone
    ties every legal six at zero - the board then says "unscored" rather
    than 100 / 100."""
    return any(
        h.kind == "heuristic" or h.form == "scored" or (h.form == "limit" and h.soft)
        for h in catalog)


class KindCounts(TypedDict):
    """Strategies per kind, in KINDS order."""
    constraint: int
    heuristic: int
    assumption: int


def counts(catalog: Iterable[Strategy]) -> KindCounts:
    """Strategies per kind: {"constraint": n, "heuristic": n, "assumption": n}."""
    kinds = [h.kind for h in catalog]
    return KindCounts(constraint=kinds.count("constraint"), heuristic=kinds.count("heuristic"),
                      assumption=kinds.count("assumption"))


def playbook_name(directory: str | None = None) -> str:
    """How the database names a playbook: its folder, relative to the repo."""
    return os.path.relpath(directory or strategies_dir(), ROOT).replace(os.sep, "/")


def playbook_digest(directory: str | None = None) -> str:
    """The playbook's fingerprint: a sha256 over its strategy files in
    strategy_files order, each name and then its bytes. A fixture proved
    under a playbook records this value, so a test can tell the playbook it
    was proved under from the one in force. README.md and tuning-log.md
    never move it."""
    directory = directory or strategies_dir()
    digest = hashlib.sha256()
    for name in strategy_files(directory):
        digest.update(name.encode("utf-8") + b"\0")
        with open(os.path.join(directory, name), "rb") as handle:
            digest.update(handle.read() + b"\0")
    return digest.hexdigest()


class MirrorSummary(KindCounts):
    """What a mirror loaded: the strategies per kind, the total and the table
    it wrote; load_authored adds how many are drafts."""
    total: int
    tables: list[str]
    pending: NotRequired[int]


def mirror(
        cx: psycopg.Connection, catalog: Sequence[Strategy],
        directory: str | None = None) -> MirrorSummary:
    """Reload the strategies table from the files (whole truth), each row
    naming the playbook it came from."""
    cursor = cx.cursor()
    source_id = register_source(cursor, AUTHORED, now())
    cursor.execute("DELETE FROM strategies")
    for h in catalog:
        cursor.execute(
            "INSERT INTO strategies (strategy_id, name, kind, category,"
            " direction, metric, weight, expression, params, body, playbook, source_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                h.id, h.name, h.kind, h.category, h.direction, h.metric,
                h.weight if h.solver_reads else None, h.expressions or None,
                _params_line(h) or None, h.body, playbook_name(directory), source_id))
    cx.commit()
    return MirrorSummary(**counts(catalog), total=len(catalog), tables=["strategies"])


def _params_line(h: Strategy) -> str:
    """A strategy's params as NAME=value, by name."""
    return ", ".join("%s=%s" % (name, h.params[name]) for name in sorted(h.params))


def catalog_rendered(catalog: Iterable[Strategy]) -> str:
    """The catalog as text, one line per strategy: kind, form, id, category and
    what it weighs - the `strategies` tool's reply."""
    lines = []
    for h in catalog:
        head = "%-10s %-10s %-28s %-9s" % (h.kind, h.form, h.id, h.category)
        if h.form == "heuristic":
            head += " %s %s x%g%s" % (h.direction, h.metric, h.weight, " need" if h.need else "")
        elif h.form == "limit":
            head += " %s%s" % (h.expressions, " (soft)" if h.soft else "")
        elif h.form == "scored":
            head += " %s x%g" % (h.expressions, h.weight)
        elif h.form == "draft":
            head += " (draft: name, kind and prose only - /strategy infers the rest)"
        lines.append(head)
    return "\n".join(lines)


def _form_line(h: Strategy, reg: Mapping[str, str]) -> str:
    """The line under a strategy's heading in the docs: what it weighs, by form."""
    when = "; when `%s`" % h.when.source if h.when else ""
    if h.form == "heuristic":
        return "`%s %s` - %s. weight %g%s%s" % (
            h.direction, h.metric, reg.get(h.metric or "", ""), h.weight,
            ", a need" if h.need else "", when)
    if h.form == "limit":
        # a limit has require:, and a soft one a penalty: (_check_limit)
        return "`require %s`%s%s" % (
            h.require.source if h.require else "",
            " (soft, penalty `%s`)" % h.penalty.source if h.soft and h.penalty else " (hard)",
            when)
    if h.form == "draft":
        return "*draft* - name, kind and prose only; `/strategy` infers the rest"
    if h.form == "assumption":
        return "*assumption* - prose the solver takes as given and the session holds a comp to"
    return "weight %g; %s" % (h.weight, "; ".join(
        "%s `%s`" % (label, expr.source) for label, expr in (
            ("when", h.when), ("bonus", h.bonus), ("penalty", h.penalty))
        if expr is not None))


def _without_title(body: str) -> str:
    """The prose without its title line: the docs' heading names the strategy."""
    first, newline, rest = body.partition("\n")
    return rest.lstrip("\n") if first.startswith("#") and newline else body


def write_docs(catalog: Sequence[Strategy], path: str = DOCS_PATH) -> str | None:
    """The catalog and the vocabulary, generated into docs/inference.md
    between its <!-- generated:catalog --> markers - from the shipped
    playbook only: while another folder is in force the docs keep describing
    the shipped one, and this returns None."""
    if strategies_dir() != SHIPPED_DIR:
        return None
    kinds = counts(catalog)
    forms = {f: sum(1 for h in catalog if h.form == f) for f in FORMS}
    reg = compute.registry()
    out = [
        "%d files in `inference/strategies/`: %d constraints (%d limits, %d scored),"
        " %d heuristics and %d assumptions%s. Regenerated by `python -m db.mcp call db_docs`."
        % (
            len(catalog), kinds["constraint"], forms["limit"], forms["scored"],
            kinds["heuristic"], kinds["assumption"],
            "; %d draft(s) awaiting /strategy" % forms["draft"] if forms["draft"] else ""),
        ""]
    for kind in KINDS:
        items = [h for h in catalog if h.kind == kind]
        if not items:
            continue
        out += ["#### %ss" % kind.capitalize(), ""]
        for h in items:
            out.append("##### %s (`%s`, %s%s)" % (
                h.name, h.id, h.category, ", %s" % h.form if h.form != h.kind else ""))
            out += ["", _form_line(h, reg)]
            if h.params:
                out.append("params: " + _params_line(h))
            out += ["", _without_title(h.body), ""]
    out += ["#### The vocabulary", "",
            "Every key a strategy may reference, with its meaning. `enemy.*` are",
            "the `team.*` metrics computed for the red side.", "",
            "| key | meaning |", "| --- | --- |"]
    for key, description in reg.items():
        if key.startswith("enemy."):
            continue
        out.append("| `%s`%s | %s |" % (key, " (text)" if key in compute.TEXT_METRICS
                                        else "", description))
    embed(path, "catalog", "\n".join(out))
    return path
