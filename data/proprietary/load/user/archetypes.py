"""Store: archetypes.csv - what a composition IS, by playstyle.

Each row is one slot claim: this style wants this many of this role. The
file is the whole truth; unknown role codes are an error to fix in the file.

    python -m data.proprietary.load.user.archetypes
"""

import csv
import os
import sys

import psycopg

from data.proprietary import pipeline
from data.proprietary.pipeline import USER

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "archetypes.csv")


class ArchetypeError(Exception):
    pass


def read_rows(path):
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = ["style", "role", "slots", "note"]
        if reader.fieldnames != expected:
            raise ArchetypeError("%s: header must be %s, found %s"
                                % (path, ",".join(expected), reader.fieldnames))
        for n, row in enumerate(reader, start=2):
            style, role = row["style"].strip().lower(), row["role"].strip().lower()
            if not style or not role:
                raise ArchetypeError("line %d: style and role are required" % n)
            if (style, role) in seen:
                raise ArchetypeError("line %d: duplicate %s/%s" % (n, style, role))
            seen.add((style, role))
            rows.append((style, role, int(row["slots"]),
                         row["note"].strip() or None))
    return rows


def run(connection, path=CSV_PATH, log=print):
    rows = read_rows(path)
    cursor = connection.cursor()
    source_id = pipeline.register_source(cursor, USER, pipeline.now())
    role_ids = pipeline.lookup_ids(cursor, "roles", "code", "role_id")
    unknown = sorted({r for _, r, _, _ in rows if r not in role_ids})
    if unknown:
        raise ArchetypeError("unknown role codes (fix archetypes.csv): %s"
                             % ", ".join(unknown))
    cursor.execute("DELETE FROM comp_archetypes")
    for style, role, slots, note in rows:
        cursor.execute(
            "INSERT INTO comp_archetypes (style, role_id, slots, note,"
            " source_id) VALUES (%s, %s, %s, %s, %s)",
            (style, role_ids[role], slots, note, source_id))
    connection.commit()
    log("archetype slots: %d loaded" % len(rows))
    return {"slots": len(rows), "styles": sorted({s for s, *_ in rows}),
            "tables": ["comp_archetypes"]}


def main():
    parser = pipeline.build_parser(__doc__)
    args = parser.parse_args()
    with psycopg.connect(pipeline.resolve_dsn(args)) as connection:
        summary = run(connection)
        pipeline.export_raw(connection, args, summary["tables"])


if __name__ == "__main__":
    try:
        main()
    except (ArchetypeError, OSError, ValueError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
