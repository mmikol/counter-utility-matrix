"""The database: where it is, and the small things every writer needs.

    default_dsn        $DATABASE_URL, or the embedded cluster at
                       db/psql/cluster (pgserver, first touch)
    register_source    the `sources` row a page or a file becomes, upserted;
                       every table's rows carry its source_id
    lookup_ids         {name: id} for matching what a source says against
                       what is loaded
    now, current_patch, current_season
                       what a capture is stamped with
    export             the CSV mirror under db/raw, and its mark

The schema itself - migrations, the ledger, rebuild, the
generated docs - is db.psql.schema. Nothing here knows a particular source.
"""

import json
import os
from datetime import UTC, datetime

from db import DEFAULT_DB_DIR, RAW_DIR


def default_dsn():
    """Where to read and write: $DATABASE_URL, or the embedded cluster at
    db/psql/cluster (pgserver runs initdb on first touch)."""
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return explicit
    import pgserver

    return pgserver.get_server(DEFAULT_DB_DIR).get_uri()


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
    return datetime.now(UTC)


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
        with open(path, "w", encoding="utf-8", newline="") as handle, connection.cursor().copy(
                "COPY (SELECT * FROM %s) TO STDOUT WITH (FORMAT csv, HEADER true)" % table
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

