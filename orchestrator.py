"""The orchestrator: runs every pipeline, across every type of data, into one
model.

Each type is a pipeline of its own - extract, transform, load - and declares
itself in its own `pipeline.py`. This module sits above them, owns the schema
and the CSV export, and runs them in the order their data depends on:

    authoritative   what a source measured. Cooldowns, health, win rates.
    heuristic       somebody else's judgement. Who answers whom, best maps.
    proprietary     our own judgement, authored in the repo. Synergies.

The heuristic type links to heroes, maps and regions the authoritative type
loads, so it runs second. Order matters and running out of order does not
error - it quietly produces a partial database - which is why `run` exists
rather than a note in a README.

The verbs, in the order a database lives through them:

    init      apply the migrations to an empty database - schema, no data
    inflate   the first fill: every pipeline into a fresh schema. Refuses a
              database that already holds data - loading again is `update`.
    update    (default) load again into a populated database. Entity tables
              are refreshed in place; each meta run adds a new dated snapshot
              beside the old ones, so repeated updates accumulate a series.
              Never drops anything, so one type can be run alone safely.
    rebuild   create + fill from a clean slate: drop everything, reapply the
              migrations, run every pipeline. The ground truth for structural
              change - a renamed ability, a removed hero - and always runs
              everything, because a partial rebuild is how one type of data
              wipes another.
    export    refresh data/raw/*.csv from whatever is loaded
    docs      regenerate docs/erd.md and docs/data-dictionary.md from the
              migrations and the live catalog

The db/cluster directory itself is made implicitly: pgserver runs initdb the
first time a verb touches the path.

    python -m orchestrator rebuild               clean slate, everything
    python -m orchestrator                       update, everything
    python -m orchestrator --type heuristic      update one type
    python -m orchestrator --only authoritative.wiki.maps
"""

import argparse
import glob
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import psycopg


# --- shared plumbing every pipeline uses ------------------------------

ROOT = os.path.dirname(os.path.abspath(__file__))

# db/ pairs the schema with what it builds: db/migrations is the source,
# db/cluster the embedded Postgres built from it. The cluster is a directory,
# not a file, because that is Postgres's on-disk format - there is no single
# database file to point at. It is a build artifact - `rebuild` reproduces it
# from the migrations plus the page caches - so it is gitignored, not
# committed.
DEFAULT_DB_DIR = os.path.join(ROOT, "db", "cluster")


def build_parser(description, cache_dir=None):
    """A parser carrying the options every pipeline accepts."""
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


def resolve_dsn(args):
    """Where to write: --local-server, --dsn, $DATABASE_URL, or db/ at the root."""
    explicit = args.dsn or os.environ.get("DATABASE_URL")
    if not getattr(args, "local_server", None) and explicit:
        return explicit
    import pgserver

    return pgserver.get_server(
        os.path.abspath(getattr(args, "local_server", None) or DEFAULT_DB_DIR)
    ).get_uri()


def prepare_cache(args):
    """Create the page cache directory if this pipeline uses one."""
    cache = getattr(args, "cache", None)
    if cache and not os.path.isdir(cache):
        os.makedirs(cache)
    return cache


def lookup_ids(cursor, table, name_column, id_column):
    """{lowercased name: id} for matching scraped names against loaded rows."""
    return {
        row[0].lower(): row[1]
        for row in cursor.execute(
            "SELECT %s, %s FROM %s" % (name_column, id_column, table)
        ).fetchall()
    }


def export_raw(connection, args, tables=()):
    """Refresh data/raw/*.csv unless asked not to, reporting the named tables."""
    if args.no_export:
        return
    counts = dict(export(connection))
    print("\nrefreshed data/raw: %d tables" % len(counts))
    for table in tables:
        if table in counts:
            print("  %-22s %d rows" % (table + ".csv", counts[table]))


def current_patch(cursor):
    """The most recent released patch, to stamp on a capture's snapshot.

    NULL only when the patches pipeline has not run; the orchestrator orders
    it before every snapshot-writing stage.
    """
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


# --- where rows came from ----------------------------------------------
#
# One row per source rather than a URL and a timestamp repeated on every
# entity row. `cao` ("current as of") is refreshed each time a pipeline runs.
# The sources themselves are declared by the type that scrapes them, in its
# own pipeline.py, so each carries its own provenance.


def now():
    """One timestamp for a pipeline run."""
    return datetime.now(timezone.utc)


