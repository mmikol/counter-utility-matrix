"""A hero's facts from facts/hero_facts.py, written for one hero at a time
on the synthetic World: who it is, the traits its numbers carry, its kit
piece by piece, its rates and what they warn of, where it does best, the
wiki's relations, and what only the board has - the map, the opponents and
the teammates. Every sentence is worked from tests/synthetic.py. No
database."""

from db import KIND_ABILITY, KIND_ULTIMATE, KIND_WEAPON
from facts import hero_facts
from facts.draft import Draft
from facts.factset import FactSet
from facts.kit import Kit, Stat
from facts.model import Resolved
from facts.records import Modifier, PerkEffect


def _facts(world, name, *, team="blue", map_name=None, red=(), blue=()):
    """The facts hero_facts.write gives one hero on a board: `name` is seated
    on `team`, beside `red` and `blue`'s other picks."""
    hero = world.hero(name)
    red_h = [world.hero(n) for n in red] + ([hero] if team == "red" else [])
    blue_h = [world.hero(n) for n in blue] + ([hero] if team == "blue" else [])
    board = Resolved(world.map(map_name) if map_name else None, red_h, blue_h, [])
    fs = FactSet(Draft(map_name, tuple(h.name for h in red_h), tuple(h.name for h in blue_h)))
    hero_facts.write(fs, world, board, hero, team)
    return fs


def _texts(fs, key, subject):
    return [f.text for f in fs.find(key, subject)]


def test_a_hero_is_named_by_role_pool_styles_weapon_and_subrole_passive(synthetic_world):
    fs = _facts(synthetic_world, "Mortar", team="red")
    (identity,) = fs.find("hero.identity", "Mortar")
    assert identity.text == (
        "red Mortar - Tank (Bruiser), 275hp+100ar; styles: brawl; weapon: melee, projectile")
    assert identity.value == {"role": "tank", "subrole": "Bruiser"} and identity.team == "red"
    (pool,) = fs.find("hero.pool", "Mortar")
    assert pool.text == ("Mortar pool: 375 (275 health, 0 shield, 100 armor), 137.5 more armor"
                         " from its forms, time-averaged")
    assert (pool.value, pool.unit) == (375, "hp")
    assert _texts(fs, "hero.passive", "Mortar") == [
        "Mortar's Bruiser passive: Heals a little on a kill."]
    assert not fs.find("hero.announced")
    # a shield shows in the pool; a subrole with no passive on record says nothing
    quarry = _facts(synthetic_world, "Quarry")
    assert _texts(quarry, "hero.identity", "Quarry") == [
        "blue Quarry - Tank (Bruiser), 450hp+200sh; styles: poke; weapon: projectile"]
    assert not _facts(synthetic_world, "Kite").find("hero.passive")


def test_an_announced_hero_is_flagged_with_its_release_day(synthetic_world):
    w = synthetic_world
    wisp = w.hero("Wisp")
    fs = FactSet(Draft(blue=("Wisp",)))
    hero_facts.write(fs, w, Resolved(None, [], [wisp], []), wisp, "blue")
    (announced,) = fs.find("hero.announced", "Wisp")
    assert announced.text == (
        "CAUTION: Wisp is announced, not yet playable (releases 2026-12-01) - the kit is"
        " the wiki's preview and there are no rates")
    assert announced.value == "2026-12-01"
    assert not fs.find("hero.rate") and not fs.find("hero.rate_maps")     # no rates
    wisp.release_date = None
    fs = FactSet(Draft(blue=("Wisp",)))
    hero_facts.write(fs, w, Resolved(None, [], [wisp], []), wisp, "blue")
    assert fs.find("hero.announced")[0].value is None
    assert "(releases" not in fs.find("hero.announced")[0].text


