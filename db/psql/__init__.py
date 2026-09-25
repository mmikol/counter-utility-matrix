"""The database: where it is, and the small things every writer needs.

    default_dsn         where to read and write: $DATABASE_URL, or the
                        embedded cluster at db/psql/cluster once one is
                        built (pgserver starts it on first touch); it never
                        creates a cluster
    boot                the same for db_init and db_rebuild alone, creating
                        the embedded cluster when none is built
    NoDatabaseError     no DATABASE_URL and no embedded cluster to use; a
                        host without pgserver must set DATABASE_URL
    UNREACHABLE         the errors that mean the database is out of reach
    register_source     the `sources` row a page or a file becomes, upserted;
                        every table's rows carry its source_id
    identifier          a table or column name on its way into SQL text,
                        checked and returned as a psycopg.sql.Identifier
    lookup_ids          {value: id} over one column, each value as stored;
                        a name a source writes is matched through
                        db.data.names.index
    scalar              the one value a statement returns: a count, an
                        upsert's RETURNING
    now, current_patch, current_season
                        what a capture is stamped with
    SEASON_ON_DATE      the season live on a date: the one rule
                        current_season and pull_seasons' restamp share
    export              the CSV mirror under db/raw, and its mark (ExportMark)

    schema              the migrations applied and recorded in the ledger,
                        pending, rebuild, the generated docs, and state():
                        how ready the database is
    migrations/         NNN_name.sql, the schema as a sequence

Nothing here knows a particular source.
"""

import json
import os
import re
import threading
from datetime import UTC, datetime
from typing import Any, TypedDict

import psycopg
from psycopg.sql import SQL, Identifier

from db import DEFAULT_DB_DIR, RAW_DIR, Source

try:
    import pgserver
except ImportError:     # the image and CI filter it out of requirements.txt
    # the ignore is used where pgserver is installed (it ships types) and
    # unused in CI, where it is not
    pgserver = None     # type: ignore[assignment, unused-ignore]


class NoDatabaseError(Exception):
    """DATABASE_URL is unset and there is no embedded cluster to use: none is
    built at db/psql/cluster, or there is no pgserver to run one. Readers
    report it as the database out of reach; db_init and db_rebuild create
    the cluster through boot."""


# Every way the database can be out of reach, which a health endpoint reports
# as degraded: the connection and its queries (psycopg.Error); no DATABASE_URL
# and no cluster to use (NoDatabaseError, from default_dsn); the embedded
# cluster's files and socket (OSError); and pgserver's .handle_pids.json,
# left empty by a process killed while writing it (JSONDecodeError).
UNREACHABLE = (psycopg.Error, NoDatabaseError, OSError, json.JSONDecodeError)

# pgserver's own lock (fasteners, over fcntl) excludes other processes but
# not this process's threads, and get_server reads its instance cache before
# taking it, so two first touches from the threaded servers
# (inference/serve.py, ui/board.py) could interleave the read-truncate-write
# of the pid file. The first touch is serialised here. What remains: a
# .handle_pids.json left empty by a process killed mid-write makes the first
# touch in each later process raise JSONDecodeError, reported as degraded,
# and later touches in that process get pgserver's cached handle, with the
# process unregistered. The file is pgserver's and is not repaired here;
# removing it while no process uses the cluster clears the fault (pgserver
# 0.1.4's DiskList reads a missing file as []).
_FIRST_TOUCH = threading.Lock()


def default_dsn() -> str:
    """Where to read and write: $DATABASE_URL, or the embedded cluster at
    db/psql/cluster once one is built, started on first touch when it is not
    running. It never creates a cluster: with neither, NoDatabaseError, which
    the readers report as the database out of reach."""
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return explicit
    if not os.path.isfile(os.path.join(DEFAULT_DB_DIR, "PG_VERSION")):     # initdb's mark
        raise NoDatabaseError("no DATABASE_URL and no embedded cluster at db/psql/cluster:"
                              " set DATABASE_URL, or build one with db_rebuild")
    return _embedded()


def boot() -> str:
    """Where db_init and db_rebuild write: $DATABASE_URL, or the embedded
    cluster, created at db/psql/cluster when none is built. Only those two
    tools call it; every reader resolves through default_dsn."""
    return os.environ.get("DATABASE_URL") or _embedded()


def _embedded() -> str:
    """The embedded cluster's URI: pgserver starts the cluster when it is not
    running and runs initdb when it is not built. A host without pgserver
    has none to run: NoDatabaseError, naming DATABASE_URL."""
    if pgserver is None:
        raise NoDatabaseError("no DATABASE_URL and no embedded cluster: pgserver is not"
                              " installed here (the image and CI filter it out; linux/arm64"
                              " has no wheel) - set DATABASE_URL")
    with _FIRST_TOUCH:
        return pgserver.get_server(DEFAULT_DB_DIR).get_uri()


IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]*\Z")


def identifier(name: str) -> Identifier:
    """A table or column name on its way into SQL text: checked against the
    lowercase allowlist IDENTIFIER_RE, then quoted by psycopg. A query
    parameter carries a value, never a name, so every writer that names a
    table in the statement itself composes it with psycopg.sql through here.
    The names all come from a literal or from the catalog today, and this is
    what keeps it so."""
    if not IDENTIFIER_RE.match(name or ""):
        raise ValueError("not a SQL identifier: %r" % (name,))
    return Identifier(name)


