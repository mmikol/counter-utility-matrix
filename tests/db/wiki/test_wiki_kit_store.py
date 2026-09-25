"""The store stage of the kits pull, db/data/wiki/kits/kit_store.py, over a
recording cursor: the tables it reloads, the stat keys, the pools a profile
sets, weapons and their configs, the abilities it classifies and adds, a
modifier read off an ability's wording, perk stats and the abilities a perk
alters, an announced hero's perks, and the 6v6 kit beside the 5v5 one. No
database."""

from db import KIND_ABILITY, KIND_PASSIVE
from db.data.wiki.kits import kit_store
from db.data.wiki.kits.hero_articles import HeroProfile
from db.data.wiki.kits.kit_rows import AbilityEntry, HeroKit, PerkEntry, WeaponEntry
from db.data.wiki.kits.six_a_side import SixKit, SixLine
from tests.db.recording import RecordingCursor

SOURCE = 50
KINDS = [("weapon", 1), ("ability", 2), ("ultimate", 3), ("passive", 4)]


def _ability(name, kind=KIND_ABILITY, description="", **stats):
    return AbilityEntry(name=name, mode=None, input_key=None, keywords="",
                        description=description, stats=stats, kind=kind)


def _weapon(name, **stats):
    return WeaponEntry(name=name, mode=None, input_key=None, keywords="melee", description="",
                       stats=stats, display_name=name, weapon_type="melee")


def _perk(name, tier="minor", description="", **stats):
    return PerkEntry(name=name, mode=None, input_key=None, keywords="",
                     description=description, stats=stats, tier=tier)


def test_the_store_reloads_the_kit_tables_and_fills_what_blizzard_loaded():
    """Anvil's hammer and Barrier Field are on file from Blizzard: the store
    classifies both, adds the passive Blizzard does not publish with the
    damage it shrugs off, stats every piece, links the perk to the ability
    it names, and skips a wiki page that is no hero."""
    anvil = HeroKit(
        weapons=[_weapon("Rocket Hammer", damage="100")],
        abilities=[_ability("Barrier Field", barrier_health="1200"),
                   _ability("Steadfast", KIND_PASSIVE, "Takes less damage.",
                            damage_red="30% taken")],
        perks=[_perk("Shield Bash", description="Barrier Field recharges faster.",
                     cooldown="6")])
    by_hero = {"Anvil": anvil, "All heroes": HeroKit([], [_ability("Overview")], [])}
    cursor = RecordingCursor(reads=[
        ('SELECT "code", "kind_id" FROM "ability_kinds"', KINDS),
        ("SELECT name, ability_id FROM abilities", [("Barrier Field", 11), ("Rocket Hammer", 10)]),
        ("SELECT coalesce(max(position), -1) + 1 FROM abilities", [(2,)]),
        ("SELECT name FROM abilities", [("Barrier Field",), ("Rocket Hammer",), ("Steadfast",)]),
        ("SELECT name, perk_id FROM perks", [("Shield Bash", 21)])])
    profiles = {"Anvil": HeroProfile(health=400, shield=0, armor=300),
                "Nobody": HeroProfile(health=1, shield=None, armor=None)}
    tally, unknown = kit_store.store(cursor, by_hero, profiles, {"anvil": 1}, SOURCE)
    assert unknown == ["All heroes"]
    assert tally == {
        "weapons": 1, "configs": 1, "stats": 4, "classified": 2, "added": 1,
        "abilities_with_stats": 2, "modifiers": 1, "perks_announced": 0,
        "perks_with_stats": 1, "perk_links": 1, "health": 1, "six_pools": 0, "six_lines": 0}
    # the reloaded tables go first, dependents before what they hang on
    assert [text for text, _ in cursor.statements[:8]] == [
        'DELETE FROM "%s"' % table for table in kit_store.RELOADED]
    # every code any kit carries, sorted
    assert cursor.written("INSERT INTO stat_keys") == [
        ("barrier_health", SOURCE), ("cooldown", SOURCE), ("damage", SOURCE),
        ("damage_red", SOURCE)]
    # no 6v6 kit: the 6v6 pools are NULL, the 5v5 ones stand
    assert cursor.written("UPDATE heroes") == [(400, 0, 300, None, None, None, 1)]
    # the ids the upserts read back: stat keys 1-4, the weapon 5, its config 6
    assert cursor.written("INSERT INTO weapons") == [(1, "Rocket Hammer", 0, SOURCE)]
    assert cursor.written("INSERT INTO weapon_configs") == [
        (5, 1, "Rocket Hammer", "melee", "melee", 0, SOURCE)]
    assert cursor.written("UPDATE abilities") == [(1, "melee", 10), (2, None, 11)]
    assert cursor.written("INSERT INTO abilities") == [
        (1, 4, "Steadfast", "Takes less damage.", None, 2, SOURCE)]
    # Steadfast, id 7, reduces the damage its owner takes
    assert cursor.written("INSERT INTO ability_modifiers") == [
        (7, 4, "damage_taken", "self", 30.0, "percent", SOURCE)]
    assert cursor.written("INSERT INTO perk_ability_effects") == [
        (21, SOURCE, 1, "Barrier Field")]
    stats = [params for text, params in cursor.statements if text.startswith(
        ('INSERT INTO "weapon_stats"', 'INSERT INTO "ability_stats"', 'INSERT INTO "perk_stats"'))]
    assert [(owner, key, value) for owner, key, value, *_ in stats] == [
        (6, 3, 100.0), (11, 1, 1200.0), (7, 4, 30.0), (21, 2, 6.0)]


