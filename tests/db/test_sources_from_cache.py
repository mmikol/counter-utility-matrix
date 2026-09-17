"""Every source's page-to-table path, driven from the page caches the pulls
leave behind (`.cache-*`): parse, clean, store - no network. Each pull runs
for real inside one transaction that is rolled back at the end, so the
built database is exactly as it was (a rates pull would otherwise append a
dated snapshot every run). Skipped without the caches or the database."""

import os

import psycopg
import pytest

from db import CACHE_DIRS
from db.mcp import tools

pytestmark = pytest.mark.invariant

needs_caches = pytest.mark.skipif(
    not all(os.path.isdir(path) for path in CACHE_DIRS.values()),
    reason="the page caches are not on this machine")


class _RolledBack:
    """A connection the tools may commit as much as they like: nothing lands."""

    def __init__(self, connection):
        self._connection = connection
        connection.commit = lambda: None

    def __enter__(self):
        return self._connection

    def __exit__(self, *exc):
        self._connection.rollback()
        self._connection.close()
        return False


class Sandbox(tools.Context):
    def connect(self):
        return _RolledBack(psycopg.connect(self.dsn))


@pytest.fixture()
def ctx(db, dsn):
    return Sandbox(dsn=dsn)


@pytest.fixture()
def snapshots(db):
    return db.execute("select count(*) from meta_snapshots").fetchone()[0]


@needs_caches
def test_blizzard_roster_pulls_from_the_cache(ctx):
    text, data = tools.run_tool(ctx, "pull_heroes")
    assert text.startswith("pull_heroes: roster stored") and data["heroes"] >= 50
    assert "heroes" in data["tables"]


@needs_caches
def test_wiki_kits_pull_from_the_cache_and_keep_the_announced(ctx):
    _text, data = tools.run_tool(ctx, "pull_kits")
    assert data["cargo_rows"] > 500 and "abilities" in data["tables"]
    assert "All heroes" in data["unknown_heroes"]          # wiki pages that are not heroes
    assert isinstance(data["announced"], list)


@needs_caches
def test_wiki_maps_patches_and_playstyles_pull_from_the_cache(ctx):
    text, data = tools.run_tool(ctx, "pull_maps")
    assert text.startswith("pull_maps:") and data["modes"] == 5 and data["stages"] >= 2
    text, data = tools.run_tool(ctx, "pull_patches")
    assert text.startswith("pull_patches: patches stored") and data["patches"] > 0
    text, data = tools.run_tool(ctx, "pull_playstyles")
    assert text.startswith("pull_playstyles:") and data["links"] > 0
    assert {name.lower() for name in data["playstyles"]} >= {"dive", "brawl", "poke"}


@needs_caches
def test_counterpick_pulls_from_the_cache_and_leaves_no_snapshot_behind(ctx, snapshots, db):
    text, data = tools.run_tool(ctx, "pull_counters")
    assert text.startswith("pull_counters:") and data["counters"] > 100
    assert data["queue"] == "competitive_unspecified_queue"
    db.rollback()
    assert db.execute("select count(*) from meta_snapshots").fetchone()[0] == snapshots


@needs_caches
def test_load_authored_reads_every_authored_input(ctx):
    text, data = tools.run_tool(ctx, "load_authored")
    assert text.startswith("load_authored:") and set(data) == set(tools.AUTHORED_INPUTS)
