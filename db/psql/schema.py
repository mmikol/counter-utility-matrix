"""The schema and the database's life: migrations, drop, rebuild, the CSV
and the generated documentation.

    init      apply the migrations to an empty database
    rebuild   drop everything and reapply them
    docs      regenerate the schema sections of docs/db.md (ERD, dictionary)
"""

import glob
import os
import re

import psycopg

from db import ROOT

MIGRATIONS_DIR = os.path.join(ROOT, "db", "psql", "migrations")

DOC_DOMAIN = {"001_initial_schema.sql": "foundation", "002_heroes.sql": "HEROES",
              "003_maps.sql": "MAPS", "004_meta.sql": "META",
              "005_playbook.sql": "PLAYBOOK", "006_inference.sql": "INFERENCE",
              "007_three_layers.sql": "PLAYBOOK",
              "008_schema_migrations.sql": "foundation",
              "009_outcomes.sql": "INFERENCE",
              "010_constraints_and_heuristics.sql": "INFERENCE",
              "011_reader_role.sql": "foundation", "012_reader_login.sql": "foundation",
              "013_assumptions.sql": "INFERENCE", "014_no_recorded.sql": "INFERENCE",
              "015_announced_heroes.sql": "HEROES",
              "016_playbook_of_record.sql": "INFERENCE"}


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


# --- generated documentation -------------------------------------------

def _migration_tables():
    out = {}
    for path, text in read_migrations():
        fn = os.path.basename(path)
        for m in re.finditer(r"((?:^--.*\n)*)^CREATE TABLE (\w+)", text, re.M):
            prose = " ".join(line.lstrip("-").strip() for line in m.group(1).splitlines()
                             if line.strip() not in ("--", ""))
            out[m.group(2)] = (fn, prose.strip())
    return out


def embed(path, name, text):
    """Replace the generated section `name` of a markdown file - the text between
    <!-- generated:name --> and <!-- /generated:name --> - keeping the rest."""
    with open(path, encoding="utf-8") as handle:
        doc = handle.read()
    start, end = "<!-- generated:%s -->" % name, "<!-- /generated:%s -->" % name
    if start not in doc or end not in doc:
        raise SchemaError("%s has no %s markers" % (path, name))
    head = doc[:doc.index(start) + len(start)]
    tail = doc[doc.index(end):]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(head + "\n" + text.strip("\n") + "\n" + tail)


def generate_docs(connection, path=None):
    mig = _migration_tables()
    tables = [r[0] for r in connection.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")]
    cols = {t: connection.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
        " WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (t,)).fetchall() for t in tables}
    fks = connection.execute(
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
    fks = [(c, col, p, pc) for c, col, p, pc, _ in fks]
    dom = {t: DOC_DOMAIN.get(mig.get(t, ("", ""))[0], "foundation") for t in tables}
    ref = {}
    for c, col, pt, pc in fks:
        ref.setdefault((c, col), (pt, pc))

    def edges(pred):
        seen = []
        for child, col, parent, _ in fks:
            line = '    %s ||--o{ %s : "%s"' % (parent, child, col)
            if col.endswith("_id") and parent != "sources" and pred(child) \
                    and line not in seen:
                seen.append(line)
        return sorted(seen)

    erd = ["Five domains. Three are the authoritative data the sources are pulled",
           "for - which hero (HEROES), on which map (MAPS), performing how well",
           "(META) - the DATA a board's facts are derived from: the independent",
           "ones read one table each, the dependent ones join across the",
           "selections (map_meta is heroes ⋈ maps, counters and synergies are",
           "heroes ⋈ heroes). The other two are the",
           "playbook's record: the authored inputs (PLAYBOOK) and the mirror of the",
           "strategies the inference layer solves with (INFERENCE). The composition is",
           "the argmax of the strategies - the constraints, heuristics and assumptions",
           "in inference/strategies/ - over the facts.", "",
           "```", "DATA        = HEROES ∪ MAPS ∪ META",
           "FACTS       = INDEPENDENT ∪ DEPENDENT   (each selection alone; the joins across them)",
           "STRATEGIES  = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS",
           "COMP        = ARGMAX[ STRATEGIES( FACTS ) ]", "```", "",
           "Every table also carries `source_id` → `sources` and a `cao` timestamp.",
           "Those edges are left off - they would connect `sources` to all %d tables"
           % len(tables), "and obscure everything else.", ""]
    for d in ("HEROES", "MAPS", "META", "PLAYBOOK", "INFERENCE"):
        erd += ["#### %s" % d, "", "```mermaid", "erDiagram",
                *edges(lambda c, d=d: dom.get(c) == d), "```", ""]
    erd += ["#### The whole database", "", "```mermaid", "erDiagram",
            *edges(lambda c: True), "```", ""]
    path = path or os.path.join(ROOT, "docs", "db.md")
    embed(path, "erd", "\n".join(erd))

    dd = ["Generated from the live schema (`python -m db.mcp call db_docs`).", "",
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
        dd += ["", "#### `%s`" % t, "", "*%s · `%s`*" % (dom[t], fn)]
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
    embed(path, "dictionary", "\n".join(dd))
    return "regenerated the schema sections of docs/db.md: %d tables" % len(tables)