def test_an_announced_heros_perks_get_rows_and_a_stored_weapon_is_not_counted_twice():
    """Blizzard has not published Doctrine: the wiki's perks are the only
    ones, two a tier, and each gets a row; a third minor perk is dropped. A
    weapon a re-run already stored reads back no row and is left alone."""
    doctrine = HeroKit(
        weapons=[_weapon("Censer", damage="40")],
        abilities=[],
        perks=[
            _perk("Litany", cooldown="4"), _perk("Vigil"), _perk("Psalm"),
            _perk("Canticle", tier="major", cooldown="8")])
    cursor = RecordingCursor(reads=[
        ('SELECT "code", "kind_id" FROM "ability_kinds"', KINDS),
        ("INSERT INTO weapons", []),
        ("SELECT name, ability_id FROM abilities", []),
        ("SELECT coalesce(max(position), -1) + 1 FROM abilities", [(0,)]),
        ("SELECT name FROM abilities", []),
        ("SELECT name, perk_id FROM perks", []),
        ("SELECT status FROM heroes", [("announced",)])])
    tally, unknown = kit_store.store(cursor, {"Doctrine": doctrine}, {}, {"doctrine": 9}, SOURCE)
    assert unknown == []
    assert (tally["weapons"], tally["configs"]) == (0, 0)
    assert tally["perks_announced"] == 3 and tally["perks_with_stats"] == 2
    assert cursor.written("INSERT INTO perks") == [
        (9, 1, "Litany", "", 1, SOURCE), (9, 1, "Vigil", "", 2, SOURCE),
        (9, 2, "Canticle", "", 1, SOURCE)]
    assert not cursor.written("INSERT INTO weapon_configs")


def test_a_hero_blizzard_has_perks_for_keeps_them():
    """A released hero's perks are Blizzard's: the wiki's are matched to them
    by name, and one Blizzard does not publish is left out."""
    kit = HeroKit([], [], [_perk("Shield Bash", cooldown="6"), _perk("Retired Perk", cooldown="9")])
    cursor = RecordingCursor(reads=[
        ('SELECT "code", "kind_id" FROM "ability_kinds"', KINDS),
        ("SELECT name, perk_id FROM perks", [("Shield Bash", 21)])])
    tally, _ = kit_store.store(cursor, {"Anvil": kit}, {}, {"anvil": 1}, SOURCE)
    assert tally["perks_announced"] == 0 and tally["perks_with_stats"] == 1
    assert not cursor.written("SELECT status FROM heroes") and not cursor.written(
        "INSERT INTO perks")


def test_the_6v6_kit_lands_beside_the_5v5_one():
    """Anvil's article gives a 6v6 health and two 6v6 lines: the pool goes on
    the hero's row beside the 5v5 one, and each line into kit_6v6 with the
    stat its words name, or none for a line with no figure."""
    kit = HeroKit([], [_ability("Barrier Field", barrier_health="1500")], [])
    six = SixKit(pools={"health": 325}, rejected=[], lines=[
        SixLine("Barrier Field", "barrier_health", 1500.0, 1800.0,
                "Shield health increased from 1500 to 1800"),
        SixLine("Barrier Field", None, None, None, "No longer shares a cooldown")])
    cursor = RecordingCursor(reads=[
        ('SELECT "code", "kind_id" FROM "ability_kinds"', KINDS),
        ("SELECT name, ability_id FROM abilities", [("Barrier Field", 11)]),
        ("SELECT coalesce(max(position), -1) + 1 FROM abilities", [(1,)]),
        ("SELECT name FROM abilities", [("Barrier Field",)]),
        ("SELECT name, perk_id FROM perks", [])])
    profiles = {"Anvil": HeroProfile(health=250, shield=None, armor=300)}
    tally, _ = kit_store.store(cursor, {"Anvil": kit}, profiles, {"anvil": 1}, SOURCE,
                               {"Anvil": six})
    assert (tally["six_pools"], tally["six_lines"]) == (1, 2)
    assert cursor.written("UPDATE heroes") == [(250, None, 300, 325, None, None, 1)]
    # barrier_health is stat key 1, the only code the kit and the lines carry
    shield = "Shield health increased from 1500 to 1800"
    assert cursor.written("INSERT INTO kit_6v6") == [
        (1, "Barrier Field", 1, 1500.0, 1800.0, shield, SOURCE),
        (1, "Barrier Field", None, None, None, "No longer shares a cooldown", SOURCE)]
