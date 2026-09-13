"""Store: map_playstyle.csv - what kind of fight each map rewards.

The bridge between MAPS and the playbook. Same rules as every authored
input: whole truth, unknown map names are errors, 1-3 score scale.

    python -m data.proprietary.load.user.map_playstyle
"""

import csv
import os
import sys

import psycopg

from data.proprietary import pipeline
from data.proprietary.pipeline import USER

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "map_playstyle.csv")


class MapPlaystyleError(Exception):
    pass


def read_rows(path):
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = ["map", "style", "score", "note"]
        if reader.fieldnames != expected:
            raise MapPlaystyleError("%s: header must be %s, found %s"
                                   % (path, ",".join(expected), reader.fieldnames))
        for n, row in enumerate(reader, start=2):
            name, style = row["map"].strip(), row["style"].strip().lower()
            if not name or not style:
                raise MapPlaystyleError("line %d: map and style are required" % n)
            if (name.lower(), style) in seen:
                raise MapPlaystyleError("line %d: duplicate %s/%s" % (n, name, style))
            seen.add((name.lower(), style))
            score = row["score"].strip()
            rows.append((name, style, int(score) if score else None,
                         row["note"].strip() or None))
    return rows


def run(connection, path=CSV_PATH, log=print):
    rows = read_rows(path)
    cursor = connection.cursor()
    source_id = pipeline.register_source(cursor, USER, pipeline.now())
    map_ids = pipeline.lookup_ids(cursor, "maps", "name", "map_id")
    unknown = sorted({m for m, *_ in rows if m.lower() not in map_ids})
    if unknown:
        raise MapPlaystyleError("maps not in the pool (fix map_playstyle.csv):"
                                " %s" % ", ".join(unknown))
    cursor.execute("DELETE FROM map_playstyle")
    for name, style, score, note in rows:
        cursor.execute(
            "INSERT INTO map_playstyle (map_id, style, score, note,"
            " source_id) VALUES (%s, %s, %s, %s, %s)",
            (map_ids[name.lower()], style, score, note, source_id))
    connection.commit()
    log("map playstyle claims: %d" % len(rows))
    return {"claims": len(rows), "maps": len({m for m, *_ in rows}),
            "tables": ["map_playstyle"]}


def main():
    parser = pipeline.build_parser(__doc__)
    args = parser.parse_args()
    with psycopg.connect(pipeline.resolve_dsn(args)) as connection:
        summary = run(connection)
        pipeline.export_raw(connection, args, summary["tables"])


if __name__ == "__main__":
    try:
        main()
    except (MapPlaystyleError, OSError, ValueError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
