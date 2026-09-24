"""The kit reader: a kit piece's combat numbers from its rows and their
wording. Pure - no database, so it runs on the pull-request gate; every
row is built by hand in the shape the wiki publishes it."""

import pytest

from db import KIND_ABILITY, KIND_ULTIMATE, KIND_WEAPON
from ui.facts.kit import Kit, Stat, dual_rate


def _kit(kind, *rows):
    """A kit piece from (code, value, unit_num, unit_den, den_value, condition, text) rows."""
    kit = Kit("piece", kind)
    for row in rows:
        kit.stats[row[0]].append(Stat(*row))
    return kit


def _dps(kit):
    return kit.rate("dps", "damage")


def test_a_reload_worded_in_the_text_is_the_rate():
    orb = _kit(
        KIND_WEAPON,
        ("dps", 125, "hp", "seconds", 1, None,
            "125 while firing (108.7 overall w/reload) 156.25 while firing w/ discord"),
        ("fire_rate", 2.5, "shots", "seconds", 1, None, "2.5 shots/s"),
        ("ammo", 25, "rounds", None, None, None, "25"),
        ("reload_time", 1.5, "seconds", None, None, None, "1.5 seconds animation"))
    assert _dps(orb) == pytest.approx(108.7)


def test_a_reload_in_the_condition_is_the_rate():
    # a prose row: its first figure is another fire mode, the condition is the rate
    staff = _kit(KIND_WEAPON, (
        "dps", None, None, None, None, "128.21 overall w/ reload",
        "Rapid fire of uncharged orbs: 90.91 while firing (74.07 overall w/ reload)"))
    assert _dps(staff) == pytest.approx(128.21)
    volley = _kit(KIND_WEAPON, (
        "dps", 77.64, "hp", "seconds", 1, "68.18 overall w/reload", "77.64 while firing"))
    assert _dps(volley) == pytest.approx(68.18)


def test_the_magazine_and_its_reload_share_the_firing_rate():
    rows = (
        ("dps", 100, "hp", "seconds", 1, None, "100"),
        ("fire_rate", 10, "shots", "seconds", 1, None, "10 shots/s"),
        ("ammo", 20, "rounds", None, None, None, "20"),
        ("reload_time", 2, "seconds", None, None, None, "2 seconds"),
        ("reload_time", 0.5, "seconds", None, None, "per shot", "0.5 seconds per shot"))
    # 20 rounds last 2 s of every 2 + 2
    assert _dps(_kit(KIND_WEAPON, *rows)) == pytest.approx(50.0)
    # two rounds a shot empty the magazine in 1 s of every 3
    drained = _kit(KIND_WEAPON, *rows, ("ammo_drain", 2, "rounds", None, None, None, "2"))
    assert _dps(drained) == pytest.approx(100 / 3)
    # no magazine: the firing rate stands
    assert _dps(_kit(KIND_WEAPON, rows[0], rows[1], rows[3])) == 100


def test_variants_of_one_rate_count_at_their_median():
    beam = _kit(
        KIND_WEAPON,
        ("dps", 100, "hp", "seconds", 1, "variant 1", "100"),
        ("dps", 50, "hp", "seconds", 1, "variant 2", "50"),
        ("dps", 80, "hp", "seconds", 1, "at full charge", "80"))
    assert _dps(beam) == 80


def test_a_shot_times_the_fire_rate_counts_the_hit_the_rate_names():
    # "1.18 swings per second" is the swing, not the overhead strike
    blade = _kit(
        KIND_WEAPON,
        ("damage", 45, "hp", None, None, "swing", "45"),
        ("damage", 120, "hp", None, None, "overhead strike", "120"),
        ("fire_rate", 1.18, "swings", "seconds", 1, "average at 0 stacks", "1.18 swings/s"))
    assert _dps(blade) == pytest.approx(53.1)
    # a rate that names no hit counts the largest
    gun = _kit(
        KIND_WEAPON,
        ("damage", 20, "hp", None, None, None, "20"),
        ("damage", 30, "hp", None, None, "charged", "30"),
        ("fire_rate", 4, "shots", "seconds", 1, None, "4 shots/s"))
    assert _dps(gun) == 120


def test_damage_over_time_is_a_rate_only_where_nothing_else_is():
    shot = ("damage", 60, "hp", None, None, "hitscan shot", "60")
    magnum = _kit(
        KIND_WEAPON,
        ("damage", 60, "hp", None, None, "over time", "60"),
        shot,
        ("ammo", 100, "rounds", None, None, None, "100"),
        ("reload_time", 1.5, "seconds", None, None, None, "1.5 seconds"))
    assert _dps(magnum) == 60
    assert _dps(_kit(KIND_WEAPON, shot)) is None


def _ult_hit(kit):
    return kit.ult_hit()


def test_an_ultimate_hits_once_for_each_charge():
    blades = _kit(
        KIND_ULTIMATE,
        ("damage", 180, "hp", None, None, None, "180"),
        ("charges", 3, None, None, None, None, "3"))
    assert _ult_hit(blades) == 540


def test_an_ultimate_total_over_a_window_is_the_total():
    spikes = _kit(
        KIND_ULTIMATE,
        ("damage", 90, "hp", "seconds", 0.3, None, "90 over 0.3 seconds"),
        ("duration", 2, "seconds", None, None, None, "2 seconds"))
    assert _ult_hit(spikes) == 90


