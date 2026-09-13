"""The plumbing every layer shares: where the database is, how a page cache
is prepared, how provenance is recorded, and how the CSV mirror is refreshed.

Lifted out of the orchestrator so that the data layer (the MCP tools), the
conductor (orchestrator.py) and the loaders can all import it without a
cycle. Nothing here knows about a particular source or table.
"""

import argparse
import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# db/ pairs the schema with what it builds: data/db/migrations is the source,
# data/db/cluster the embedded Postgres built from it. The cluster is a build
# artifact - `rebuild` reproduces it from the migrations plus the page
# caches - so it is gitignored, not committed.
DEFAULT_DB_DIR = os.path.join(ROOT, "data", "db", "cluster")
RAW_DIR = os.path.join(ROOT, "data", "raw")
AUTHORED_DIR = os.path.join(ROOT, "data", "authored")

CACHE_DIRS = {
    "blizzard": os.path.join(ROOT, ".cache-blizzard"),
    "wiki": os.path.join(ROOT, ".cache-wiki"),
    "counterpick": os.path.join(ROOT, ".cache-counterpick"),
}


def build_parser(description, cache_dir=None):
    """A parser carrying the options every entry point accepts."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--dsn", help="Postgres DSN (default: $DATABASE_URL)")
    parser.add_argument(
        "--local-server",
        nargs="?",
        const="pgdata",
        help="run against an embedded Postgres in this directory (needs pgserver)",
    )
    parser.add_argument(
        "--no-export", action="store_true", help="skip refreshing data/raw/*.csv"
    )
    if cache_dir:
        parser.add_argument(
            "--cache",
            default=os.path.join(ROOT, cache_dir),
            help="page cache directory ('' to disable)",
        )
    return parser


def default_dsn(local_server=None, dsn=None):
    """Where to read and write: an explicit DSN, $DATABASE_URL, or the
    embedded cluster at data/db/cluster (pgserver runs initdb on first touch)."""
    explicit = dsn or os.environ.get("DATABASE_URL")
    if not local_server and explicit:
        return explicit
    import pgserver

    return pgserver.get_server(
        os.path.abspath(local_server or DEFAULT_DB_DIR)).get_uri()


def resolve_dsn(args):
    return default_dsn(getattr(args, "local_server", None),
                       getattr(args, "dsn", None))


def prepare_cache(path):
    """Create a page cache directory; '' or None disables caching."""
    if path and not os.path.isdir(path):
        os.makedirs(path)
    return path or None


def lookup_ids(cursor, table, name_column, id_column):
    """{lowercased name: id} for matching scraped names against loaded rows."""
    return {
        row[0].lower(): row[1]
        for row in cursor.execute(
            "SELECT %s, %s FROM %s" % (name_column, id_column, table)
        ).fetchall()
    }


def now():
    """One timestamp for a run."""
    return datetime.now(timezone.utc)


def register_source(cursor, source, cao):
    """Upsert one source and return its source_id. `cao` ("current as of")
    is refreshed every time a source is read."""
    code, name, url = source
    cursor.execute(
        "INSERT INTO sources (code, name, url, cao) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
        " url = EXCLUDED.url, cao = EXCLUDED.cao RETURNING source_id",
        (code, name, url, cao),
    )
    return cursor.fetchone()[0]


def current_patch(cursor):
    """The most recent released patch, to stamp on a capture's snapshot."""
    row = cursor.execute(
        "SELECT patch_id FROM patches WHERE released <= CURRENT_DATE"
        " ORDER BY released DESC, patch_id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def current_season(cursor):
    """The season live today, by latest start date. NULL until authored."""
    row = cursor.execute(
        "SELECT season_id FROM seasons WHERE started <= CURRENT_DATE"
        " ORDER BY started DESC, season_id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


# --- the CSV mirror ------------------------------------------------------

def table_names(connection):
    """Every table in the database, from the catalog - a hand-kept list
    drifts, and the table it forgets is exactly the stale one."""
    return [
        row[0]
        for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            " ORDER BY tablename"
        ).fetchall()
    ]


EXPORT_MARK = "EXPORT.json"


def database_identity(connection):
    """The cluster's own identifier (assigned at initdb): the same for every
    connection string that reaches the same database, different for every
    other database. What the mirror is stamped with."""
    return str(connection.execute(
        "SELECT system_identifier FROM pg_control_system()").fetchone()[0])


def export(connection, raw_dir=RAW_DIR):
    """Write one CSV per table, and EXPORT.json saying which database they
    came from and when. Returns [(table, row_count)]."""
    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir)
    counts = []
    for table in table_names(connection):
        path = os.path.join(raw_dir, table + ".csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            with connection.cursor().copy(
                "COPY (SELECT * FROM %s) TO STDOUT WITH (FORMAT csv, HEADER true)"
                % table
            ) as copy:
                for chunk in copy:
                    handle.write(bytes(chunk).decode("utf-8"))
        # Counted from the database, not by counting newlines: descriptions
        # embed newlines, which inflates the latter.
        counts.append(
            (table, connection.execute("SELECT count(*) FROM " + table).fetchone()[0])
        )
    current = {table + ".csv" for table, _ in counts}
    for stale in sorted(set(os.listdir(raw_dir)) - current):
        if stale.endswith(".csv"):
            os.remove(os.path.join(raw_dir, stale))
    with open(os.path.join(raw_dir, EXPORT_MARK), "w", encoding="utf-8") as handle:
        json.dump({"system_identifier": database_identity(connection),
                   "exported_at": now().isoformat(), "tables": len(counts)}, handle)
    return counts


def export_mark(raw_dir=RAW_DIR):
    """{system_identifier, exported_at, tables} of the mirror, or None."""
    path = os.path.join(raw_dir, EXPORT_MARK)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def export_raw(connection, args, tables=()):
    """Refresh data/raw/*.csv unless asked not to (CLI entry points)."""
    if getattr(args, "no_export", False):
        return {}
    return dict(export(connection))
