"""The tools the data layer serves, and - through the same door - the board
tools of the UI and inference layers.

Every pull_* tool is pull -> clean -> store for one source and domain: that
domain's run() in its source package under db/data/. `sync_all` runs them in
dependency order. A session, the refresher or a shell (`python -m db.mcp
call`) decides what to pull and when, and reads the summary back.
"""

import datetime
import functools
import json
import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

import psycopg
from psycopg.sql import SQL

from db import CACHE_DIRS, ROOT, Refusal, embed, psql
from db.data import PullSummary, fetch
from db.data.blizzard import BLIZZARD
from db.data.blizzard import heroes as blizzard_heroes
from db.data.blizzard import meta as blizzard_meta
from db.data.fetch import Log
from db.data.wiki import WIKI
from db.data.wiki import heroes as wiki_heroes
from db.data.wiki import maps as wiki_maps
from db.data.wiki import matchups as wiki_matchups
from db.data.wiki import patches as wiki_patches
from db.data.wiki import playstyles as wiki_playstyles
from db.data.wiki import seasons as wiki_seasons
from db.data.wiki import synergies as wiki_synergies
from db.data.wiki import terrain as wiki_terrain
from db.mcp.server import Tool, audited
from db.psql import schema
from inference import catalog, derive, engine, reach, tune
from inference.result import Result
from ui.facts import board_facts, compute, tables
from ui.facts.draft import Draft

# A tool's answer: its text, and the same as a JSON object for a structured reply.
Reply = tuple[str, Mapping[str, Any]]


class Context:
    """Where a tool call lands: the database, the page caches and the log."""

    def __init__(
            self, dsn: str | None = None, caches: Mapping[str, str] | None = None,
            log: Log | None = None) -> None:
        self._dsn = dsn
        self.caches: dict[str, str] = dict(CACHE_DIRS, **(caches or {}))
        self.log: Log = log or fetch.to_stderr

    @property
    def dsn(self) -> str:
        if self._dsn is None:
            self._dsn = psql.default_dsn()
        return self._dsn

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn)

    def cache(self, source: str) -> str | None:
        return fetch.prepare_cache(self.caches[source])


# --- the registry ----------------------------------------------------------

# A tool's function: its context first, its arguments by name.
ToolFn = Callable[..., Reply]


@dataclass(frozen=True)
class ToolSpec:
    """A tool as registered: its name, description, JSON schema and function,
    and for a pull, the source whose page cache it reads."""
    name: str
    description: str
    schema: dict[str, Any]
    fn: ToolFn
    source: str | None = None


class NoSuchToolError(KeyError):
    """No registered tool has the name a caller asked for - told apart from a
    KeyError raised inside a tool, which is the server's fault."""

    def __str__(self) -> str:
        return "no tool named %r" % self.args[0]


class Registry:
    """The tools in the order they were registered, each name once. The pulls
    are the tools that name a source, in the same order."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def add(self, spec: ToolSpec) -> None:
        # a name registered twice is a programmer's error, raised at import
        if spec.name in self._specs:
            raise ValueError("tool %r is registered twice" % spec.name)
        self._specs[spec.name] = spec

    def tool(
            self, name: str, description: str, properties: dict[str, Any] | None = None,
            required: Sequence[str] = (), *,
            source: str | None = None) -> Callable[[ToolFn], ToolFn]:
        """The decorator that registers a function as a tool: its arguments
        are the named properties, the required ones must be present, and no
        other is accepted."""
        # json_schema, not schema: db.psql.schema is imported above
        json_schema = {"type": "object", "properties": properties or {},
                       "required": list(required), "additionalProperties": False}

        def decorate(fn: ToolFn) -> ToolFn:
            self.add(ToolSpec(name, description, json_schema, fn, source))
            return fn
        return decorate

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    def names(self) -> list[str]:
        return list(self._specs)

    def get(self, name: str) -> ToolSpec:
        """The tool of that name; a name no tool has is a NoSuchToolError."""
        try:
            return self._specs[name]
        except KeyError:
            raise NoSuchToolError(name) from None

    def pulls(self) -> list[ToolSpec]:
        """The tools that pull a source, in registration order: the
        dependency order sync_all runs them in."""
        return [spec for spec in self if spec.source is not None]


REGISTRY = Registry()
tool = REGISTRY.tool


def _bind(ctx: Context, spec: ToolSpec) -> Tool:
    """One registered tool bound to a context: the wrapper that checks every
    call against the tool's schema, over the function with ctx filled in."""
    return Tool(spec.name, spec.description, spec.schema, functools.partial(spec.fn, ctx))


def build(ctx: Context) -> list[Tool]:
    """Bind every registered tool to a context -> [Tool]."""
    return [_bind(ctx, spec) for spec in REGISTRY]


def run_tool(ctx: Context, name: str, /, **arguments: Any) -> tuple[str, Any]:
    """Call a registered tool by name, in-process - the refresher's, the
    shell's and the board's path. The call is validated against the tool's
    schema and audited, like a call through either door: a call the schema
    refuses is a Refusal, and a name no tool has is a NoSuchToolError, which
    reaches no tool and leaves no audit line. The name is positional only, so
    a tool argument called `name` (add_strategy has one) reaches the tool
    instead of colliding here."""
    tool = _bind(ctx, REGISTRY.get(name))
    return audited(name, arguments, lambda: tool(arguments), "in-process")


