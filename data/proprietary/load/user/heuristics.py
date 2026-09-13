"""Load pipeline: heuristics.csv + heuristic_params.csv - the playbook's
tunable brain.

heuristics.csv is the catalog: one row per consideration the dossier
mathematically encodes when weighing a team composition, numbered,
with the formula written out and an honest status - `live` (the dossier
emits it today, under the tag in the tag column), `ready` (computable from
the current schema, not yet wired), or `blocked` (names the data the schema
does not hold yet). heuristic_params.csv is the dial panel: the named
constants the live formulas read at build time. Tuning is meant to be
continuous - edit a value, re-run this loader, and the next dossier build
computes with it; the same names exist as defaults in dossier.py so a
database that predates these tables still works.

Both files are the whole truth: the tables are cleared and reloaded, so
deleting a row deletes the claim. And because this input is authored rather
than scraped, nothing is fuzzily matched or silently skipped - a malformed
row is an error to fix in the file, not a row to drop.

    python -m data.proprietary.load.user.heuristics
"""

import csv
import os
import sys

import psycopg

from data.proprietary import pipeline
from data.proprietary.pipeline import USER

BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
CATALOG_PATH = os.path.join(BASE, "heuristics.csv")
PARAMS_PATH = os.path.join(BASE, "heuristic_params.csv")

STATUSES = ("live", "ready", "blocked")


class HeuristicError(Exception):
    pass


def read_catalog(path):
    """[(id, tag, name, category, formula, inputs, status, rationale)]."""
    rows, seen_ids, seen_names = [], set(), set()
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = ["id", "tag", "name", "category", "formula", "inputs",
                    "status", "rationale"]
        if reader.fieldnames != expected:
            raise HeuristicError("%s: header must be %s, found %s"
                                 % (path, ",".join(expected),
                                    reader.fieldnames))
        for n, row in enumerate(reader, start=2):
            try:
                hid = int(row["id"])
            except ValueError:
                raise HeuristicError("line %d: id %r is not an integer"
                                     % (n, row["id"]))
            if hid in seen_ids:
                raise HeuristicError("line %d: duplicate id %d" % (n, hid))
            seen_ids.add(hid)
            name = row["name"].strip()
            if name.lower() in seen_names:
                raise HeuristicError("line %d: duplicate name %r" % (n, name))
            seen_names.add(name.lower())
            status = row["status"].strip()
            if status not in STATUSES:
                raise HeuristicError("line %d: status must be one of %s,"
                                     " found %r" % (n, "/".join(STATUSES),
                                                    status))
            fields = [row[c].strip() for c in expected[1:]]
            if not all(fields):
                raise HeuristicError("line %d: every column is required" % n)
            rows.append((hid, *fields))
    ids = sorted(seen_ids)
    if ids != list(range(1, len(ids) + 1)):
        raise HeuristicError("catalog ids must run 1..%d with no gaps"
                             % len(ids))
    return rows


def read_params(path):
    """[(code, value, note)] - every dial named once, every value numeric."""
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = ["code", "value", "note"]
        if reader.fieldnames != expected:
            raise HeuristicError("%s: header must be %s, found %s"
                                 % (path, ",".join(expected),
                                    reader.fieldnames))
        for n, row in enumerate(reader, start=2):
            code, note = row["code"].strip(), row["note"].strip()
            if not code or not note:
                raise HeuristicError("line %d: code and note are required"
                                     % n)
            if code in seen:
                raise HeuristicError("line %d: duplicate param %s" % (n, code))
            seen.add(code)
            try:
                value = float(row["value"])
            except ValueError:
                raise HeuristicError("line %d: %s value %r is not numeric"
                                     % (n, code, row["value"]))
            rows.append((code, value, note))
    return rows


def main():
    parser = pipeline.build_parser(__doc__)
    args = parser.parse_args()

    catalog = read_catalog(CATALOG_PATH)
    params = read_params(PARAMS_PATH)
    cao = pipeline.now()

    with psycopg.connect(pipeline.resolve_dsn(args)) as connection:
        cursor = connection.cursor()
        source_id = pipeline.register_source(cursor, USER, cao)

        # The files are the whole truth, so the tables mirror them exactly.
        cursor.execute("DELETE FROM heuristics")
        for hid, tag, name, category, formula, inputs, status, why in catalog:
            cursor.execute(
                "INSERT INTO heuristics (heuristic_id, tag, name, category,"
                " formula, inputs, status, rationale, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (hid, tag, name, category, formula, inputs, status, why,
                 source_id),
            )
        cursor.execute("DELETE FROM heuristic_params")
        for code, value, note in params:
            cursor.execute(
                "INSERT INTO heuristic_params (code, value, note, source_id)"
                " VALUES (%s, %s, %s, %s)",
                (code, value, note, source_id),
            )
        connection.commit()
        pipeline.export_raw(connection, args, ("heuristics",
                                               "heuristic_params"))

    live = sum(1 for r in catalog if r[6] == "live")
    print("authored heuristics: %d in the catalog (%d live), %d params"
          % (len(catalog), live, len(params)))


if __name__ == "__main__":
    try:
        main()
    except (HeuristicError, OSError, ValueError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
