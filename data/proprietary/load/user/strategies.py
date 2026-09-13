"""Store: strategies/*.md - free-form strategy notes.

Each markdown file becomes one row, title from the filename, body verbatim.
The directory is the whole truth; an empty directory is a valid state. The
inference layer's heuristics live elsewhere (inference/heuristics/); these
are the operator's own notes, cited as facts.

    python -m data.proprietary.load.user.strategies
"""

import os
import sys

import psycopg

from data.proprietary import pipeline
from data.proprietary.pipeline import USER

STRATEGIES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "strategies")


def read_files(directory):
    out = []
    if not os.path.isdir(directory):
        return out
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".md") or name == "README.md":
            continue
        with open(os.path.join(directory, name), encoding="utf-8") as handle:
            body = handle.read().strip()
        if body:
            out.append((name[:-3].replace("_", " ").replace("-", " "), body))
    return out


def run(connection, directory=STRATEGIES_DIR, log=print):
    rows = read_files(directory)
    cursor = connection.cursor()
    source_id = pipeline.register_source(cursor, USER, pipeline.now())
    cursor.execute("DELETE FROM strategies")
    for title, body in rows:
        cursor.execute(
            "INSERT INTO strategies (title, body, source_id)"
            " VALUES (%s, %s, %s)", (title, body, source_id))
    connection.commit()
    log("strategies: %d loaded" % len(rows))
    return {"strategies": len(rows), "tables": ["strategies"]}


def main():
    parser = pipeline.build_parser(__doc__)
    args = parser.parse_args()
    with psycopg.connect(pipeline.resolve_dsn(args)) as connection:
        summary = run(connection)
        pipeline.export_raw(connection, args, summary["tables"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