REFRESH = {"refresh": {"type": "boolean",
                       "description": "fetch every page again instead of reading"
                                      " the cache; a page that fails to fetch keeps"
                                      " its cached copy"}}


def _summary(title: str, summary: PullSummary) -> Reply:
    """A pull's reply: its headline over one line per count (the tables it
    wrote left out), and the summary itself as the payload."""
    lines = [title]
    for key, value in summary.items():
        if key == "tables":
            continue
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value) or "-"
        lines.append("  %-16s %s" % (key, value))
    return "\n".join(lines), dict(summary)


# --- pull, clean, store: one tool per source and domain --------------------

@tool("list_sources", "The sources the data layer pulls from, what each"
      " supplies, and how many pages its cache holds.")
def list_sources(ctx: Context) -> Reply:
    rows: list[dict[str, Any]] = []
    for source in (BLIZZARD, WIKI):
        path = ctx.caches[source.code]
        cached = len(os.listdir(path)) if os.path.isdir(path) else 0
        rows.append({"code": source.code, "name": source.name, "url": source.url,
                     "cached_pages": cached,
                     "tools": [s.name for s in REGISTRY.pulls() if s.source == source.code]})
    text = "\n".join("%-12s %-24s %4d cached pages  tools: %s"
                     % (r["code"], r["name"], r["cached_pages"],
                        ", ".join(r["tools"])) for r in rows)
    return text, {"sources": rows}


# A pull's own function: the source module's run(connection, pull, **options).
PullFn = Callable[..., PullSummary]


def _pull(ctx: Context, source: str, fn: PullFn, refresh: bool, **options: bool) -> PullSummary:
    """One pull against the database, reading through the source's page cache
    and logging to the context's log -> the summary its run() returns."""
    pull = fetch.PullContext(ctx.cache(source), log=ctx.log)
    # refresh: every cached page counts as stale and is fetched again; the
    # cached copy survives a failed fetch (see db.data.fetch.keep_stale)
    with fetch.max_age(0 if refresh else None), ctx.connect() as cx:
        return fn(cx, pull, **options)


def pull_tool(
        name: str, description: str, *, source: str, stored: str,
        properties: dict[str, Any] = REFRESH) -> Callable[[PullFn], PullFn]:
    """The decorator that registers a pull as a tool: the tool runs the
    function against `source`'s page cache, refreshing every page when asked,
    and replies under the headline "<name>: <stored>". The function is
    returned as it is."""
    def decorate(fn: PullFn) -> PullFn:
        def call(ctx: Context, refresh: bool = False, **options: bool) -> Reply:
            return _summary("%s: %s" % (name, stored), _pull(ctx, source, fn, refresh, **options))
        tool(name, description, properties, source=source)(call)
        return fn
    return decorate


# Registration order is dependency order, and sync_all runs the pulls in it:
# heroes before what links to them, maps and their stages before the terrain
# counted for them, seasons and patches before the pull that stamps a
# snapshot (rates). Each body looks its module's run up when it is called, so
# a test that replaces the run replaces the pull's.

@pull_tool("pull_heroes", "Blizzard's roster: heroes, roles, subroles, portraits,"
           " ability and perk text. Run first - everything links to heroes.",
           source="blizzard", stored="roster stored")
