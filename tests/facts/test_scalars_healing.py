"""Sustained healing, hero.hps, from facts/scalars.py: the formation model,
the reach of an area heal, a beam held to its resource, and what the sum
leaves out. Each test builds the pieces by hand in the shape the load reads
them. The built World's figures are tests/facts/test_world_kits.py's. No
database."""

import pytest

from db import KIND_ABILITY, KIND_PASSIVE, KIND_ULTIMATE, KIND_WEAPON
from facts import scalars
from facts.kit import KitPiece, Stat
from facts.model import Hero


def _stat(code, value, unit_num=None, unit_den=None, den=None, condition=None, text=None):
    return Stat(code=code, value=value, unit_num=unit_num, unit_den=unit_den, den_value=den,
                condition=condition, text=text)


def _rate(code, value, condition=None, unit="hp"):
    return _stat(code, value, unit, "seconds", 1, condition)


def _kit(name, kind, *stats, keywords=""):
    kit = KitPiece(name, kind, keywords=keywords)
    for s in stats:
        kit.stats[s.code].append(s)
    if kind == KIND_WEAPON:
        kit.extra.update(weapon=name, slot="primary_fire")
    return kit


def _hero(role="support", *, weapons=(), abilities=(), perks=()):
    hero = Hero(id=1, name="Test", role=role, subrole="Medic", weapons=list(weapons),
                abilities=list(abilities), perks=list(perks))
    scalars.derive_scalars(hero)
    return hero


def test_the_formation_reads_the_disks_distance_distribution_in_closed_form():
    """Two points spread over a 15 m disk lie within 3, 12 and 20 m of each
    other 3.7%, 42.6% and 81.9% of the time; always within twice the radius."""
    assert scalars.FORMATION_RADIUS == 15.0 and scalars.TEAMMATES == 5
    got = [scalars.p_within(r) for r in (3, 12, 20)]
    assert got == pytest.approx([0.03661, 0.42624, 0.81893], abs=0.000005)
    assert scalars.p_within(0) == 0.0 and scalars.p_within(30) == 1.0 == scalars.p_within(40)
    # the closed form rises with r and meets 1 at 2R
    assert scalars.p_within(29.99) == pytest.approx(1.0, abs=0.0001)
    # reach: five teammates at most, the aimed one always
    assert scalars.around_caster(12) == pytest.approx(5 * 0.42624, abs=0.00005)
    assert scalars.on_teammate(4) == pytest.approx(1 + 4 * scalars.p_within(4))
    assert scalars.around_caster(100) == 5 == scalars.on_teammate(100)
    assert scalars.around_caster(0) == 0 and scalars.on_teammate(0) == 1


def test_a_beam_heals_at_what_its_resource_sustains():
    """Fire until x% is spent, wait out the delay, regenerate, at the best x:
    Illari's 115 sustains 53.41, Moira's 80 with its 17/s lingering 49.40,
    Wuyang's manual 50 12.87."""
    assert scalars.energy_duty(33.3, 35.0, 0.6, 115.0, empty=0.4) == pytest.approx(53.41, abs=0.005)
    assert scalars.energy_duty(12.5, 15.6, 0.45, 80.0, 17.0, 3.0) == pytest.approx(49.40, abs=0.005)
    assert scalars.energy_duty(33.3, 15.0, 2.0, 50.0) == pytest.approx(12.87, abs=0.005)
    beam = _kit(
        "Solar Beam", KIND_WEAPON, _rate("heal", 115), _rate("hps", 115),
        _rate("energy", 33.3, "cost", "percent"), _rate("energy", 35, "regen rate", "percent"),
        _stat("duration", 0.6, "seconds", condition="energy regen delay"), keywords="beam")
    assert _hero(weapons=[beam]).hps == pytest.approx(scalars.energy_duty(33.3, 35.0, 0.6, 115.0))
    # a beam with no resource heals at its heal row, before its hps field
    staff = _kit("Staff", KIND_WEAPON, _rate("heal", 55), _rate("hps", 60), keywords="beam")
    assert _hero(weapons=[staff]).hps == 55.0


