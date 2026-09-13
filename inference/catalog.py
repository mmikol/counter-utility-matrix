"""The heuristics catalog: markdown files with frontmatter, read from
inference/heuristics/, validated against the facts layer's metric
registry, and mirrored into the `heuristics` table.

A heuristic file:

    ---
    name: Answer every revealed enemy
    kind: goal                # constraint | goal | strategy
    category: matchup
    direction: maximize       # goals: maximize | minimize
    metric: team.coverage_share
    weight: 3
    when: enemy.size >= 1     # optional guard, any kind
    ---
    prose: what it means, why it is weighted this way, how to read it

Kinds:
    constraint  `require: <expr>` must hold. Hard by default - a comp that
                fails is discarded; `soft: true` with `penalty: <number>`
                subtracts instead.
    goal        `metric` (a numeric fact key) is min-max normalised across
                the candidates and weighted; `direction` says which end is
                good.
    strategy    prose the /comp skill reads and the board shows; when it
                also carries `bonus: <expr>` and/or `penalty: <expr>`, the
                solver adds `weight x (bonus - penalty)` while `when` holds.

`params:` (an indented block of NAME: number) are the dials an expression
reads as params.NAME - tuning is editing the file.
"""

import os
import re

from data.common import ROOT
from user.facts import compute
from inference.expr import ExprError, compile_expr

HEURISTICS_DIR = os.path.join(ROOT, "inference", "heuristics")
DOCS_PATH = os.path.join(ROOT, "docs", "heuristics.md")
KINDS = ("constraint", "goal", "strategy")
NOT_HEURISTICS = ("README.md", "tuning-log.md")     # markdown that lives beside the files
KIND_ORDER = {k: i for i, k in enumerate(KINDS)}


class CatalogError(ValueError):
    pass


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


# --- the heuristic --------------------------------------------------------------

class Heuristic:
    def __init__(self, hid, meta, body, raw, path):
        self.id, self.body, self.raw, self.path = hid, body, raw, path
        self.name = str(meta.get("name") or hid.replace("-", " "))
        self.kind = meta.get("kind")
        if self.kind not in KINDS:
            raise CatalogError("%s: kind must be one of %s" % (hid, "/".join(KINDS)))
        self.category = str(meta.get("category") or "general")
        self.direction = meta.get("direction")
        self.metric = meta.get("metric")
        self.weight = float(meta.get("weight", 1.0) or 0.0)
        self.soft = bool(meta.get("soft", False))
        self.params = {k: v for k, v in (meta.get("params") or {}).items()}
        try:
            self.when = compile_expr(str(meta["when"])) if "when" in meta else None
            self.require = compile_expr(str(meta["require"])) if "require" in meta else None
            self.bonus = compile_expr(str(meta["bonus"])) if "bonus" in meta else None
            self.penalty = (compile_expr(str(meta["penalty"]))
                            if "penalty" in meta else None)
        except ExprError as error:
            raise CatalogError("%s: %s" % (hid, error))
        self._check()

    def _check(self):
        known = compute.registry()
        if self.kind == "goal":
            if self.direction not in ("maximize", "minimize"):
                raise CatalogError("%s: a goal needs direction maximize|minimize" % self.id)
            if not self.metric or self.metric not in known:
                raise CatalogError("%s: metric %r is not a registered fact key"
                                   % (self.id, self.metric))
            if self.metric in compute.TEXT_METRICS:
                raise CatalogError("%s: metric %r is text, not a number" % (self.id, self.metric))
        if self.kind == "constraint" and self.require is None:
            raise CatalogError("%s: a constraint needs require:" % self.id)
        if self.kind == "constraint" and self.soft and self.penalty is None:
            raise CatalogError("%s: a soft constraint needs penalty:" % self.id)
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
    def scored(self):
        """Whether the solver adds anything for this heuristic."""
        return self.kind != "strategy" or self.bonus is not None or self.penalty is not None

    @property
    def expressions(self):
        parts = []
        for label, expr in (("when", self.when), ("require", self.require),
                            ("bonus", self.bonus), ("penalty", self.penalty)):
            if expr is not None:
                parts.append("%s: %s" % (label, expr.source))
        return "; ".join(parts)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "kind": self.kind,
                "category": self.category, "direction": self.direction,
                "metric": self.metric, "weight": self.weight, "soft": self.soft,
                "when": self.when.source if self.when else None,
                "require": self.require.source if self.require else None,
                "bonus": self.bonus.source if self.bonus else None,
                "penalty": self.penalty.source if self.penalty else None,
                "params": self.params, "body": self.body}


def load(directory=HEURISTICS_DIR):
    """Every heuristic file, validated, ordered constraint/goal/strategy."""
    if not os.path.isdir(directory):
        raise CatalogError("no heuristics directory at %s" % directory)
    out, ids = [], set()
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".md") or name in NOT_HEURISTICS:
            continue
        path = os.path.join(directory, name)
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        try:
            meta, body = parse_frontmatter(raw)
        except CatalogError as error:
            raise CatalogError("%s: %s" % (name, error))
        hid = str(meta.get("id") or name[:-3])
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", hid):
            raise CatalogError("%s: id %r must be lowercase-kebab" % (name, hid))
        if hid in ids:
            raise CatalogError("%s: duplicate id %r" % (name, hid))
        ids.add(hid)
        out.append(Heuristic(hid, meta, body, raw, path))
    if not out:
        raise CatalogError("no heuristics in %s" % directory)
    out.sort(key=lambda h: (KIND_ORDER[h.kind], h.category, h.id))
    return out


