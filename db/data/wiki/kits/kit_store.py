"""The store stage of the kits pull: each hero's kit into the tables.

Loads weapons and their firing configs, classifies every ability, adds the
abilities Blizzard does not publish, stores each ability's keywords, and
attaches stat measurements to abilities, weapons and perks, with the
modifiers an ability applies and the abilities a perk alters, then the 6v6
kit beside the 5v5 one: the pools on the hero's row, the lines in kit_6v6.
The weapon, stat, modifier and 6v6 tables are reloaded whole; the hero,
ability and perk rows blizzard.heroes owns are filled in, never replaced.
"""

import dataclasses
import re
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import NamedTuple, TypedDict

import psycopg
from psycopg.sql import SQL

from db import KIND_WEAPON, PERK_TIERS, psql
from db.data.names import ability_key, name_key
from db.data.wiki.kits import modifiers
from db.data.wiki.kits.hero_articles import HeroProfile
from db.data.wiki.kits.kit_rows import AbilityEntry, HeroKit, PerkEntry, WeaponEntry
from db.data.wiki.kits.measurements import parse_measurements
from db.data.wiki.kits.six_a_side import SixKit
from db.data.wiki.kits.weapons import group_weapons, slot_id

# The unit a stat is measured in when its value carries none of its own
# ("damage = 90" is 90 hp). Stats absent here are categorical or boolean.
STAT_UNITS = {
    "damage": "hp", "heal": "hp", "dps": "hp", "hps": "hp",
    "overhealth": "hp", "health": "hp", "barrier_health": "hp",
    "shields": "hp", "armor": "hp",
    "ammo": "rounds", "ammo_drain": "rounds",
    "pellets": "pellets", "charges": "charges",
    "cooldown": "seconds", "duration": "seconds", "cast_time": "seconds",
    "reload_time": "seconds",
    "pradius": "meters", "radius": "meters", "range": "meters",
    "damage_falloff_range": "meters", "height": "meters", "width": "meters",
    "pspeed": "meters", "kbspeed": "meters", "mspeed": "meters",
    "fire_rate": "shots",
    "spread": "degrees",
    "mspeed_buff": "percent", "mspeed_pen": "percent", "mspeed_slow": "percent",
    "damage_red": "percent", "damage_amp": "percent", "kbmod": "percent",
    "healing_mod": "percent", "energy": "percent",
    "ult_req": "points",
    "headshot_mod": "multiplier",
    "aoe": "meters", "view_angle": "degrees",
}

# Stats that are inherently per-second, so a bare number is still a rate.
STAT_DEFAULT_DENOMINATOR = {"dps": "seconds", "hps": "seconds"}


class KitCounts(TypedDict):
    """What the store wrote, counted as it writes: rows, or heroes for
    health and for six_pools, the heroes given a 6v6 pool. The pull's
    summary reports every count."""
    weapons: int
    configs: int
    stats: int
    classified: int
    added: int
    abilities_with_stats: int
    modifiers: int
    perks_announced: int
    perks_with_stats: int
    perk_links: int
    health: int
    six_pools: int
    six_lines: int


@dataclasses.dataclass(frozen=True, slots=True)
class _StorePass:
    """What one store() pass writes with: the cursor, the stat key and
    ability kind ids, the source every row carries, and the tally each
    writer counts into. Only the tally's counts change."""
    cursor: psycopg.Cursor
    key_ids: Mapping[str, int]
    kind_ids: Mapping[str, int]
    source_id: int
    tally: KitCounts


def _insert_modifiers(store_pass: _StorePass, ability_id: int, entry: AbilityEntry) -> None:
    """Store the buffs and debuffs an ability applies to someone's numbers."""
    cursor = store_pass.cursor
    keywords = entry["keywords"]
    for code, value_text in entry["stats"].items():
        affects = modifiers.affected_quantity(code, value_text, keywords)
        if affects is None:
            continue                # not a modifier stat, or the wording settles nothing
        for measured in parse_measurements(value_text, "percent"):
            if measured.value is None or measured.numerator is None:
                continue
            cursor.execute(
                "INSERT INTO ability_modifiers (ability_id, stat_key_id, affects,"
                " applies_to, magnitude, unit, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (ability_id, stat_key_id, affects, magnitude)"
                " DO NOTHING",
                (ability_id, store_pass.key_ids[code], affects,
                 modifiers.applies_to(code, value_text, keywords),
                 measured.value, measured.numerator, store_pass.source_id),
            )
            store_pass.tally["modifiers"] += cursor.rowcount


