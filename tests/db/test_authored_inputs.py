"""The one input a user writes is the playbook. Every other table is pulled
from Blizzard or the wiki: load_authored takes the playbook alone, no table
but `strategies` carries the `user` source, and no third source is read."""

import contextlib
import os
import time

import pytest
import requests

import db
from door.mcp import tools
from door.mcp.schema import ToolReply
from inference import catalog


def test_the_catalog_holds_the_playbooks_source_row():
    assert catalog.AUTHORED.code == "user"
    assert catalog.AUTHORED.url == "inference/strategies/"
    assert os.path.join(db.ROOT, catalog.AUTHORED.url) == os.path.join(catalog.SHIPPED_DIR, "")
    assert os.path.isdir(os.path.join(db.ROOT, catalog.AUTHORED.url))


def test_load_authored_takes_strategies_and_nothing_else():
    """One input, and no argument to narrow it to: the tool takes none."""
    schema = tools.REGISTRY.get("load_authored").schema
    assert schema["properties"] == {} and schema["required"] == []


def test_seasons_and_synergies_are_pulls_in_dependency_order():
    pulls = {spec.name: spec.source for spec in tools.REGISTRY.pulls()}
    order = list(pulls)
    assert pulls["pull_seasons"] == "wiki"
    assert pulls["pull_synergies"] == "wiki"
    # a rates pull stamps its snapshot with the season live today
    assert order.index("pull_seasons") < order.index("pull_rates")
    # a synergy and a counter are pairs of heroes on the roster
    assert order.index("pull_heroes") < order.index("pull_synergies")
    assert order.index("pull_heroes") < order.index("pull_counters")
    # every pull_* tool is a pull, in the order it was registered
    assert order == [n for n in tools.REGISTRY.names() if n.startswith("pull_")]


def test_every_pull_reads_blizzard_or_the_wiki():
    assert {spec.source for spec in tools.REGISTRY.pulls()} == {"blizzard", "wiki"}
    assert set(db.CACHE_DIRS) == {"blizzard", "wiki"}
    nowhere = tools.Context(dsn="postgresql://nowhere", client="test")
    assert set(nowhere.caches) == {"blizzard", "wiki"}
    _text, data = nowhere.call("list_sources")
    assert [s["code"] for s in data["sources"]] == ["blizzard", "wiki"]
    assert sorted(t for s in data["sources"] for t in s["tools"]) == sorted(
        spec.name for spec in tools.REGISTRY.pulls())


class Offline(tools.Context):
    def connect(self):
        return contextlib.nullcontext("cx")


def test_pull_counters_runs_the_wikis_matchups(monkeypatch, tmp_path):
    from db.data.wiki import matchups
    spec = tools.REGISTRY.get("pull_counters")
    assert spec.source == "wiki"
    assert set(spec.schema["properties"]) == {"refresh"}
    text = spec.description
    assert "wiki" in text and "Match-Up" in text
    seen = {}

    def run(connection, pull):
        seen.update(connection=connection, cache_dir=pull.cache_dir)
        return {"counters": 3, "unwritten": ["Freja"], "tables": ["counters"]}
    monkeypatch.setattr(matchups, "run", run)
    # a cache folder of its own: the tool creates the one it is handed, and an
    # empty .cache-wiki at the root lets the next run's cache tests fetch
    ctx = Offline(dsn="postgresql://nowhere", caches={"wiki": str(tmp_path / "wiki")},
                  client="test")
    text, data = ctx.call("pull_counters")
    assert seen == {"connection": "cx", "cache_dir": ctx.caches["wiki"]}
    assert text.splitlines()[0] == "pull_counters: counters stored"
    assert data == {"counters": 3, "unwritten": ["Freja"], "tables": ["counters"], "stale": []}


def test_a_pull_hands_run_its_sources_cache_and_the_context_log(monkeypatch, tmp_path):
    from db.data.blizzard import meta
    seen = {}

    def run(connection, pull):
        seen.update(connection=connection, pull=pull)
        return {"snapshots": 1, "tables": ["meta_snapshots"]}
    monkeypatch.setattr(meta, "run", run)
    ctx = Offline(dsn="postgresql://nowhere", caches={"blizzard": str(tmp_path / "blizzard")},
                  log=lambda line: None, client="test")
    began = time.time()
    text, _ = ctx.call("pull_rates", refresh=True)
    assert text.splitlines()[0] == "pull_rates: snapshot stored"
    assert seen["connection"] == "cx"
    assert seen["pull"].cache_dir == ctx.caches["blizzard"]
    assert seen["pull"].log is ctx.log
    # refresh: every page cached before the call began is stale
    assert began <= seen["pull"].cutoff <= time.time()
    assert seen["pull"].max_age is None
    ctx.call("pull_rates")
    assert seen["pull"].cutoff is None and seen["pull"].max_age is None   # a build keeps every page


