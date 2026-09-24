"""The maps the load builds from the database: the terrain z-scored across the
maps with text, the style as the rates' lift plus the terrain's lean, the
same on every load, the stages per mode and each stage's terrain. The wiki's
own maps are the point; the arithmetic on hand-built maps is
tests/ui/test_tables.py's."""

import statistics

import pytest

from ui.facts import compute, model, tables

pytestmark = pytest.mark.invariant


def test_terrain_metrics_are_z_scores_across_the_maps_with_text(world, rows):
    features = model.TERRAIN_FEATURES
    assert set(features) == {f for (f,) in rows("select distinct feature from map_terrain")}
    assert set(features) < set(compute.MAP_METRICS)
    assert not {"map." + f for f in features} & compute.TEXT_METRICS
    assert all("map." + f in compute.registry() for f in features)
    read = [m for m in world.maps.values() if m.terrain]
    assert len(read) == rows("select count(distinct map_id) from map_terrain")[0][0] >= 2
    for m in read:
        assert set(m.terrain) == set(features)             # all eight rows, zeros included
    for f in features:
        raw = {m.id: m.terrain[f] for m in read}
        mean, sd = statistics.fmean(raw.values()), statistics.pstdev(raw.values())
        assert sd > 0
        for m in read:
            assert m.terrain_z[f] == pytest.approx((raw[m.id] - mean) / sd, abs=1e-3)
        zs = [m.terrain_z[f] for m in read]
        assert statistics.fmean(zs) == pytest.approx(0, abs=1e-3)
        assert statistics.pstdev(zs) == pytest.approx(1, abs=1e-2)
    # the wiki's King's Row: narrow streets and a first chokepoint
    kings = world.map("King's Row")
    assert max(features, key=lambda f: kings.terrain_z[f]) == "chokes"
    assert kings.terrain_z["chokes"] == max(m.terrain_z["chokes"] for m in read)


def test_a_maps_style_is_the_rates_lift_plus_the_terrains_lean(world):
    assert model.TERRAIN_LEAN == {
        "brawl": ("chokes", "interiors"), "dive": ("high_ground", "flanks", "hazards"),
        "poke": ("sightlines", "open_ground")}
    read = [m for m in world.maps.values() if m.terrain]
    for style, features in model.TERRAIN_LEAN.items():
        means = {m.id: statistics.fmean(m.terrain_z[f] for f in features) for m in read}
        mean, sd = statistics.fmean(means.values()), statistics.pstdev(means.values())
        for m in read:
            assert m.terrain_lean[style] == pytest.approx((means[m.id] - mean) / sd, abs=1e-3)
        # on the rates' scale
        assert statistics.pstdev(m.terrain_lean[style] for m in read) == pytest.approx(1, abs=1e-2)
    for m in world.maps.values():
        for style, (score, note) in m.styles.items():
            assert note is None and score == pytest.approx(
                m.rate_lift.get(style, 0.0) + m.terrain_lean.get(style, 0.0), abs=1e-3)
    # the wiki's chokes outweigh King's Row's rates: the terrain rectifies the style
    kings = world.map("King's Row")
    assert max(kings.terrain_lean, key=kings.terrain_lean.get) == "brawl"
    assert kings.style_top == max(kings.styles, key=lambda s: kings.styles[s][0])


def test_the_terrain_and_the_style_are_the_same_on_every_load(world, db):
    again = tables.load(db)
    db.rollback()
    for m in world.maps.values():
        other = again.maps[m.id]
        assert (m.terrain, m.terrain_z, m.terrain_lean, m.rate_lift, m.styles) == (
            other.terrain, other.terrain_z, other.terrain_lean, other.rate_lift, other.styles)
        assert (list(compute.map_metrics(m, ban_count=0))
                == list(compute.map_metrics(other, ban_count=0)))
    before = {m.id: (dict(m.terrain_z), dict(m.terrain_lean)) for m in world.maps.values()}
    tables.map_terrain(world)
    assert before == {m.id: (dict(m.terrain_z), dict(m.terrain_lean)) for m in world.maps.values()}


def test_stages_are_read_per_mode_as_the_wiki_holds_them(world, rows):
    stored = {}
    for name, stage in rows("""select m.name, s.name from map_stages s join maps m
            using(map_id) order by m.name, s.position"""):
        stored.setdefault(name, []).append(stage)
    assert {m.name: m.stages for m in world.maps.values() if m.stages} == stored
    by_mode = {}
    for m in world.maps.values():
        by_mode.setdefault(m.mode, []).append(m)
    assert all(len(m.stages) == 3 for m in by_mode["Control"])
    assert all(len(m.stages) == 5 for m in by_mode["Flashpoint"])
    assert all(m.stages == ["Assault", "Escort"] for m in by_mode["Hybrid"])   # point, then payload
    assert all(m.stages == [] for m in by_mode["Push"])
    # an Escort map holds the three stretches its own article names, or none
    assert {len(m.stages) for m in by_mode["Escort"]} == {0, 3}
    assert world.map("Havana").stages == ["City Streets", "Distillery", "Sea Fort"]
    assert world.map("Dorado").stages == []
    assert world.map("Ilios").stages == ["Lighthouse", "Well", "Ruins"]


def test_stage_terrain_is_z_scored_across_the_stages_with_text(world, rows):
    features = model.TERRAIN_FEATURES
    read = [(m, stage) for m in world.maps.values() for stage in m.stage_terrain]
    assert len(read) == rows("select count(distinct stage_id) from stage_terrain")[0][0] >= 2
    for m, stage in read:
        assert stage in m.stages and set(m.stage_terrain[stage]) == set(features)
        assert set(m.stage_z[stage]) == set(features)
    for f in features:
        raw = [m.stage_terrain[stage][f][0] for m, stage in read]
        mean, sd = statistics.fmean(raw), statistics.pstdev(raw)
        for m, stage in read:
            assert m.stage_z[stage][f] == pytest.approx(
                (m.stage_terrain[stage][f][0] - mean) / sd if sd else 0.0, abs=1e-3)
    (rate, mentions), = rows("""select t.per_thousand, t.mentions from stage_terrain t
        join map_stages s using(stage_id) join maps m using(map_id)
        where m.name = 'Ilios' and s.name = 'Well' and t.feature = 'hazards'""")
    assert world.map("Ilios").stage_terrain["Well"]["hazards"] == (float(rate), mentions)
    # the same on every pass
    before = {m.id: {s: dict(z) for s, z in m.stage_z.items()} for m in world.maps.values()}
    tables.stage_terrain(world)
    assert before == {m.id: m.stage_z for m in world.maps.values()}
