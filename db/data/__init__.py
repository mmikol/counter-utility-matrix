"""The sources: one package per source, each owning the whole path from
page to table, plus what they share.

    blizzard/     the official site: heroes (roster, roles, portraits,
                  text), meta (rates as dated snapshots)
    wiki/         the MediaWiki endpoint: heroes (kits, numbers, keywords),
                  maps, patches, seasons, playstyles, synergies, matchups
                  (counters) - and the markup, measurement, weapon and
                  modifier readers the kit data needs
    authored/     the source row of the one input a user writes, the
                  strategies in inference/strategies/
    fetch         the page cache, its freshness policy and the request loop
    names         matching hero, map and ability names across sources
    returned_int  the int a writer's statement returned: an id, a count

Each fetched source's domain module ends in a
run(connection, cache_dir, session, log); authored/ has no run - the
strategies mirror is inference.catalog.mirror.
The MCP tools call them. Nothing here is an entry point of its own.
"""

import psycopg


def returned_int(cursor: psycopg.Cursor) -> int:
    """The int in the one row the cursor's last statement returned - an id
    from RETURNING, a count. A statement that returned no row is a broken
    statement, raised as LookupError."""
    row = cursor.fetchone()
    if row is None:
        raise LookupError("the statement returned no row")
    value: int = row[0]
    return value