def _register_stat_keys(
        cursor: psycopg.Cursor, codes: Iterable[str], source_id: int) -> dict[str, int]:
    """Upsert the stat keys and return {code: stat_key_id}. A code already on
    file keeps its row: the update changes nothing and lets RETURNING give
    its id."""
    ids: dict[str, int] = {}
    for code in sorted(codes):
        cursor.execute(
            "INSERT INTO stat_keys (code, source_id) VALUES (%s, %s)"
            " ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code"
            " RETURNING stat_key_id",
            (code, source_id),
        )
        ids[code] = psql.scalar(cursor)
    return ids


def _insert_stats(
        store_pass: _StorePass, table: str, owner_column: str, owner_id: int,
        stats: Mapping[str, str]) -> None:
    """Write one row per measurement, each counted into the tally's stats."""
    cursor = store_pass.cursor
    insert = SQL(
        "INSERT INTO {table} ({owner}, stat_key_id, value, unit_numerator,"
        " unit_denominator, denominator_value, condition, value_text, source_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT ({owner}, stat_key_id, value, unit_numerator,"
        " unit_denominator, denominator_value, condition, value_text)"
        " DO NOTHING").format(table=psql.identifier(table),
                              owner=psql.identifier(owner_column))
    for code, value_text in stats.items():
        default_unit = STAT_UNITS.get(code)
        implied = STAT_DEFAULT_DENOMINATOR.get(code)
        for value, numerator, denominator, window, condition, text in (
            parse_measurements(value_text, default_unit)
        ):
            if denominator is None and implied and value is not None:
                denominator, window = implied, 1
            cursor.execute(
                insert,
                (owner_id, store_pass.key_ids[code], value, numerator, denominator, window,
                 condition, text, store_pass.source_id),
            )
            store_pass.tally["stats"] += cursor.rowcount


def _load_weapons(store_pass: _StorePass, hero_id: int, weapons: list[WeaponEntry]) -> None:
    """Weapons, their firing configs (with keywords), and the stats on each."""
    cursor = store_pass.cursor
    for position, weapon in enumerate(group_weapons(weapons)):
        cursor.execute(
            "INSERT INTO weapons (hero_id, name, position, source_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (hero_id, name) DO NOTHING RETURNING weapon_id",
            (hero_id, weapon.name, position, store_pass.source_id),
        )
        row = cursor.fetchone()
        if row is None:
            continue
        store_pass.tally["weapons"] += 1

        for config_position, config in enumerate(weapon.configs):
            cursor.execute(
                "INSERT INTO weapon_configs (weapon_id, slot_id, name,"
                " weapon_type, keywords, position, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (weapon_id, slot_id) DO NOTHING"
                " RETURNING config_id",
                (row[0], slot_id(config),
                 config["display_name"], config["weapon_type"],
                 config["keywords"] or None, config_position, store_pass.source_id),
            )
            config_row = cursor.fetchone()
            if config_row is None:
                continue
            store_pass.tally["configs"] += 1
            _insert_stats(store_pass, "weapon_stats", "config_id", config_row[0],
                          config["stats"])


def _classify(store_pass: _StorePass, ability_id: int, kind: str, keywords: str) -> None:
    """Set a stored ability's kind and keywords, counted as classified."""
    store_pass.cursor.execute(
        "UPDATE abilities SET kind_id = %s, keywords = %s WHERE ability_id = %s",
        (store_pass.kind_ids[kind], keywords or None, ability_id),
    )
    store_pass.tally["classified"] += store_pass.cursor.rowcount


