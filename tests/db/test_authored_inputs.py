"""The one input a user writes is the playbook. Every other table is pulled
from Blizzard or the wiki: no authored CSV exists, no loader reads one, no
table but `strategies` carries the `user` source, and no third source is read."""

import os

import pytest

import db
from db.data import authored
from db.mcp import tools

GONE = ("seasons.csv", "synergies.csv", "archetypes.csv", "map_playstyle.csv")


def test_the_authored_csvs_are_gone():
    folder = os.path.dirname(authored.__file__)
    assert [n for n in os.listdir(folder) if n.endswith(".csv")] == []
    for name in GONE:
        assert not os.path.exists(os.path.join(folder, name)), name


def test_the_authored_package_holds_the_source_row_and_no_loader():
    assert authored.AUTHORED[0] == "user"
    assert authored.AUTHORED[2] == "inference/strategies/"
    assert os.path.isdir(os.path.join(db.ROOT, authored.AUTHORED[2]))
    for name in ("LOADERS", "load_seasons", "load_synergies", "load_archetypes",
                 "load_map_playstyle", "read_seasons", "read_synergies",
                 "read_archetypes", "read_map_playstyle"):
        assert not hasattr(authored, name), name
    assert not hasattr(db, "AUTHORED_DIR")


def test_load_authored_takes_strategies_and_nothing_else():
    """One input, and no argument to narrow it to: the tool takes none."""
    [schema] = [s for name, _, s, _ in tools.REGISTRY if name == "load_authored"]
    assert schema["properties"] == {} and schema["required"] == []


def test_seasons_and_synergies_are_pulls_in_dependency_order():
    order = [name for name, _ in tools.PULLS]
    assert dict(tools.PULLS)["pull_seasons"] == "wiki"
    assert dict(tools.PULLS)["pull_synergies"] == "wiki"
    # a rates pull stamps its snapshot with the season live today
    assert order.index("pull_seasons") < order.index("pull_rates")
    # a synergy and a counter are pairs of heroes on the roster
    assert order.index("pull_heroes") < order.index("pull_synergies")
    assert order.index("pull_heroes") < order.index("pull_counters")
    registered = {name for name, *_ in tools.REGISTRY}
    assert {name for name, _ in tools.PULLS} <= registered


def test_every_pull_reads_blizzard_or_the_wiki():
    assert {source for _, source in tools.PULLS} == {"blizzard", "wiki"}
    assert set(db.CACHE_DIRS) == {"blizzard", "wiki"}
    assert set(tools.Context(dsn="postgresql://nowhere").caches) == {"blizzard", "wiki"}
    _text, data = tools.run_tool(tools.Context(dsn="postgresql://nowhere"), "list_sources")
    assert [s["code"] for s in data["sources"]] == ["blizzard", "wiki"]
    assert sorted(t for s in data["sources"] for t in s["tools"]) == sorted(
        name for name, _ in tools.PULLS)


def test_pull_counters_runs_the_wikis_matchups(monkeypatch):
    from db.data.wiki import matchups
    assert dict(tools.PULLS)["pull_counters"] == "wiki"
    [schema] = [s for name, _, s, _ in tools.REGISTRY if name == "pull_counters"]
    assert set(schema["properties"]) == {"refresh"}
    [text] = [d for name, d, _, _ in tools.REGISTRY if name == "pull_counters"]
    assert "wiki" in text and "Match-Up" in text
    seen = {}

    class Offline(tools.Context):
        def connect(self):
            import contextlib
            return contextlib.nullcontext("cx")

    def run(connection, cache_dir=None, session=None, log=print):
        seen.update(connection=connection, cache_dir=cache_dir)
        return {"counters": 3, "unwritten": ["Freja"], "tables": ["counters"]}
    monkeypatch.setattr(matchups, "run", run)
    ctx = Offline(dsn="postgresql://nowhere")
    text, data = tools.run_tool(ctx, "pull_counters")
    assert seen == {"connection": "cx", "cache_dir": ctx.caches["wiki"]}
    assert text.splitlines()[0] == "pull_counters: counters stored"
    assert data == {"counters": 3, "unwritten": ["Freja"], "tables": ["counters"]}


def test_counterpick_is_gone_from_the_data_layer():
    import importlib.util
    assert importlib.util.find_spec("db.data.counterpick") is None
    assert not os.path.exists(os.path.join(db.ROOT, "db", "data", "counterpick"))


def test_the_dropped_tables_are_named_nowhere_in_the_data_layer():
    from db import sentry
    gone = ("map_playstyle", "comp_archetypes", "map_strategy", "counterpick")
    for folder, _, names in os.walk(os.path.join(db.ROOT, "db")):
        if os.sep + "cluster" in folder:
            continue
        for name in names:
            if name.endswith(".py"):
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    text = handle.read()
                assert not [word for word in gone if word in text], name
    scanned = {table for table, _ in sentry.TEXT_COLUMNS}
    assert not scanned & {"comp_archetypes", "map_playstyle", "map_strategy"}
    assert {"synergies", "seasons", "strategies"} <= scanned


def test_the_data_dictionary_says_where_seasons_and_synergies_come_from():
    # a statement in an applied migration is never edited: 018's COMMENT ON
    # TABLE replaces the prose 004 and 005 wrote above their CREATE TABLE
    from db.psql import schema
    described = schema._migration_tables()
    assert described["seasons"][0] == "004_meta.sql"           # the domain stays the creator's
    assert described["synergies"][0] == "005_playbook.sql"
    assert "pull_seasons" in described["seasons"][1]
    assert "pull_synergies" in described["synergies"][1]
    assert "hero's wiki article" in described["synergies"][1]   # '' unescaped
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
    [sql] = [text for path, text in schema.read_migrations()
             if os.path.basename(path) == "019_wiki_replaces_counterpick.sql"]
    body = [line for line in sql.splitlines() if line and not line.startswith("--")]
    assert body[0] == "BEGIN;" and body[-1] == "COMMIT;"
    assert "DROP TABLE IF EXISTS map_strategy;" in body
    # children before parents: rates, their snapshots, counters, then the source
    order = [sql.index(statement) for statement in (
        "DELETE FROM hero_meta", "DELETE FROM meta_snapshots", "DELETE FROM counters",
        "DELETE FROM sources WHERE code = 'counterpick';")]
    assert order == sorted(order)


def test_a_table_name_that_reaches_sql_text_is_checked():
    """psycopg parameterises values, never identifiers, so every writer that
    names a table in the statement itself goes through psql.identifier. The
    names all come from a literal or the catalog; this is what keeps it so."""
    from db.psql import identifier
    for good in ("heroes", "ability_stats", "weapon_configs", "hero_id", "_x9"):
        assert identifier(good) == good
    for bad in ("heroes; drop table heroes", "Heroes", "hero-id", "", None, "1table",
                "heroes ", "heroes--", "*"):
        with pytest.raises(ValueError, match="not a SQL identifier"):
            identifier(bad)


def test_every_path_the_layer_declares_exists():
    # the folder move once doubled a segment of one of these; the containers
    # found out, the suite did not - now it does
    from db.psql import schema
    from inference import catalog
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
