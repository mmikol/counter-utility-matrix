"""The playbook through the door: the metric vocabulary a strategy may
reference, the catalog, the tools that write a strategy file - tune,
add_strategy, infer_strategy, derive_strategies - the tuning log, and the
strategy files served as MCP resources.

Every write validates through the catalog, rewrites the docs catalog for the
shipped playbook and logs a reasoned line (inference.tune does all three),
then reloads the strategies table from the files (_remirror): the database
half of the write, and the one step this module adds. derive_strategies
reloads only when it completed a draft, since otherwise it wrote nothing.
The frontmatter fields the writes take are declared from
inference.strategy.FIELDS, the rule that checks them, so the door admits
what a file may hold.
"""

import os

from db import ROOT, Refusal
from door.mcp.registry import Context, tool
from door.mcp.schema import Properties, Property, ToolReply
from door.mcp.server import NoSuchResourceError, Resource, ResourceText
from facts import compute
from inference import catalog, derive, tune
from inference.strategy import FIELDS, TUNABLE, Field, FieldKind


@tool(
    "metrics", "The vocabulary a strategy may reference: every metric key with its"
    " meaning - team.*, enemy.* (the same for the red side), matchup.*, map.*,"
    " world.* - and which are text. What /strategy reads to infer a heuristic's"
    " metric or a constraint's expression from prose.")
def metrics(ctx: Context) -> ToolReply:
    reg = compute.registry()
    numeric = {k: v for k, v in reg.items() if k not in compute.TEXT_METRICS}
    lines = [
        "%-32s %s%s" % (k, v, "  (text)" if k in compute.TEXT_METRICS else "")
        for k, v in reg.items() if not k.startswith("enemy.")]
    return ToolReply("\n".join(lines), {"metrics": reg, "numeric": sorted(numeric),
                                        "text": sorted(compute.TEXT_METRICS)})


@tool(
    "strategies", "The inference layer's catalog - STRATEGIES = CONSTRAINTS ∪ HEURISTICS"
    " ∪ ASSUMPTIONS: every markdown strategy with its kind (constraint, heuristic or"
    " assumption), a constraint's form (limit, scored, draft), metric, direction, weight"
    " and expressions.")
def strategies(ctx: Context) -> ToolReply:
    cat = catalog.load()
    pending = [h.id for h in cat if h.pending]
    text = catalog.catalog_rendered(cat)
    if catalog.strategies_dir() != catalog.SHIPPED_DIR:
        text = "playbook in force: %s (the shipped one is %s)\n\n%s" % (
            os.path.relpath(catalog.strategies_dir(), ROOT),
            os.path.relpath(catalog.SHIPPED_DIR, ROOT), text)
    if pending:
        text += "\n\n%d draft(s) awaiting /strategy: %s" % (len(pending), ", ".join(pending))
    return ToolReply(text, {"strategies": [h.to_dict() for h in cat], "pending": pending})


# the JSON schema type the door declares for each kind of frontmatter field:
# an expression may be a bare number, as a soft limit's penalty is
KIND_TYPES: dict[FieldKind, str | list[str]] = {
    "line": "string", "choice": "string", "number": "number", "flag": "boolean",
    "expression": ["string", "number"], "params": "object"}


def _property(field: Field) -> Property:
    """A frontmatter field as the door declares it, from the rule that checks
    it (strategy.FIELDS): its kind's JSON type, a choice's enum and its
    meaning."""
    prop = Property(type=KIND_TYPES[field.kind], description=field.meaning)
    if field.choices:
        prop["enum"] = list(field.choices)
    return prop


# the fields add_strategy and infer_strategy take beside a strategy's name and kind
STRATEGY_FIELDS: Properties = {
    name: _property(field) for name, field in FIELDS.items() if name not in ("name", "kind")}


# who asked, for the log line: the three writers take it alike, so a
# headless agent names itself whichever it calls
BY: Properties = {
    "by": {"type": "string", "description": "who asked, for the log line (default %s;"
                                           " the board says so)" % tune.BY_SESSION}}


def _remirror(ctx: Context) -> None:
    """A playbook write's database half: the strategies table reloaded from
    the files the write changed."""
    with ctx.connect() as cx:
        catalog.mirror(cx, catalog.load())


@tool(
    "tune", "Change one strategy's frontmatter - its weight, a params dial, or"
    " a when/require/bonus/penalty expression - validated through the"
    " catalog before it is written, mirrored into the database, and logged"
    " with the reason in inference/strategies/tuning-log.md.",
    {
        "id": {"type": "string", "description": "the strategy's id (its filename)"},
        "field": {"type": "string", "description": " | ".join((*TUNABLE, "params.NAME"))},
        "value": {"description": "the new value: a number, a boolean, or an expression"},
        "reason": {"type": "string", "description": "why, in a sentence"},
        **BY},
    ["id", "field", "value", "reason"])