class Synced(Offline):
    """A context whose sync reaches the pulls and stops short of the
    database: the strategies mirror and the export answer empty."""

    def call(self, name, /, **arguments):
        if name in ("load_authored", "export_csv"):
            return ToolReply("%s: skipped" % name, {})
        return super().call(name, **arguments)


def test_a_full_refresh_holds_every_pull_to_the_moment_it_began(monkeypatch, tmp_path):
    """sync_all refreshes against one cutoff, so the hero article pull_kits
    refetched is read from the cache by pull_synergies and pull_counters, and
    a map article pull_maps refetched by pull_terrain."""
    from door.mcp import pulls
    seen = []

    def run(connection, pull, **options):
        seen.append((pull.cutoff, pull.max_age))
        return {"tables": []}

    def no_request(*args, **kwargs):
        raise AssertionError("a stubbed pull asks the network for nothing")
    monkeypatch.setattr(requests.Session, "get", no_request)
    for module in (pulls.blizzard_heroes, pulls.wiki_heroes, pulls.wiki_maps,
                   pulls.wiki_terrain, pulls.wiki_patches, pulls.wiki_seasons,
                   pulls.blizzard_meta, pulls.wiki_playstyles, pulls.wiki_synergies,
                   pulls.wiki_matchups):
        monkeypatch.setattr(module, "run", run)
    caches = {"blizzard": str(tmp_path / "blizzard"), "wiki": str(tmp_path / "wiki")}
    ctx = Synced(dsn="postgresql://nowhere", caches=caches, log=lambda line: None,
                 client="test")
    began = time.time()
    ctx.call("sync_all", refresh=True)
    assert len(seen) == len(tools.REGISTRY.pulls())
    [(cutoff, max_age)] = set(seen)
    assert began <= cutoff <= time.time() and max_age is None
    assert ctx.cutoff is None                       # the caller's context holds none
    seen.clear()
    ctx.call("sync_all")
    assert set(seen) == {(None, None)}              # a build keeps every cached page


def test_a_stale_page_is_named_in_the_pull_reply(monkeypatch, tmp_path):
    """A page whose refetch failed and whose cached copy was read reaches the
    reply's data under stale, and its count ends the headline the refresher
    logs."""
    from db.data.blizzard import meta

    def run(connection, pull):
        pull.stale.append("rates_x.html: gone")
        return {"snapshots": 1, "tables": ["meta_snapshots"]}
    monkeypatch.setattr(meta, "run", run)
    ctx = Offline(dsn="postgresql://nowhere", caches={"blizzard": str(tmp_path / "blizzard")},
                  log=lambda line: None, client="test")
    text, data = ctx.call("pull_rates", refresh=True)
    assert text.splitlines()[0] == "pull_rates: snapshot stored; stale: 1"
    assert data["stale"] == ["rates_x.html: gone"]
    assert "  stale            rates_x.html: gone" in text.splitlines()


def test_a_pull_that_stores_no_table_says_nothing_stored(monkeypatch, tmp_path):
    """pull_rates stamps no snapshot from a stale page: its run() writes no
    table, and the headline says so in place of "snapshot stored"."""
    from db.data.blizzard import meta

    def run(connection, pull):
        pull.stale.append("rates_x.html: gone")
        return {"snapshot_id": None, "tables": []}
    monkeypatch.setattr(meta, "run", run)
    ctx = Offline(dsn="postgresql://nowhere", caches={"blizzard": str(tmp_path / "blizzard")},
                  log=lambda line: None, client="test")
    text, data = ctx.call("pull_rates", refresh=True)
    assert text.splitlines()[0] == "pull_rates: nothing stored; stale: 1"
    assert data["tables"] == [] and data["snapshot_id"] is None


def test_the_sentry_scans_the_wiki_tables_and_the_playbook():
    from door import sentry
    assert {"synergies", "seasons", "strategies"} <= {table for table, _ in sentry.TEXT_COLUMNS}


