"""A hero the wiki announced, then Blizzard lists: the roster pull trades the
wiki's abilities and perks for Blizzard's, on the database inside a
transaction that is rolled back. Skipped without the database."""

import pytest

from db import KIND_ABILITY, KIND_ULTIMATE, psql
from db.data.blizzard import heroes as blizzard_heroes
from db.data.blizzard.heroes import AbilityText, HeroCard, PerkText, RoleIcons, Subrole
from db.data.names import name_key, slug
from db.data.wiki.kits import kit_store
from db.data.wiki.kits.kit_rows import AbilityEntry, HeroKit, PerkEntry, StatValue

pytestmark = pytest.mark.invariant

HERALD, WARDEN = "Test Herald", "Test Warden"


def _ability(name, kind=KIND_ABILITY, **stats):
    return AbilityEntry(
        name=name, mode=None, input_key=None, keywords="", description="%s." % name,
        stats={code: StatValue(text, text) for code, text in stats.items()}, kind=kind,
        display_name=name)


def _perk(name, tier, description="", **stats):
    return PerkEntry(
        name=name, mode=None, input_key=None, keywords="", description=description or name,
        stats={code: StatValue(text, text) for code, text in stats.items()}, tier=tier)


def _announce(cursor, name, subrole, wiki_id):
    """An announced hero's row, as the kits pull stores one."""
    return psql.scalar(cursor.execute(
        "INSERT INTO heroes (slug, name, role_id, subrole_id, status, source_id)"
        " SELECT %s, %s, role_id, subrole_id, 'announced', %s FROM subroles WHERE code = %s"
        " RETURNING hero_id", (slug(name), name, wiki_id, subrole.code)))


def _kit(cursor, hero_id):
    """A hero's abilities and perks: each at its place, and whose row it is."""
    abilities = cursor.execute(
        "SELECT a.position, a.name, s.code FROM abilities a JOIN sources s USING (source_id)"
        " WHERE a.hero_id = %s ORDER BY a.position", (hero_id,)).fetchall()
    perks = cursor.execute(
        "SELECT p.tier_id, p.position, p.name, s.code FROM perks p JOIN sources s USING (source_id)"
        " WHERE p.hero_id = %s ORDER BY p.tier_id, p.position", (hero_id,)).fetchall()
    return abilities, perks


def test_a_listed_hero_trades_the_wikis_kit_for_blizzards_carousel(sandbox):
    """Herald's kit is on file from the wiki, ultimate first at position 0, as
    Doctrine's was. Blizzard's carousel puts the weapon at 0 and the ultimate
    last, and reorders and renames perks: the pull stores it without a
    UniqueViolation, and Herald keeps Blizzard's rows alone, the wiki's stats
    and perk links gone with the rows they hung on. Warden's page would not
    fetch, so its wiki rows stay as they were."""
    cursor = sandbox.cursor()
    wiki_id = psql.scalar(cursor.execute("SELECT source_id FROM sources WHERE code = 'wiki'"))
    subrole = Subrole(*cursor.execute(
        "SELECT s.code, r.code, s.name, s.passive_description FROM subroles s"
        " JOIN roles r USING (role_id) WHERE r.code = 'support' ORDER BY s.code").fetchone())
    herald = _announce(cursor, HERALD, subrole, wiki_id)
    warden = _announce(cursor, WARDEN, subrole, wiki_id)
    herald_kit = HeroKit(
        weapons=[],
        abilities=[
            _ability("Test Deliverance", KIND_ULTIMATE), _ability("Test Drones", cooldown="10"),
            _ability("Test Momentum")],
        perks=[
            _perk("Test Siphon", "minor"), _perk("Test Grace", "minor"),
            _perk("Test Cost", "major"),
            _perk("Test Transfusion", "major", "Test Drones heal more.", cooldown="6")])
    warden_kit = HeroKit(
        weapons=[], abilities=[_ability("Test Beacon")],
        perks=[_perk("Test Vigil", "minor"), _perk("Test Watch", "minor")])
    kit_store.store(
        cursor, {HERALD: herald_kit, WARDEN: warden_kit}, {},
        {name_key(HERALD): herald, name_key(WARDEN): warden}, wiki_id)
    assert _kit(cursor, herald)[0][0] == (0, "Test Deliverance", "wiki")
    warden_wiki = _kit(cursor, warden)
    ability_ids = [row[0] for row in cursor.execute(
        "SELECT ability_id FROM abilities WHERE hero_id = %s", (herald,))]
    perk_ids = [row[0] for row in cursor.execute(
        "SELECT perk_id FROM perks WHERE hero_id = %s", (herald,))]
    hung = (
        "SELECT (SELECT count(*) FROM ability_stats WHERE ability_id = ANY(%s)),"
        " (SELECT count(*) FROM perk_stats WHERE perk_id = ANY(%s)),"
        " (SELECT count(*) FROM perk_ability_effects WHERE perk_id = ANY(%s))")
    assert cursor.execute(hung, (ability_ids, perk_ids, perk_ids)).fetchone() == (1, 1, 1)

    carousel = [
        AbilityText("Test Rifle", "Fires.", 0), AbilityText("Test Drones", "Heals.", 1),
        AbilityText("Test Momentum", "Moves.", 2), AbilityText("Test Deliverance", "Saves.", 3)]
    perk_texts = [
        PerkText(1, "Test Grace", "Grace.", 1), PerkText(1, "Test Siphon", "Siphon.", 2),
        PerkText(2, "Test Price", "Price.", 1), PerkText(2, "Test Transfusion", "More.", 2)]
    roster = [
        HeroCard(slug(name), name, "support", subrole.code, None) for name in (HERALD, WARDEN)]
    blizzard_heroes._store(
        cursor, {subrole.code: subrole}, roster, {slug(HERALD): carousel},
        {slug(HERALD): perk_texts}, RoleIcons({}, {}), psql.now())

    abilities, perks = _kit(cursor, herald)
    assert abilities == [
        (0, "Test Rifle", "blizzard"), (1, "Test Drones", "blizzard"),
        (2, "Test Momentum", "blizzard"), (3, "Test Deliverance", "blizzard")]
    assert perks == [
        (1, 1, "Test Grace", "blizzard"), (1, 2, "Test Siphon", "blizzard"),
        (2, 1, "Test Price", "blizzard"), (2, 2, "Test Transfusion", "blizzard")]
    assert cursor.execute(hung, (ability_ids, perk_ids, perk_ids)).fetchone() == (0, 0, 0)
    assert _kit(cursor, warden) == warden_wiki
    assert cursor.execute(
        "SELECT DISTINCT status FROM heroes WHERE hero_id IN (%s, %s)",
        (herald, warden)).fetchall() == [("released",)]
