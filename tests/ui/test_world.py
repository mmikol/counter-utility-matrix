"""The World the load builds from the database: every table read, each hero's
kit numbers in their own units, the maps' terrain and styles, the names."""

import pathlib
import re
import statistics

import pytest

from db import Refusal
from ui.facts import compute, model, tables
from ui.facts.team import FLIER_REACH, team_metrics

pytestmark = pytest.mark.invariant


def test_every_data_table_is_read_by_the_load(world, rows):
    """Every data table is named in the load, the ledger aside, and read whole."""
    src = pathlib.Path(tables.__file__).read_text(encoding="utf-8")
    unread = [
        t for (t,) in rows("select tablename from pg_tables where schemaname='public'")
        if t != "schema_migrations" and not re.search(r"\b%s\b" % t, src)]
    assert unread == [], unread
    modifiers = sum(len(h.modifiers) for h in world.heroes.values())
    assert modifiers == rows("select count(*) from ability_modifiers")[0][0]
    # one population of rates, Blizzard's: no third party is read or named
    both = src + pathlib.Path(model.__file__).read_text(encoding="utf-8")
    assert "map_strategy" not in both and "counterpick" not in both


def test_world_loads_the_whole_roster_with_kit_numbers(world):
    assert len(world.heroes) > 40 and len(world.maps) >= 25
    ana = world.hero("Ana")
    assert ana.role == "support" and ana.hitscan
    # an ultimate's numbers are its own: Nano Boost's 250 is not Ana's healing,
    # Self-Destruct's 1000 not D.Va's burst, Transcendence not Zenyatta's rate,
    # Deadeye's lock-on not Cassidy's reach
    assert 75 <= ana.peak_heal < 250
    assert world.hero("D.Va").burst < 1000 <= world.hero("D.Va").ult_damage
    assert world.hero("Zenyatta").hps < 100
    assert 30 <= world.hero("Cassidy").max_range < world.hero("Widowmaker").max_range
    assert "Sleep Dart" in ana.cc_tools
    assert world.hero("Pharah").flyer and not world.hero("Reinhardt").flyer
    assert world.hero("Reinhardt").barrier_hp >= 1000
    assert world.hero("Kiriko").cleanse_tools
    assert world.heal_bench > 0


def test_kit_rows_are_read_in_their_own_units(world):
    # a percent is not hit points: lifesteal is a share, overhealth its published cap,
    # EMP a damage ultimate that adds no hit points
    reaper, mauga, sombra = world.hero("Reaper"), world.hero("Mauga"), world.hero("Sombra")
    assert reaper.self_heal == 0 and reaper.lifesteal == pytest.approx(0.3)
    assert mauga.peak_heal == 0 and mauga.self_hps == 0 and mauga.lifesteal == 1.0
    # an own heal that runs for a duration is also a cast: a share of the held rate
    # for Overdrive's 3 s, a rate for its longest duration, "100 over 3 seconds".
    # A passive's share has no duration; Siphon Blaster heals off its own damage
    assert mauga.self_heal == pytest.approx(mauga.dps * 3.0)
    assert world.hero("Junker Queen").self_heal == 100 and world.hero("Mei").self_heal == 250
    assert world.hero("Roadhog").self_heal == 450 and world.hero("Emre").self_heal == 30
    assert world.hero("Domina").self_heal == 0
    assert world.hero("Sigma").overhealth == 400 and mauga.overhealth == 150
    assert world.hero("Lifeweaver").overhealth == 100 == world.hero("Brigitte").overhealth
    assert sombra.dmg_ult and sombra.ult_damage == 0 and sombra.dmg_amp == 0
    assert team_metrics(world, [reaper, mauga])["lifelines"] == 2
    # a sum, a volley and a window's total are not one hit or a rate
    hazard = world.hero("Hazard")
    assert hazard.burst == 75 and hazard.ult_damage == 90
    assert world.hero("Ramattra").burst == 65
    assert world.hero("Zenyatta").burst == 100 and world.hero("Widowmaker").burst >= 250
    assert team_metrics(world, [world.hero("Zenyatta")])["one_shots"] == 0
    # an ultimate fired at its rate for its duration, under the roster's cap
    assert world.hero("Pharah").ult_damage == world.ult_cap
    assert 130 < world.hero("Venture").ult_damage < world.ult_cap
    # three charges of 180; a 175 heavy round on a 2.5 s cooldown, four in 8.8 s
    assert world.hero("Shion").ult_damage == 540
    assert world.hero("Emre").ult_damage == 700
    assert world.hero("Bastion").ult_damage == 550 and world.hero("Genji").ult_damage > 900
    # sustained rates: the reload in the row's text, the swing the rate counts,
    # the magazine's share where no reload figure is usable
    assert world.hero("Zenyatta").dps == pytest.approx(108.7)
    # both chainguns off one magazine: 138.88 for 8.64 s of every 10.64
    assert world.hero("Mauga").dps == pytest.approx(112.78, abs=0.01)
    assert world.hero("Mauga").hitscan_range == 40
    assert world.hero("Wuyang").dps == pytest.approx(128.21)
    assert world.hero("Vendetta").dps == pytest.approx(53.1)
    cat = world.hero("Jetpack Cat")
    assert cat.dps == pytest.approx(87.18, abs=0.01) and cat.hps == pytest.approx(cat.dps)