def test_each_trait_the_kit_carries_is_one_fact(synthetic_world):
    """A trait with no number on the hero says nothing; each one it has is a
    fact of its own, sourced to the derivation."""
    w = synthetic_world
    anvil = _facts(w, "Anvil")
    said = {
        f.key: f.text for f in anvil.facts
        if f.source.startswith("derived:") and f.key != "hero.best_map"}
    assert said == {
        "hero.dps": "Anvil's weapon sustains 85 damage per second",
        "hero.burst": "Anvil's biggest single hit: 300",
        "hero.range": "Anvil's weapon reaches 5m",
        "hero.cooldown_median": "Anvil's median cooldown: 8.5s across 2 abilities",
        "hero.cc": "Anvil brings crowd control: Quake Slam",
        "hero.mobility": "Anvil brings movement: Bull Rush",
        "hero.barrier": "Anvil fields a 1200-hp barrier"}
    assert all(f.source == "derived:" + f.key for f in anvil.facts if f.key in said)
    assert _texts(anvil, "hero.style", "Anvil") == ["Anvil is a brawl hero"]
    assert _texts(_facts(w, "Flint"), "hero.style", "Flint") == [
        "Flint is a dive hero", "Flint is a poke hero"]
    balm = _facts(w, "Balm")
    assert _texts(balm, "hero.heal_peak", "Balm") == ["Balm's biggest single heal: 70"]
    assert _texts(balm, "hero.hps", "Balm") == [
        "Balm sustains 60 healing per second on teammates"]
    assert _texts(balm, "hero.cleanse", "Balm") == ["Balm can cleanse: Warding Charm"]
    assert _texts(balm, "hero.invuln", "Balm") == ["Balm has an invulnerability: Warding Charm"]
    assert _texts(_facts(w, "Quarry"), "hero.self_heal", "Quarry") == [
        "Quarry heals itself: 300 a cast"]
    assert _texts(_facts(w, "Myrrh"), "hero.antiheal", "Myrrh") == [
        "Myrrh carries anti-heal (-50% healing)"]
    assert _texts(_facts(w, "Tansy"), "hero.dmg_amp", "Tansy") == [
        "Tansy amplifies damage by up to 30%"]
    assert _texts(_facts(w, "Sorrel"), "hero.deployables", "Sorrel") == [
        "Sorrel deploys: Stasis Field"]
    assert _texts(_facts(w, "Kite"), "hero.flyer", "Kite") == [
        "Kite flies: a vertical threat, answered by hitscan"]
    assert _texts(_facts(w, "Mortar"), "hero.pierces_barrier", "Mortar") == [
        "Mortar's kit ignores barriers"]


def test_the_ultimate_and_the_rarer_traits_read_their_own_numbers(synthetic_world):
    """An ultimate's damage is a fact only where the hero has an ultimate to
    name; its cost, a heal amp, overhealth and a heal over a rate read as
    given."""
    w = synthetic_world
    rook = w.hero("Rook")
    assert rook.ult_damage == 500.0 and not _facts(w, "Rook").find("hero.ult_damage")
    rook.ult = Kit("Death Bloom", KIND_ULTIMATE, "Spins in place.")
    rook.ult_cost = 2100.0
    rook.self_hps, rook.heal_amp, rook.overhealth = 25.0, 15.0, 75.0
    fs = _facts(w, "Rook")
    assert _texts(fs, "hero.ult_damage", "Rook") == [
        "Rook's ultimate Death Bloom deals up to 500"]
    assert _texts(fs, "hero.ult_cost", "Rook") == ["Rook's ultimate costs 2100 charge"]
    assert _texts(fs, "hero.self_heal", "Rook") == ["Rook heals itself: 25 per second"]
    assert fs.find("hero.self_heal", "Rook")[0].value == {"cast": 0.0, "per_second": 25.0}
    assert _texts(fs, "hero.heal_amp", "Rook") == ["Rook amplifies healing by up to 15%"]
    assert _texts(fs, "hero.overhealth", "Rook") == ["Rook grants up to 75 overhealth"]
    assert "; ult Death Bloom: Spins in place." in fs.find("hero.identity", "Rook")[0].text