def register_source(cursor, source, cao):
    """Upsert one source and return its source_id."""
    code, name, url = source
    cursor.execute(
        "INSERT INTO sources (code, name, url, cao) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
        " url = EXCLUDED.url, cao = EXCLUDED.cao RETURNING source_id",
        (code, name, url, cao),
    )
    return cursor.fetchone()[0]


# --- generated documentation -------------------------------------------
#
# erd.md and data-dictionary.md are derived artifacts: table prose comes from
# the comment block above each CREATE TABLE, structure and counts from the
# live catalog. Regenerate after any schema change; hand-edits get overwritten.

DOC_DOMAIN = {"001_initial_schema.sql": "foundation", "002_heroes.sql": "HEROES",
              "003_maps.sql": "MAPS", "004_meta.sql": "META",
              "005_playbook.sql": "PLAYBOOK",
              "006_inference.sql": "INFERENCE"}


def _migration_tables():
    out = {}
    for path, text in read_migrations():
        fn = os.path.basename(path)
        for m in re.finditer(r"((?:^--.*\n)*)^CREATE TABLE (\w+)", text, re.M):
            prose = " ".join(l.lstrip("-").strip() for l in m.group(1).splitlines()
                             if l.strip() not in ("--", ""))
            out[m.group(2)] = (fn, prose.strip())
    return out


