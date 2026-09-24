"""The strategies catalog: the playbook in force read from its folder,
each file parsed (inference.frontmatter) and checked (inference.strategy)
into a Strategy, the whole ordered, mirrored into the `strategies` table
and written into docs/inference.md; and what reads the playbook as a
whole - the weights one board overrides, whether anything scores, the
count per kind, the playbook's name and digest.
"""

import copy
import hashlib
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import NotRequired, TypedDict

import psycopg

from db import ROOT, Refusal, embed
from db.data.authored import AUTHORED
from db.psql import now, register_source
from facts import compute
from inference.frontmatter import FrontmatterError, parse_frontmatter
from inference.strategy import FORMS, KINDS, CatalogError, Strategy

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
NOT_STRATEGIES = ("README.md", "tuning-log.md")     # markdown that lives beside the files
KIND_ORDER = {k: i for i, k in enumerate(KINDS)}


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
        parsed = parse_frontmatter(raw)
        if "id" in parsed.meta and str(parsed.meta["id"]) != hid:
            raise CatalogError("%s: id: is the filename; drop it" % name)
        if hid in ids:
            raise CatalogError("%s: duplicate id %r" % (name, hid))
        return Strategy(hid, parsed.meta, body=parsed.body, raw=raw, path=path)
    except (CatalogError, FrontmatterError) as error:
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
        " %d heuristics and %d assumptions%s. Regenerated by"
        " `.venv/bin/python -m db.mcp call db_docs`."
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