def test_the_kit_is_told_piece_by_piece(synthetic_world):
    """Each ability, its keywords and its stats; each weapon config with its
    type and slot; each perk, what it alters, and what an ability scales."""
    w = synthetic_world
    kite = w.hero("Kite")
    slam = Kit("Rocket Punch", KIND_ABILITY, "A fist that flies.", keywords="knockback::movement")
    slam.stats["cooldown"].append(Stat(code="cooldown", value=4, unit_num="seconds",
                                       unit_den=None, den_value=None, condition=None,
                                       text="4 seconds"))
    gun = Kit("Burst", KIND_WEAPON)
    gun.extra.update(weapon="Rotary Cannon", weapon_type="Projectile", slot="secondary_fire")
    gun.stats["damage"].append(Stat(code="damage", value=30, unit_num="hp", unit_den=None,
                                    den_value=None, condition="per shell", text="30"))
    perk = Kit("Longer Punch", "perk:minor", "Rocket Punch travels further.")
    kite.abilities, kite.weapons, kite.perks = [slam], [gun], [perk]
    kite.perk_effects = [PerkEffect("Longer Punch", "Rocket Punch")]
    kite.modifiers = [Modifier("Rocket Punch", "move_speed", "self", 30.0, "percent")]
    fs = _facts(w, "Kite")
    assert _texts(fs, "hero.ability", "Kite") == [
        "Kite - Rocket Punch (ability): A fist that flies."]
    assert _texts(fs, "hero.ability_keywords", "Kite") == [
        "Kite's Rocket Punch is tagged: knockback, movement"]
    assert _texts(fs, "hero.ability_stat", "Kite") == ["Kite's Rocket Punch cooldown: 4 seconds"]
    assert _texts(fs, "hero.weapon", "Kite") == [
        "Kite weapon: Rotary Cannon - Burst [Projectile], secondary fire"]
    assert _texts(fs, "hero.weapon_stat", "Kite") == ["Kite's Burst damage: 30 hp (per shell)"]
    assert _texts(fs, "hero.perk", "Kite") == [
        "Kite perk (minor) - Longer Punch: Rocket Punch travels further."]
    assert _texts(fs, "hero.perk_effect", "Kite") == [
        "Kite's perk Longer Punch alters Rocket Punch"]
    assert _texts(fs, "hero.modifier", "Kite") == [
        "Kite's Rocket Punch changes move speed by +30% on self"]


def test_the_rates_and_what_they_warn_of(synthetic_world):
    """Needle: 52 across all ranks, seven points between its tiers, banned in
    30% of lobbies. Gale rose two points since the previous capture; Rook's
    one-point fall is under TREND_POINTS."""
    w = synthetic_world
    needle = _facts(w, "Needle")
    assert _texts(needle, "hero.rate", "Needle") == [
        "Needle across all ranks: wins 52.0%, picked 10.0%, banned 30.0%"]
    assert _texts(needle, "hero.rate_tier", "Needle") == [
        "Needle in bronze lobbies: wins 48.5%, picked 10.0%, banned 30.0%",
        "Needle in grandmaster lobbies: wins 55.5%, picked 10.0%, banned 30.0%"]
    assert _texts(needle, "hero.rank_sensitivity", "Needle") == [
        "RANK-SENSITIVE: Needle swings 7.0 points across ranks (48.5%-55.5%)"]
    assert _texts(needle, "hero.ban_pressure", "Needle") == [
        "Needle is banned in 30% of lobbies - a near-certain ban"]
    assert not needle.find("hero.trend")
    assert _texts(_facts(w, "Gale"), "hero.trend", "Gale") == [
        "trend since the previous capture: Gale +2.0 win rate"]
    rook = _facts(w, "Rook")
    assert not rook.find("hero.trend") and not rook.find("hero.rank_sensitivity")
    w.hero("Rook").ban = 22.0
    assert _texts(_facts(w, "Rook"), "hero.ban_pressure", "Rook") == [
        "Rook is banned in 22% of lobbies - a likely ban"]


def test_with_no_map_a_hero_names_where_it_does_best(synthetic_world):
    """Anvil: 52.5 on Harbor Gate, 50 on Ember Ruins, 47 on Salt Flats, over
    its own 50 - one line of its best rates and one of its positive lifts."""
    w = synthetic_world
    fs = _facts(w, "Anvil")
    assert _texts(fs, "hero.rate_maps", "Anvil") == [
        "Anvil's best maps: Harbor Gate (52.5%), Ember Ruins (50.0%), Salt Flats (47.0%)"]
    assert _texts(fs, "hero.best_map", "Anvil") == [
        "Anvil's three best maps by Blizzard's map rates, over its own 50.0%: Harbor Gate (+2.5)"]
    on_map = _facts(w, "Anvil", map_name="Ember Ruins")
    assert not on_map.find("hero.rate_maps") and not on_map.find("hero.best_map")


