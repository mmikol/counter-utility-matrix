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


KIT_ROWS = """
    select h.name, a.name, k.code, s.value::float, s.unit_numerator,
           s.unit_denominator, s.condition
    from ability_stats s join abilities a using (ability_id)
    join heroes h using (hero_id) join stat_keys k using (stat_key_id)
    where (h.name, a.name, k.code) in (('Symmetra', 'Sentry Turret', 'mspeed_slow'),
        ('Mizuki', 'Healing Kasa', 'heal'), ('Reaper', 'Death Blossom', 'damage'),
        ('Symmetra', 'Teleporter', 'ult_req'), ('Symmetra', 'Photon Barrier', 'cooldown'))
    order by h.name, a.name, s.value desc"""


class _ReadThenRolledBack(_RolledBack):
    """Reads the kit rows the pull wrote, then rolls back like the rest."""

    def __init__(self, connection, seen):
        super().__init__(connection)
        self._seen = seen

    def __exit__(self, *exc):
        if exc[0] is None:
            self._seen.extend(self._connection.execute(KIT_ROWS).fetchall())
        return super().__exit__(*exc)


@needs_caches
def test_wiki_kits_store_the_numbers_the_pages_publish(db, dsn):
    seen = []

    class Reading(tools.Context):
        def connect(self):
            return _ReadThenRolledBack(psycopg.connect(self.dsn), seen)

    tools.run_tool(Reading(dsn=dsn), "pull_kits")
    assert seen == [
        # Cargo's heal is empty for Kasa; the article supplies it
        ("Mizuki", "Healing Kasa", "heal", 90.0, "hp", None, "1st bounce"),
        ("Mizuki", "Healing Kasa", "heal", 70.0, "hp", None, "2nd bounce"),
        ("Mizuki", "Healing Kasa", "heal", 50.0, "hp", None, "3rd bounce"),
        ("Mizuki", "Healing Kasa", "heal", 30.0, "hp", None, "self"),
        # "185/s per enemy" is a rate
        ("Reaper", "Death Blossom", "damage", 185.0, "hp", "seconds", None),
        # written with U+2212; no row from the retired "(old)" blocks
        ("Symmetra", "Sentry Turret", "mspeed_slow", -15.0, "percent", None, None),
    ]


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