def _load_abilities(
        store_pass: _StorePass, hero_id: int, weapon_entries: list[WeaponEntry],
        entries: list[AbilityEntry]) -> None:
    """Classify the abilities Blizzard loaded, add the ones it omits, stat
    them, store their keywords. Weapon entries take part ONLY to classify."""
    cursor = store_pass.cursor
    existing: dict[str, int] = {
        ability_key(row[0]): row[1]
        for row in cursor.execute(
            "SELECT name, ability_id FROM abilities WHERE hero_id = %s",
            (hero_id,),
        ).fetchall()
    }
    next_position: int = psql.scalar(cursor.execute(
        "SELECT coalesce(max(position), -1) + 1 FROM abilities WHERE hero_id = %s",
        (hero_id,),
    ))

    for weapon in weapon_entries:
        for candidate in (weapon["name"], weapon["display_name"]):
            ability_id = existing.get(ability_key(candidate))
            if ability_id is not None:
                _classify(store_pass, ability_id, KIND_WEAPON, weapon["keywords"])
                break

    for entry in entries:
        ability_id = existing.get(ability_key(entry["name"]))
        if ability_id is None:
            cursor.execute(
                "INSERT INTO abilities (hero_id, kind_id, name, description,"
                " keywords, position, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (hero_id, name) DO NOTHING RETURNING ability_id",
                (hero_id, store_pass.kind_ids[entry["kind"]], entry["name"],
                 entry["description"], entry["keywords"] or None,
                 next_position, store_pass.source_id),
            )
            inserted = cursor.fetchone()
            if inserted is None:
                continue
            ability_id = inserted[0]
            existing[ability_key(entry["name"])] = ability_id
            next_position += 1
            store_pass.tally["added"] += 1
        else:
            _classify(store_pass, ability_id, entry["kind"], entry["keywords"])

        if entry["stats"]:
            store_pass.tally["abilities_with_stats"] += 1
        _insert_stats(store_pass, "ability_stats", "ability_id", ability_id, entry["stats"])
        _insert_modifiers(store_pass, ability_id, entry)


def _abilities_named_in(description: str, ability_names: Iterable[str]) -> list[str]:
    """Ability names this text names, longest first so overlaps resolve.

    Matching is scoped to one hero's kit, so a bare name cannot collide with a
    different hero's ability.
    """
    found: list[str] = []
    for name in sorted(ability_names, key=len, reverse=True):
        # Skip a name already covered by a longer one just matched.
        if re.search(r"\b%s\b" % re.escape(name), description) and not any(
                name in seen for seen in found):
            found.append(name)
    return found


def _load_perks(store_pass: _StorePass, hero_id: int, perks: list[PerkEntry]) -> None:
    """Perk stats, and the link from a perk to the ability it alters."""
    cursor = store_pass.cursor
    ability_names: list[str] = [
        row[0] for row in cursor.execute(
            "SELECT name FROM abilities WHERE hero_id = %s", (hero_id,)
        ).fetchall()
    ]
    perk_ids: dict[str, int] = {
        ability_key(row[0]): row[1]
        for row in cursor.execute(
            "SELECT name, perk_id FROM perks WHERE hero_id = %s", (hero_id,)
        ).fetchall()
    }
    if not perk_ids and perks and psql.scalar(cursor.execute(
            "SELECT status FROM heroes WHERE hero_id = %s", (hero_id,)
            )) == "announced":
        # Blizzard has not published the hero yet: the wiki's perks are the
        # only ones, so they get rows of their own (blizzard.heroes replaces
        # them once the hero's page parses)
        position = {"minor": 0, "major": 0}
        for entry in perks:
            tier = entry["tier"]
            position[tier] += 1
            if position[tier] > 2:
                continue
            cursor.execute(
                "INSERT INTO perks (hero_id, tier_id, name, description, position, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (hero_id, name) DO NOTHING"
                " RETURNING perk_id",
                (hero_id, PERK_TIERS[tier], entry["name"], entry["description"],
                 position[tier], store_pass.source_id))
            row = cursor.fetchone()
            if row:
                perk_ids[ability_key(entry["name"])] = row[0]
                store_pass.tally["perks_announced"] += 1
    for entry in perks:
        perk_id = perk_ids.get(ability_key(entry["name"]))
        if perk_id is None:
            continue  # a perk Blizzard does not currently publish
        if entry["stats"]:
            store_pass.tally["perks_with_stats"] += 1
        _insert_stats(store_pass, "perk_stats", "perk_id", perk_id, entry["stats"])
        for name in _abilities_named_in(entry["description"], ability_names):
            cursor.execute(
                "INSERT INTO perk_ability_effects (perk_id, ability_id,"
                " source_id) SELECT %s, ability_id, %s FROM abilities"
                " WHERE hero_id = %s AND name = %s"
                " ON CONFLICT DO NOTHING",
                (perk_id, store_pass.source_id, hero_id, name),
            )
            store_pass.tally["perk_links"] += cursor.rowcount


