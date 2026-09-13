"""Store: synergies.csv - our hand-authored half of the playbook.

Each row is one PAIR, scored, with the reasoning in `note`. Synergy is
bidirectional, so a pair is written once and stored once in canonical order;
the same pair twice is an error. The file is the whole truth and unknown
names are errors to fix in the file, not rows to drop.

    python -m data.proprietary.load.user.synergies
"""

import csv
import os
import sys

import psycopg

from data.proprietary import pipeline
from data.proprietary.pipeline import USER

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "synergies.csv")


class SynergyError(Exception):
    pass


def read_rows(path):
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = ["hero", "other", "score", "note"]
        if reader.fieldnames != expected:
            raise SynergyError("%s: header must be %s, found %s"
                              % (path, ",".join(expected), reader.fieldnames))
        for n, row in enumerate(reader, start=2):
            hero, other = row["hero"].strip(), row["other"].strip()
            if not hero or not other:
                raise SynergyError("line %d: hero and other are required" % n)
            if hero.lower() == other.lower():
                raise SynergyError("line %d: %s paired with itself" % (n, hero))
            key = frozenset((hero.lower(), other.lower()))
            if key in seen:
                raise SynergyError("line %d: duplicate pair %s / %s - synergy"
                                  " is bidirectional, write each pair once"
                                  % (n, hero, other))
            seen.add(key)
            score = row["score"].strip()
            rows.append((hero, other, int(score) if score else None,
                         row["note"].strip() or None))
    return rows


def run(connection, path=CSV_PATH, log=print):
    rows = read_rows(path)
    cursor = connection.cursor()
    source_id = pipeline.register_source(cursor, USER, pipeline.now())
    hero_ids = pipeline.lookup_ids(cursor, "heroes", "name", "hero_id")
    unknown = sorted({name for pair in rows for name in pair[:2]
                      if name.lower() not in hero_ids})
    if unknown:
        raise SynergyError("names not in the roster (fix synergies.csv): %s"
                           % ", ".join(unknown))
    cursor.execute("DELETE FROM synergies")
    for hero, other, score, note in rows:
        a, b = sorted((hero_ids[hero.lower()], hero_ids[other.lower()]))
        cursor.execute(
            "INSERT INTO synergies (hero_id, other_id, score, note,"
            " source_id) VALUES (%s, %s, %s, %s, %s)",
            (a, b, score, note, source_id))
    connection.commit()
    log("authored synergies: %d claims loaded" % len(rows))
    return {"synergies": len(rows), "tables": ["synergies"]}


def main():
    parser = pipeline.build_parser(__doc__)
    args = parser.parse_args()
    with psycopg.connect(pipeline.resolve_dsn(args)) as connection:
        summary = run(connection)
        pipeline.export_raw(connection, args, summary["tables"])


if __name__ == "__main__":
    try:
        main()
    except (SynergyError, OSError, ValueError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
