"""The heroes the load builds from the database: the whole roster with its
kit numbers, each read in its own units - an ultimate's numbers its own, a
percent not hit points, a sum not one hit - the weapon a hero fights with,
the tools counted once, the roster-wide benches and role-median pools, and no
hole in a released hero's core numbers. The scrape is the point: every
figure is the wiki's. The derivation's rules are tests/facts/test_scalars.py's,
test_scalars_healing.py's and test_kit.py's."""

import statistics

import pytest

from facts import compute

pytestmark = pytest.mark.invariant


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
    assert sombra.ult_deals_damage and sombra.ult_damage == 0 and sombra.dmg_amp == 0
    # a sum, a volley and a window's total are not one hit or a rate
    hazard = world.hero("Hazard")
    assert hazard.burst == 75 and hazard.ult_damage == 90
    assert world.hero("Ramattra").burst == 65
    assert world.hero("Zenyatta").burst == 100 and world.hero("Widowmaker").burst >= 250
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
    # the gun heals at its damage's rate, and Purr adds 12.0 on top
    cat = world.hero("Jetpack Cat")
    assert cat.dps == pytest.approx(87.18, abs=0.01)
    assert cat.hps_pieces["Biotic Pawjectiles"] == pytest.approx(cat.dps)
    assert cat.hps == pytest.approx(99.18, abs=0.005)


# hero.hps at FORMATION_RADIUS 15 on the 6v6 kit: every piece that runs beside
# the others, summed over the teammates it reaches (facts/scalars.py)
SUSTAINED_HEALING = {
    "Baptiste": 111.76, "Juno": 107.59, "Jetpack Cat": 99.18, "Brigitte": 98.36,
    "Ana": 92.72, "Kiriko": 81.50, "Illari": 70.07, "Mizuki": 69.79, "Moira": 69.40,
    "Lifeweaver": 60.35, "Mercy": 60.00, "Lúcio": 54.56, "Wuyang": 48.07, "Zenyatta": 35.00,
    "Mauga": 16.32, "Soldier: 76": 4.77}


def test_sustained_healing_sums_the_pieces_over_the_teammates_they_reach(world):
    """Each healer's hps on the built World, and nobody else's. The bench,
    twice the median support, sits on Illari, Mizuki and Moira, within 0.7
    hp/s of each other: a judgement that moves one of them past Kiriko moves
    the bench, and these pins show it."""
    released = [h for h in world.heroes.values() if h.released]
    got = {h.name: h.hps for h in released if h.hps}
    assert got == pytest.approx(SUSTAINED_HEALING, abs=0.005)
    for hero in released:
        assert hero.hps == pytest.approx(sum(hero.hps_pieces.values()))
    assert world.hps_bench == pytest.approx(139.87, abs=0.005)
    assert world.hps_bench / compute.pool_ref(world) == pytest.approx(0.0691, abs=0.00005)
    cluster = [world.hero(n).hps for n in ("Illari", "Mizuki", "Moira")]
    assert max(cluster) - min(cluster) < 0.7 < world.hero("Kiriko").hps - max(cluster)
    # a beam at what its energy sustains; Wuyang's wave refunds 33% of the stream
    illari, moira = world.hero("Illari"), world.hero("Moira")
    assert illari.hps_pieces["Solar Rifle Alt Fire"] == pytest.approx(53.41, abs=0.01)
    assert moira.hps_pieces["Biotic Grasp"] == pytest.approx(49.40, abs=0.01)
    assert world.hero("Wuyang").hps_pieces == pytest.approx(
        {"Restorative Stream": 41.41, "Guardian Wave": 6.67}, abs=0.01)
    # an area heal counts the teammates it reaches: Crossfade 18/s on 2.13 of them
    assert world.hero("Lúcio").hps_pieces["Crossfade"] == pytest.approx(38.36, abs=0.01)
    assert world.hero("Brigitte").hps_pieces == pytest.approx(
        {"Repair Pack": 25.0, "Inspire": 73.36}, abs=0.01)


