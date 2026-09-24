"""The store stage of the kits pull: each hero's kit into the tables.

Loads weapons and their firing configs, classifies every ability, adds the
abilities Blizzard does not publish, stores each ability's keywords, and
attaches stat measurements to abilities, weapons and perks, with the
modifiers an ability applies and the abilities a perk alters. The weapon,
stat and modifier tables are reloaded whole; the hero, ability and perk rows
blizzard.heroes owns are filled in, never replaced.
"""

import dataclasses
from collections.abc import Iterable, Mapping
from typing import NamedTuple, TypedDict

import psycopg
from psycopg.sql import SQL

from db import PERK_TIERS, psql
from db.data.names import abilities_named_in, ability_key
from db.data.wiki.kits import modifiers
from db.data.wiki.kits.hero_articles import HeroProfile
from db.data.wiki.kits.kit_rows import AbilityEntry, HeroKit, PerkEntry, StatValue, WeaponEntry
from db.data.wiki.kits.measurements import parse_measurements
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
    """The tally as the pull's summary reports it."""
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


@dataclasses.dataclass
class KitTally:
    """What the store wrote, counted as it writes: rows, or heroes for
    health."""
    weapons: int = 0
    configs: int = 0
    stats: int = 0
    classified: int = 0
    added: int = 0
    abilities_with_stats: int = 0
    modifiers: int = 0
    perks_announced: int = 0
    perks_with_stats: int = 0
    perk_links: int = 0
    health: int = 0

    def counts(self) -> KitCounts:
        """Every count, 0 where nothing was counted."""
        return KitCounts(
            weapons=self.weapons, configs=self.configs, stats=self.stats,
            classified=self.classified, added=self.added,
            abilities_with_stats=self.abilities_with_stats, modifiers=self.modifiers,
            perks_announced=self.perks_announced, perks_with_stats=self.perks_with_stats,
            perk_links=self.perk_links, health=self.health)


def _insert_modifiers(
        cursor: psycopg.Cursor, ability_id: int, entry: AbilityEntry,
        key_ids: Mapping[str, int], source_id: int) -> int:
    """Store the buffs and debuffs an ability applies to someone's numbers."""
    written = 0
    for code, (value_text, _) in entry["stats"].items():
        if code not in modifiers.MODIFIER_STATS:
            continue
        keywords = entry["keywords"]
        affects = modifiers.affected_quantity(code, value_text, keywords)
        if affects is None:
            continue
        for measured in parse_measurements(value_text, "percent"):
            if measured.value is None or measured.numerator is None:
                continue
            cursor.execute(
                "INSERT INTO ability_modifiers (ability_id, stat_key_id, affects,"
                " applies_to, magnitude, unit, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (ability_id, stat_key_id, affects, magnitude)"
                " DO NOTHING",
                (ability_id, key_ids[code], affects,
                 modifiers.applies_to(code, value_text, keywords),
                 measured.value, measured.numerator, source_id),
            )
            written += cursor.rowcount
    return written


def _register_stat_keys(
        cursor: psycopg.Cursor, codes: Iterable[str], source_id: int) -> dict[str, int]:
    """Upsert the stat keys and return {code: stat_key_id}."""
    ids: dict[str, int] = {}
    for code in sorted(codes):
        cursor.execute(
            "INSERT INTO stat_keys (code, label, unit, source_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET label = EXCLUDED.label,"
            " unit = EXCLUDED.unit RETURNING stat_key_id",
            (code, code.replace("_", " "), STAT_UNITS.get(code), source_id),
        )
        ids[code] = psql.scalar(cursor)
    return ids