def tune_tool(      # _tool: inference.tune holds the bare name
        ctx: Context, id: str, field: str, value: object, reason: str,
        by: str = tune.BY_SESSION) -> ToolReply:
    change = tune.tune(id, field, value, reason, by=by)
    _remirror(ctx)
    return ToolReply("tuned %s: %s %s -> %s\n%s" % (
        change["id"], change["field"], change["old"], change["new"], change["line"]), change)


@tool(
    "add_strategy", "Store a new strategy in inference/strategies/ from its name,"
    " kind and prose plus the frontmatter /strategy inferred - a heuristic's"
    " metric/direction/weight, or a constraint's require or when/bonus/penalty"
    " and params; an assumption is prose and needs nothing. The prose is three"
    " sentences at most. Validated through the"
    " catalog before the file exists, mirrored into the database, logged."
    " Left with nothing inferred it lands as a draft the solver ignores.",
    {
        "id": {"type": "string", "description": "lowercase-kebab, becomes the filename"},
        "name": _property(FIELDS["name"]),
        "kind": _property(FIELDS["kind"]),
        "body": {"type": "string", "description": "the prose: what it means and why"},
        "reason": {"type": "string", "description": "why it was added, in a sentence"},
        **BY, **STRATEGY_FIELDS},
    ["id", "name", "kind", "body", "reason"])
def add_strategy(
        ctx: Context, id: str, name: str, kind: str, body: str, reason: str,
        by: str = tune.BY_SESSION, **fields: object) -> ToolReply:
    added = tune.add(id, name, kind, body, fields, reason, by=by)
    _remirror(ctx)
    note = ("\nstored as a DRAFT: the solver ignores it until /strategy infers its frontmatter"
            if added["form"] == "draft" else "")
    return ToolReply("added %s as %s/%s -> %s\n%s%s" % (
        id, kind, added["form"], os.path.relpath(added["path"], ROOT), added["line"], note),
        added)


@tool(
    "infer_strategy", "Complete a draft (or rewrite a strategy's scoring): set several"
    " frontmatter fields at once - metric/direction/weight, when/require/bonus/"
    "penalty, params - validated as a whole, mirrored, logged as one line.",
    {
        "id": {"type": "string"},
        "reason": {"type": "string", "description": "how the fields follow from the prose"},
        **BY, **STRATEGY_FIELDS},
    ["id", "reason"])
def infer_strategy(
        ctx: Context, id: str, reason: str, by: str = tune.BY_SESSION,
        **fields: object) -> ToolReply:
    done = tune.complete(id, fields, reason, by=by)
    _remirror(ctx)
    return ToolReply("%s is now %s: %s\n%s" % (id, done["form"], ", ".join(
        "%s=%s" % kv for kv in done["set"].items()), done["line"]), done)


@tool(
    "derive_strategies", "Complete every draft (a strategy with only a name, a kind"
    " and prose) by asking Claude Code in print mode - the subscription, no key -"
    " for the frontmatter, validated through the catalog and logged. Runs where"
    " the claude CLI is signed in (the host); elsewhere drafts stay pending.",
    {"ids": {
        "type": "array", "items": {"type": "string"},
        "description": "which drafts (default: all)"}})
def derive_strategies(ctx: Context, ids: list[str] | None = None) -> ToolReply:
    result = derive.derive(ids, log=ctx.log)
    if result["derived"]:
        _remirror(ctx)
    return ToolReply(derive.derive_rendered(result), result)


@tool(
    "tuning_log", "The audit trail of every change to the strategies'"
    " frontmatter, newest last.",
    {"lines": {"type": "integer", "description": "how many, 1 or more (default 20)"}})
def tuning_log(ctx: Context, lines: int = 20) -> ToolReply:
    if lines < 1:
        raise Refusal("lines is 1 or more")
    tail = tune.log_tail(lines)
    return ToolReply("\n".join(tail) or "no tuning yet", {"lines": tail})


class StrategyResources:
    """The strategies files (and the tuning log), readable as MCP resources."""

    def list(self) -> list[Resource]:
        out = [Resource(uri="strategy://" + h.id, name=h.name,
                        description="%s (%s)" % (h.kind, h.category),
                        mimeType="text/markdown") for h in catalog.load()]
        out.append(Resource(uri="strategy://tuning-log", name="tuning log",
                            description="every change to the strategies, with reasons",
                            mimeType="text/markdown"))
        return out

    def read(self, uri: str) -> ResourceText:
        hid = uri.replace("strategy://", "", 1)
        if hid == "tuning-log":
            return ResourceText(uri=uri, mimeType="text/markdown",
                                text="\n".join(tune.log_tail(1000)) or "no tuning yet")
        for h in catalog.load():
            if h.id == hid:
                return ResourceText(uri=uri, mimeType="text/markdown", text=h.raw)
        raise NoSuchResourceError(uri)
