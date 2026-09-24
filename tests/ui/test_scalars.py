"""A hero's derived numbers from ui/facts/scalars.py, section by section:
each test builds a hero's kit by hand, in the shape the load reads it, runs
scalars.derive and reads the fields it sets. The kit reader's own wording
rules are tests/ui/test_kit.py's. No database."""

import pytest

from db import KIND_ABILITY, KIND_PASSIVE, KIND_ULTIMATE, KIND_WEAPON
from ui.facts import scalars
from ui.facts.kit import Kit, Stat
from ui.facts.model import Hero


def _stat(code, value, unit_num=None, unit_den=None, den=None, condition=None, text=None):
    return Stat(code=code, value=value, unit_num=unit_num, unit_den=unit_den, den_value=den,
                condition=condition, text=text)


def _kit(name, kind, *stats, keywords="", **extra):
    """A kit piece with its stat rows; a weapon config's extra (weapon,
    weapon_type, slot) by keyword."""
    kit = Kit(name, kind, keywords=keywords)
    for s in stats:
        kit.stats[s.code].append(s)
    kit.extra.update(extra)
    return kit


def _gun(name, weapon_type, *stats, slot="primary_fire", keywords=""):
    return _kit(name, KIND_WEAPON, *stats, keywords=keywords, weapon=name,
                weapon_type=weapon_type, slot=slot)


def _hero(role="damage", *, weapons=(), abilities=(), **fields):
    hero = Hero(id=1, name="Test", role=role, subrole="Flanker", weapons=list(weapons),
                abilities=list(abilities), **fields)
    scalars.derive(hero)
    return hero


def _per_second(code, value):
    return _stat(code, value, "hp", "seconds", 1)


def test_the_body_counts_a_forms_armor_by_its_uptime_and_every_cooldown():
    """A form's 275 armor for 8 s of every 16 is 137.5, outside the spawn
    pool; armor that lands on allies is theirs; an ultimate's cooldown is not
    counted."""
    form = _kit("Nemesis Form", KIND_ABILITY, _stat("armor", 275, "hp"),
                _stat("cooldown", 8, "seconds"), _stat("duration", 8, "seconds"),
                keywords="movement::armor")
    rally = _kit("Rally", KIND_ABILITY, _stat("armor", 50, "hp", condition="allies"),
                 _stat("cooldown", 11, "seconds"))
    ult = _kit("Annihilation", KIND_ULTIMATE, _stat("cooldown", 30, "seconds"))
    hero = _hero("tank", health=275, armor=100, abilities=[form, rally, ult])
    assert hero.pool == 375 and hero.form_armor == 137.5
    assert hero.keywords == {"movement", "armor"}
    assert hero.cooldowns == [8.0, 11.0] and hero.median_cooldown == 9.5
    assert _hero().median_cooldown is None and _hero().cooldowns == []


def test_the_damage_is_the_held_weapons_and_a_form_gated_one_is_not():
    held = _gun("Pulse Rifle", "Hitscan", _per_second("dps", 100))
    alt = _gun("Helix Rockets", "Projectile", _per_second("dps", 150), slot="secondary_fire")
    assault = _gun("Configuration: Assault", "Hitscan", _per_second("dps", 300))
    assert _hero(weapons=[held, alt, assault]).dps == 100.0
    # with no primary slot the steady weapons' best rate stands
    side = _gun("Helix Rockets", "Projectile", _per_second("dps", 150), slot="secondary_fire")
    assert _hero(weapons=[side, assault]).dps == 150.0
    assert _hero().dps == 0.0


def test_the_burst_is_the_biggest_hit_and_a_pilots_gun_is_not_the_heros():
    gun = _gun("Fusion Cannons", "Projectile", _stat("damage", 120, "hp"))
    pilot = _gun("Light Gun", "Projectile", _stat("damage", 500, "hp"))
    boosters = _kit("Boosters", KIND_ABILITY, _stat("damage", 250, "hp"))
    assert _hero("tank", weapons=[gun, pilot], abilities=[boosters]).burst == 250.0
    # six bombs of 25 thrown in one cast hit as one: 150
    bombs = _kit("Sticky Bombs", KIND_ABILITY,
                 _stat("damage", 25, "hp", condition="explosion, enemy"), _stat("pellets", 6))
    assert _hero(weapons=[gun], abilities=[bombs]).burst == 150.0


def test_a_supports_healing_lands_on_teammates_and_a_self_heal_is_its_own():
    stream = _gun("Healing Stream", "Beam", _per_second("hps", 60))
    burst = _kit("Healing Burst", KIND_ABILITY, _stat("heal", 70, "hp"),
                 _stat("heal", 30, "hp", condition="self"))
    hero = _hero("support", weapons=[stream], abilities=[burst])
    assert (hero.hps, hero.peak_heal, hero.self_hps, hero.self_heal) == (60.0, 70.0, 0.0, 30.0)
    # a healing beam deals no damage: it is not a beam weapon
    assert not hero.beam and hero.weapon_kinds == set()