def mirror(cx, catalog):
    """Reload the heuristics table from the files (whole truth)."""
    from data.sources.authored import AUTHORED
    from data.common import now, register_source
    cursor = cx.cursor()
    source_id = register_source(cursor, AUTHORED, now())
    cursor.execute("DELETE FROM heuristics")
    for h in catalog:
        cursor.execute(
            "INSERT INTO heuristics (heuristic_id, name, kind, category,"
            " direction, metric, weight, expression, params, body, source_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (h.id, h.name, h.kind, h.category, h.direction, h.metric,
             h.weight if h.scored else None, h.expressions or None,
             ", ".join("%s=%s" % kv for kv in sorted(h.params.items())) or None,
             h.body, source_id))
    cx.commit()
    counts = {k: sum(1 for h in catalog if h.kind == k) for k in KINDS}
    return dict(counts, total=len(catalog), tables=["heuristics"])


def render(catalog):
    lines = []
    for h in catalog:
        head = "%-11s %-28s %-9s" % (h.kind, h.id, h.category)
        if h.kind == "goal":
            head += " %s %s x%g" % (h.direction, h.metric, h.weight)
        elif h.scored:
            head += " %s%s" % (h.expressions, " x%g" % h.weight if h.kind == "strategy" else "")
        lines.append(head)
    return "\n".join(lines)


def write_docs(catalog, path=DOCS_PATH):
    """docs/heuristics.md, generated from the files."""
    counts = {k: sum(1 for h in catalog if h.kind == k) for k in KINDS}
    reg = compute.registry()
    out = ["# The heuristics", "",
           "The inference layer's brain: %d markdown files in `inference/heuristics/`"
           % len(catalog),
           "(%d constraints, %d goals, %d strategies). Each file is"
           % (counts["constraint"], counts["goal"], counts["strategy"]),
           "frontmatter a machine scores by and prose a person argues with; the",
           "solver reads the files live, and `load_playbook` mirrors them into the",
           "`heuristics` table so a recommendation can cite the ids it was scored",
           "under. Tuning is editing a file (the compose stack bind-mounts the",
           "directory, so the `inference` container picks edits up live). This",
           "page is generated: `python -m data.orchestrator docs`. Every change to a",
           "file goes through the `tune` tool (or a `fit_weights` nudge) and is logged",
           "in [tuning-log.md](../inference/heuristics/tuning-log.md).", "",
           "## How a composition is scored", "",
           "```", "COMP = ARGMAX[ STRATEGIES( FACTS ) ]", "```", "",
           "For a board (map, red picks, locked blue picks) the solver enumerates",
           "candidate sixes around the locked picks, computes every team, enemy and",
           "matchup metric for each (the same functions the board renders as facts),",
           "then:", "",
           "- **constraints** discard a candidate whose `require` fails (soft ones",
           "  subtract their `penalty` instead);",
           "- **goals** min-max normalise their `metric` across the surviving",
           "  candidates to [0, 1] (flipped for `minimize`) and add `weight x norm`;",
           "- **strategies** are prose the session reads and the board shows; one",
           "  that also carries `bonus`/`penalty` adds `weight x (bonus - penalty)`",
           "  while its `when` holds.", "",
           "Score = the sum. Players are assumed to play optimally, so the score is",
           "a comp's ceiling, not a prediction for a given lobby.", "",
           "## Catalog", ""]
    for kind in KINDS:
        items = [h for h in catalog if h.kind == kind]
        if not items:
            continue
        out += ["### %ss" % kind.capitalize(), ""]
        for h in items:
            out.append("#### %s (`%s`, %s)" % (h.name, h.id, h.category))
            out.append("")
            if h.kind == "goal":
                out.append("`%s %s` - %s. weight %g%s" % (
                    h.direction, h.metric, reg.get(h.metric, ""), h.weight,
                    "; when `%s`" % h.when.source if h.when else ""))
            elif h.kind == "constraint":
                out.append("`require %s`%s%s" % (
                    h.require.source, " (soft, penalty `%s`)" % h.penalty.source
                    if h.soft else " (hard)",
                    "; when `%s`" % h.when.source if h.when else ""))
            elif h.scored:
                out.append("weight %g; %s" % (h.weight, "; ".join(
                    "%s `%s`" % (label, expr.source) for label, expr in (
                        ("when", h.when), ("bonus", h.bonus), ("penalty", h.penalty))
                    if expr is not None)))
            if h.params:
                out.append("params: " + ", ".join("%s=%s" % kv
                                                    for kv in sorted(h.params.items())))
            body = re.sub(r"^#[^\n]*\n+", "", h.body)      # the header names it
            out += ["", body, ""]
    out += ["## The vocabulary", "",
            "Every key a heuristic may reference, with its meaning. `enemy.*` are",
            "the `team.*` metrics computed for the red side.", "",
            "| key | meaning |", "| --- | --- |"]
    for key, description in reg.items():
        if key.startswith("enemy."):
            continue
        out.append("| `%s`%s | %s |" % (key, " (text)" if key in compute.TEXT_METRICS
                                        else "", description))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")
    return path
