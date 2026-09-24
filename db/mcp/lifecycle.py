"""The database's life: which database the tools point at and how ready it
is, creating, migrating and rebuilding it, the CSV mirror, the generated
docs, and read-only SQL against it.

query is the one tool that runs a caller's SQL. It is guarded twice: the
statement is checked before any connection opens (one read-only statement,
no function that reaches a file or a server), and it runs as the reader
role, which can SELECT and nothing else, in a read-only transaction under a
timeout. A reply carries at most MAX_ROWS rows within MAX_QUERY_BYTES, and
says when it left rows out.
"""

import datetime
import os
import re
from collections.abc import Mapping, Sequence
from typing import TypedDict

import psycopg
from psycopg.sql import SQL

from db import ROOT, Refusal, psql
from db.mcp.registry import REFRESH, Context, Registry, ToolReply
from db.psql import schema
from inference import catalog

TOOLS = Registry()
tool = TOOLS.tool


class Snapshot(TypedDict):
    """A rates snapshot as db_status lists it."""
    id: int
    captured: str
    queue: str
    source: str


class DbStatus(TypedDict):
    """db_status's payload: the database (its password left out), how ready
    it is, its tables and row counts, the rates snapshots it holds and the
    migrations it has not seen. The data container's /health reads it."""
    dsn: str
    state: str
    table_count: int
    counts: dict[str, int]
    snapshots: list[Snapshot]
    newest_capture: str | None
    pending_migrations: list[str]


# the tables db_status counts, where they exist
COUNTED = ("heroes", "abilities", "maps", "hero_meta", "map_meta", "counters", "synergies",
           "strategies")


@tool("db_status", "Which database the tools are pointed at, its state (empty,"
      " stale, unfilled or current - what the containers wait on), its table and"
      " row counts, and the rates snapshots it holds.")
def db_status(ctx: Context) -> ToolReply:
    with ctx.connect() as cx:
        ready = schema.state(cx)
        tables = schema.table_count(cx)
        counts: dict[str, int] = {}
        snaps: list[Snapshot] = []
        if tables:
            counts = _counts(cx)
            snaps = _snapshots(cx)
        missing = schema.pending(cx) if tables else []
    dsn = re.sub(r"//[^@/]*@", "//", ctx.dsn)
    newest = max((s["captured"] for s in snaps), default=None)
    text = "database: %s\nstate: %s\ntables: %d\n%s\nsnapshots: %d%s%s" % (
        dsn, ready, tables, "\n".join("  %-16s %d" % kv for kv in counts.items()),
        len(snaps), ", newest capture %s" % newest if newest else "",
        "\nPENDING MIGRATIONS (rebuild): %s" % ", ".join(missing)
        if missing else "")
    return ToolReply(text, DbStatus(
        dsn=dsn, state=ready, table_count=tables, counts=counts, snapshots=snaps,
        newest_capture=newest, pending_migrations=missing))


def _counts(cx: psycopg.Connection) -> dict[str, int]:
    """The rows in each counted table that exists, and the announced heroes."""
    counts: dict[str, int] = {}
    for t in COUNTED:
        if psql.scalar(cx.execute("select to_regclass(%s)", (t,))):
            counts[t] = psql.scalar(cx.execute(
                SQL("select count(*) from {}").format(psql.identifier(t))))
    if "heroes" in counts:
        counts["announced"] = psql.scalar(cx.execute(
            "select count(*) from heroes where status = 'announced'"))
    return counts


def _snapshots(cx: psycopg.Connection) -> list[Snapshot]:
    """Every rates snapshot, oldest first; none before the table exists."""
    if not psql.scalar(cx.execute("select to_regclass('meta_snapshots')")):
        return []
    return [Snapshot(id=i, captured=str(c), queue=q, source=s) for i, c, q, s in cx.execute("""
        select ms.snapshot_id, ms.captured_at::date, ms.queue,
               src.code from meta_snapshots ms
        join sources src using(source_id) order by 1""")]


@tool("db_init", "Apply the migrations to an EMPTY database (schema only;"
      " sync_all fills it). Refuses a database that already has tables.")
def db_init(ctx: Context) -> ToolReply:
    with ctx.connect() as cx:
        if schema.table_count(cx):
            raise Refusal("the database already has tables; db_rebuild"
                          " starts over")
        schema.apply(cx, schema.read_migrations(), quiet=True)
        n = schema.table_count(cx)
    return ToolReply("db_init: %d tables, no data" % n, {"table_count": n})


@tool("db_migrate", "Apply the migrations the ledger has not recorded, in"
      " place: a populated database catching up with the files without a"
      " rebuild. Nothing pending is not an error.")
def db_migrate(ctx: Context) -> ToolReply:
    with ctx.connect() as cx:
        names = schema.pending(cx)
        todo = [m for m in schema.read_migrations() if m.name in names]
        schema.apply(cx, todo, quiet=True)
    return ToolReply("db_migrate: applied %d migration(s)%s"
                     % (len(names), ": " + ", ".join(names) if names else ""),
                     {"applied": names})


@tool("db_rebuild", "Drop everything, reapply the migrations and run"
      " sync_all.", REFRESH)
def db_rebuild(ctx: Context, refresh: bool = False) -> ToolReply:
    with ctx.connect() as cx:
        dropped = schema.rebuild(cx, quiet=True)
    results = ctx.call("sync_all", refresh=refresh).data
    return ToolReply("db_rebuild: dropped %d tables, rebuilt" % len(dropped),
                     {"dropped": len(dropped), "sync": results})


@tool("export_csv", "Refresh db/raw/*.csv: one CSV per table.")
def export_csv(ctx: Context) -> ToolReply:
    with ctx.connect() as cx:
        counts = psql.export(cx)
    return ToolReply("export_csv: %d tables mirrored to db/raw" % len(counts),
                     {"row_counts": counts})


@tool("db_docs", "Regenerate the generated sections of the docs: the ERD and data"
      " dictionary in docs/db.md from the live schema, the catalog and vocabulary in"
      " docs/inference.md from the strategies files, the tool reference in docs/mcp.md.")
def db_docs(ctx: Context) -> ToolReply:
    with ctx.connect() as cx:
        text = schema.generate_docs(cx)
    paths = [p for p in (catalog.write_docs(catalog.load()), ctx.tools.write_docs()) if p]
    if catalog.strategies_dir() != catalog.SHIPPED_DIR:
        ctx.log("db_docs: another playbook folder is in force (%s); the catalog section"
                " of docs/inference.md was left as the shipped playbook" % catalog.strategies_dir())
    return ToolReply(text + "; wrote " + ", ".join(os.path.relpath(p, ROOT) for p in paths), {})


# --- read-only SQL ----------------------------------------------------------

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
def query(ctx: Context, sql: str) -> ToolReply:
    columns, rows = _read_only(ctx.dsn, _checked_sql(sql))
    kept, truncated = _page(rows)
    text = "\t".join(columns) + "\n" + "\n".join(
        "\t".join(str(v) for v in row) for row in kept) if columns else "(no rows)"
    if truncated:
        text += "\n(truncated: %d rows shown)" % len(kept)
    return ToolReply(text, {"columns": columns, "rows": kept, "truncated": truncated})


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
    if isinstance(value, Mapping):
        return {str(k): _cell(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
