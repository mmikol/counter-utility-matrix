"""Map and stage terrain pulled from the wiki page cache: run() inside a
transaction that is rolled back, the tables it fills and the ground the
well-known maps and stages are known for. Skipped without the cache or the
database."""

import os

import pytest

from db import CACHE_DIRS
from db.data.wiki import maps, terrain

needs_cache = pytest.mark.skipif(
    not os.path.isdir(CACHE_DIRS["wiki"]), reason="the wiki page cache is not on this machine")


# --- the page cache -> the table -----------------------------------------------

def terrain_of(connection, name):
    return {feature: (mentions, per_thousand) for feature, mentions, per_thousand
            in connection.execute(
                "select t.feature, t.mentions, t.per_thousand from map_terrain t"
                " join maps m using (map_id) where m.name = %s", (name,))}


@needs_cache
@pytest.mark.invariant
def test_terrain_pulls_from_the_cache(sandbox):
    data = terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    rows = sandbox.execute(
        "select t.map_id, t.feature, t.mentions, t.per_thousand, src.code"
        " from map_terrain t join sources src using (source_id)").fetchall()
    total = sandbox.execute("select count(*) from maps").fetchone()[0]

    assert set(data) == {"maps", "without_text", "missing", "rows", "words", "stages",
                         "stages_no_text", "stage_rows", "tables"}
    assert data["missing"] == []                  # every article fetched from the cache
    assert data["tables"] == ["map_terrain", "stage_terrain"]
    assert data["rows"] == len(rows) == data["maps"] * len(terrain.FEATURES)
    assert data["maps"] + len(data["without_text"]) == total
    # most maps' articles describe their ground; the thin ones are named
    assert data["maps"] > total / 2
    assert data["words"] >= data["maps"] * terrain.MIN_WORDS

    assert {code for *_, code in rows} == {"wiki"}
    assert {feature for _, feature, *_ in rows} == set(terrain.FEATURES)
    assert all(mentions >= 0 and per_thousand >= 0
               for _, _, mentions, per_thousand, _ in rows)
    assert all((mentions == 0) == (per_thousand == 0)
               for _, _, mentions, per_thousand, _ in rows)
    by_map = {}
    for map_id, feature, *_ in rows:
        by_map.setdefault(map_id, set()).add(feature)
    assert all(features == set(terrain.FEATURES) for features in by_map.values())


@needs_cache
@pytest.mark.invariant
def test_the_wiki_states_the_well_known_ground(sandbox):
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)

    # King's Row: narrow streets, the first chokepoint, the gateway
    kings_row = terrain_of(sandbox, "King's Row")
    assert kings_row["chokes"][0] >= 3
    assert max(kings_row, key=lambda f: kings_row[f][1]) == "chokes"
    # Ilios: the hole in the middle of the Well
    ilios = terrain_of(sandbox, "Ilios")
    assert ilios["hazards"][0] >= 2
    assert max(ilios, key=lambda f: ilios[f][1]) == "hazards"
    # Lijiang Tower: environmental kills on the bridges
    assert terrain_of(sandbox, "Lijiang Tower")["hazards"][0] >= 2
    # Havana: "the massive sightlines", "long open stretches"
    havana = terrain_of(sandbox, "Havana")
    assert havana["sightlines"][0] >= 3 and havana["open_ground"][0] >= 2
    # Eichenwalde: "the multitude of chokepoints", the castle interior
    eichenwalde = terrain_of(sandbox, "Eichenwalde")
    assert eichenwalde["chokes"][0] >= 2 and eichenwalde["interiors"][0] >= 2


def stage_terrain_of(connection, map_name, stage):
    return {feature: (mentions, per_thousand) for feature, mentions, per_thousand
            in connection.execute(
                "select t.feature, t.mentions, t.per_thousand from stage_terrain t"
                " join map_stages s using (stage_id) join maps m using (map_id)"
                " where m.name = %s and s.name = %s", (map_name, stage))}


