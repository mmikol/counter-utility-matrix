"""Pull + clean + store: the wiki's Patches cargo table - game versions.

A win rate is true of a patch, and snapshots link to the most recent patch
released at capture time. Runs before the rates pulls so their snapshots
have patches to link to.
"""

from typing import NamedTuple

import psycopg

from db import psql
from db.data import PullSummary, fetch
from db.data.wiki import WIKI, cargo_query

CARGO_TABLE = "Patches"
# Cargo refuses bare underscore fields; _pageName must be aliased.
CARGO_FIELDS = ("_pageName=name", "date")


class Patch(NamedTuple):
    """A patches row as the pull writes it."""
    name: str
    released: str


def dated_patches(rows: list[dict[str, str]]) -> tuple[list[Patch], int]:
    """The Cargo rows that name a patch and its date, and how many do not: a
    page without a date anchors nothing."""
    patches: list[Patch] = []
    skipped = 0
    for row in rows:
        name, released = row.get("name"), row.get("date")
        if not name or not released:
            skipped += 1
            continue
        patches.append(Patch(name=name, released=released))
    return patches, skipped


class PatchesSummary(PullSummary):
    patches: int
    skipped: int
    latest: str | None


def run(connection: psycopg.Connection, pull: fetch.PullContext) -> PatchesSummary:
    """Upsert every dated patch from the Patches cargo table -> the patches
    loaded, the undated ones skipped and the latest."""
    patches, skipped = dated_patches(cargo_query(pull, CARGO_TABLE, CARGO_FIELDS))

    cursor = connection.cursor()
    source_id = psql.register_source(cursor, WIKI, psql.now())
    for patch in patches:
        cursor.execute(
            "INSERT INTO patches (name, released, source_id) VALUES (%s, %s, %s)"
            " ON CONFLICT (name) DO UPDATE SET released = EXCLUDED.released,"
            " source_id = EXCLUDED.source_id, cao = now()",
            (*patch, source_id),
        )
    connection.commit()
    latest = cursor.execute(
        "SELECT name, released FROM patches ORDER BY released DESC LIMIT 1"
    ).fetchone()
    pull.log("patches: %d loaded, %d skipped (no date)" % (len(patches), skipped))
    return {"patches": len(patches), "skipped": skipped,
            "latest": "%s (%s)" % latest if latest else None,
            "tables": ["patches"]}