# Every table the store reloads whole, dependents first.
RELOADED = ("kit_6v6", "ability_modifiers", "perk_ability_effects", "perk_stats",
            "weapon_stats", "ability_stats", "weapon_configs", "weapons")


class Stored(NamedTuple):
    """What store wrote: the tally, and the heroes it skipped, sorted."""
    tally: KitCounts
    unknown_heroes: list[str]


def _load_six(store_pass: _StorePass, hero_id: int, six: SixKit) -> None:
    """A hero's 6v6 lines, each with the stat its words name where they name
    one; the pools are set with the 5v5 ones."""
    for line in six.lines:
        store_pass.cursor.execute(
            "INSERT INTO kit_6v6 (hero_id, piece, stat_key_id, from_value, to_value,"
            " value_text, source_id) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (hero_id, piece, value_text) DO NOTHING",
            (hero_id, line.piece, store_pass.key_ids[line.stat] if line.stat else None,
                line.before, line.after, line.text, store_pass.source_id))
        store_pass.tally["six_lines"] += store_pass.cursor.rowcount


def store(
        cursor: psycopg.Cursor, by_hero: Mapping[str, HeroKit],
        profiles: Mapping[str, HeroProfile], hero_ids: Mapping[str, int],
        source_id: int, six: Mapping[str, SixKit] = MappingProxyType({})) -> Stored:
    """Reload the kit tables from `by_hero` and `six` and set each profiled
    hero's pools, its 5v5 ones and the 6v6 ones its article gives (NULL
    where it gives none). hero_ids is {name_key: hero_id}, as names.index
    builds it; a hero it lacks is skipped and named in the result."""
    for table in RELOADED:
        cursor.execute(SQL("DELETE FROM {}").format(psql.identifier(table)))
    all_codes: set[str] = set()
    for kit in by_hero.values():
        for entry in kit.entries():
            all_codes.update(entry["stats"])
    all_codes.update(line.stat for said in six.values() for line in said.lines if line.stat)
    key_ids = _register_stat_keys(cursor, all_codes, source_id)
    kind_ids = psql.lookup_ids(cursor, "ability_kinds", "code", "kind_id")
    store_pass = _StorePass(cursor, key_ids, kind_ids, source_id, KitCounts(
        weapons=0, configs=0, stats=0, classified=0, added=0, abilities_with_stats=0,
        modifiers=0, perks_announced=0, perks_with_stats=0, perk_links=0, health=0,
        six_pools=0, six_lines=0))

    for hero_name, profile in profiles.items():
        hero_id = hero_ids.get(name_key(hero_name))
        if hero_id is None:
            continue
        pools = six[hero_name].pools if hero_name in six else {}
        cursor.execute(
            "UPDATE heroes SET health = %s, shield = %s, armor = %s, health_6v6 = %s,"
            " shield_6v6 = %s, armor_6v6 = %s WHERE hero_id = %s",
            (profile.health, profile.shield, profile.armor, pools.get("health"),
                pools.get("shield"), pools.get("armor"), hero_id),
        )
        store_pass.tally["health"] += cursor.rowcount
        store_pass.tally["six_pools"] += cursor.rowcount if pools else 0

    unknown_heroes: list[str] = []
    for hero_name, kit in sorted(by_hero.items()):
        hero_id = hero_ids.get(name_key(hero_name))
        if hero_id is None:
            unknown_heroes.append(hero_name)
            continue
        _load_weapons(store_pass, hero_id, kit.weapons)
        _load_abilities(store_pass, hero_id, kit.weapons, kit.abilities)
        _load_perks(store_pass, hero_id, kit.perks)
        if hero_name in six:
            _load_six(store_pass, hero_id, six[hero_name])
    return Stored(store_pass.tally, sorted(unknown_heroes))
