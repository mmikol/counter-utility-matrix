"""The schema and the database's life: the migrations, the ledger, rebuild
and the generated documentation.

    read_migrations, apply   the files in order (Migration), and applying them
    applied, pending         the ledger against the files on disk
    state                    how ready the database is: empty, stale,
                             unfilled or current - the one definition every
                             reader of readiness asks
    drop_all, rebuild        drop every table and reapply every migration
    table_prose              a table's description: the -- block directly
                             above its CREATE TABLE
    generate_docs            the ERD and data dictionary of docs/db.md from
                             the live schema

    python -m db.psql.schema     print the state (the container entrypoint's
                                 probe); exit 1 when the database never answers
"""

import glob
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple

import psycopg
from psycopg.sql import SQL, Identifier

from db import ROOT, embed, psql

MIGRATIONS_DIR = os.path.join(ROOT, "db", "psql", "migrations")

# Which domain the data dictionary files a table under, keyed by the migration
# that last created it. A migration that creates no surviving table needs no
# entry; a table with none falls to "foundation".
DOC_DOMAIN = {
    "001_initial_schema.sql": "foundation", "002_heroes.sql": "HEROES",
    "003_maps.sql": "MAPS", "004_meta.sql": "META",
    "005_playbook.sql": "PLAYBOOK",
    "008_schema_migrations.sql": "foundation",
    "010_constraints_and_heuristics.sql": "INFERENCE",
    "020_map_terrain.sql": "MAPS", "021_stage_terrain.sql": "MAPS"}


class SchemaError(Exception):
    """No migrations where the schema should be."""


@dataclass(frozen=True)
class Migration:
    """One migration file: where it is and its SQL."""
    path: str
    sql: str

    @property
    def name(self) -> str:
        """The filename, as the ledger records it."""
        return os.path.basename(self.path)


def read_migrations() -> list[Migration]:
    """Every migration, in filename order."""
    migrations = []
    for path in sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql"))):
        with open(path, encoding="utf-8") as handle:
            migrations.append(Migration(path=path, sql=handle.read()))
    if not migrations:
        raise SchemaError("no migrations found in %s/" % MIGRATIONS_DIR)
    return migrations


def apply(
        connection: psycopg.Connection, migrations: Sequence[Migration],
        quiet: bool = False) -> None:
    """Run each migration and commit it, then record them all in the ledger
    once the ledger exists."""
    for migration in migrations:
        with connection.cursor() as cursor:
            cursor.execute(migration.sql)
        connection.commit()
        if not quiet:
            print("  applied %s" % migration.name)
    if psql.scalar(connection.execute("select to_regclass('schema_migrations')")):
        for migration in migrations:
            connection.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)"
                " ON CONFLICT (filename) DO NOTHING", (migration.name,))
        connection.commit()


def applied(connection: psycopg.Connection) -> list[str]:
    """The migration filenames the database recorded ([] before the ledger)."""
    if not psql.scalar(connection.execute("select to_regclass('schema_migrations')")):
        return []
    return [r[0] for r in connection.execute(
        "SELECT filename FROM schema_migrations ORDER BY filename")]


def pending(connection: psycopg.Connection) -> list[str]:
    """Migration files on disk the database has not recorded."""
    have = set(applied(connection))
    return [m.name for m in read_migrations() if m.name not in have]