def test_the_wikis_counters_and_partners_are_told_whoever_else_is_picked(synthetic_world):
    fs = _facts(synthetic_world, "Gale")
    assert _texts(fs, "hero.answered_by", "Gale") == [
        "Gale is countered by, in the wiki's match-up advice: Flint, Needle"]
    assert _texts(fs, "hero.answers", "Gale") == [
        "Gale answers, in the wiki's match-up advice: Anvil"]
    # the stronger pair first
    assert _texts(fs, "hero.partner", "Gale") == [
        "Gale + Kite (2/3): both take the fight to the air",
        "Gale + Sorrel (1/3): the field covers a dive"]


def test_on_a_map_a_hero_reads_its_rates_there_against_its_own(synthetic_world):
    """Anvil's lift is exactly SPECIALIST_DELTA on Harbor Gate, nothing on
    Ember Ruins and three points down on Salt Flats."""
    w = synthetic_world
    harbor = _facts(w, "Anvil", map_name="Harbor Gate")
    assert _texts(harbor, "hero.map_win", "Anvil") == [
        "Anvil on Harbor Gate (this map): wins 52.5%, picked 12.0%"]
    assert _texts(harbor, "hero.map_delta", "Anvil") == [
        "Anvil runs +2.5 on Harbor Gate vs their own overall 50.0% - map specialist"]
    assert _texts(harbor, "hero.map_strategy", "Anvil") == [
        "this map is Anvil's top-1 by Blizzard's map rates"]
    assert _texts(harbor, "hero.map_style_fit", "Anvil") == [
        "Anvil fits the brawl style Harbor Gate rewards"]
    ember = _facts(w, "Anvil", map_name="Ember Ruins")
    assert _texts(ember, "hero.map_delta", "Anvil") == [
        "Anvil runs +0.0 on Ember Ruins vs their own overall 50.0% - in line with their"
        " baseline"]
    assert not ember.find("hero.map_strategy") and not ember.find("hero.map_style_fit")
    salt = _facts(w, "Anvil", map_name="Salt Flats")
    assert salt.find("hero.map_delta")[0].text.endswith("- off-map liability")
    # a map's ban rate rides the line where the rates publish one
    assert _texts(_facts(w, "Needle", map_name="Harbor Gate"), "hero.map_win", "Needle") == [
        "Needle on Harbor Gate (this map): wins 50.0%, picked 9.0%, banned 40.0%"]


def test_against_the_opponents_and_beside_the_teammates(synthetic_world):
    """Anvil answers Mortar: blue's Mortar is warned, red's only noted; Anvil
    and Balm are wiki partners on one side."""
    w = synthetic_world
    blue = _facts(w, "Mortar", team="blue", red=("Anvil",))
    assert _texts(blue, "hero.vs_answered_by", "Mortar") == [
        "WARNING: blue Mortar is answered by red Anvil"]
    red = _facts(w, "Mortar", team="red", blue=("Anvil",))
    assert _texts(red, "hero.vs_answered_by", "Mortar") == [
        "NOTE: red Mortar is answered by blue Anvil"]
    anvil = _facts(w, "Anvil", team="blue", red=("Mortar",), blue=("Balm",))
    assert _texts(anvil, "hero.vs_answers", "Anvil") == ["blue Anvil answers red Mortar"]
    assert anvil.find("hero.vs_answers", "Anvil")[0].value == ["Mortar"]
    assert _texts(anvil, "hero.with_ally", "Anvil") == [
        "blue Anvil + Balm (2/3): the charm keeps the hammer swinging"]
    # an opponent is no ally, whatever the wiki pairs
    assert not _facts(w, "Anvil", team="blue", red=("Balm",)).find("hero.with_ally")


def test_a_long_description_is_trimmed_to_its_limit():
    assert hero_facts._trim("  a   b\nc ") == "a b c"
    assert hero_facts._trim(None) == ""
    long = "x" * 120
    assert hero_facts._trim(long) == "x" * 109 + "…" and len(hero_facts._trim(long, 20)) == 20
