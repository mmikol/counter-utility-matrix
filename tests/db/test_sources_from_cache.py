"""Every source's page-to-table path, driven from the page caches the pulls
leave behind (`.cache-*`): parse, clean, store - no network. Each pull runs
for real inside one transaction that is rolled back at the end, so the
built database is exactly as it was (a rates pull would otherwise append a
dated snapshot every run). Skipped without the caches or the database."""

import os

import psycopg
import pytest
import requests

from db import CACHE_DIRS
from door.mcp import tools

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


def _offline(self, url, params=None, **kwargs):
    """requests.Session.get for a pull that must read only the page cache."""
    raise AssertionError("%s %s is not in the page cache" % (url, params or ""))


@needs_caches
def test_blizzard_roster_pulls_from_the_cache(ctx):
    text, data = tools.run_tool(ctx, "pull_heroes")
    assert text.startswith("pull_heroes: roster stored") and data["heroes"] >= 50
    assert "heroes" in data["tables"]
    assert data["missing"] == []                 # every hero page read from the cache


@needs_caches
def test_blizzard_rates_pull_from_the_cache_and_leave_no_snapshot(ctx, snapshots, db, monkeypatch):
    # a page missing from the cache fails at once: the request loop retries
    # only a requests failure, so the pull neither waits out six attempts nor
    # reads the live site at 5 s a page
    monkeypatch.setattr(requests.Session, "get", _offline)
    text, data = tools.run_tool(ctx, "pull_rates")
    assert text.startswith("pull_rates: snapshot stored")
    assert data["tables"] == ["regions", "competitive_tiers", "meta_snapshots",
                              "hero_meta", "map_meta"]
    assert data["queue"] == "competitive_role_queue" and data["tiers"] >= 8
    assert data["hero_rows"] > 0 and data["map_rows"] > 0
    assert data["unmatched"] == [] and data["skipped_maps"] == []
    # the pull counts inside its own transaction, which holds the snapshot it stamped
    assert data["snapshots"] == snapshots + 1
    db.rollback()
    assert db.execute("select count(*) from meta_snapshots").fetchone()[0] == snapshots


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


class _Kept:
    """One connection for several tools: each leaves it open and uncommitted."""

    def __init__(self, connection):
        self._connection = connection
        connection.commit = lambda: None

    def __enter__(self):
        return self._connection

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def shared(db, dsn):
    """(context, connection): every tool writes on the one connection, which the
    test reads and the teardown rolls back."""
    connection = psycopg.connect(dsn)

    class Shared(tools.Context):
        def connect(self):
            return _Kept(connection)

    yield Shared(dsn=dsn), connection
    connection.rollback()
    connection.close()


STAGES_BY_MAP = """
    select g.code, m.name, coalesce(array_agg(s.name order by s.position)
                                    filter (where s.name is not null), '{}')
    from maps m join map_modes mm using (map_id) join game_modes g using (mode_id)
    left join map_stages s using (map_id) group by g.code, m.name"""


@needs_caches
def test_wiki_maps_store_each_modes_stages(shared):
    ctx, connection = shared
    text, data = tools.run_tool(ctx, "pull_maps")
    assert "maps_with_stages" in text and data["missing"] == []
    stages = {}
    for code, name, names in connection.execute(STAGES_BY_MAP):
        stages.setdefault(code, {})[name] = names

    # Control: three stages. Flashpoint: five points. Hybrid: the two phases.
    assert len(stages["control"]) >= 7 and len(stages["flashpoint"]) >= 3
    assert all(len(names) == 3 for names in stages["control"].values())
    assert all(len(names) == 5 for names in stages["flashpoint"].values())
    assert len(stages["hybrid"]) >= 8
    assert all(names == ["Assault", "Escort"] for names in stages["hybrid"].values())
    # Push: whole
    assert stages["push"] and not any(stages["push"].values())
    # Escort: the stretches an article names, none where it names none
    assert stages["escort"]["Havana"] == ["City Streets", "Distillery", "Sea Fort"]
    assert stages["escort"]["Rialto"] == [
        "The Grand Hotel and Courtyard", "The Rialto Bridge and Dock",
        "Talon Headquarters"]                       # not its Gondola Rides
    assert stages["escort"]["Dorado"] == [] and stages["escort"]["Junkertown"] == []
    assert all(len(names) in (0, 3) for names in stages["escort"].values())
    assert stages["control"]["Ilios"] == ["Lighthouse", "Well", "Ruins"]

    assert data["maps_with_stages"] == {
        code: sum(1 for names in maps.values() if names)
        for code, maps in stages.items() if any(maps.values())}
    assert data["stages"] == sum(len(names) for maps in stages.values()
                                 for names in maps.values())


@needs_caches
def test_wiki_terrain_pulls_the_stages_terrain_after_the_maps(shared):
    ctx, connection = shared
    order = [spec.name for spec in tools.REGISTRY.pulls()]
    assert order.index("pull_maps") < order.index("pull_terrain")
    tools.run_tool(ctx, "pull_maps")
    text, data = tools.run_tool(ctx, "pull_terrain")
    assert text.startswith("pull_terrain: terrain stored")
    assert data["tables"] == ["map_terrain", "stage_terrain"]
    assert data["stage_rows"] == data["stages"] * 8 > 0
    assert data["stages"] + data["stages_no_text"] == connection.execute(
        "select count(*) from map_stages").fetchone()[0]
    # every row hangs off a stage of a map that has stages
    assert connection.execute(
        "select count(*), count(distinct t.stage_id) from stage_terrain t"
        " join map_stages s using (stage_id)").fetchone() == (
        data["stage_rows"], data["stages"])


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
def test_wiki_counters_pull_from_the_cache_and_stamp_no_snapshot(ctx, snapshots, db):
    text, data = tools.run_tool(ctx, "pull_counters")
    assert text.startswith("pull_counters: counters stored") and data["counters"] > 100
    assert data["tables"] == ["counters"] and data["unmatched"] == [] and data["missing"] == []
    assert data["articles"] >= 40 and data["cells"] > data["no_verdict"] > 0
    assert 0 < data["rated"] < data["cells"]
    # a hero in no edge is one no article wrote about, its own included
    assert set(data["no_edge"]) <= set(data["unwritten"])
    db.rollback()
    assert db.execute("select count(*) from meta_snapshots").fetchone()[0] == snapshots
    # the pull's edges are the table's: the built database holds the same count
    assert db.execute("select count(*) from counters").fetchone()[0] == data["counters"]


@needs_caches
def test_wiki_seasons_and_synergies_pull_from_the_cache(ctx, snapshots):
    text, data = tools.run_tool(ctx, "pull_seasons")
    assert text.startswith("pull_seasons: seasons stored") and data["seasons"] > 20
    assert data["stamped"] == snapshots and data["tables"] == ["seasons", "meta_snapshots"]
    text, data = tools.run_tool(ctx, "pull_synergies")
    assert text.startswith("pull_synergies: pairs stored") and data["synergies"] > 100
    assert 0 < data["mutual"] < data["synergies"] and data["unmatched"] == []
    assert data["missing"] == []


@needs_caches
def test_load_authored_mirrors_the_strategies_and_nothing_else(ctx):
    from inference import catalog
    text, data = tools.run_tool(ctx, "load_authored")
    assert text.startswith("load_authored: strategies ") and set(data) == {"strategies"}
    assert data["strategies"]["total"] == len(catalog.load())
    assert data["strategies"]["tables"] == ["strategies"]