def test_an_area_heal_counts_the_teammates_it_reaches():
    """An aura on the caster reaches 5 p(r) teammates, a grenade on an aimed
    one 1 + 4 p(r), a wave its angle's share; a heal on no listed area
    counts one target. The pieces add up."""
    aura = _kit("Crossfade", KIND_ABILITY, _rate("heal", 18, "allies"), _rate("heal", 12, "self"),
                _stat("radius", 12, "meters"))
    grenade = _kit("Biotic Grenade", KIND_ABILITY, _stat("heal", 90, "hp"),
                   _stat("radius", 4, "meters"), _stat("cooldown", 12, "seconds"))
    wave = _kit("Wave", KIND_ABILITY, _stat("heal", 80, "hp"), _stat("cooldown", 14, "seconds"),
                _stat("view_angle", 15, "degrees"), keywords="shockwave")
    lone = _kit("Pack", KIND_ABILITY, _stat("heal", 25, "hp", condition="instantly"),
                _stat("heal", 100, "hp", "seconds", 2, "over time"),
                _stat("radius", 20, "meters"), _stat("cooldown", 5, "seconds"))
    hero = _hero(abilities=[aura, grenade, wave, lone])
    assert hero.hps_pieces == pytest.approx({
        "Crossfade": 18 * 5 * scalars.p_within(12),
        "Biotic Grenade": 90 * (1 + 4 * scalars.p_within(4)) / 12,
        "Wave": 80 * (1 + 4 * 15 / 360) / 14,
        "Pack": 125 / 5})
    assert hero.hps == pytest.approx(sum(hero.hps_pieces.values()))
    assert hero.hps_pieces["Crossfade"] == pytest.approx(38.36, abs=0.005)


def test_a_cast_cycles_on_its_cooldown_and_a_held_effect_on_both():
    """Amp It Up adds 56 - 18 over Crossfade for 3 s of every 12 + 3; an orb
    stops at its 300; the smaller of two instant figures is the one every
    cast lands."""
    crossfade = _kit("Crossfade", KIND_ABILITY, _rate("heal", 18, "allies"),
                     _stat("radius", 12, "meters"))
    amp = _kit(
        "Amp It Up", KIND_ABILITY, _rate("heal", 56), _stat("radius", 12, "meters"),
        _stat("cooldown", 12, "seconds"), _stat("duration", 3, "seconds"))
    reach = 5 * scalars.p_within(12)
    assert _hero(abilities=[crossfade, amp]).hps_pieces["Amp It Up"] == pytest.approx(
        38 * 3 / 15 * reach)
    orb = _kit(
        "Biotic Orb", KIND_ABILITY,
        _stat("heal", 75, "hp", "seconds", 1, text="75 per second , up to 300"),
        _stat("cooldown", 8, "seconds"), _stat("duration", 7, "seconds", condition="max"))
    assert _hero(abilities=[orb]).hps == pytest.approx(300 / 15)
    flash = _kit("Flash Heal", KIND_ABILITY, _stat("heal", 60, "hp", condition="default"),
                 _stat("heal", 120, "hp", condition="low health"), _stat("cooldown", 12, "seconds"))
    assert _hero(abilities=[flash]).hps == pytest.approx(5.0)


def test_a_bounce_a_trigger_and_a_lock_on_read_their_own_rows():
    """Kasa's second bounce lands when one of four teammates stands within 12
    m, its third when one of three more does; Inspire fires on the first
    Flail swing past its 1.25 s lockout; the torpedo lock holds the gun."""
    kasa = _kit("Healing Kasa", KIND_ABILITY,
                *(_stat("heal", v, "hp", condition=c)
                  for v, c in ((90, "1st bounce"), (70, "2nd bounce"), (50, "3rd bounce"),
                               (30, "self"))),
                _stat("range", 12, "meters", condition="bounce range from target"),
                _stat("cooldown", 6, "seconds"))
    q = scalars.p_within(12)
    second = 1 - (1 - q) ** 4
    third = second * (1 - (1 - q) ** 3)
    assert _hero(abilities=[kasa]).hps == pytest.approx((90 + 70 * second + 50 * third) / 6)
    flail = _kit("Rocket Flail", KIND_WEAPON, _stat("fire_rate", 1, "swings", "seconds", 0.6),
                 _rate("dps", 75))
    inspire = _kit("Inspire", KIND_PASSIVE, _stat("heal", 12, "hp", condition="instant"),
                   _rate("heal", 11.25), _stat("duration", 4, "seconds"),
                   _stat("radius", 20, "meters"))
    brig = _hero(weapons=[flail], abilities=[inspire])
    assert brig.hps == pytest.approx((11.25 + 12 / 1.8) * 5 * scalars.p_within(20))
    assert brig.hps == pytest.approx(73.36, abs=0.005)
    blaster = _kit("Blaster", KIND_WEAPON, _stat("heal", 72, "hp"), _rate("hps", 80))
    torpedoes = _kit(
        "Torpedoes", KIND_ABILITY, _stat("heal", 85, "hp", condition="direct"),
        _stat("heal", 50, "hp", condition="over time"), _stat("cooldown", 12, "seconds"),
        _stat("duration", 0.35, "seconds", condition="lock-on, min"),
        _stat("duration", 1.0, "seconds", condition="lock-on, max"),
        _stat("range", 40, "meters", condition="targeting"))
    juno = _hero(weapons=[blaster], abilities=[torpedoes])
    lock = 0.35 + 0.65 * (15 - 5) / (40 - 5)
    cycle = 12 + lock
    assert juno.hps_pieces == pytest.approx({
        "Blaster": 80 * (1 - lock / cycle), "Torpedoes": 135 * (1 + 4 * 0.5) / cycle})