def test_the_weapon_a_hero_fights_with_sets_its_kind_and_reach(world):
    winston, torb, ramattra = (world.hero(n) for n in ("Winston", "Torbjörn", "Ramattra"))
    assert not winston.hitscan and winston.beam and winston.max_range == 8
    assert winston.burst == 60 and winston.pierces_barrier
    assert not torb.melee and not torb.pierces_barrier and torb.max_range == 0
    assert torb.self_heal == 0 and torb.self_hps == 0
    assert ramattra.melee and ramattra.pierces_barrier and ramattra.dps == 100
    assert ramattra.max_range == 0 and world.hero("Anran").max_range == 0
    # Nemesis Form's 275 armor for 8 s of every 16: the form's, not the base row's.
    # An ultimate's armor (Rally) stays out
    assert ramattra.form_armor == 137.5 and ramattra.armor == 100 and ramattra.pool == 375
    assert [h.name for h in world.heroes.values() if h.form_armor] == ["Ramattra"]
    t = team_metrics(world, [ramattra])
    assert t["armor_total"] == 237.5 and t["pool_total"] == 512.5 and t["weakest"] == "Ramattra"
    assert t["armor_share"] == pytest.approx(237.5 / 512.5)
    assert world.hero("Mei").max_range == 12 and world.hero("Sojourn").max_range == 60
    dmon, dva = world.hero("D.Mon"), world.hero("D.Va")
    assert dmon.max_range == 4 and dmon.dps == pytest.approx(91.2) and dmon.ult_damage == 125
    assert dva.burst == 25 and dva.cc_tools == [] and dmon.cc_tools == ["Surging Strike"]
    # a healing beam is not a beam; a kick is not a barrier piercer
    assert not world.hero("Mercy").beam and not world.hero("Illari").beam
    assert world.hero("Moira").beam
    assert not world.hero("Zenyatta").pierces_barrier