def test_an_ultimate_rate_runs_for_its_duration():
    beam = _kit(
        KIND_ULTIMATE,
        ("dps", 150, "hp", "seconds", 1, None, "150 per second"),
        ("damage", 500, "hp", None, None, None, "500"),
        ("duration", 4, "seconds", None, None, None, "4 seconds"))
    assert _ult_hit(beam) == 600        # a dps row: the flat figure is not a hit of its own


def test_an_ultimate_fires_at_its_rate_until_its_ammo_runs_out():
    rows = (
        ("damage", 40, "hp", None, None, None, "40"),
        ("fire_rate", 10, "shots", "seconds", 1, None, "10 shots/s"),
        ("duration", 3, "seconds", None, None, None, "3 seconds"))
    assert _ult_hit(_kit(KIND_ULTIMATE, *rows)) == 1200
    ammo = ("ammo", 20, "rounds", None, None, None, "20")
    assert _ult_hit(_kit(KIND_ULTIMATE, *rows, ammo)) == 800
    # a hit on the hero itself is not the ultimate's
    own = _kit(KIND_ULTIMATE, ("damage", 40, "hp", None, None, "self", "40"), *rows[1:])
    assert _ult_hit(own) == 40


def test_an_ultimate_shot_on_its_own_cooldown_fires_each_time_it_returns():
    rows = (
        ("damage", 175, "hp", None, None, "heavy round direct hit", "175"),
        ("cooldown", 2.5, "seconds", None, None, "heavy round", "2.5 seconds"),
        ("duration", 8.8, "seconds", None, None, None, "8.8 seconds"))
    assert _ult_hit(_kit(KIND_ULTIMATE, *rows)) == 700    # once, and three returns in 8.8 s
    # a published fire rate says how it fires: the cooldown is not read
    fired = _kit(KIND_ULTIMATE, *rows, ("fire_rate", 1, "shots", "seconds", 1, None, "1 shot/s"))
    assert _ult_hit(fired) == pytest.approx(175 * 8.8)


def test_two_guns_fired_together_share_one_magazine():
    # both chainguns off one magazine: 138.88 for 8.64 s of every 10.64
    def gun(dps):
        return _kit(
            KIND_WEAPON,
            ("dps", dps, "hp", "seconds", 1, None, str(dps)),
            ("fire_rate", 25, "shots", "seconds", 1, None, "25 shots/s"),
            ("ammo", 432, "rounds", None, None, None, "432"),
            ("reload_time", 2, "seconds", None, None, None, "2 seconds"),
            ("spread", 3, "degrees", None, None, "simultaneous fire", "3 degrees"))
    assert dual_rate([gun(69.44), gun(69.44)]) == pytest.approx(138.88 * 8.64 / 10.64)
    # one gun, or two off different magazines, is no pair
    assert dual_rate([gun(69.44)]) is None
    other = gun(69.44)
    other.stats["ammo"][0] = Stat("ammo", 300, "rounds", None, None, None, "300")
    assert dual_rate([gun(69.44), other]) is None


def test_a_single_hit_is_one_row_and_a_headshot_where_one_counts():
    rifle = _kit(
        KIND_WEAPON,
        ("damage", 75, "hp", None, None, None, "75"),
        ("damage", 35, "hp", None, None, "explosion", "35"),
        ("damage", 160, "hp", None, None, "if all hit", "160"),
        ("headshot", 1, None, None, None, None, "yes"),
        ("headshot_mod", 2, "multiplier", None, None, None, "2"))
    # the head doubles the bolt; an explosion lands on the body; a sum is no hit
    assert sorted(rifle.hits()) == [35, 150]
    orbs = _kit(
        KIND_WEAPON,
        ("damage", 50, "hp", None, None, None, "50 per orb"),
        ("damage", 250, "hp", None, None, None, "250 per volley"))
    assert orbs.hits() == [50]                  # five orbs at once: not one hit
    beam = _kit(
        KIND_WEAPON,
        ("damage", 30, "hp", "seconds", 1, None, "30 per second"),
        ("damage", 90, "hp", None, None, None, "90"),
        ("duration", 3, "seconds", None, None, None, "3 seconds"))
    assert beam.hits() == []                    # the rate over its duration, not a hit


def test_a_cast_of_several_pieces_hits_with_all_of_them():
    bombs = _kit(
        KIND_ABILITY,
        ("damage", 25, "hp", None, None, "explosion, enemy", "25"),
        ("damage", 10, "hp", None, None, "explosion, self", "10"),
        ("pellets", 6, None, None, None, None, "6"))
    assert bombs.cast_hit() == 150 and sorted(bombs.hits()) == [10, 25]
    # one piece, a sum among the rows, or a weapon: no cast
    one = _kit(KIND_ABILITY, ("damage", 25, "hp", None, None, "explosion", "25"))
    summed = _kit(
        KIND_ABILITY,
        ("damage", 25, "hp", None, None, "explosion", "25"),
        ("damage", 150, "hp", None, None, "total", "150"),
        ("pellets", 6, None, None, None, None, "6"))
    gun = _kit(
        KIND_WEAPON,
        ("damage", 25, "hp", None, None, "pellet", "25"),
        ("pellets", 6, None, None, None, None, "6"))
    assert one.cast_hit() is None and summed.cast_hit() is None and gun.cast_hit() is None
