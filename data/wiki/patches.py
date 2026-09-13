"""Pull + clean + store: the wiki's Patches cargo table - game versions.

A win rate is true of a patch, and snapshots link to the most recent patch
released at capture time. Runs before the rates pulls so their snapshots
have patches to link to.
"""


from data import common, sources
from data.wiki import WIKI, cargo_query

CARGO_TABLE = "Patches"
# Cargo refuses bare underscore fields; _pageName must be aliased.
CARGO_FIELDS = ("_pageName=name", "date", "platform", "source")


def run(connection, cache_dir=None, session=None, log=print):
    session = sources.session(session)
    rows = cargo_query(session, CARGO_TABLE, CARGO_FIELDS, cache_dir)

    cursor = connection.cursor()
    source_id = common.register_source(cursor, WIKI, common.now())
    loaded, skipped = 0, 0
    for row in rows:
        name, released = row.get("name"), row.get("date")
        if not name or not released:
            skipped += 1          # a page without a date anchors nothing
            continue
        cursor.execute(
            "INSERT INTO patches (name, released, platform, url, source_id)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (name) DO UPDATE SET released = EXCLUDED.released,"
            " platform = EXCLUDED.platform, url = EXCLUDED.url,"
            " source_id = EXCLUDED.source_id, cao = now()",
            (name, released, row.get("platform") or None,
             row.get("source") or None, source_id),
        )
        loaded += 1
    connection.commit()
    latest = cursor.execute(
        "SELECT name, released FROM patches ORDER BY released DESC LIMIT 1"
    ).fetchone()
    log("patches: %d loaded, %d skipped (no date)" % (loaded, skipped))
    return {"patches": loaded, "skipped": skipped,
            "latest": "%s (%s)" % latest if latest else None,
            "tables": ["patches"]}