def lookup_ids(
        cursor: psycopg.Cursor, table: str, key_column: str, id_column: str) -> dict[str, int]:
    """{value: id} over key_column, each value as stored. A code needs no
    fold: ability_kinds is seeded with db.ABILITY_KINDS, in lower case. A
    hero or map name a source writes is matched through
    db.data.names.index, which rekeys this by name_key."""
    return {
        row[0]: row[1]
        for row in cursor.execute(
            SQL("SELECT {}, {} FROM {}").format(
                identifier(key_column), identifier(id_column), identifier(table))
        ).fetchall()
    }


def scalar(cursor: psycopg.Cursor) -> Any:
    """The first column of the row the last statement returned - an aggregate,
    an upsert's RETURNING, a lookup by key - for a statement that always
    returns one. No row is a bug in the statement, and raises. The value is
    typed Any, as psycopg types a row's cells: the statement decides what the
    column holds."""
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("a statement that always returns a row returned none")
    return row[0]


def now() -> datetime:
    """One timestamp for a run."""
    return datetime.now(UTC)


def register_source(cursor: psycopg.Cursor, source: Source, cao: datetime) -> int:
    """Upsert one source and return its source_id. `cao` ("current as of")
    is refreshed every time a source is read."""
    cursor.execute(
        "INSERT INTO sources (code, name, url, cao) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
        " url = EXCLUDED.url, cao = EXCLUDED.cao RETURNING source_id",
        (source.code, source.name, source.url, cao),
    )
    return scalar(cursor)


def current_patch(cursor: psycopg.Cursor) -> int | None:
    """The most recent released patch, to stamp on a capture's snapshot."""
    row = cursor.execute(
        "SELECT patch_id FROM patches WHERE released <= CURRENT_DATE"
        " ORDER BY released DESC, patch_id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


# The season live on a date: the latest started by then, the later id on a
# tie. The date is SQL text - CURRENT_DATE, or a snapshot's
# ms.captured_at::date inside an UPDATE of meta_snapshots ms.
SEASON_ON_DATE = SQL(
    "SELECT season_id FROM seasons WHERE started <= {}"
    " ORDER BY started DESC, season_id DESC LIMIT 1")


def current_season(cursor: psycopg.Cursor) -> int | None:
    """The season live today (SEASON_ON_DATE). NULL until pull_seasons."""
    row = cursor.execute(SEASON_ON_DATE.format(SQL("CURRENT_DATE"))).fetchone()
    return row[0] if row else None


# --- the CSV mirror ------------------------------------------------------

def table_names(connection: psycopg.Connection) -> list[str]:
    """Every table in the database, read from the catalog rather than a
    hand-kept list, which drifts."""
    return [
        row[0]
        for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            " ORDER BY tablename"
        ).fetchall()
    ]


EXPORT_MARK = "EXPORT.json"


class ExportMark(TypedDict):
    """EXPORT.json: which database the mirror came from, when, and how many tables."""
    system_identifier: str
    exported_at: str
    table_count: int


def database_identity(connection: psycopg.Connection) -> str:
    """The cluster's own identifier (assigned at initdb): the same for every
    connection string that reaches the same database, different for every
    other database. What the mirror is stamped with."""
    return str(scalar(connection.execute(
        "SELECT system_identifier FROM pg_control_system()")))


def export(connection: psycopg.Connection, raw_dir: str = RAW_DIR) -> dict[str, int]:
    """Write one CSV per table, and EXPORT.json saying which database they
    came from and when. Any other CSV in `raw_dir` is removed, so the mirror
    holds the schema's tables and nothing else. Returns {table: row count},
    in table order."""
    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir)
    counts: dict[str, int] = {}
    for table in table_names(connection):
        path = os.path.join(raw_dir, table + ".csv")
        name = identifier(table)
        with open(path, "w", encoding="utf-8", newline="") as handle, connection.cursor().copy(
                SQL("COPY (SELECT * FROM {}) TO STDOUT WITH (FORMAT csv, HEADER true)")
                .format(name)) as copy:
            for chunk in copy:
                handle.write(bytes(chunk).decode("utf-8"))
        # Counted from the database, not by counting newlines: descriptions
        # embed newlines, which inflates the latter.
        counts[table] = scalar(connection.execute(SQL("SELECT count(*) FROM {}").format(name)))
    current = {table + ".csv" for table in counts}
    for stale in sorted(set(os.listdir(raw_dir)) - current):
        if stale.endswith(".csv"):
            os.remove(os.path.join(raw_dir, stale))
    with open(os.path.join(raw_dir, EXPORT_MARK), "w", encoding="utf-8") as handle:
        json.dump(ExportMark(system_identifier=database_identity(connection),
                             exported_at=now().isoformat(),
                             table_count=len(counts)), handle)
    return counts


def export_mark(raw_dir: str = RAW_DIR) -> ExportMark | None:
    """The mirror's EXPORT.json, or None before the first export."""
    path = os.path.join(raw_dir, EXPORT_MARK)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)