def test_a_non_supports_healing_is_its_own_unless_it_lands_on_an_ally():
    """150 a second for 3 s is a 450 cast on itself; a heal tagged for a
    target ally is the team's even on a damage hero."""
    gun = _gun("Shotgun", "Hitscan", _per_second("dps", 120))
    siphon = _kit("Siphon", KIND_ABILITY, _per_second("heal", 150), _stat("duration", 3, "seconds"))
    field = _kit("Field", KIND_ABILITY, _stat("heal", 40, "hp"), keywords="heal;;target ally")
    hero = _hero(weapons=[gun], abilities=[siphon, field])
    assert hero.self_hps == 150.0 and hero.self_heal == 450.0
    assert hero.peak_heal == 40.0 and hero.hps == 0.0


def test_a_heal_off_the_damage_dealt_is_the_held_weapons_rate_over_it():
    """Overdrive heals 30% of the damage dealt for 3 s on an 8 s cooldown:
    of a 100 a second gun, 90. The same share is the hero's lifesteal."""
    gun = _gun("Chainguns", "Hitscan", _per_second("dps", 100))
    overdrive = _kit("Overdrive", KIND_ABILITY, _stat("heal", 30, "percent"),
                     _stat("duration", 3, "seconds"), _stat("cooldown", 8, "seconds"))
    hero = _hero("tank", weapons=[gun], abilities=[overdrive])
    assert hero.self_heal == pytest.approx(90.0) and hero.lifesteal == pytest.approx(0.3)


def test_the_reach_is_the_published_limit_and_a_blind_projectile_leaves_hitscan():
    rifle = _gun("Rifle", "Hitscan", _per_second("dps", 90), _stat("range", 40, "meters"))
    hero = _hero(weapons=[rifle])
    assert (hero.max_range, hero.hitscan_range) == (40.0, 40.0)
    # a held projectile that publishes no limit: only the hitscan figure stands
    rockets = _gun("Rockets", "Projectile", _per_second("dps", 120))
    pistol = _gun("Pistol", "Hitscan", _stat("damage", 40, "hp"), _stat("range", 25, "meters"),
                  slot="secondary_fire")
    blind = _hero(weapons=[rockets, pistol])
    assert (blind.max_range, blind.hitscan_range) == (25.0, 25.0)
    lobbed = _gun("Rockets", "Projectile", _per_second("dps", 120), _stat("range", 60, "meters"))
    assert _hero(weapons=[lobbed, pistol]).max_range == 60.0
    assert _hero(weapons=[lobbed]).hitscan_range == 0.0


def test_the_weapon_kinds_read_the_damaging_weapons():
    hammer = _gun("Rocket Hammer", "Melee", _stat("damage", 100, "hp"))
    swinger = _hero("tank", weapons=[hammer])
    assert swinger.weapon_kinds == {"melee"} and swinger.melee and swinger.melee_only
    cannon = _gun("Cannon", "Projectile", _stat("damage", 80, "hp"), slot="secondary_fire")
    both = _hero("tank", weapons=[hammer, cannon])
    assert both.weapon_kinds == {"melee", "projectile"} and both.melee and not both.melee_only
    beam = _gun("Particle Beam", "Beam", _per_second("dps", 90))
    tagged = _gun("Auto Rifle", "", _per_second("dps", 90), keywords="hitscan")
    hero = _hero(weapons=[beam, tagged])
    assert hero.beam and hero.hitscan and hero.weapon_kinds == {"beam"}


def test_area_pieces_count_once_and_those_that_hurt_apart():
    blast = _kit("Blast", KIND_ABILITY, _stat("damage", 60, "hp"), keywords="area of effect")
    wave = _kit("Wave", KIND_ABILITY, _stat("damage", 40, "hp"), _stat("shot_type", None,
                text="Area of effect"))
    suzu = _kit("Suzu", KIND_ABILITY, _stat("heal", 80, "hp"), keywords="area of effect")
    grenade = _gun("Launcher", "Projectile", _stat("damage", 50, "hp"), keywords="area of effect")
    # the same weapon as the abilities table lists it: counted once, as the weapon
    listed = _kit("Launcher", KIND_WEAPON, _stat("damage", 50, "hp"), keywords="area of effect")
    hero = _hero(weapons=[grenade], abilities=[blast, wave, suzu, listed])
    assert (hero.aoe_count, hero.aoe_damage) == (4, 3)