@needs_cache
@pytest.mark.invariant
def test_stage_terrain_pulls_from_the_cache(sandbox):
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    data = terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    rows = sandbox.execute(
        "select t.stage_id, t.feature, t.mentions, t.per_thousand, src.code"
        " from stage_terrain t join sources src using (source_id)").fetchall()
    total = sandbox.execute("select count(*) from map_stages").fetchone()[0]

    assert data["stage_rows"] == len(rows) == data["stages"] * len(terrain.FEATURES)
    assert data["stages"] + data["stages_no_text"] == total
    # most stages are a name in a list; the wiki writes about some
    assert 20 <= data["stages"] < total

    assert {code for *_, code in rows} == {"wiki"}
    assert all(mentions >= 0 and (mentions == 0) == (per_thousand == 0)
               for _, _, mentions, per_thousand, _ in rows)
    by_stage = {}
    for stage_id, feature, *_ in rows:
        by_stage.setdefault(stage_id, set()).add(feature)
    assert all(features == set(terrain.FEATURES) for features in by_stage.values())

    # a stage's mentions are text of its own map's article: never more than the
    # article holds, when the map's terrain is stored
    assert sandbox.execute(
        "select count(*) from stage_terrain t join map_stages s using (stage_id)"
        " join map_terrain m on m.map_id = s.map_id and m.feature = t.feature"
        " where t.mentions > m.mentions").fetchone()[0] == 0
    # no Push map holds a stage, so none holds stage terrain
    assert sandbox.execute(
        "select count(*) from stage_terrain t join map_stages s using (stage_id)"
        " join map_modes mm using (map_id) join game_modes g using (mode_id)"
        " where g.code = 'push'").fetchone()[0] == 0
    # the articles that name their route describe every stretch of it
    assert dict(sandbox.execute(
        "select m.name, count(distinct t.stage_id) from stage_terrain t"
        " join map_stages s using (stage_id) join maps m using (map_id)"
        " join map_modes mm using (map_id) join game_modes g using (mode_id)"
        " where g.code = 'escort' group by m.name").fetchall()) == {
        "Circuit Royal": 3, "Havana": 3, "Rialto": 3, "Route 66": 3}


@needs_cache
@pytest.mark.invariant
def test_the_wiki_states_a_stages_ground(sandbox):
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)

    # Ilios: "On the Well section of the map, the big hole in the middle"
    well = stage_terrain_of(sandbox, "Ilios", "Well")
    assert well["hazards"][0] == 2
    assert [f for f in well if well[f][0]] == ["hazards"]
    # the article says nothing of the other two
    assert stage_terrain_of(sandbox, "Ilios", "Lighthouse") == {}
    assert stage_terrain_of(sandbox, "Ilios", "Ruins") == {}
    # Samoa: "environmental kills on Volcano, as there is a lava moat"
    assert stage_terrain_of(sandbox, "Samoa", "Volcano")["hazards"][0] == 3
    # Lijiang Tower: Garden's bridges and knockback kills, its back route
    garden = stage_terrain_of(sandbox, "Lijiang Tower", "Garden")
    assert garden["hazards"][0] >= 3 and garden["flanks"][0] >= 2
    # Havana: the Distillery is "an enclosed building"; the Sea Fort's straight
    # has "very minimal cover" and "an environmental hazard"
    assert stage_terrain_of(sandbox, "Havana", "Distillery")["interiors"][0] >= 2
    assert stage_terrain_of(sandbox, "Havana", "City Streets")["interiors"][0] == 0
    sea_fort = stage_terrain_of(sandbox, "Havana", "Sea Fort")
    assert sea_fort["open_ground"][0] >= 1 and sea_fort["hazards"][0] >= 1
    # King's Row: defenders hold "the first chokepoint"; the payload runs
    # "the narrow streets"
    assert stage_terrain_of(sandbox, "King's Row", "Assault")["chokes"][0] >= 2
    assert stage_terrain_of(sandbox, "King's Row", "Escort")["chokes"][0] >= 2
    # Eichenwalde: The Town's "multitude of chokepoints" is the capture point's;
    # the bridge's "environmental hazards" and the castle are the payload's
    town = stage_terrain_of(sandbox, "Eichenwalde", "Assault")
    castle = stage_terrain_of(sandbox, "Eichenwalde", "Escort")
    assert town["chokes"][0] >= 2 and town["hazards"][0] == 0
    assert castle["hazards"][0] >= 1 and castle["interiors"][0] >= 2
    # Hollywood's Attack and Defense sections are not split by phase
    assert stage_terrain_of(sandbox, "Hollywood", "Assault") == {}


@needs_cache
@pytest.mark.invariant
def test_the_pull_replaces_the_tables_whole(sandbox):
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    counts = "select (select count(*) from map_terrain), (select count(*) from stage_terrain)"
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    first = sandbox.execute(counts).fetchone()
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    assert sandbox.execute(counts).fetchone() == first and all(first)


@needs_cache
@pytest.mark.invariant
def test_pulling_the_maps_again_keeps_the_stages_and_their_terrain(sandbox):
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    terrain.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    before = sandbox.execute(
        "select s.stage_id, s.map_id, s.position, s.name, count(t.feature)"
        " from map_stages s left join stage_terrain t using (stage_id)"
        " group by s.stage_id order by s.stage_id").fetchall()
    maps.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    assert sandbox.execute(
        "select s.stage_id, s.map_id, s.position, s.name, count(t.feature)"
        " from map_stages s left join stage_terrain t using (stage_id)"
        " group by s.stage_id order by s.stage_id").fetchall() == before
