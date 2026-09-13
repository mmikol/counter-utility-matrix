"""Store: seasons.csv - the coarse delineator of snapshots.

Authored rather than scraped, because the wiki's season pages are lore
articles with no dates. Loading also RECOMPUTES season_id on every existing
snapshot, so a season added later corrects history.

    python -m data.load.authored.seasons
"""

import csv
import os
import sys
from datetime import date

import psycopg

from data import common
from data.sources.authored import AUTHORED

CSV_PATH = os.path.join(common.AUTHORED_DIR, "seasons.csv")


class SeasonError(Exception):
    pass


def read_rows(path):
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = ["name", "started", "note"]
        if reader.fieldnames != expected:
            raise SeasonError("%s: header must be %s, found %s"
                             % (path, ",".join(expected), reader.fieldnames))
        for n, row in enumerate(reader, start=2):
            name = row["name"].strip()
            if not name:
                raise SeasonError("line %d: name is required" % n)
            if name.lower() in seen:
                raise SeasonError("line %d: duplicate season %s" % (n, name))
            seen.add(name.lower())
            try:
                started = date.fromisoformat(row["started"].strip())
            except ValueError:
                raise SeasonError("line %d: started must be YYYY-MM-DD" % n)
            rows.append((name, started, row["note"].strip() or None))
    return rows


def run(connection, path=CSV_PATH, log=print):
    rows = read_rows(path)
    cursor = connection.cursor()
    source_id = common.register_source(cursor, AUTHORED, common.now())
    cursor.execute("UPDATE meta_snapshots SET season_id = NULL")
    cursor.execute("DELETE FROM seasons")
    for name, started, note in rows:
        cursor.execute(
            "INSERT INTO seasons (name, started, note, source_id)"
            " VALUES (%s, %s, %s, %s)", (name, started, note, source_id))
    cursor.execute(
        "UPDATE meta_snapshots ms SET season_id ="
        " (SELECT season_id FROM seasons s"
        "  WHERE s.started <= ms.captured_at::date"
        "  ORDER BY s.started DESC, s.season_id DESC LIMIT 1)")
    stamped = cursor.rowcount
    connection.commit()
    log("seasons: %d loaded; %d snapshots stamped" % (len(rows), stamped))
    return {"seasons": len(rows), "stamped": stamped,
            "tables": ["seasons", "meta_snapshots"]}


def main():
    parser = common.build_parser(__doc__)
    args = parser.parse_args()
    with psycopg.connect(common.resolve_dsn(args)) as connection:
        summary = run(connection)
        common.export_raw(connection, args, summary["tables"])


if __name__ == "__main__":
    try:
        main()
    except (SeasonError, OSError, ValueError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
