"""The schema and the database's life: migrations, drop, rebuild, the CSV
mirror's restore path, and the generated documentation.

    init      apply the migrations to an empty database
    rebuild   drop everything and reapply them
    restore   bring recorded recommendations back from the data/raw mirror
    docs      regenerate docs/erd.md and docs/data-dictionary.md
"""

import glob
import os
import re

import psycopg

from data import RAW_DIR, ROOT

MIGRATIONS_DIR = os.path.join(ROOT, "data", "db", "migrations")

DOC_DOMAIN = {"001_initial_schema.sql": "foundation", "002_heroes.sql": "HEROES",
              "003_maps.sql": "MAPS", "004_meta.sql": "META",
              "005_playbook.sql": "PLAYBOOK", "006_inference.sql": "INFERENCE",
              "007_three_layers.sql": "PLAYBOOK",
              "008_schema_migrations.sql": "foundation",
              "009_outcomes.sql": "INFERENCE",
              "010_constraints_and_heuristics.sql": "INFERENCE"}


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
    if connection.execute("select to_regclass('schema_migrations')").fetchone()[0]:
        for path, _ in migrations:
            connection.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)"
                " ON CONFLICT (filename) DO NOTHING", (os.path.basename(path),))
        connection.commit()


def applied(connection):
    """The migration filenames the database recorded ([] before the ledger)."""
    if not connection.execute("select to_regclass('schema_migrations')").fetchone()[0]:
        return []
    return [r[0] for r in connection.execute(
        "SELECT filename FROM schema_migrations ORDER BY filename")]


def pending(connection):
    """Migration files on disk the database has not recorded."""
    have = set(applied(connection))
    return [os.path.basename(p) for p, _ in read_migrations()
            if os.path.basename(p) not in have]


def table_count(connection):
    return connection.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
    ).fetchone()[0]


def drop_all(connection):
    """Drop every table in the public schema, read from the catalog rather
    than the migration text so a table whose migration was deleted still
    goes."""
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
    return dropped


# --- restoring what no source can re-fetch ---------------------------------

RECORD_TABLES = ("recommendations", "recommendation_picks",
                 "recommendation_evidence", "outcomes", "outcome_picks")
SEQUENCED = (("recommendations", "rec_id"), ("outcomes", "outcome_id"))


def restore_recommendations(connection, raw_dir=RAW_DIR):
    """Re-import recorded recommendations and outcomes from the data/raw
    mirror.

    They are the inference layer's own output and the matches that followed
    - the one thing no pull tool can re-scrape - and the mirror CSVs are
    their backup. Never merges: a database that already holds
    recommendations keeps them. A mirror that predates the outcomes tables
    restores what it has.
    """
    cursor = connection.cursor()
    if cursor.execute("SELECT count(*) FROM recommendations").fetchone()[0]:
        return 0
    paths = [(t, os.path.join(raw_dir, t + ".csv")) for t in RECORD_TABLES]
    paths = [(t, p) for t, p in paths if os.path.exists(p)]
    if not any(t == "recommendations" for t, _ in paths):
        return 0
    restored = 0
    try:
        for table, path in paths:
            with open(path, encoding="utf-8") as handle:
                with cursor.copy("COPY %s FROM STDIN WITH (FORMAT csv,"
                                 " HEADER true)" % table) as copy:
                    copy.write(handle.read())
            restored += cursor.execute(
                "SELECT count(*) FROM " + table).fetchone()[0]
        for table, column in SEQUENCED:
            cursor.execute(
                "SELECT setval(pg_get_serial_sequence('%s', '%s'),"
                " greatest((SELECT coalesce(max(%s), 0) FROM %s), 1))"
                % (table, column, column, table))
        connection.commit()
    except psycopg.Error as error:
        connection.rollback()
        print("WARNING: could not restore recorded recommendations from"
              " data/raw (%s); the transcripts in"
              " data/authored/recommendations/ still hold them" % error)
        return 0
    return restored


# --- generated documentation -------------------------------------------

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
           "Five domains. Three are the authoritative data the sources are pulled",
           "for - which hero (HEROES), on which map (MAPS), performing how well",
           "(META) - and become the FACTS of a board. The other two are the",
           "playbook's record: the authored inputs and the mirror of the constraints and",
           "heuristics (PLAYBOOK), and what the inference layer decided and what came of",
           "it (INFERENCE). The composition is the argmax of the strategies - the",
           "constraints and heuristics in inference/strategies/ - over the facts.", "",
           "```", "FACTS      = HEROES ∪ MAPS ∪ META",
           "STRATEGIES = CONSTRAINTS ∪ HEURISTICS",
           "COMP       = ARGMAX[ STRATEGIES( FACTS ) ]", "```", "",
           "Every table also carries `source_id` → `sources` and a `cao` timestamp.",
           "Those edges are left off - they would connect `sources` to all %d tables"
           % len(tables), "and obscure everything else.", ""]
    for d in ("HEROES", "MAPS", "META", "PLAYBOOK", "INFERENCE"):
        erd += ["## %s" % d, "", "```mermaid", "erDiagram"] + \
               edges(lambda c, d=d: dom.get(c) == d) + ["```", ""]
    erd += ["## The whole database", "", "```mermaid", "erDiagram"] + \
           edges(lambda c: True) + ["```", ""]
    with open(os.path.join(ROOT, "docs", "erd.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(erd))

    dd = ["# Data dictionary", "", "Generated from the live schema"
          " (`python -m data.mcp call db_docs`).", "",
          "Every table carries two columns omitted from the lists below, because they",
          "are on all of them: `source_id` (which source the row came from, see",
          "`sources`) and `cao` — \"current as of\", when that row was read.", "",
          "| domain | tables |", "| --- | --- |"]
    for d in ("foundation", "HEROES", "MAPS", "META", "PLAYBOOK", "INFERENCE"):
        dd.append("| **%s** | %s |" % (d, " · ".join(
            "`%s`" % t for t in tables if dom[t] == d)))
    dd.append("")
    for t in tables:
        fn, prose = mig.get(t, ("", ""))
        dd += ["", "## `%s`" % t, "", "*%s · %d rows · `%s`*" % (dom[t], counts[t], fn)]
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