def table_count(connection: psycopg.Connection) -> int:
    """How many tables the public schema holds."""
    return psql.scalar(connection.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"))


State = Literal["empty", "stale", "unfilled", "current"]


def state(connection: psycopg.Connection) -> State:
    """How ready the database is, named by its first unmet condition: empty
    (no tables), stale (a migration file the ledger has not recorded),
    unfilled (no heroes yet) or current. The one definition of ready: the
    container entrypoint asks it through main(), db_status reports it, the
    data container's /health carries it, and compose's healthcheck and
    orchestrator.py wait on it."""
    if table_count(connection) == 0:
        return "empty"
    if pending(connection):
        return "stale"
    if psql.scalar(connection.execute("SELECT count(*) FROM heroes")) == 0:
        return "unfilled"
    return "current"


def drop_all(connection: psycopg.Connection) -> list[str]:
    """Drop every table in the public schema, read from the catalog rather
    than the migration text so a table whose migration was deleted still
    goes. Returns the tables dropped."""
    tables = psql.table_names(connection)
    if tables:
        connection.execute(SQL("DROP TABLE IF EXISTS {} CASCADE").format(
            SQL(", ").join(Identifier(t) for t in tables)))
    connection.commit()
    return tables


def rebuild(connection: psycopg.Connection, quiet: bool = False) -> list[str]:
    """Drop everything and reapply every migration. Returns the tables dropped."""
    dropped = drop_all(connection)
    if dropped and not quiet:
        print("  dropped %d existing tables" % len(dropped))
    apply(connection, read_migrations(), quiet)
    return dropped


# --- generated documentation -------------------------------------------

CREATE_RE = re.compile(r"CREATE TABLE (\w+)")
COMMENT_RE = re.compile(r"^COMMENT ON TABLE (\w+) IS\s+'((?:[^']|'')*)'\s*;", re.M)


class ForeignKey(NamedTuple):
    """One foreign-key column: the child table and its column, and the parent
    table and column it references."""
    child: str
    column: str
    parent: str
    parent_column: str


class Column(NamedTuple):
    """One column as the data dictionary lists it: its name, its type and
    whether it admits NULL."""
    name: str
    data_type: str
    nullable: bool


class TableOrigin(NamedTuple):
    """Where the data dictionary files a table: the migration that last
    created it, and its prose."""
    migration: str
    prose: str


NO_ORIGIN = TableOrigin(migration="", prose="")      # a table no migration's text creates


def table_prose(text: str) -> dict[str, str]:
    """{table: its prose} for each CREATE TABLE in one migration's text. The
    prose is the block of lines starting with -- at column 0 directly above
    the CREATE TABLE line, each without its dashes, joined by spaces; a bare
    -- line is dropped, and any other line - a blank one, an indented comment
    - ends the block."""
    prose: dict[str, str] = {}
    block: list[str] = []
    for line in text.splitlines():
        if line.startswith("--"):
            block.append(line)
            continue
        created = CREATE_RE.match(line)
        if created:
            prose[created.group(1)] = " ".join(
                part.lstrip("-").strip() for part in block
                if part.strip() not in ("--", "")).strip()
        block = []
    return prose


def _migration_tables() -> dict[str, TableOrigin]:
    """{table: its origin} over every migration, a later COMMENT ON TABLE's
    text in place of the prose."""
    out: dict[str, TableOrigin] = {}
    for migration in read_migrations():
        for table, prose in table_prose(migration.sql).items():
            out[table] = TableOrigin(migration=migration.name, prose=prose)
        # a later COMMENT ON TABLE rewrites the prose: a statement in an applied
        # migration is never edited, so this is how a stored description is
        # corrected
        for m in COMMENT_RE.finditer(migration.sql):
            if m.group(1) in out:
                out[m.group(1)] = out[m.group(1)]._replace(
                    prose=m.group(2).replace("''", "'").strip())
    return out


def _foreign_keys(connection: psycopg.Connection) -> list[ForeignKey]:
    """Every foreign-key column in the public schema, one row per column of a
    composite key."""
    rows = connection.execute(
        "SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, af.attname,"
        " array_length(c.conkey, 1)"
        " FROM pg_constraint c"
        " JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true"
        " JOIN unnest(c.confkey) WITH ORDINALITY AS f(attnum, ord) ON f.ord = k.ord"
        " JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum"
        " JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = f.attnum"
        " WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace"
        " ORDER BY 1, 2, 5, 3, 4").fetchall()
    # a column under two keys (its own, and part of a composite) is documented
    # by the narrower one; the composite still draws its edge in the diagram
    return [ForeignKey(child=child, column=column, parent=parent, parent_column=parent_column)
            for child, column, parent, parent_column, _ in rows]


def _columns(connection: psycopg.Connection, table: str) -> list[Column]:
    """A table's columns in their order, as information_schema describes them."""
    rows = connection.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
        " WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,)).fetchall()
    return [Column(name=name, data_type=data_type, nullable=nullable == "YES")
            for name, data_type, nullable in rows]


def _edges(fks: list[ForeignKey], keep: Callable[[str], bool]) -> list[str]:
    """The mermaid lines for the id columns of the child tables `keep` accepts,
    one per edge, sorted; the edges to `sources` are left off."""
    seen: set[str] = set()
    for fk in fks:
        if fk.column.endswith("_id") and fk.parent != "sources" and keep(fk.child):
            seen.add('    %s ||--o{ %s : "%s"' % (fk.parent, fk.child, fk.column))
    return sorted(seen)


def _erd(tables: list[str], fks: list[ForeignKey], domain: dict[str, str]) -> str:
    """The ER diagrams: one per domain, then the whole database."""
    erd = [
        "Five domains. Three hold the data the sources are pulled for: which",
        "hero (HEROES), on which map (MAPS), performing how well (META).",
        "Every domain",
        "yields independent facts (a selection's own row) and dependent ones",
        "(the selection joined with others: map_meta is heroes ⋈ maps ⋈ meta,",
        "counters and synergies are heroes ⋈ heroes), and a join belongs to",
        "every domain it touches. The other two are the",
        "playbook's record: the judgements pulled from the wiki",
        "(PLAYBOOK) and the mirror of the strategies, the one input a user writes,",
        "that the inference layer solves with (INFERENCE). The composition is",
        "the argmax of the strategies - the constraints, heuristics and assumptions",
        "in inference/strategies/ - over the facts.",
        "",
        "```",
        "DATA        = HEROES ∪ MAPS ∪ META",
        "FACTS(D)    = INDEPENDENT(D) ∪ DEPENDENT(D)   for each domain D: its rows; its joins",
        "FACTS       = FACTS(HEROES) ∪ FACTS(MAPS) ∪ FACTS(META)",
        "STRATEGIES  = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS",
        "COMP        = ARGMAX[ STRATEGIES( FACTS ) ]",
        "```",
        "",
        "Every table but `sources` and `schema_migrations` also carries",
        "`source_id` -> `sources` and a `cao` timestamp. Those edges are left off -",
        "they would connect `sources` to %d tables and obscure everything else."
        % (len(tables) - 2),
        "",
    ]
    for d in ("HEROES", "MAPS", "META", "PLAYBOOK", "INFERENCE"):
        members = {t for t, owner in domain.items() if owner == d}
        erd += ["#### %s" % d, "", "```mermaid", "erDiagram",
                *_edges(fks, members.__contains__), "```", ""]
    erd += ["#### The whole database", "", "```mermaid", "erDiagram",
            *_edges(fks, lambda child: True), "```", ""]
    return "\n".join(erd)


def _dictionary(
        tables: list[str], columns: dict[str, list[Column]], fks: list[ForeignKey],
        domain: dict[str, str], origins: dict[str, TableOrigin]) -> str:
    """The data dictionary: each domain's tables, then every table's prose
    and columns, a foreign key naming the column it references."""
    references: dict[tuple[str, str], tuple[str, str]] = {}
    for fk in fks:
        references.setdefault((fk.child, fk.column), (fk.parent, fk.parent_column))
    dd = [
        "Generated from the live schema (`.venv/bin/python -m door.mcp call db_docs`).",
        "",
        "Two columns are omitted from the lists below: `source_id` (which source the",
        "row came from, see `sources`) and `cao` - \"current as of\", when that row",
        "was read. Every table but `sources` and `schema_migrations` carries both;",
        "`sources` carries `cao` alone and `schema_migrations` neither.",
        "",
        "| domain | tables |",
        "| --- | --- |",
    ]
    for d in ("foundation", "HEROES", "MAPS", "META", "PLAYBOOK", "INFERENCE"):
        dd.append("| **%s** | %s |" % (d, " · ".join(
            "`%s`" % t for t in tables if domain[t] == d)))
    dd.append("")
    for t in tables:
        fn, text = origins.get(t, NO_ORIGIN)
        dd += ["", "#### `%s`" % t, "", "*%s · `%s`*" % (domain[t], fn)]
        if text:
            dd += ["", text]
        dd += ["", "| column | type | null | references |", "| --- | --- | --- | --- |"]
        for column in columns[t]:
            if column.name in ("source_id", "cao"):
                continue
            r = references.get((t, column.name))
            dd.append("| `%s` | %s | %s | %s |" % (
                column.name, column.data_type, "yes" if column.nullable else "no",
                "`%s.%s`" % r if r else ""))
    return "\n".join(dd)


def generate_docs(connection: psycopg.Connection, path: str | None = None) -> str:
    """Write the ER diagrams and the data dictionary into docs/db.md (or
    `path`) from the live schema and the migrations' prose -> a summary line."""
    origins = _migration_tables()
    tables = psql.table_names(connection)
    columns = {t: _columns(connection, t) for t in tables}
    fks = _foreign_keys(connection)
    domain = {t: DOC_DOMAIN.get(origins.get(t, NO_ORIGIN).migration, "foundation") for t in tables}
    path = path or os.path.join(ROOT, "docs", "db.md")
    embed(path, "erd", _erd(tables, fks, domain))
    embed(path, "dictionary", _dictionary(tables, columns, fks, domain, origins))
    return "regenerated the schema sections of docs/db.md: %d tables" % len(tables)


# --- the entrypoint's probe ----------------------------------------------

CONNECT_TRIES = 60          # one a second: a database container starting up


def main() -> int:
    """Print the state for docker-entrypoint.sh, and the pending migrations
    on stderr when it is stale. A database that never answers is a line on
    stderr with the last try's error and exit 1, which ends the container
    under `set -e`."""
    last: psycopg.OperationalError | None = None
    for _ in range(CONNECT_TRIES):
        try:
            cx = psycopg.connect(psql.default_dsn())
            break
        except psycopg.OperationalError as error:
            last = error
            time.sleep(1)
    else:
        sys.stderr.write("the database never became reachable (%d tries, a second apart): %s\n"
                         % (CONNECT_TRIES, last))
        return 1
    with cx:
        found = state(cx)
        if found == "stale":
            sys.stderr.write("pending migrations: %s\n" % ", ".join(pending(cx)))
    print(found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