def test_the_data_dictionary_says_where_seasons_and_synergies_come_from():
    # 018's COMMENT ON TABLE replaces the prose 004 wrote above CREATE TABLE
    # seasons; 005's prose above CREATE TABLE synergies is kept current itself
    from db.psql import schema
    described = schema._migration_tables()
    assert described["seasons"][0] == "004_meta.sql"           # the domain stays the creator's
    assert described["synergies"][0] == "005_playbook.sql"
    assert "pull_seasons" in described["seasons"][1]
    assert "wiki's Season pages" in described["seasons"][1]    # '' unescaped
    assert "pull_synergies" in described["synergies"][1]
    assert "hero's wiki article" in described["synergies"][1]
    for table in ("seasons", "synergies"):
        assert "authored" not in described[table][1].lower(), table
        assert ".csv" not in described[table][1], table
    assert "pull_patches" in described["patches"][1] and "season" not in described["patches"][1]


def test_the_data_dictionary_says_counters_are_the_wikis_matchups():
    # 019's COMMENT ON TABLE replaces the prose 005 wrote about counterpick.gg
    from db.psql import schema
    described = schema._migration_tables()
    assert described["counters"][0] == "005_playbook.sql"
    prose = described["counters"][1]
    assert "pull_counters" in prose and "wiki article" in prose and "Match-Up" in prose
    assert "countered_by_id answers hero_id" in prose
    assert "loader" not in prose and "tooltip" not in prose     # 005's, about counterpick


def test_the_migration_that_drops_counterpick_is_one_transaction():
    from db.psql import schema
    [sql] = [
        m.sql for m in schema.read_migrations() if m.name == "019_wiki_replaces_counterpick.sql"]
    body = [line for line in sql.splitlines() if line and not line.startswith("--")]
    assert body[0] == "BEGIN;" and body[-1] == "COMMIT;"
    assert "DROP TABLE IF EXISTS map_strategy;" in body
    # children before parents: rates, their snapshots, counters, then the source
    order = [sql.index(statement) for statement in (
        "DELETE FROM hero_meta", "DELETE FROM meta_snapshots", "DELETE FROM counters",
        "DELETE FROM sources WHERE code = 'counterpick';")]
    assert order == sorted(order)


def test_a_table_name_that_reaches_sql_text_is_checked():
    """psycopg parameterises values, never identifiers, so a name reaches SQL
    text only as the sql.Identifier psql.identifier returns once the name has
    passed its check. The names all come from a literal or the catalog; this
    is what keeps it so."""
    from psycopg.sql import Identifier

    from db.psql import identifier
    for good in ("heroes", "ability_stats", "weapon_configs", "hero_id", "_x9"):
        assert identifier(good) == Identifier(good)
    for bad in ("heroes; drop table heroes", "Heroes", "hero-id", "", None, "1table",
                "heroes ", "heroes--", "*"):
        with pytest.raises(ValueError, match="not a SQL identifier"):
            identifier(bad)


def test_every_path_the_layer_declares_exists():
    # the folder move once doubled a segment of one of these; the containers
    # found out, the suite did not - now it does
    from db.psql import schema
    for path in (schema.MIGRATIONS_DIR, catalog.strategies_dir(),
                 os.path.join(db.ROOT, "docs")):
        assert os.path.isdir(path), path
    # the CSV mirror is created on first export and never committed: scraped
    # text and rates stay out of the public repository
    assert db.RAW_DIR.endswith(os.path.join("db", "raw"))
    with open(os.path.join(db.ROOT, ".gitignore"), encoding="utf-8") as handle:
        assert "db/raw/" in handle.read().split()


# --- the built database ----------------------------------------------------

@pytest.mark.invariant
def test_only_strategies_carries_the_user_source(rows):
    tables = [t for (t,) in rows(
        "select table_name from information_schema.columns"
        " where table_schema = 'public' and column_name = 'source_id'"
        " and table_name <> 'sources' order by 1")]
    assert "strategies" in tables
    carrying = [t for t in tables if rows(
        "select 1 from %s t join sources s using (source_id)"
        " where s.code = 'user' limit 1" % t)]
    assert carrying == ["strategies"]


@pytest.mark.invariant
def test_the_dropped_tables_are_gone_and_no_table_is_empty(rows, one):
    tables = [t for (t,) in rows(
        "select tablename from pg_tables where schemaname = 'public' order by 1")]
    assert not {"map_playstyle", "comp_archetypes", "map_strategy"} & set(tables)
    empty = [t for t in tables if one("select count(*) from %s" % t) == 0]
    assert empty == []


@pytest.mark.invariant
def test_the_sources_are_blizzard_the_wiki_and_the_playbook(rows):
    assert {c for (c,) in rows("select code from sources")} == {"blizzard", "wiki", "user"}


@pytest.mark.invariant
def test_seasons_synergies_and_counters_come_from_the_wiki(rows):
    for table in ("seasons", "synergies", "counters"):
        assert {c for (c,) in rows(
            "select distinct s.code from %s t join sources s using (source_id)"
            % table)} == {"wiki"}, table