def pull_heroes(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return blizzard_heroes.run(connection, pull)


@pull_tool("pull_kits", "The wiki's Cargo ability table and hero articles: weapons"
           " and firing configs, every published number, ability kinds and"
           " keywords, hero health pools. Run after pull_heroes.",
           source="wiki", stored="kit numbers stored",
           properties=dict(REFRESH, supplement={
               "type": "boolean",
               "description": "also read each hero article for the flags Cargo lacks"
                              " (default true)"}))
def pull_kits(
        connection: psycopg.Connection, pull: fetch.PullContext,
        supplement: bool = True) -> PullSummary:
    return wiki_heroes.run(connection, pull, supplement=supplement)


@pull_tool("pull_maps", "The wiki's map pool: maps, game modes, playable"
           " combinations, and each map's stages: a Control map's three, a Flashpoint"
           " map's five points, a Hybrid map's two phases, an Escort map's stretches"
           " where its article names them. Push maps have none.",
           source="wiki", stored="map pool stored")
def pull_maps(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_maps.run(connection, pull)


@pull_tool("pull_terrain", "The wiki's map articles: per map, the mentions of each"
           " terrain feature (chokes, interiors, high_ground, flanks, sightlines,"
           " open_ground, hazards, cover) and the mentions per thousand words; the"
           " same per stage, where the article has text about the stage. Reloads"
           " map_terrain and stage_terrain whole. Run after pull_maps: a stage must"
           " exist before its terrain.", source="wiki", stored="terrain stored")
def pull_terrain(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_terrain.run(connection, pull)


@pull_tool("pull_patches", "The wiki's patch list, so every rates snapshot can say"
           " which game version it measured.", source="wiki", stored="patches stored")
def pull_patches(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_patches.run(connection, pull)


@pull_tool("pull_seasons", "The wiki's Season pages: every season that has started,"
           " with its start date. Restamps every rates snapshot with its season. Run"
           " before pull_rates.", source="wiki", stored="seasons stored")
def pull_seasons(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_seasons.run(connection, pull)


@pull_tool("pull_rates", "Blizzard's win/pick/ban rates as a NEW dated snapshot,"
           " by rank tier and by map (Competitive Role Queue - the page offers no"
           " Open Queue - console, Americas). Slow when uncached: ~40 pages, 5s apart.",
           source="blizzard", stored="snapshot stored")
def pull_rates(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return blizzard_meta.run(connection, pull)


@pull_tool("pull_playstyles", "The wiki's team-composition page: which playstyle"
           " (dive, brawl, poke) each hero belongs to.", source="wiki", stored="styles stored")
def pull_playstyles(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_playstyles.run(connection, pull)


@pull_tool("pull_synergies", "The Synergy section of every hero's wiki article: one"
           " row per pair, score 2 when both articles name each other, 1 when one"
           " does, the wiki's advice as the note. Run after pull_heroes.",
           source="wiki", stored="pairs stored")
def pull_synergies(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_synergies.run(connection, pull)


@pull_tool("pull_counters", "The Match-Up column of every hero's wiki article: each"
           " written cell read as a verdict and stored as a directed edge, one row ="
           " countered_by answers hero. Reloads the table whole. Run after"
           " pull_heroes.", source="wiki", stored="counters stored")
def pull_counters(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_matchups.run(connection, pull)

@tool("load_authored", "Store the one input a user writes: the mirror of the"
      " strategies in inference/strategies/. A whole-truth reload.")
def load_authored(ctx: Context) -> Reply:
    with ctx.connect() as cx:
        cat = catalog.load()
        if any(h.pending for h in cat) and derive.available():
            # drafts on a host with the CLI: the engine derives them now
            ctx.log(derive.derive_rendered(derive.derive(log=ctx.log)))
            cat = catalog.load()
        summary = catalog.mirror(cx, cat)
        pending = [h.id for h in cat if h.pending]
        if pending:
            summary["pending"] = len(pending)
    text = "load_authored: strategies " + ", ".join(
        "%s=%s" % (k, v) for k, v in summary.items() if k != "tables")
    # the payload still names what was loaded, so a caller reads it the same way
    return text, {"strategies": summary}


@tool("sync_all", "Every pull_* tool in dependency order, then the strategies"
      " mirror, then the CSV mirror. On a populated database this is an"
      " update: entities refresh in place, rates append a snapshot.", REFRESH)
def sync_all(ctx: Context, refresh: bool = False) -> Reply:
    results: dict[str, Any] = {}
    pulls = REGISTRY.pulls()
    for spec in pulls:
        ctx.log("=== %s ===" % spec.name)
        results[spec.name] = run_tool(ctx, spec.name, refresh=refresh)[1]
    ctx.log("=== load_authored ===")
    results["load_authored"] = run_tool(ctx, "load_authored")[1]
    results["export_csv"] = run_tool(ctx, "export_csv")[1]
    return "sync_all: %d pulls + strategies mirror + export done" % len(pulls), results


# --- the database's life ----------------------------------------------------

@tool("db_status", "Which database the tools are pointed at, its state (empty,"
      " stale, unfilled or current - what the containers wait on), its table and"
      " row counts, and the rates snapshots it holds.")
def db_status(ctx: Context) -> Reply:
    with ctx.connect() as cx:
        ready = schema.state(cx)
        tables = schema.table_count(cx)
        counts: dict[str, int] = {}
        snaps: list[dict[str, Any]] = []
        if tables:
            for t in ("heroes", "abilities", "maps", "hero_meta", "map_meta",
                      "counters", "synergies", "strategies"):
                if psql.scalar(cx.execute("select to_regclass(%s)", (t,))):
                    counts[t] = psql.scalar(cx.execute(
                        SQL("select count(*) from {}").format(psql.identifier(t))))
            if "heroes" in counts:
                counts["announced"] = psql.scalar(cx.execute(
                    "select count(*) from heroes where status = 'announced'"))
            if psql.scalar(cx.execute("select to_regclass('meta_snapshots')")):
                snaps = [{"id": i, "captured": str(c), "queue": q, "source": s}
                         for i, c, q, s in cx.execute("""
                    select ms.snapshot_id, ms.captured_at::date, ms.queue,
                           src.code from meta_snapshots ms
                    join sources src using(source_id) order by 1""")]
        missing = schema.pending(cx) if tables else []
    dsn = re.sub(r"//[^@/]*@", "//", ctx.dsn)
    newest = max((s["captured"] for s in snaps), default=None)
    text = "database: %s\nstate: %s\ntables: %d\n%s\nsnapshots: %d%s%s" % (
        dsn, ready, tables, "\n".join("  %-16s %d" % kv for kv in counts.items()),
        len(snaps), ", newest capture %s" % newest if newest else "",
        "\nPENDING MIGRATIONS (rebuild): %s" % ", ".join(missing)
        if missing else "")
    return text, {"dsn": dsn, "state": ready, "table_count": tables, "counts": counts,
                  "snapshots": snaps, "newest_capture": newest,
                  "pending_migrations": missing}


@tool("db_init", "Apply the migrations to an EMPTY database (schema only;"
      " sync_all fills it). Refuses a database that already has tables.")
def db_init(ctx: Context) -> Reply:
    with ctx.connect() as cx:
        if schema.table_count(cx):
            raise Refusal("the database already has tables; db_rebuild"
                          " starts over")
        schema.apply(cx, schema.read_migrations(), quiet=True)
        n = schema.table_count(cx)
    return "db_init: %d tables, no data" % n, {"table_count": n}


@tool("db_migrate", "Apply the migrations the ledger has not recorded, in"
      " place: a populated database catching up with the files without a"
      " rebuild. Nothing pending is not an error.")
def db_migrate(ctx: Context) -> Reply:
    with ctx.connect() as cx:
        names = schema.pending(cx)
        todo = [m for m in schema.read_migrations() if m.name in names]
        schema.apply(cx, todo, quiet=True)
    return ("db_migrate: applied %d migration(s)%s"
            % (len(names), ": " + ", ".join(names) if names else ""), {"applied": names})


@tool("db_rebuild", "Drop everything, reapply the migrations and run"
      " sync_all.", REFRESH)
def db_rebuild(ctx: Context, refresh: bool = False) -> Reply:
    with ctx.connect() as cx:
        dropped = schema.rebuild(cx, quiet=True)
    results = run_tool(ctx, "sync_all", refresh=refresh)[1]
    return ("db_rebuild: dropped %d tables, rebuilt" % len(dropped),
            {"dropped": len(dropped), "sync": results})


@tool("export_csv", "Refresh db/raw/*.csv: one CSV per table.")
def export_csv(ctx: Context) -> Reply:
    with ctx.connect() as cx:
        counts = psql.export(cx)
    return ("export_csv: %d tables mirrored to db/raw" % len(counts),
            {"row_counts": counts})


def write_tool_docs(path: str | None = None) -> str:
    """The tool reference - every registered tool, its description and its
    arguments - generated into docs/mcp.md between its markers."""
    path = path or os.path.join(ROOT, "docs", "mcp.md")
    out = ["%d tools, in the order the server lists them. Regenerated by"
           " `python -m db.mcp call db_docs`." % len(REGISTRY), "",
           "| tool | does | arguments |", "| --- | --- | --- |"]
    for entry in REGISTRY:
        required = set(entry.schema.get("required", ()))
        args = []
        for arg, spec in entry.schema.get("properties", {}).items():
            kind = spec.get("type") or "any"
            if "enum" in spec:
                kind = " \\| ".join(str(v) for v in spec["enum"])
            args.append("`%s`%s (%s)%s" % (arg, " *required*" if arg in required else "",
                                            kind, ": " + spec["description"].replace("|", "\\|")
                                            if spec.get("description") else ""))
        out.append("| `%s` | %s | %s |" % (entry.name, entry.description.replace("|", "\\|"),
                                          "<br>".join(args) if args else "none"))
    embed(path, "tools", "\n".join(out))
    return path


@tool("db_docs", "Regenerate the generated sections of the docs: the ERD and data"
      " dictionary in docs/db.md from the live schema, the catalog and vocabulary in"
      " docs/inference.md from the strategies files, the tool reference in docs/mcp.md.")
def db_docs(ctx: Context) -> Reply:
    with ctx.connect() as cx:
        text = schema.generate_docs(cx)
    paths = [p for p in (catalog.write_docs(catalog.load()), write_tool_docs()) if p]
    if catalog.strategies_dir() != catalog.SHIPPED_DIR:
        ctx.log("db_docs: another playbook folder is in force (%s); the catalog section"
                " of docs/inference.md was left as the shipped playbook" % catalog.strategies_dir())
    return text + "; wrote " + ", ".join(os.path.relpath(p, ROOT) for p in paths), {}


READ_ONLY_STARTS = ("select", "with", "explain", "show", "table", "values")
# Names that reach the file system or the network from inside SQL, refused
# before the database sees them. The reader role below is the second guard.
SQL_DENIED = re.compile(r"\b(pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|"
                        r"lo_import|lo_export|lo_get|lo_put|pg_execute_server_program|"
                        r"dblink|pg_sleep|pg_terminate_backend|pg_cancel_backend|"
                        r"set_config|query_to_xml|query_to_xmlschema|query_to_xml_and_xmlschema|"
                        r"cursor_to_xml|cursor_to_xmlschema|pg_reload_conf)\b", re.I)
READER_ROLE = "matrix_reader"          # a login of its own (migration 012): SELECT, nothing else
MAX_SQL_CHARS = 20000                  # what one statement may run to
MAX_ROWS = 200                         # rows one reply carries
MAX_QUERY_BYTES = 1 << 20              # what one query may return
MAX_CELL = 2000                        # characters per cell
# What Postgres says of a statement the caller can fix: a syntax error, an
# unknown table, column or function, a privilege the reader lacks, a bad cast,
# the ten-second timeout.
QUERY_REFUSED = (psycopg.errors.ProgrammingError, psycopg.errors.DataError,
                 psycopg.errors.QueryCanceled)

# A cell as JSON carries it.
type Cell = str | int | float | bool | list[Cell] | dict[str, Cell] | None


def reader_dsn(dsn: str) -> str:
    """The same database, connected as the reader: a non-superuser session
    cannot SET ROLE back up."""
    parts = psycopg.conninfo.conninfo_to_dict(dsn)
    parts["user"] = READER_ROLE
    parts["password"] = READER_ROLE
    return psycopg.conninfo.make_conninfo("", **parts)


@tool("query", "Run read-only SQL against the database (SELECT/WITH only,"
      " one statement, first %d rows). Every table is documented in"
      " the data dictionary in docs/db.md." % MAX_ROWS,
      {"sql": {"type": "string", "description": "the statement"}}, ["sql"])
def query(ctx: Context, sql: str) -> Reply:
    columns, rows = _read_only(ctx.dsn, _checked_sql(sql))
    kept, truncated = _page(rows)
    text = "\t".join(columns) + "\n" + "\n".join(
        "\t".join(str(v) for v in row) for row in kept) if columns else "(no rows)"
    if truncated:
        text += "\n(truncated: %d rows shown)" % len(kept)
    return text, {"columns": columns, "rows": kept, "truncated": truncated}


def _checked_sql(sql: str) -> str:
    """The statement a caller sent, once it is one read-only statement no
    longer than MAX_SQL_CHARS that names no file or server function -> its
    body, the trailing semicolon dropped. Anything else is a Refusal, before
    a connection is opened."""
    body = sql.strip().rstrip(";").strip()
    if ";" in body or not body.lower().startswith(READ_ONLY_STARTS):
        raise Refusal("query is read-only: one SELECT/WITH statement")
    if len(body) > MAX_SQL_CHARS:
        raise Refusal("query too long")
    denied = SQL_DENIED.search(body)
    if denied:
        raise Refusal("query refuses %r: SQL here reads tables, not files or servers"
                      % denied.group(1))
    return body


def _read_only(dsn: str, body: str) -> tuple[list[str], list[tuple[object, ...]]]:
    """One checked statement, run as the reader in a read-only transaction
    under the timeout -> (its column names, its first MAX_ROWS + 1 rows: one
    more than a reply carries, so _page can tell the rest were cut). A
    statement Postgres rejects is the caller's to fix, like the checks before
    it: a Refusal in Postgres's own words. A connection that fails is the
    server's fault and is not caught."""
    with psycopg.connect(reader_dsn(dsn)) as cx:
        cx.execute("SET TRANSACTION READ ONLY")
        cx.execute("SET LOCAL statement_timeout = '10s'")
        try:
            cursor = cx.execute(body)
            columns = [d.name for d in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(MAX_ROWS + 1)
        except QUERY_REFUSED as error:
            raise Refusal("query: %s" % str(error).partition("\n")[0]) from error
        cx.rollback()
    return columns, rows


def _page(rows: Sequence[Sequence[object]]) -> tuple[list[list[Cell]], bool]:
    """The rows a reply carries -> (at most MAX_ROWS of them, each cell as
    JSON carries it and a string cut to MAX_CELL characters, until the
    MAX_QUERY_BYTES budget is spent; whether any row was left out - past
    MAX_ROWS or past the budget)."""
    kept: list[list[Cell]] = []
    size = 0
    for row in rows[:MAX_ROWS]:
        cells = [_cut(_cell(value)) for value in row]
        size += sum(len(str(cell)) for cell in cells)
        if size > MAX_QUERY_BYTES:
            return kept, True
        kept.append(cells)
    return kept, len(rows) > MAX_ROWS


def _cut(cell: Cell) -> Cell:
    """A string cell cut to MAX_CELL characters, marked with an ellipsis."""
    if isinstance(cell, str) and len(cell) > MAX_CELL:
        return cell[:MAX_CELL] + "…"
    return cell


def _cell(value: object) -> Cell:
    """A cell as JSON carries it: a date or a time as ISO text; a list, tuple
    or dict cell by cell, so an array or JSONB column arrives as JSON; a
    string, number, boolean or None as it is; anything else through str()."""
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_cell(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _cell(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)

# --- the board: UI layer and inference layer through the same door -------

BOARD = {
    "map": {"type": "string", "description": "map name (any spelling)"},
    "red": {"type": "array", "items": {"type": "string"},
            "description": "the enemy team's revealed heroes"},
    "blue": {"type": "array", "items": {"type": "string"},
             "description": "your team's locked heroes"},
    "bans": {"type": "array", "items": {"type": "string"},
             "description": "the match's bans, up to five (each team's two and"
                            " the lobby's), all optional; neither team can"
                            " pick them"},
    "side": {"type": "string", "enum": ["attack", "defense", ""],
             "description": "blue's side on an Escort or Hybrid map (red gets"
                            " the other); ignored on Control, Push, Flashpoint"},
}

# A board tool's function: its context, the Draft, then its own arguments.
BoardFn = Callable[..., Reply]


def _names(value: object) -> tuple[str, ...]:
    """An array of names the schema admitted, as the tuple a Draft holds."""
    return tuple(str(v) for v in value) if isinstance(value, (list, tuple)) else ()


def _draft(arguments: dict[str, object]) -> Draft:
    """The board BOARD's five arguments name, taken out of the call's
    arguments: the lists as tuples, and what the call left out empty."""
    map_name = arguments.pop("map", None)
    return Draft(map_name=None if map_name is None else str(map_name),
                 red=_names(arguments.pop("red", ())),
                 blue=_names(arguments.pop("blue", ())),
                 bans=_names(arguments.pop("bans", ())),
                 side=str(arguments.pop("side", "")))


def board_tool(
        name: str, description: str, properties: dict[str, Any] | None = None,
        required: Sequence[str] = ()) -> Callable[[BoardFn], BoardFn]:
    """The decorator that registers a board tool: BOARD's five properties
    first, then its own, and the function called with the one Draft they name
    and the rest of the arguments. The function is returned as it is."""
    def decorate(fn: BoardFn) -> BoardFn:
        def call(ctx: Context, **arguments: object) -> Reply:
            return fn(ctx, _draft(arguments), **arguments)
        tool(name, description, dict(BOARD, **(properties or {})), required)(call)
        return fn
    return decorate


@tool("roster", "Every hero with role, subrole, health pool, portrait and status"
      " (released, or announced with its release day - shown, never picked), plus"
      " the map pool with modes - the vocabulary the board tools accept.")
def roster(ctx: Context) -> Reply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    heroes: list[dict[str, Any]] = [{"name": h.name, "role": h.role, "subrole": h.subrole,
               "pool": h.pool, "portrait": h.portrait, "status": h.status,
               "release_date": str(h.release_date) if h.release_date else None}
              for h in world.heroes_by_role()]
    maps = [{"name": m.name, "mode": m.mode} for m in world.maps_sorted()]
    text = "\n".join("%-9s %-14s %s%s" % (h["role"], h["subrole"], h["name"],
                                          "" if h["status"] == "released" else
                                          "  (announced%s)" % (", releases " + h["release_date"]
                                                               if h["release_date"] else ""))
                     for h in heroes) + "\n\nmaps: " + ", ".join(
        "%s (%s)" % (m["name"], m["mode"]) for m in maps)
    return text, {"heroes": heroes, "maps": maps}


@board_tool("facts", "The UI LAYER: every fact the database holds about a board -"
            " independent facts per named hero and for the map, joint facts per"
            " team once it has picks (shape, effective HP, damage and healing"
            " floors, range, tempo, cohesion, coverage...), and matchup facts"
            " once both teams have picks. Numbered F1.. for citation.",
            {"format": {"type": "string", "enum": ["lines", "json"],
                        "description": "lines (default) or json"}})
def facts(ctx: Context, draft: Draft, format: str = "lines") -> Reply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    fs = board_facts.generate(world, draft)
    payload = fs.to_dict()
    text = fs.rendered() if format == "lines" else json.dumps(payload)
    return text, payload


COMPACT_TERMS = 15        # the heaviest terms a compact reply carries


@board_tool("infer", "The INFERENCE LAYER: the optimal six for this board under"
            " the markdown strategies in inference/strategies/ (players assumed"
            " to play optimally). Locked blue picks are kept; the rest is"
            " searched. Returns the comp, per-pick reasons with fact citations,"
            " the strategy score breakdown, and alternatives.",
            {"top": {"type": "integer", "description": "alternatives to return (default 5)"},
             "pool": {"type": "integer",
                      "description": "candidates per role the search keeps (default 6)"},
             "compact": {"type": "boolean",
                         "description": "true: a reply small enough to carry under a"
                                        " playbook of hundreds. The structured payload"
                                        " then has its own keys: map, side, red, blue,"
                                        " score, terms (how many scoring terms the full"
                                        " reply carries), idle, silent (applying,"
                                        " metric not varying on this board) and largest"
                                        " (the %d heaviest terms, each an id and its"
                                        " weighted value)" % COMPACT_TERMS}})
def infer(ctx: Context, draft: Draft, top: int = 5, pool: int = 6,
          compact: bool = False) -> Reply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    pool, top = engine.clamp_search(pool, top)
    result = engine.infer(world, draft, pool_size=pool, top=top)
    if compact:
        return _compact(result)
    return result.rendered(), result.to_dict()


class WeightedTerm(TypedDict):
    """One scoring term of a compact reply: its strategy and its weighted part
    of the score."""
    id: str
    weighted: float


class CompactInfer(TypedDict):
    """A compact infer reply's payload: the board and the six with its score;
    how many scoring terms the full reply's contributions carry (terms), how
    many of them do not apply here (idle), the applying heuristics whose
    metric does not vary on this board (silent), and the heaviest terms."""
    map: str | None
    side: str
    red: list[str]
    blue: list[str]
    score: float
    terms: int
    idle: int
    silent: list[str]
    largest: list[WeightedTerm]


def _compact(result: Result) -> tuple[str, CompactInfer]:
    """A result small enough for a tool reply under a playbook of hundreds:
    the comp, the heuristics that apply but whose metric does not vary on this
    board, and the largest terms."""
    terms = result.contributions
    silent = sorted(c["id"] for c in terms if c.get("spread") is False)   # applying heuristics
    idle = sum(1 for c in terms if not c["applies"])
    largest = sorted((c for c in terms if c["weighted"]),
                     key=lambda c: (-abs(c["weighted"]), c["id"]))[:COMPACT_TERMS]
    payload = CompactInfer(
        map=result.map_name, side=result.side, red=list(result.red), blue=list(result.blue),
        score=round(result.score, 3), terms=len(terms), idle=idle, silent=silent,
        largest=[WeightedTerm(id=c["id"], weighted=round(c["weighted"], 4)) for c in largest])
    lines = result.rendered().split("\n")[:2]
    lines.append("  %d terms, %d not applying here" % (len(terms), idle))
    lines.append("  silent (applies, metric does not vary here): %s"
                 % (", ".join(silent) or "none"))
    lines += ["  %+.2f  %s" % (c["weighted"], c["id"]) for c in largest]
    return "\n".join(lines), payload


@board_tool("evaluate", "Score a FULL blue six against the strategies without"
            " searching: the breakdown per strategy, constraint violations, and"
            " how it ranks against the optimum.", required=["blue"])
def evaluate(ctx: Context, draft: Draft) -> Reply:
    # the schema requires blue: the engine takes a full six, so a call
    # without one never reaches the engine
    with ctx.connect() as cx:
        world = tables.load(cx)
    result = engine.evaluate(world, draft)
    return result.rendered(), result.to_dict()


@tool("reach", "Can the playbook ever pick this hero? A board that suits it - one of"
      " its maps, a red it answers, the match's bans spent on the rivals holding its seat - on"
      " which it is in the optimal six; with none, the closest it came. A hero that"
      " cannot be reached is one the facts or the strategies cannot see.",
      {"hero": {"type": "string", "description": "a released hero (any spelling)"}},
      ["hero"])
def reach_tool(ctx: Context, hero: str) -> Reply:   # _tool: inference.reach holds the bare name
    with ctx.connect() as cx:
        world = tables.load(cx)
    found = reach.search(world, hero)
    where = "%s%s against %s" % (found["map"], " " + found["side"] if found["side"] else "",
                                 ", ".join(found["red"]) or "the likely six")
    if found["bans"] is None:
        return ("%s is never the optimal pick, even with every ban; closest on %s, %.2f behind"
                % (found["hero"], where, found["gap"])), found
    return ("%s is optimal on %s%s: %s" % (
        found["hero"], where,
        ", with %s banned" % ", ".join(found["banned"]) if found["banned"] else "",
        ", ".join(found["six"]))), found


@board_tool("board", "The whole board at any stage of the draft (no map, a map, a side,"
            " bans, red's picks as they reveal): blue's optimal six as the best counter"
            " to red's selection - to their likely six until they reveal a pick"
            " (blue's own picks never constrain it), red's best"
            " counter to yours, both current comps scored on those scales, your picks"
            " against red's best counter, your locked picks with the empty slots filled,"
            " the fight odds (each seat's share of its own optimal, and the two against"
            " each other), the game plan in prose, the shapes the queue and the"
            " playbook's limits allow, and red's likely six"
            " from the data alone (a two-two-two from the map's pick rates and the"
            " wiki's synergies, past the bans; static for the board, no strategy read).",
            {"pool": {"type": "integer",
                      "description": "candidates per role the search keeps (default 6)"},
             "weights": {"type": "object",
                         "description": "{heuristic id: 0..10} - weights to score this"
                                        " board under instead of the files' (the playbook"
                                        " tab's sliders); the files are untouched"}})
def board(ctx: Context, draft: Draft, pool: int = 6,
          weights: Mapping[str, object] | None = None) -> Reply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    pool, _ = engine.clamp_search(pool)
    brief = engine.Brief(pool_size=pool, weights=catalog.parse_weights(weights or {}))
    b = engine.board(world, draft, brief=brief)
    return b.rendered(), b.to_dict()

@tool("strategies", "The inference layer's catalog - STRATEGIES = CONSTRAINTS ∪ HEURISTICS"
      " ∪ ASSUMPTIONS: every markdown strategy with its kind (constraint, heuristic or"
      " assumption), a constraint's form (limit, scored, draft), metric, direction, weight"
      " and expressions.")
def strategies(ctx: Context) -> Reply:
    cat = catalog.load()
    pending = [h.id for h in cat if h.pending]
    text = catalog.catalog_rendered(cat)
    if catalog.strategies_dir() != catalog.SHIPPED_DIR:
        text = "playbook in force: %s (the shipped one is %s)\n\n%s" % (
            os.path.relpath(catalog.strategies_dir(), ROOT),
            os.path.relpath(catalog.SHIPPED_DIR, ROOT), text)
    if pending:
        text += "\n\n%d draft(s) awaiting /strategy: %s" % (len(pending), ", ".join(pending))
    return text, {"strategies": [h.to_dict() for h in cat], "pending": pending}


@tool("tune", "Change one strategy's frontmatter - its weight, a params dial, or"
      " a when/require/bonus/penalty expression - validated through the"
      " catalog before it is written, mirrored into the database, and logged"
      " with the reason in inference/strategies/tuning-log.md.",
      {"id": {"type": "string", "description": "the strategy's id (its filename)"},
       "field": {"type": "string", "description": "weight | direction | soft | when |"
                                                  " require | bonus | penalty | metric |"
                                                  " params.NAME"},
       "value": {"description": "the new value: a number, a boolean, or an expression"},
       "reason": {"type": "string", "description": "why, in a sentence"},
       "by": {"type": "string", "description": "who asked, for the log line (default"
                                              " claude-code-session; the board says so)"}},
      ["id", "field", "value", "reason"])
def tune_tool(      # _tool: inference.tune holds the bare name
        ctx: Context, id: str, field: str, value: object, reason: str,
        by: str = "claude-code-session") -> Reply:
    change = tune.tune(id, field, value, reason, by=str(by or "claude-code-session")[:40])
    _remirror(ctx)
    return "tuned %s: %s %s -> %s\n%s" % (change["id"], change["field"], change["old"],
                                         change["new"], change["line"]), change


@tool("metrics", "The vocabulary a strategy may reference: every metric key with its"
      " meaning - team.*, enemy.* (the same for the red side), matchup.*, map.*,"
      " world.* - and which are text. What /strategy reads to infer a heuristic's"
      " metric or a constraint's expression from prose.")
def metrics(ctx: Context) -> Reply:
    reg = compute.registry()
    numeric = {k: v for k, v in reg.items() if k not in compute.TEXT_METRICS}
    lines = ["%-32s %s%s" % (k, v, "  (text)" if k in compute.TEXT_METRICS else "")
             for k, v in reg.items() if not k.startswith("enemy.")]
    return "\n".join(lines), {"metrics": reg, "numeric": sorted(numeric),
                              "text": sorted(compute.TEXT_METRICS)}


STRATEGY_FIELDS = {
    "metric": {"type": "string", "description": "heuristics: a numeric key from `metrics`"},
    "direction": {"type": "string", "enum": ["maximize", "minimize"]},
    "weight": {"type": "number", "description": "0..10; 1-4 is the working range"},
    "when": {"type": "string", "description": "a guard expression; optional"},
    "require": {"type": "string", "description": "constraints: a limit expression"},
    "soft": {"type": "boolean",
             "description": "with require: charge `penalty` instead of discarding"},
    "bonus": {"type": "string",
              "description": "constraints: an expression added while `when` holds"},
    "penalty": {"type": "string",
                "description": "constraints: an expression (or a number with soft) subtracted"},
    "params": {"type": "object",
               "description": "NAME: number dials the expressions read as params.NAME"},
    "category": {"type": "string"},
}


def _remirror(ctx: Context) -> None:
    """A playbook write's database half: the strategies table reloaded from
    the files the write changed."""
    with ctx.connect() as cx:
        catalog.mirror(cx, catalog.load())


@tool("add_strategy", "Store a new strategy in inference/strategies/ from its name,"
      " kind and prose plus the frontmatter /strategy inferred - a heuristic's"
      " metric/direction/weight, or a constraint's require or when/bonus/penalty"
      " and params; an assumption is prose and needs nothing. The prose is three"
      " sentences at most. Validated through the"
      " catalog before the file exists, mirrored into the database, logged."
      " Left with nothing inferred it lands as a draft the solver ignores.",
      dict({"id": {"type": "string", "description": "lowercase-kebab, becomes the filename"},
            "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["constraint", "heuristic", "assumption"]},
            "body": {"type": "string", "description": "the prose: what it means and why"},
            "reason": {"type": "string", "description": "why it was added, in a sentence"}},
           **STRATEGY_FIELDS),
      ["id", "name", "kind", "body", "reason"])
def add_strategy(
        ctx: Context, id: str, name: str, kind: str, body: str, reason: str,
        **fields: Any) -> Reply:
    category = fields.pop("category", "general")
    fields.pop("kind", None)
    added = tune.add(id, name, kind, body, fields, reason, category=category)
    _remirror(ctx)
    note = ("\nstored as a DRAFT: the solver ignores it until /strategy infers its frontmatter"
            if added["form"] == "draft" else "")
    return "added %s as %s/%s -> %s\n%s%s" % (
        id, kind, added["form"], os.path.relpath(added["path"], ROOT), added["line"], note), added


@tool("infer_strategy", "Complete a draft (or rewrite a strategy's scoring): set several"
      " frontmatter fields at once - metric/direction/weight, when/require/bonus/"
      "penalty, params - validated as a whole, mirrored, logged as one line.",
      dict({"id": {"type": "string"},
            "reason": {"type": "string", "description": "how the fields follow from the prose"}},
           **STRATEGY_FIELDS),
      ["id", "reason"])
def infer_strategy(ctx: Context, id: str, reason: str, **fields: Any) -> Reply:
    done = tune.complete(id, fields, reason)
    _remirror(ctx)
    return "%s is now %s: %s\n%s" % (id, done["form"], ", ".join(
        "%s=%s" % kv for kv in done["set"].items()), done["line"]), done


@tool("derive_strategies", "Complete every draft (a strategy with only a name, a kind"
      " and prose) by asking Claude Code in print mode - the subscription, no key -"
      " for the frontmatter, validated through the catalog and logged. Runs where"
      " the claude CLI is signed in (the host); elsewhere drafts stay pending.",
      {"ids": {"type": "array", "items": {"type": "string"},
               "description": "which drafts (default: all)"}})
def derive_strategies(ctx: Context, ids: list[str] | None = None) -> Reply:
    result = derive.derive(ids, log=ctx.log)
    if result["derived"]:
        _remirror(ctx)
    return derive.derive_rendered(result), result


@tool("tuning_log", "The audit trail of every change to the strategies'"
      " frontmatter, newest last.",
      {"lines": {"type": "integer", "description": "how many (default 20)"}})
def tuning_log(ctx: Context, lines: int = 20) -> Reply:
    tail = tune.log_tail(lines)
    return "\n".join(tail) or "no tuning yet", {"lines": tail}


class StrategyResources:
    """The strategies files (and the tuning log), readable as MCP resources."""

    def list(self) -> list[dict[str, str]]:
        out = [{"uri": "strategy://" + h.id, "name": h.name,
                "description": "%s (%s)" % (h.kind, h.category),
                "mimeType": "text/markdown"} for h in catalog.load()]
        out.append({"uri": "strategy://tuning-log", "name": "tuning log",
                    "description": "every change to the strategies, with reasons",
                    "mimeType": "text/markdown"})
        return out

    def read(self, uri: str) -> dict[str, str]:
        hid = uri.replace("strategy://", "", 1)
        if hid == "tuning-log":
            return {"uri": uri, "mimeType": "text/markdown",
                    "text": "\n".join(tune.log_tail(1000)) or "no tuning yet"}
        for h in catalog.load():
            if h.id == hid:
                return {"uri": uri, "mimeType": "text/markdown", "text": h.raw}
        raise KeyError(uri)