def test_barriers_count_their_health_and_a_passives_swing_pierces_nothing():
    shield = _kit("Barrier Field", KIND_ABILITY, _stat("barrier_health", 1200, "hp"))
    dome = _kit("Dome", KIND_ABILITY, _stat("health", 600, "hp"), keywords="barrier")
    hero = _hero("tank", abilities=[shield, dome])
    assert hero.barrier_hp == 1200.0 and not hero.pierces_barrier
    beam = _kit("Tesla", KIND_ABILITY, _stat("damage", 60, "hp"), keywords="barrier piercing")
    kick = _kit("Snap Kick", KIND_PASSIVE, _stat("damage", 30, "hp"), keywords="barrier piercing")
    assert _hero(abilities=[beam]).pierces_barrier
    assert not _hero(abilities=[kick]).pierces_barrier


def test_amps_anti_heal_and_overhealth_read_their_own_rows():
    grenade = _kit("Biotic Grenade", KIND_ABILITY, _stat("healing_mod", -100, "percent"),
                   _stat("healing_mod", 50, "percent"))
    boost = _kit("Boost", KIND_ABILITY, _stat("damage_amp", 30, "percent"))
    opportunist = _kit("Opportunist", KIND_PASSIVE, _stat("damage_amp", 20, "percent"))
    grip = _kit("Grip", KIND_ABILITY, _stat("overhealth", 400, "hp"))
    hero = _hero("support", abilities=[grenade, boost, opportunist, grip])
    assert (hero.antiheal, hero.heal_amp, hero.dmg_amp, hero.overhealth) == (
        -100.0, 50.0, 30.0, 400.0)
    # a passive's own bonus is not the team's
    assert _hero(abilities=[opportunist]).dmg_amp == 0.0


def test_control_movement_and_flight_read_the_keywords_and_the_rows():
    stun = _kit("Flashbang", KIND_ABILITY, keywords="stun")
    shove = _kit("Concussive Blast", KIND_ABILITY, _stat("damage", 70, "hp"),
                 _stat("kbspeed", 15, "meters"))
    nudge = _kit("Nudge", KIND_ABILITY, _stat("damage", 20, "hp"), _stat("kbspeed", 5, "meters"))
    slow = _kit("Frost", KIND_ABILITY, _stat("mspeed_slow", -30, "percent"))
    jet = _kit("Jet Pack", KIND_ABILITY, keywords="flight")
    roll = _kit("Roll", KIND_ABILITY, _stat("shot_type", None, text="Movement"))
    hero = _hero(abilities=[stun, shove, nudge, slow, jet, roll])
    assert hero.cc_tools == ["Concussive Blast", "Flashbang", "Frost"]
    assert hero.mobility_tools == ["Jet Pack", "Roll"] and hero.flyer


def test_saves_split_what_lands_on_a_teammate_from_what_saves_its_owner():
    suzu = _kit("Protection Suzu", KIND_ABILITY, _stat("heal", 80, "hp"),
                keywords="greater cleanse::invulnerable::area of effect")
    fade = _kit("Fade", KIND_ABILITY, keywords="lesser cleanse::invulnerable")
    field = _kit("Immortality Field", KIND_ABILITY, keywords="deployable")
    matrix = _kit("Bubble", KIND_ABILITY, keywords="deployable::attached")
    hero = _hero("support", abilities=[suzu, fade, field, matrix])
    assert hero.cleanse_tools == ["Fade", "Protection Suzu"]
    assert hero.invuln_tools == ["Fade", "Immortality Field", "Protection Suzu"]
    assert hero.team_cleanse_tools == ["Protection Suzu"]
    assert hero.save_tools == ["Protection Suzu"]
    assert hero.deployables == ["Immortality Field"]


def test_the_ultimate_is_its_own_numbers_and_the_mech_call_is_not_one():
    barrage = _kit("Barrage", KIND_ULTIMATE, _per_second("dps", 150),
                   _stat("duration", 3, "seconds"), _stat("ult_req", 2100, "points"))
    remech = _kit("Call Mech", KIND_ULTIMATE, _stat("damage", 1000, "hp"),
                  _stat("ult_req", 1500, "points"))
    hero = _hero(abilities=[barrage, remech])
    assert hero.ult is barrage and hero.ult_damage_raw == 450.0
    assert hero.ult_cost == 2100.0 and hero.dmg_ult
    # an ultimate with no damage row is no damage ultimate
    sound = _kit("Sound Barrier", KIND_ULTIMATE, _stat("overhealth", 750, "hp"))
    quiet = _hero("support", abilities=[sound])
    assert quiet.ult is sound and not quiet.dmg_ult and quiet.ult_damage_raw == 0.0
    assert _hero().ult is None and _hero().ult_cost is None