def _insert_stats(
        cursor: psycopg.Cursor, table: str, owner_column: str, owner_id: int,
        stats: Mapping[str, StatValue], key_ids: Mapping[str, int], source_id: int) -> int:
    """Write one row per measurement. Returns how many rows were written."""
    insert = SQL(
        "INSERT INTO {table} ({owner}, stat_key_id, value, unit_numerator,"
        " unit_denominator, denominator_value, condition, value_text,"
        " raw_value, source_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT ({owner}, stat_key_id, value, unit_numerator,"
        " unit_denominator, denominator_value, condition, value_text)"
        " DO NOTHING").format(table=psql.identifier(table),
                              owner=psql.identifier(owner_column))
    written = 0
    for code, (value_text, raw) in stats.items():
        default_unit = STAT_UNITS.get(code)
        implied = STAT_DEFAULT_DENOMINATOR.get(code)
        for value, numerator, denominator, window, condition, text in (
            parse_measurements(value_text, default_unit)
        ):
            if denominator is None and implied and value is not None:
                denominator, window = implied, 1
            cursor.execute(
                insert,
                (owner_id, key_ids[code], value, numerator, denominator, window,
                 condition, text, raw, source_id),
            )
            written += cursor.rowcount
    return written


def _load_weapons(
        cursor: psycopg.Cursor, hero_id: int, weapons: list[WeaponEntry],
        key_ids: Mapping[str, int], source_id: int, tally: KitTally) -> None:
    """Weapons, their firing configs (with keywords), and the stats on each."""
    for position, weapon in enumerate(group_weapons(weapons)):
        cursor.execute(
            "INSERT INTO weapons (hero_id, name, position, source_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (hero_id, name) DO NOTHING RETURNING weapon_id",
            (hero_id, weapon.name, position, source_id),
        )
        row = cursor.fetchone()
        if row is None:
            continue
        tally.weapons += 1

        for config_position, config in enumerate(weapon.configs):
            cursor.execute(
                "INSERT INTO weapon_configs (weapon_id, slot_id, name,"
                " weapon_type, keywords, position, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (weapon_id, slot_id) DO NOTHING"
                " RETURNING config_id",
                (row[0], slot_id(config["mode"] or config["input_key"]),
                 config["display_name"], config["weapon_type"],
                 config["keywords"] or None, config_position, source_id),
            )
            config_row = cursor.fetchone()
            if config_row is None:
                continue
            tally.configs += 1
            tally.stats += _insert_stats(
                cursor, "weapon_stats", "config_id", config_row[0],
                config["stats"], key_ids, source_id,
            )


def _load_abilities(
        cursor: psycopg.Cursor, hero_id: int, weapon_entries: list[WeaponEntry],
        entries: list[AbilityEntry], key_ids: Mapping[str, int], kind_ids: Mapping[str, int],
        source_id: int, tally: KitTally) -> None:
    """Classify the abilities Blizzard loaded, add the ones it omits, stat
    them, store their keywords. Weapon entries take part ONLY to classify."""
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
                cursor.execute(
                    "UPDATE abilities SET kind_id = %s, keywords = %s"
                    " WHERE ability_id = %s",
                    (kind_ids[weapon["kind"]], weapon["keywords"] or None, ability_id),
                )
                tally.classified += cursor.rowcount
                break

    for entry in entries:
        ability_id = existing.get(ability_key(entry["name"]))
        if ability_id is None:
            cursor.execute(
                "INSERT INTO abilities (hero_id, kind_id, name, description,"
                " keywords, position, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (hero_id, name) DO NOTHING RETURNING ability_id",
                (hero_id, kind_ids[entry["kind"]], entry["display_name"],
                 entry["description"], entry["keywords"] or None,
                 next_position, source_id),
            )
            inserted = cursor.fetchone()
            if inserted is None:
                continue
            ability_id = inserted[0]
            existing[ability_key(entry["name"])] = ability_id
            next_position += 1
            tally.added += 1
        else:
            cursor.execute(
                "UPDATE abilities SET kind_id = %s, keywords = %s"
                " WHERE ability_id = %s",
                (kind_ids[entry["kind"]], entry["keywords"] or None, ability_id),
            )
            tally.classified += 1

        if entry["stats"]:
            tally.abilities_with_stats += 1
        tally.stats += _insert_stats(
            cursor, "ability_stats", "ability_id", ability_id,
            entry["stats"], key_ids, source_id,
        )
        tally.modifiers += _insert_modifiers(
            cursor, ability_id, entry, key_ids, source_id
        )