def test_the_weapon_a_hero_fights_with_sets_its_kind_and_reach(world):
    winston, torb, ramattra = (world.hero(n) for n in ("Winston", "Torbjörn", "Ramattra"))
    assert not winston.hitscan and winston.beam and winston.max_range == 8
    assert winston.burst == 60 and winston.pierces_barrier
    assert not torb.melee and not torb.pierces_barrier and torb.max_range == 0
    assert torb.self_heal == 0 and torb.self_hps == 0
    assert ramattra.melee and ramattra.pierces_barrier and ramattra.dps == 100
    assert ramattra.max_range == 0 and world.hero("Anran").max_range == 0
    # Nemesis Form's armor for 8 s of every 16: the form's, not the base row's - 225
    # in 6v6, the kit's format, where 5v5 gives 275. An ultimate's armor (Rally)
    # stays out. 6v6's health is 350, 5v5's 275
    assert ramattra.form_armor == 112.5 and ramattra.armor == 100 and ramattra.pool == 450
    assert [h.name for h in world.heroes.values() if h.form_armor] == ["Ramattra"]
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
    assert world.hero("Baptiste").aoe_count == 3 and world.hero("Baptiste").aoe_damage_count == 0
    # a damaging piece typed Area of effect counts without the tag; a piece that
    # deals no damage (Defense Matrix, Kinetic Grasp) does not
    names = ("Sierra", "Orisa", "Emre", "Lúcio", "Jetpack Cat", "D.Va", "Sigma")
    area = {n: (world.hero(n).aoe_count, world.hero(n).aoe_damage_count) for n in names}
    assert area == {
        "Sierra": (2, 2), "Orisa": (2, 2), "Emre": (3, 3), "Lúcio": (4, 1),
        "Jetpack Cat": (3, 2), "D.Va": (2, 2), "Sigma": (3, 3)}
    assert world.hero("Junkrat").aoe_damage_count == 4
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
    assert [h.name for h in picks if h.cleanse_tools] == ["Kiriko", "Reaper", "Venture", "Moira"]
    assert [h.name for h in picks if h.team_cleanse_tools] == ["Kiriko"]     # Protection Suzu
    assert all(h.invuln_tools for h in picks)
    assert [h.name for h in picks if h.save_tools] == ["Kiriko", "Baptiste", "Mercy"]
    assert world.hero("Zenyatta").team_cleanse_tools == ["Transcendence"]
    # Reinhardt's 300 is a swing, all he fights with; Widowmaker's is the biggest shot here
    five = [world.hero(n) for n in ("Reinhardt", "Ana", "Widowmaker", "Tracer", "Winston")]
    reinhardt, widowmaker = world.hero("Reinhardt"), world.hero("Widowmaker")
    assert reinhardt.burst == 300 and reinhardt.melee_only and not widowmaker.melee_only
    assert widowmaker.burst == max(h.burst for h in five if not h.melee_only)
    assert [h.name for h in five if h.hitscan] == ["Ana", "Widowmaker", "Tracer"]
    assert [h.name for h in five if h.hitscan_range >= 30] == ["Widowmaker"]     # 70 m
    # 30 m answers a flier (Shion's pistols), 25 m does not
    four = [world.hero(n) for n in ("Shion", "Wrecking Ball", "Junker Queen", "Cassidy")]
    assert all(h.hitscan for h in four) and world.hero("Shion").hitscan_range == 30
    assert [h.name for h in four if h.hitscan_range >= 30] == ["Shion", "Cassidy"]
    # an explosion does not crit: Freja's bolt is 35 to the head, 75 flat
    assert world.hero("Freja").burst == 75


def test_an_announced_hero_sets_no_roster_wide_figure(world):
    out = [h for h in world.heroes.values() if h.released and h.role == "support"]
    assert world.heal_bench == 2 * statistics.median(h.peak_heal for h in out if h.peak_heal)
    assert world.hps_bench == 2 * statistics.median(h.hps for h in out if h.hps)
    assert world.ult_cap == max(h.ult_damage for h in world.heroes.values() if h.released)


def test_the_role_median_pools_count_a_forms_armor_and_set_the_reference_pool(world):
    """Each role's median pool is read as team.pool_total reads a pool, a
    form's armor in, over the released heroes; the 6v6 kit gives 525, 250 and
    237.5, and a 2-2-2 of them, pool_ref, is 2025. Ramattra's form moves the
    tanks' median: without it the median is 500."""
    released = [h for h in world.heroes.values() if h.released]
    for role in ("tank", "damage", "support"):
        assert world.pool_medians[role] == statistics.median(
            h.pool + h.form_armor for h in released if h.role == role), role
    assert world.pool_medians == {"tank": 525.0, "damage": 250.0, "support": 237.5}
    assert compute.pool_ref(world) == 2 * sum(world.pool_medians.values()) == 2025.0
    assert statistics.median(h.pool for h in released if h.role == "tank") == 500.0


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
