"""The kit in the format in force, facts/kit_format.py: the wiki's 6v6
figures laid over the 5v5 rows on a hero built by hand, a row that holds
the figure twice and a stale line left alone and said so; then on the built
database, where 6v6 is the format the load reads by default and 5v5 reads
the kit as stored."""

import pytest

from facts import board_facts, kit_format, tables
from facts.draft import FIVE_V_FIVE, KIT_FORMAT, SIX_V_SIX, Draft
from facts.kit import KitPiece, Stat
from facts.model import Hero, World
from facts.records import KitLine


def _stat(code, value, text):
    return Stat(code=code, value=value, unit_num=None, unit_den=None, den_value=None,
                condition=None, text=text)


def _hero():
    """Anvil: a 5v5 kit of three pieces, the 6v6 kit its article states."""
    barrier = KitPiece("Barrier Field", "ability")
    barrier.stats["barrier_health"].append(_stat("barrier_health", 1500.0, "1500"))
    barrier.stats["cooldown"].append(_stat("cooldown", 5.0, "5 seconds"))
    shield = KitPiece("Adaptive Shield", "ability")
    shield.stats["overhealth"].append(_stat("overhealth", 100.0, "100 base + 100 per enemy"))
    hammer = KitPiece("Rocket Hammer", "weapon")
    hammer.extra["weapon"] = "Rocket Hammer"
    hammer.stats["spread"].append(_stat("spread", 3.0, "3 degrees"))
    return Hero(
        id=1, name="Anvil", role="tank", subrole="Stalwart", health=250, armor=300,
        abilities=[barrier, shield], weapons=[hammer], six_pools={"health": 325},
        six_lines=[
            KitLine("Barrier Field", "barrier_health", 1500.0, 1800.0,
                    "Shield health increased from 1500 to 1800"),
            KitLine("Barrier Field", "cooldown", 7.0, 8.0, "Cooldown increased from 7 to 8"),
            KitLine("Adaptive Shield", "overhealth", 100.0, 50.0,
                    "Overhealth gained per target reduced from 100 to 50"),
            KitLine("Rocket Hammer", "spread", 3.0, 4.0, "Spread increased from 3 to 4"),
            KitLine("Rocket Hammer", None, None, None, "No longer staggers")])


def _world(hero):
    w = World()
    w.heroes[hero.id] = hero
    return w


def test_the_6v6_kit_moves_the_pool_and_every_row_it_names_once():
    """The health pool is 6v6's; the barrier's health and the weapon's spread
    move. The cooldown line's 7 is not the 5 the kit holds, so the line is
    stale and the row stays; "100 base + 100 per enemy" holds 100 twice, so
    a line about the per-enemy part moves nothing; a line with no figure
    moves nothing. Each is kept, applied or not."""
    hero = _hero()
    w = _world(hero)
    kit_format.apply(w, SIX_V_SIX)
    barrier, shield = hero.abilities
    assert (w.kit_format, hero.health, hero.armor) == (SIX_V_SIX, 325, 300)
    assert barrier.max_stat("barrier_health") == 1800.0
    assert barrier.max_stat("cooldown") == 5.0
    assert shield.max_stat("overhealth") == 100.0
    assert hero.weapons[0].max_stat("spread") == 4.0
    assert [(c.piece, c.stat, c.applied) for c in hero.kit_changes] == [
        ("", "health", True), ("Barrier Field", "barrier_health", True),
        ("Barrier Field", "cooldown", False), ("Adaptive Shield", "overhealth", False),
        ("Rocket Hammer", "spread", True), ("Rocket Hammer", None, False)]


def test_the_5v5_format_reads_the_kit_as_stored():
    hero = _hero()
    w = _world(hero)
    kit_format.apply(w, FIVE_V_FIVE)
    assert (w.kit_format, hero.health, hero.kit_changes) == (FIVE_V_FIVE, 250, [])
    assert hero.abilities[0].max_stat("barrier_health") == 1500.0


def test_the_kit_is_read_in_6v6():
    """The shipped playbook's open-queue-ranked assumption: the format is one
    constant, 6v6."""
    assert KIT_FORMAT == SIX_V_SIX


@pytest.mark.invariant
def test_the_built_world_reads_the_6v6_kit_and_keeps_the_5v5_one(db):
    """Reinhardt's barrier holds 1800 in 6v6 and 1500 as stored, his pool is
    6v6's, and a board names what 6v6 moved in his kit."""
    six = tables.load(db)
    five = tables.load(db, FIVE_V_FIVE)
    db.rollback()
    rein6, rein5 = six.hero("Reinhardt"), five.hero("Reinhardt")
    assert (rein6.barrier_hp, rein5.barrier_hp) == (1800.0, 1500.0)
    assert (rein6.health, rein6.armor) == (325, 225)
    assert (rein5.health, rein5.armor) == (250, 300)
    assert five.kit_format == FIVE_V_FIVE and not rein5.kit_changes
    moved = [c for h in six.heroes.values() for c in h.kit_changes if c.applied]
    assert len(moved) >= 50
    fs = board_facts.generate(six, Draft(map_name="King's Row", red=("Reinhardt",)))
    (fact,) = fs.find("hero.kit_format")
    assert fact.text.startswith("Reinhardt in 6v6: health 250 -> 325, armor 300 -> 225,")
    assert "Barrier Field barrier health 1500 -> 1800" in fact.text