def generate_docs(connection):
    mig = _migration_tables()
    tables = [r[0] for r in connection.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")]
    cols = {t: connection.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
        " WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (t,)).fetchall() for t in tables}
    fks = connection.execute(
        "SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name"
        " FROM information_schema.table_constraints tc"
        " JOIN information_schema.key_column_usage kcu"
        "   ON tc.constraint_name = kcu.constraint_name"
        " JOIN information_schema.constraint_column_usage ccu"
        "   ON tc.constraint_name = ccu.constraint_name"
        " WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'"
        " ORDER BY 1, 2").fetchall()
    counts = {t: connection.execute("SELECT count(*) FROM " + t).fetchone()[0]
              for t in tables}
    dom = {t: DOC_DOMAIN.get(mig.get(t, ("", ""))[0], "foundation") for t in tables}
    ref = {(c, col): (pt, pc) for c, col, pt, pc in fks}

    def edges(pred):
        seen = []
        for child, col, parent, _ in fks:
            line = '    %s ||--o{ %s : "%s"' % (parent, child, col)
            if col.endswith("_id") and parent != "sources" and pred(child) \
                    and line not in seen:
                seen.append(line)
        return sorted(seen)

    erd = ["# Entity relationship diagram", "",
           "The model is domains that intersect. A counter-pick question is a join",
           "across them: which hero (HEROES), on which map (MAPS), performing how well",
           "(META), answering whom and alongside whom (PLAYBOOK).", "",
           "```", "COUNTER = MAX[ HEROES \u2229 MAPS \u2229 META ]", "```", "",
           "Each section shows every relationship its tables own, including the ones",
           "that reach into another domain - PLAYBOOK's tables are almost entirely",
           "edges like that, judgements attached to heroes and maps defined elsewhere.",
           "",
           "Two tables can be joinable with no edge between them: `hero_meta` and",
           "`map_meta` share dimension keys and join on any of them - an edge here",
           "means a foreign key, and neither owns the other.", "",
           "Every table also carries `source_id` \u2192 `sources` and a `cao` timestamp.",
           "Those edges are left off - they would connect `sources` to all %d tables"
           % len(tables), "and obscure everything else.", ""]
    for d in ("HEROES", "MAPS", "META", "PLAYBOOK", "INFERENCE"):
        erd += ["## %s" % d, "", "```mermaid", "erDiagram"] + \
               edges(lambda c, d=d: dom.get(c) == d) + ["```", ""]
    erd += ["## The whole database", "",
            "Every table and every foreign key in one picture (still minus the",
            "`source_id` edges). The domain sections above are this diagram cut",
            "into readable pieces.", "",
            "```mermaid", "erDiagram"] + edges(lambda c: True) + ["```", ""]
    with open(os.path.join(ROOT, "docs", "erd.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(erd))

    dd = ["# Data dictionary", "", "Generated from the live schema"
          " (`python -m orchestrator docs`).", "",
          "Every table carries two columns omitted from the lists below, because they",
          "are on all of them: `source_id` (which source the row came from, see",
          "`sources`) and `cao` \u2014 \"current as of\", when that row was read.", "",
          "| domain | tables |", "| --- | --- |"]
    for d in ("foundation", "HEROES", "MAPS", "META", "PLAYBOOK", "INFERENCE"):
        dd.append("| **%s** | %s |" % (d, " \u00b7 ".join(
            "`%s`" % t for t in tables if dom[t] == d)))
    dd.append("")
    for t in tables:
        fn, prose = mig.get(t, ("", ""))
        dd += ["", "## `%s`" % t, "", "*%s \u00b7 %d rows \u00b7 `%s`*" % (dom[t], counts[t], fn)]
        if prose:
            dd += ["", prose]
        dd += ["", "| column | type | null | references |", "| --- | --- | --- | --- |"]
        for name, typ, nullable in cols[t]:
            if name in ("source_id", "cao"):
                continue
            r = ref.get((t, name))
            dd.append("| `%s` | %s | %s | %s |" % (
                name, typ, "yes" if nullable == "YES" else "no",
                "`%s.%s`" % r if r else ""))
    with open(os.path.join(ROOT, "docs", "data-dictionary.md"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(dd) + "\n")
    return "regenerated docs/erd.md and docs/data-dictionary.md: %d tables" % len(tables)


# --- the schema, from migrations/ -------------------------------------

MIGRATIONS_DIR = os.path.join(ROOT, "db", "migrations")


class SchemaError(Exception):
    pass


def read_migrations():
    """Every migration, in filename order."""
    migrations = []
    for path in sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql"))):
        with open(path, encoding="utf-8") as handle:
            migrations.append((path, handle.read()))
    if not migrations:
        raise SchemaError("no migrations found in %s/" % MIGRATIONS_DIR)
    return migrations


def apply(connection, migrations, quiet=False):
    for path, sql in migrations:
        with connection.cursor() as cursor:
            cursor.execute(sql)
        connection.commit()
        if not quiet:
            print("  applied %s" % os.path.basename(path))


def drop_all(connection):
    """Drop every table in the public schema.

    Read from the catalog rather than from the migration text. Deriving the
    list from the migrations leaves orphans behind: a table whose migration is
    later deleted is never dropped, and goes on holding stale rows that nothing
    references. This database is a full rebuild of one project's schema, so the
    catalog is the honest source of truth for what to clear.
    """
    with connection.cursor() as cursor:
        tables = [
            row[0]
            for row in cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        ]
        if tables:
            cursor.execute(
                "DROP TABLE IF EXISTS %s CASCADE"
                % ", ".join(
                    psycopg.sql.Identifier(t).as_string(connection) for t in tables
                )
            )
    connection.commit()
    return tables


def rebuild(connection, quiet=False):
    """Drop everything and reapply every migration."""
    dropped = drop_all(connection)
    if dropped and not quiet:
        print("  dropped %d existing tables" % len(dropped))
    apply(connection, read_migrations(), quiet)


# --- exporting every table to data/raw --------------------------------

RAW_DIR = os.path.join(ROOT, "data", "raw")

def table_names(connection):
    """Every table in the database, from the catalog.

    Read rather than listed: a hand-maintained list drifts silently, and the
    table it forgets is exactly the one nobody notices is stale.
    """
    return [
        row[0]
        for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            " ORDER BY tablename"
        ).fetchall()
    ]


def export(connection, raw_dir=RAW_DIR):
    """Write one CSV per table. Returns [(table, row_count)]."""
    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir)

    counts = []
    for table in table_names(connection):
        path = os.path.join(raw_dir, table + ".csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            with connection.cursor().copy(
                "COPY (SELECT * FROM %s) TO STDOUT WITH (FORMAT csv, HEADER true)" % table
            ) as copy:
                for chunk in copy:
                    handle.write(bytes(chunk).decode("utf-8"))
        # Counted from the database, not by counting newlines in the file:
        # descriptions contain embedded newlines, which inflates the latter.
        counts.append(
            (table, connection.execute("SELECT count(*) FROM " + table).fetchone()[0])
        )

    # A table that is renamed or dropped leaves its old CSV behind, and a stale
    # file is indistinguishable from a current one. Remove what no longer maps
    # to a table.
    current = {table + ".csv" for table, _ in counts}
    for stale in sorted(set(os.listdir(raw_dir)) - current):
        if stale.endswith(".csv"):
            os.remove(os.path.join(raw_dir, stale))
            print("  removed stale %s" % stale)
    return counts


# --- running the stages in order --------------------------------------

# Each type's stages as source.domain, in the order they must run, and the
# types themselves in the order they must run. Held here as plain strings and
# dispatched as subprocesses: a type's pipeline.py imports this module for its
# shared plumbing, so importing them back would be a cycle.
PIPELINES = {
    "authoritative": (
        "blizzard.heroes",
        "wiki.heroes",
        "wiki.maps",
        "wiki.patches",
        "blizzard.meta",
    ),
    "heuristic": (
        "wiki.meta",
        "counterpick.heroes",
    ),
    "proprietary": (
        "user.seasons",
        "user.strategies",
        "user.synergies",
        "user.archetypes",
        "user.map_playstyle",
    ),
}


def qualified():
    """Every pipeline as type.source.domain, in the order they must run."""
    return [
        "%s.%s" % (dtype, stage)
        for dtype, stages in PIPELINES.items()
        for stage in stages
    ]


# --- command line ------------------------------------------------------


def main():
    parser = build_parser(__doc__)
    parser.add_argument(
        "command", nargs="?", default="update",
        choices=("init", "inflate", "update", "rebuild", "export", "docs"),
        help="init creates the schema; inflate is the first fill; update"
             " (default) loads again; rebuild starts clean and does all of"
             " it; export refreshes data/raw",
    )
    parser.add_argument(
        "--type", action="append", choices=tuple(PIPELINES),
        help="run just this type of data (repeatable)",
    )
    parser.add_argument(
        "--only", action="append",
        help="run just this pipeline, as type.source.domain (repeatable)",
    )
    args, passthrough = parser.parse_known_args()

    if args.command == "docs":
        with psycopg.connect(resolve_dsn(args)) as connection:
            print(generate_docs(connection))
        return

    if args.command == "export":
        with psycopg.connect(resolve_dsn(args)) as connection:
            for table, rows in export(connection):
                print("  data/raw/%s.csv  %d rows" % (table, rows))
        return

    def table_count(connection):
        return connection.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        ).fetchone()[0]

    if args.command == "init":
        with psycopg.connect(resolve_dsn(args)) as connection:
            if table_count(connection):
                sys.exit("error: the database already has tables; `rebuild`"
                         " is the verb that starts over")
            apply(connection, read_migrations())
            print("\n%d tables, no data; `inflate` fills them" %
                  table_count(connection))
        return

    if args.command in ("rebuild", "inflate"):
        # Always the whole thing. Filling or rebuilding a slice would leave
        # the exact half-loaded database the verb split exists to prevent.
        if args.type or args.only:
            sys.exit("error: %s always runs every pipeline; use update with"
                     " --type/--only for partial runs" % args.command)

    if args.command == "rebuild":
        with psycopg.connect(resolve_dsn(args)) as connection:
            rebuild(connection)
    else:
        # inflate and update need the schema to exist already, and inflate
        # additionally means FIRST fill - a populated database is update's.
        with psycopg.connect(resolve_dsn(args)) as connection:
            if table_count(connection) == 0:
                sys.exit("error: the database is empty; run"
                         " `python -m orchestrator init` (or rebuild) first")
            if args.command == "inflate" and connection.execute(
                "SELECT count(*) FROM heroes"
            ).fetchone()[0]:
                sys.exit("error: the database already holds data; `update`"
                         " is the verb for loading again")

    run_pipelines(args, passthrough)


def run_pipelines(args, passthrough):
    """Every selected pipeline, in dependency order, stopping at the first
    failure.

    A later stage run against a half-loaded database does not fail loudly - it
    silently drops the rows it cannot link - so a failure stops the run.
    """
    every = qualified()
    selected = set(every)
    if args.type:
        selected = {name for name in every if name.split(".")[0] in args.type}
    if args.only:
        unknown = [name for name in args.only if name not in every]
        if unknown:
            sys.exit("error: unknown pipeline(s): %s\nknown: %s"
                     % (", ".join(unknown), ", ".join(every)))
        selected &= set(args.only)
    selected = [name for name in every if name in selected]
    if not selected:
        sys.exit("error: no pipelines selected")

    forwarded = list(passthrough)
    for flag, value in (("--dsn", args.dsn), ("--local-server", args.local_server)):
        if value:
            forwarded += [flag, value]
    if args.no_export:
        forwarded.append("--no-export")

    shown = None
    for index, name in enumerate(selected, start=1):
        dtype, stage = name.split(".", 1)
        if dtype != shown:
            print("\n--- %s ---" % dtype)
            shown = dtype
        print("\n=== [%d/%d] %s ===" % (index, len(selected), name))
        result = subprocess.run(
            [sys.executable, "-m", "data.%s.load.%s" % (dtype, stage)] + forwarded,
            cwd=ROOT,
        )
        if result.returncode != 0:
            sys.exit("\n%s failed (exit %d); stopping so later stages do not run"
                     " against a partial database." % (name, result.returncode))
    print("\nall %d pipelines completed" % len(selected))


if __name__ == "__main__":
    try:
        main()
    except (SchemaError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