def test_tools_are_counted_once_and_for_what_they_do(world):
    names = ("Sigma", "Junkrat", "Pharah", "Freja", "Reinhardt", "Doomfist", "Mauga")
    assert [world.hero(n).aoe_count for n in names] == [3, 4, 3, 2, 1, 3, 3]
    assert world.hero("Baptiste").aoe_count == 3 and world.hero("Baptiste").aoe_damage == 0
    # a damaging piece typed Area of effect counts without the tag; a piece that
    # deals no damage (Defense Matrix, Kinetic Grasp) does not
    names = ("Sierra", "Orisa", "Emre", "Lúcio", "Jetpack Cat", "D.Va", "Sigma")
    area = {n: (world.hero(n).aoe_count, world.hero(n).aoe_damage) for n in names}
    assert area == {
        "Sierra": (2, 2), "Orisa": (2, 2), "Emre": (3, 3), "Lúcio": (4, 1),
        "Jetpack Cat": (3, 2), "D.Va": (2, 2), "Sigma": (3, 3)}
    assert world.hero("Junkrat").aoe_damage == 4
    assert world.hero("Soldier: 76").cc_tools == [] and world.hero("Emre").cc_tools == []
    assert "Concussion Mine" in world.hero("Junkrat").cc_tools
    assert world.hero("Sierra").mobility_tools == ["Anchor Drone"]
    # typed Movement with no movement tag; a speed buff alone is not one
    assert world.hero("Emre").mobility_tools == ["Siphon Blaster"]
    assert "Roll" in world.hero("Wrecking Ball").mobility_tools
    assert "Commanding Shout" not in world.hero("Junker Queen").mobility_tools
    assert "Nemesis Form" not in world.hero("Ramattra").mobility_tools
    assert sum(1 for h in world.heroes.values() if h.released and h.mobility_tools) == 39
    assert world.hero("Zarya").deployables == []
    assert world.hero("Baptiste").invuln_tools == ["Immortality Field"]
    doomfist = world.hero("Doomfist")
    assert doomfist.cleanse_tools == [] and doomfist.invuln_tools == []
    assert 2.5 not in world.hero("Emre").cooldowns
    # what lands on a teammate, apart from what saves only its owner
    picks = [world.hero(n) for n in ("Kiriko", "Reaper", "Venture", "Baptiste", "Mercy", "Moira")]
    t = team_metrics(world, picks)
    assert t["cleanse"] == 4 and t["team_cleanse"] == 1            # Protection Suzu alone
    assert t["invuln"] == 6 and t["team_saves"] == 3               # Suzu, the Field, Resurrect
    assert world.hero("Zenyatta").team_cleanse_tools == ["Transcendence"]
    five = [world.hero(n) for n in ("Reinhardt", "Ana", "Widowmaker", "Tracer", "Winston")]
    t = team_metrics(world, five)
    assert t["burst_max"] == 300 and t["burst_hero"] == "Reinhardt"
    assert t["burst_ranged"] == world.hero("Widowmaker").burst
    assert team_metrics(world, [world.hero("Reinhardt")])["burst_ranged"] == 0
    assert t["hitscan"] == 3 and t["hitscan_reach"] == 1            # Widowmaker's 70 m
    # 30 m answers a flier (Shion's pistols), 25 m does not
    assert FLIER_REACH == 30 and world.hero("Shion").hitscan_range == 30
    four = [world.hero(n) for n in ("Shion", "Wrecking Ball", "Junker Queen", "Cassidy")]
    reach = team_metrics(world, four)
    assert reach["hitscan"] == 4 and reach["hitscan_reach"] == 2
    # an explosion does not crit: Freja's bolt is 35 to the head, 75 flat
    assert world.hero("Freja").burst == 75
    assert "enemy.team_saves" in compute.registry()


def test_an_announced_hero_sets_no_roster_wide_figure(world):
    out = [h for h in world.heroes.values() if h.released and h.role == "support"]
    assert world.heal_bench == 2 * statistics.median(h.peak_heal for h in out if h.peak_heal)
    assert world.hps_bench == 2 * statistics.median(h.hps for h in out if h.hps)
    assert world.ult_cap == max(h.ult_damage for h in world.heroes.values() if h.released)


def test_names_resolve_across_spellings(world):
    assert world.hero("lucio").name == "Lúcio"
    assert world.hero("D.VA").name == "D.Va"
    assert world.map("kings row").name == "King's Row"
    with pytest.raises(Refusal, match="unknown heroes"):
        world.resolve(None, ["Goku"], [])
    with pytest.raises(Refusal, match="unknown map"):
        world.resolve("Atlantis", [], [])


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
            assert compute.map_metrics(m, ban_count=0)[f] == m.terrain_z[f]
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
    assert compute.map_metrics(kings, ban_count=0)["style_top"] == kings.style_top
    assert compute.map_metrics(kings, ban_count=0)["style_margin"] == kings.style_margin


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


def test_no_released_hero_is_missing_a_core_kit_number(world):
    """The kit block carries most of the playbook's weight, and a hole in it is
    silent: a tank that deals no damage still scores, just wrongly. Domina read
    zero because her beam publishes a rate only as damage `over time`."""
    holes = []
    for hero in sorted(world.heroes.values(), key=lambda h: h.name):
        if not hero.released:
            continue
        if not hero.pool:
            holes.append("%s has no health pool" % hero.name)
        if not hero.dps:
            holes.append("%s deals no damage" % hero.name)
        if hero.role == "support" and not hero.hps:
            holes.append("%s is a support that heals nothing" % hero.name)
    assert not holes, holes