def _load_perks(
        cursor: psycopg.Cursor, hero_id: int, perks: list[PerkEntry],
        key_ids: Mapping[str, int], source_id: int, tally: KitTally) -> None:
    """Perk stats, and the link from a perk to the ability it alters."""
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
        # only ones, so they get rows of their own (Blizzard's replace them)
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
                 position[tier], source_id))
            row = cursor.fetchone()
            if row:
                perk_ids[ability_key(entry["name"])] = row[0]
                tally.perks_announced += 1
    for entry in perks:
        perk_id = perk_ids.get(ability_key(entry["name"]))
        if perk_id is None:
            continue  # a perk Blizzard does not currently publish
        if entry["stats"]:
            tally.perks_with_stats += 1
        tally.stats += _insert_stats(
            cursor, "perk_stats", "perk_id", perk_id, entry["stats"],
            key_ids, source_id,
        )
        for name in abilities_named_in(entry["description"], ability_names):
            cursor.execute(
                "INSERT INTO perk_ability_effects (perk_id, ability_id,"
                " source_id) SELECT %s, ability_id, %s FROM abilities"
                " WHERE hero_id = %s AND name = %s"
                " ON CONFLICT DO NOTHING",
                (perk_id, source_id, hero_id, name),
            )
            tally.perk_links += cursor.rowcount


# Every table the store reloads whole, dependents first.
RELOADED = ("ability_modifiers", "perk_ability_effects", "perk_stats",
            "weapon_stats", "ability_stats", "weapon_configs", "weapons")


class Stored(NamedTuple):
    """What store wrote: the tally, and the heroes it skipped, sorted."""
    tally: KitTally
    unknown_heroes: list[str]


def store(
        cursor: psycopg.Cursor, by_hero: Mapping[str, HeroKit],
        profiles: Mapping[str, HeroProfile], hero_ids: Mapping[str, int],
        source_id: int) -> Stored:
    """Reload the kit tables from `by_hero` and set each profiled hero's
    pools. hero_ids is {lowercased name: hero_id}; a hero it lacks is
    skipped and named in the result."""
    for table in RELOADED:
        cursor.execute(SQL("DELETE FROM {}").format(psql.identifier(table)))
    all_codes: set[str] = set()
    for kit in by_hero.values():
        for entry in kit.entries():
            all_codes.update(entry["stats"])
    key_ids = _register_stat_keys(cursor, all_codes, source_id)
    kind_ids = psql.lookup_ids(cursor, "ability_kinds", "code", "kind_id")

    tally = KitTally()
    for hero_name, profile in profiles.items():
        hero_id = hero_ids.get(hero_name.lower())
        if hero_id is None:
            continue
        cursor.execute(
            "UPDATE heroes SET health = %s, shield = %s, armor = %s"
            " WHERE hero_id = %s",
            (profile["health"], profile["shield"], profile["armor"], hero_id),
        )
        tally.health += cursor.rowcount

    unknown_heroes: list[str] = []
    for hero_name, kit in sorted(by_hero.items()):
        hero_id = hero_ids.get(hero_name.lower())
        if hero_id is None:
            unknown_heroes.append(hero_name)
            continue
        _load_weapons(cursor, hero_id, kit.weapons, key_ids, source_id, tally)
        _load_abilities(cursor, hero_id, kit.weapons, kit.abilities, key_ids, kind_ids,
                        source_id, tally)
        _load_perks(cursor, hero_id, kit.perks, key_ids, source_id, tally)
    return Stored(tally, sorted(unknown_heroes))
