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
    prose: what it means, why it is weighted this way, how to read it

Three kinds. A HEURISTIC names a numeric fact key (`metric`) that is
min-max normalised against a seeded reference sample of legal sixes for
the board and weighted; `direction` says which end is good. A CONSTRAINT
takes one of two forms, read off its frontmatter (`form`):

    limit    `require: <expr>` must hold. Hard by default - a comp that
             fails is discarded; `soft: true` with `penalty: <number>`
             subtracts instead.
    scored   `bonus: <expr>` and/or `penalty: <expr>`: the solver adds
             `weight x (bonus - penalty)` while `when` holds.

An ASSUMPTION is prose by definition: what the solver takes as given and
the /comp session holds a comp to (players play optimally, rates are a
proxy, trust the kit when the rates are stale); it carries nothing to
score and is never a draft.

A constraint or heuristic with only a name, a kind and prose - no metric,
no expression - is a DRAFT: it loads, it is shown and served, the solver
ignores it, and the `/strategy` skill infers the rest (a heuristic's
metric, direction and weight; a constraint's limit or bonus/penalty and
params) from the prose and writes it through `infer_strategy` - or turns
it into an assumption when nothing measurable captures it. Nothing here
derives a formula on its own.

`params:` (an indented block of NAME: number) are the dials an expression
reads as params.NAME - tuning is editing the file.
"""

import copy
import os
import re

from db import ROOT
from inference.expr import ExprError, Section, compile_expr
from ui.facts import compute

SHIPPED_DIR = os.path.join(ROOT, "inference", "strategies")


def strategies_dir():
    """The playbook in force: the shipped one, unless COUNTER_MATRIX_STRATEGIES
    names another (an experiment under inference/experiments/, say) - a path
    relative to the repo root or absolute."""
    chosen = os.environ.get("COUNTER_MATRIX_STRATEGIES", "").strip()
    return os.path.abspath(os.path.join(ROOT, chosen)) if chosen else SHIPPED_DIR


STRATEGIES_DIR = strategies_dir()
DOCS_PATH = os.path.join(ROOT, "docs", "inference.md")
KINDS = ("constraint", "heuristic", "assumption")
FORMS = ("limit", "scored", "draft", "heuristic", "assumption")
NOT_HEURISTICS = ("README.md", "tuning-log.md")     # markdown that lives beside the files
KIND_ORDER = {k: i for i, k in enumerate(KINDS)}


class CatalogError(ValueError):
    file = None         # the strategy file at fault, when one is


# --- the frontmatter dialect --------------------------------------------------

def _scalar(text):
    text = text.strip()
    if not text:
        return ""
    if text[0] == text[-1] and text[0] in "\"'" and len(text) >= 2:
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(p) for p in inner.split(",")] if inner else []
    low = text.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse_frontmatter(text):
    """'---\\nkey: value\\n---\\nbody' -> (meta, body). Flat keys plus one
    level of indented mapping (params:)."""
    if not text.startswith("---"):
        raise CatalogError("no frontmatter (the file must open with ---)")
    end = text.find("\n---", 3)
    if end < 0:
        raise CatalogError("unterminated frontmatter")
    header, body = text[3:end], text[end + 4:]
    meta, current = {}, None
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
            if current is None:
                raise CatalogError("indented line %r under no mapping" % raw)
            meta[current][key] = _scalar(value)
        elif value.strip() == "":
            meta[key] = {}
            current = key
        else:
            meta[key] = _scalar(value)
            current = None
    return meta, body.strip("\n")


# --- the strategy --------------------------------------------------------------

class Strategy:
    def __init__(self, hid, meta, body, raw, path):
        self.id, self.body, self.raw, self.path = hid, body, raw, path
        self.name = str(meta.get("name") or hid.replace("-", " "))
        self.kind = meta.get("kind")
        if self.kind not in KINDS:
            raise CatalogError("%s: kind must be one of %s" % (hid, "/".join(KINDS)))
        self.category = str(meta.get("category") or "general")
        self.direction = meta.get("direction")
        self.metric = meta.get("metric")
        try:
            self.weight = float(meta.get("weight", 1.0) or 0.0)
        except (TypeError, ValueError):
            raise CatalogError("%s: weight must be a number" % hid) from None
        if not 0.0 <= self.weight <= 10.0:
            raise CatalogError("%s: weight must be within 0..10" % hid)
        self.soft = bool(meta.get("soft", False))
        if "prose" in meta:
            raise CatalogError("%s: prose: is gone - a ground rule is kind: assumption" % hid)
        self.params = dict((meta.get("params") or {}).items())
        self.params_section = Section(self.params)
        try:
            self.when = compile_expr(str(meta["when"])) if "when" in meta else None
            self.require = compile_expr(str(meta["require"])) if "require" in meta else None
            self.bonus = compile_expr(str(meta["bonus"])) if "bonus" in meta else None
            self.penalty = (compile_expr(str(meta["penalty"]))
                            if "penalty" in meta else None)
        except ExprError as error:
            raise CatalogError("%s: %s" % (hid, error)) from error
        self._check()

    def _check(self):
        known = compute.registry()
        if self.kind == "heuristic" and (self.metric or self.direction):
            if self.direction not in ("maximize", "minimize"):
                raise CatalogError("%s: a heuristic needs direction maximize|minimize" % self.id)
            if not self.metric or self.metric not in known:
                raise CatalogError("%s: metric %r is not a registered fact key"
                                   % (self.id, self.metric))
            if self.metric in compute.TEXT_METRICS:
                raise CatalogError("%s: metric %r is text, not a number" % (self.id, self.metric))
        if self.kind == "assumption" and (self.metric or self.require is not None
                                          or self.bonus is not None or self.penalty is not None
                                          or self.when is not None):
            raise CatalogError("%s: an assumption is prose; it carries nothing to score" % self.id)
        if self.kind == "heuristic" and (self.require is not None or self.bonus is not None):
            raise CatalogError("%s: a heuristic weighs a metric;"
                               " require/bonus belong to a constraint"
                               % self.id)
        if self.kind == "constraint" and self.metric:
            raise CatalogError("%s: a constraint has no metric; that is a heuristic" % self.id)
        if self.require is not None and self.bonus is not None:
            raise CatalogError("%s: a constraint is a limit (require) or scored (bonus/penalty),"
                               " not both" % self.id)
        if self.require is not None and self.soft and self.penalty is None:
            raise CatalogError("%s: a soft limit needs penalty:" % self.id)
        if self.require is None and self.soft:
            raise CatalogError("%s: soft: only means something with require:" % self.id)
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
    def form(self):
        """heuristic, a constraint's form (limit, scored), assumption (prose by
        definition), or draft (name, kind and prose only - awaiting /strategy)."""
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
    def scored(self):
        """Whether the solver reads this strategy at all (assumptions and drafts it does not)."""
        return self.form in ("heuristic", "limit", "scored")

    @property
    def pending(self):
        """A draft: the /strategy skill has not inferred its frontmatter yet."""
        return self.form == "draft"

    @property
    def expressions(self):
        parts = []
        for label, expr in (("when", self.when), ("require", self.require),
                            ("bonus", self.bonus), ("penalty", self.penalty)):
            if expr is not None:
                parts.append("%s: %s" % (label, expr.source))
        return "; ".join(parts)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "kind": self.kind, "form": self.form,
                "pending": self.pending,
                "category": self.category, "direction": self.direction,
                "metric": self.metric, "weight": self.weight, "soft": self.soft,
                "when": self.when.source if self.when else None,
                "require": self.require.source if self.require else None,
                "bonus": self.bonus.source if self.bonus else None,
                "penalty": self.penalty.source if self.penalty else None,
                "params": self.params, "body": self.body}


def load(directory=STRATEGIES_DIR):
    """Every strategy file, validated, ordered constraints (limits, scored) then
    heuristics, then assumptions; drafts sit last within their kind."""
    if not os.path.isdir(directory):
        raise CatalogError("no strategies directory at %s" % directory)
    out, ids = [], set()
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".md") or name in NOT_HEURISTICS:
            continue
        path = os.path.join(directory, name)
        hid = name[:-3]                       # the id IS the filename; nothing overrides it
        try:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", hid):
                raise CatalogError("%s: the filename must be lowercase-kebab" % name)
            with open(path, encoding="utf-8") as handle:
                raw = handle.read()
            meta, body = parse_frontmatter(raw)
            if "id" in meta and str(meta["id"]) != hid:
                raise CatalogError("%s: id: is the filename; drop it" % name)
            if hid in ids:
                raise CatalogError("%s: duplicate id %r" % (name, hid))
            strategy = Strategy(hid, meta, body, raw, path)
        except CatalogError as error:
            text = str(error)
            wrapped = CatalogError(text if text.startswith((name, hid))
                                   else "%s: %s" % (name, text))
            wrapped.file = name
            raise wrapped from error
        except Exception as error:            # bytes that are not text, a directory, ...
            wrapped = CatalogError("%s: %s: %s" % (name, type(error).__name__, error))
            wrapped.file = name
            raise wrapped from error
        ids.add(hid)
        out.append(strategy)
    if not out:
        raise CatalogError("no strategies in %s" % directory)
    out.sort(key=lambda h: (KIND_ORDER[h.kind], FORMS.index(h.form), h.category, h.id))
    return out


def parse_weights(items):
    """`id:value` strings (a query's repeated `weight` parameter) or a mapping
    -> {id: weight}, each clamped to the file's 0..10; malformed entries are
    dropped. What a board's sliders send."""
    pairs = items.items() if isinstance(items, dict) else \
        (str(x).split(":", 1) for x in (items or []) if ":" in str(x))
    out = {}
    for hid, value in pairs:
        try:
            out[str(hid).strip()] = min(10.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            continue
    return out


def weighted(catalog, weights):
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


def scores(catalog):
    """Whether the playbook has any term that scores: a heuristic, a scored
    constraint or a soft limit. A playbook of hard limits and prose alone
    ties every legal six at zero - the board then says "unscored" rather
    than 100 / 100."""
    return any(h.kind == "heuristic" or getattr(h, "form", None) == "scored"
               or (getattr(h, "form", None) == "limit" and getattr(h, "soft", False))
               for h in catalog)


def playbook_name(directory=None):
    """How the database names a playbook: its folder, relative to the repo."""
    return os.path.relpath(directory or STRATEGIES_DIR, ROOT).replace(os.sep, "/")


def mirror(cx, catalog, directory=None):
    """Reload the strategies table from the files (whole truth), each row
    naming the playbook it came from."""
    from db.data.authored import AUTHORED
    from db.psql import now, register_source
    cursor = cx.cursor()
    source_id = register_source(cursor, AUTHORED, now())
    cursor.execute("DELETE FROM strategies")
    for h in catalog:
        cursor.execute(
            "INSERT INTO strategies (strategy_id, name, kind, category,"
            " direction, metric, weight, expression, params, body, playbook, source_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (h.id, h.name, h.kind, h.category, h.direction, h.metric,
             h.weight if h.scored else None, h.expressions or None,
             ", ".join("%s=%s" % kv for kv in sorted(h.params.items())) or None,
             h.body, playbook_name(directory), source_id))
    cx.commit()
    counts = {k: sum(1 for h in catalog if h.kind == k) for k in KINDS}
    return dict(counts, total=len(catalog), tables=["strategies"])


def render(catalog):
    lines = []
    for h in catalog:
        head = "%-10s %-10s %-28s %-9s" % (h.kind, h.form, h.id, h.category)
        if h.form == "heuristic":
            head += " %s %s x%g" % (h.direction, h.metric, h.weight)
        elif h.form == "limit":
            head += " %s%s" % (h.expressions, " (soft)" if h.soft else "")
        elif h.form == "scored":
            head += " %s x%g" % (h.expressions, h.weight)
        elif h.form == "draft":
            head += " (draft: name, kind and prose only - /strategy infers the rest)"
        lines.append(head)
    return "\n".join(lines)


def write_docs(catalog, path=DOCS_PATH):
    """The catalog and the vocabulary, generated into docs/inference.md
    between its <!-- generated:catalog --> markers - from the shipped
    playbook only: while an experiment is in force the docs keep describing
    the real one, and this returns None."""
    from db.psql.schema import embed
    if STRATEGIES_DIR != SHIPPED_DIR:
        return None
    counts = {k: sum(1 for h in catalog if h.kind == k) for k in KINDS}
    forms = {f: sum(1 for h in catalog if h.form == f) for f in FORMS}
    reg = compute.registry()
    out = ["%d files in `inference/strategies/`: %d constraints (%d limits, %d scored),"
           " %d heuristics and %d assumptions%s. Regenerated by `python -m db.mcp call db_docs`."
           % (len(catalog), counts["constraint"], forms["limit"], forms["scored"],
              counts["heuristic"], counts["assumption"],
              "; %d draft(s) awaiting /strategy" % forms["draft"] if forms["draft"] else ""),
           ""]
    for kind in KINDS:
        items = [h for h in catalog if h.kind == kind]
        if not items:
            continue
        out += ["#### %ss" % kind.capitalize(), ""]
        for h in items:
            out.append("##### %s (`%s`, %s%s)" % (
                h.name, h.id, h.category, ", %s" % h.form if h.form not in (h.kind,) else ""))
            out.append("")
            if h.form == "heuristic":
                out.append("`%s %s` - %s. weight %g%s" % (
                    h.direction, h.metric, reg.get(h.metric, ""), h.weight,
                    "; when `%s`" % h.when.source if h.when else ""))
            elif h.form == "limit":
                out.append("`require %s`%s%s" % (
                    h.require.source, " (soft, penalty `%s`)" % h.penalty.source
                    if h.soft else " (hard)",
                    "; when `%s`" % h.when.source if h.when else ""))
            elif h.form == "draft":
                out.append("*draft* - name, kind and prose only; `/strategy` infers the rest")
            elif h.form == "assumption":
                out.append("*assumption* - prose the solver takes as given"
                           " and the session holds a comp to")
            elif h.form == "scored":
                out.append("weight %g; %s" % (h.weight, "; ".join(
                    "%s `%s`" % (label, expr.source) for label, expr in (
                        ("when", h.when), ("bonus", h.bonus), ("penalty", h.penalty))
                    if expr is not None)))
            if h.params:
                out.append("params: " + ", ".join("%s=%s" % kv
                                                    for kv in sorted(h.params.items())))
            body = re.sub(r"^#[^\n]*\n+", "", h.body)      # the header names it
            out += ["", body, ""]
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