def test_a_stream_ticks_at_its_tooltips_and_a_wave_refunds_its_energy():
    """Wuyang's stream: 25 free, 50 at the duty its energy allows, and each
    wave's 33% refund is 0.99 s more of the 50 once every 14 s."""
    stream = _kit(
        "Restorative Stream", KIND_ABILITY, _rate("heal", 20, "passive"),
        _rate("heal", 55, "bonus manual healing"), _rate("energy", 33.3, "cost", "percent"),
        _rate("energy", 15, "recharge", "percent"),
        _stat("duration", 2, "seconds", condition="recharge delay"), keywords="heal;;target ally")
    wave = _kit("Guardian Wave", KIND_ABILITY, _stat("heal", 80, "hp"),
                _stat("cooldown", 14, "seconds"), _stat("view_angle", 15, "degrees"),
                keywords="shockwave")
    refund = 50 * 33 / 33.3 / 14
    got = _hero(abilities=[stream, wave]).hps_pieces
    assert refund == pytest.approx(3.54, abs=0.005)
    assert got["Restorative Stream"] == pytest.approx(
        25 + scalars.energy_duty(33.3, 15, 2, 50) + refund)
    assert got["Restorative Stream"] == pytest.approx(41.41, abs=0.005)


def test_the_sum_leaves_out_what_does_not_run_beside_the_gun_or_heal_a_teammate():
    """Lifeline ends on primary fire, a dash heals its owner, an ultimate and
    a perk are no baseline, a self row is the hero's own, and a damage hero's
    heal on itself is not the team's; of two healing weapons the better
    counts."""
    gun = _kit("Gun", KIND_WEAPON, _stat("heal", 24, "hp"), _rate("hps", 87))
    alt = _kit("Gun (ADS)", KIND_WEAPON, _rate("hps", 60))
    lifeline = _kit("Lifeline", KIND_ABILITY, _rate("heal", 25, "ally"),
                    _stat("cooldown", 2, "seconds"))
    dash = _kit("Rejuvenating Dash", KIND_ABILITY, _stat("heal", 55, "hp"),
                _stat("cooldown", 5, "seconds"))
    ult = _kit("Tree", KIND_ULTIMATE, _rate("heal", 400))
    perk = _kit("Perk", KIND_ABILITY, _rate("heal", 50))
    purr = _kit("Purr", KIND_ABILITY, _stat("heal", 30, "hp", condition="per pulse, allies"),
                _stat("heal", 18, "hp", condition="per pulse, self"),
                _stat("duration", 4, "seconds", condition="total"),
                _stat("duration", 0.95, "seconds", condition="healing pulse rate"),
                _stat("range", 10, "meters"), _stat("cooldown", 12, "seconds"))
    hero = _hero(weapons=[gun, alt], abilities=[lifeline, dash, ult, purr], perks=[perk])
    assert hero.hps_pieces == pytest.approx({
        "Gun": 87.0, "Purr": 4 * 30 * 5 * scalars.p_within(10) / 16})
    assert hero.hps == pytest.approx(sum(hero.hps_pieces.values()))
    siphon = _kit("Siphon", KIND_ABILITY, _rate("heal", 150), _stat("duration", 3, "seconds"))
    assert _hero("damage", abilities=[siphon]).hps == 0.0


def test_a_share_of_the_teammates_damage_heals_at_the_rosters_dps():
    """Cardiac Overdrive heals the teammates 50% of what they deal for 3 s of
    every 12 + 3, around Mauga: at 94.29 dps a teammate, 16.32."""
    overdrive = _kit(
        "Cardiac Overdrive", KIND_ABILITY, _stat("heal", 50, "percent", condition="allies"),
        _stat("heal", 100, "percent", condition="self"), _stat("duration", 3, "seconds"),
        _stat("cooldown", 12, "seconds"), _stat("radius", 10.5, "meters"),
        keywords="area of effect;;spherical::ignore barrier;;target ally")
    mauga = _hero("tank", abilities=[overdrive])
    assert mauga.hps == 0.0
    scalars.ally_lifesteal(mauga, 94.29)
    assert mauga.hps == pytest.approx(0.5 * 94.29 * 3 / 15 * 5 * scalars.p_within(10.5))
    assert mauga.hps == pytest.approx(16.32, abs=0.005)
    assert mauga.hps_pieces == {"Cardiac Overdrive": mauga.hps}
