"""Pull + clean + store: overwatch.fandom.com - hero kit data, via Cargo.

The wiki stores its ability data in a Cargo table with one row per ability:
every stat as its own column, an explicit `removed` flag for retired kit, an
`ability_key` naming the input slot and a keyword list ("hitscan", "strong
movement", "stun", "lesser cleanse", ...). A few template parameters are
never registered as Cargo fields - the interaction flags among them - so
those are supplemented from the article wikitext, which also carries the
hero's health pool and, for a hero marked upcoming, its announcement.

Loads weapons and their firing configs, classifies every ability, adds the
abilities Blizzard does not publish, stores each ability's keywords, and
attaches stat measurements to abilities, weapons and perks. kit_rows.py
reads the rows into each hero's kit; weapons.py groups its weapons. Runs
after blizzard.heroes, which owns the hero, ability and perk rows this
fills in.
"""

import collections
import contextlib
import datetime
import re
from collections.abc import Callable, Iterable, Mapping
from typing import TypedDict

import psycopg
import requests
from psycopg.sql import SQL

from db import PERK_TIERS, psql
from db.data import fetch
from db.data.names import abilities_named_in, ability_key
from db.data.wiki import (
    WIKI,
    cargo_query,
    fetch_wikitext,
    markup,
    modifiers,
)
from db.data.wiki.kit_rows import (
    AbilityEntry,
    PerkEntry,
    StatValue,
    WeaponEntry,
    parse_rows,
)
from db.data.wiki.measurements import parse_measurements
from db.data.wiki.weapons import (
    group_weapons,
    slot_id,
)

# --- extract: markup -> Python ---------------------------------------------

# {health, shield, armor} from a hero's infobox, each None when it gives none.
HeroProfile = dict[str, int | None]
# {ability key: {stat code: value}} - what an article adds to the Cargo kit.
ExtraStats = dict[str, dict[str, StatValue]]


class Announcement(TypedDict):
    role: str
    subrole: str
    health: int | None
    release_date: datetime.date | None


def parse_hero_profile(text: str) -> HeroProfile:
    """{health, shield, armor} for one hero, from its infobox.

    Blizzard publishes no hero health at all, and the wiki keeps it on the
    article rather than in a Cargo table, so it comes from the same page fetch
    the stat supplement already makes.
    """
    for block in markup.find_templates(text, r"Infobox character"):
        params = markup.parse_params(block)
        return {field: _pool(params, field) for field in ("health", "shield", "armor")}
    return {}


def _pool(params: dict[str, str], field: str) -> int | None:
    """An infobox's number for one pool, or None when it gives none."""
    digits = re.match(r"\s*(\d+)", markup.wikitext_to_text(params.get(field, "")))
    return int(digits.group(1)) if digits else None


UPCOMING_RE = re.compile(r"\{\{\s*Upcoming\s*\}\}", re.I)
RELEASE_RE = re.compile(r"release[^.]{0,80}?\bon\s+([A-Z][a-z]+ \d{1,2}, \d{4})")


def parse_announcement(text: str) -> Announcement | None:
    """An article marked {{Upcoming}} -> {role, subrole, health, release_date}
    from its infobox and its release sentence; None for a released hero (no
    marker) or an infobox without a role."""
    if not UPCOMING_RE.search(text or ""):
        return None
    for block in markup.find_templates(text, r"Infobox character"):
        params = markup.parse_params(block)
        role = markup.wikitext_to_text(params.get("role", "")).strip().lower()
        subrole = markup.wikitext_to_text(params.get("sub-role", "")).strip().lower()
        if role not in ("tank", "damage", "support"):
            return None
        health = re.match(r"\s*(\d+)", markup.wikitext_to_text(params.get("health", "")))
        released = RELEASE_RE.search(markup.wikitext_to_text(text))
        release_date: datetime.date | None = None
        if released:
            # a date the wiki spells another way leaves release_date as it is
            with contextlib.suppress(ValueError):
                release_date = datetime.datetime.strptime(released.group(1),
                                                          "%B %d, %Y").date()
        return Announcement(role=role, subrole=subrole,
                            health=int(health.group(1)) if health else None,
                            release_date=release_date)
    return None


def announce_heroes(
        cursor: psycopg.Cursor, session: requests.Session, names: Iterable[str],
        hero_ids: dict[str, int], cache_dir: str | None, source_id: int,
        log: Callable[[str], None] = print) -> tuple[list[str], list[str]]:
    """Heroes the Cargo table names that the roster lacks: those whose
    article is marked upcoming get a row - role, subrole, health, release
    day, status announced - so their kit loads and the board can show
    them; Blizzard listing them later flips the status to released. Returns
    (the names stored, the pages that would not fetch), and adds each stored
    hero's id to `hero_ids`, which the kit and ability lookups that follow
    read; the rest stay unknown."""
    stored: list[str] = []
    missing: list[str] = []
    for hero_name in sorted(names):
        if hero_name.lower() in hero_ids:
            continue
        try:
            text = fetch_wikitext(session, hero_name.replace(" ", "_"), cache_dir)
        except fetch.FetchError as error:
            missing.append("%s: %s" % (hero_name, error))
            continue
        found = parse_announcement(text)
        if not found:
            continue
        cursor.execute("SELECT s.subrole_id, r.role_id FROM subroles s JOIN roles r USING (role_id)"
                       " WHERE r.code = %s AND s.code = %s", (found["role"], found["subrole"]))
        row = cursor.fetchone()
        if row is None:
            log("announced hero %s: subrole %s/%s not on the roster yet, skipped"
                % (hero_name, found["role"], found["subrole"]))
            continue
        subrole_id, role_id = row
        slug = re.sub(r"[^a-z0-9]+", "-", hero_name.lower()).strip("-")
        cursor.execute(
            "INSERT INTO heroes (slug, name, role_id, subrole_id, health, status,"
            " release_date, source_id) VALUES (%s, %s, %s, %s, %s, 'announced', %s, %s)"
            " ON CONFLICT (slug) DO UPDATE SET release_date = EXCLUDED.release_date,"
            " health = coalesce(EXCLUDED.health, heroes.health), cao = now()"
            " RETURNING hero_id",
            (slug, hero_name, role_id, subrole_id, found["health"], found["release_date"],
             source_id))
        hero_ids[hero_name.lower()] = psql.scalar(cursor)
        stored.append(hero_name)
        log("announced hero stored: %s (%s, %s%s)" % (
            hero_name, found["role"], found["subrole"],
            ", releases %s" % found["release_date"] if found["release_date"] else ""))
    return stored, missing


# --- store ---------------------------------------------------------------------

CARGO_TABLE = "Abilities"
CARGO_FIELDS = (
    "hero_name", "ability_name", "ability_type", "ability_key", "removed",
    "official_description", "shot_type", "ult_req", "cooldown", "charges",
    "health", "armor", "shields", "overhealth", "barrier_health", "damage",
    "damage_falloff_range", "headshot", "headshot_mod", "heal", "damage_red",
    "damage_amp", "healing_mod", "spread", "pspeed", "pradius", "mspeed",
    "mspeed_buff", "mspeed_pen", "mspeed_slow", "kbspeed", "kbmod",
    "range_distance", "height", "width", "radius", "pellets", "fire_rate",
    "ammo", "ammo_drain", "energy", "reload_time", "cast_time", "duration",
    "dps", "hps", "ignores_speedcap", "ability_keywords",
)

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

# Declared on Template:Ability details but not registered as Cargo fields.
# `heal` is registered, but Cargo returns it empty for some abilities
# (Mizuki's Healing Kasa); the merge fills only what Cargo left empty.
SUPPLEMENT_FIELDS = (
    "ignores_matrix", "ignores_deflect", "ignores_window", "ignores_barrier",
    "ignores_boost", "aoe", "view_angle", "heal",
)

# A retired kit's block: "Teleporter (old)". ability_key() drops the
# parenthetical, so it would overwrite the live block of the same name.
RETIRED_BLOCK_RE = re.compile(r"\(old\)\s*$", re.I)
# A citation is not part of the value.
REF_RE = re.compile(r"<ref\b[^>]*/>|<ref\b[^>]*>.*?</ref>", re.I | re.S)


def supplement_from_wikitext(
        session: requests.Session, hero_name: str,
        cache_dir: str | None) -> tuple[ExtraStats, HeroProfile]:
    """One hero page -> ({ability ability_key: {stat: ...}}, {health/shield/armor}).
    A page that will not fetch raises; run() records it among the pull's missing."""
    text = fetch_wikitext(session, hero_name.replace(" ", "_"), cache_dir)
    extra: ExtraStats = {}
    for block in markup.find_templates(text, r"Ability[ _]details"):
        params = markup.parse_params(block)
        name = markup.wikitext_to_text(params.get("ability_name", ""))
        if not name or RETIRED_BLOCK_RE.search(name):
            continue
        stats: dict[str, StatValue] = {}
        for code in SUPPLEMENT_FIELDS:
            value = markup.wikitext_to_text(REF_RE.sub("", params.get(code, "")))
            if value:
                stats[code] = (value, params[code])
        if stats:
            extra[ability_key(name)] = stats
    return extra, parse_hero_profile(text)


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
        for value, numerator, _, _, _, _ in parse_measurements(
            value_text, "percent"
        ):
            if value is None or numerator is None:
                continue
            cursor.execute(
                "INSERT INTO ability_modifiers (ability_id, stat_key_id, affects,"
                " applies_to, magnitude, unit, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (ability_id, stat_key_id, affects, magnitude)"
                " DO NOTHING",
                (ability_id, key_ids[code], affects,
                 modifiers.applies_to(code, value_text, keywords),
                 value, numerator, source_id),
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
        key_ids: Mapping[str, int], source_id: int, tally: collections.Counter[str]) -> None:
    """Weapons, their firing configs (with keywords), and the stats on each."""
    for position, (weapon_name, configs) in enumerate(group_weapons(weapons)):
        cursor.execute(
            "INSERT INTO weapons (hero_id, name, position, source_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (hero_id, name) DO NOTHING RETURNING weapon_id",
            (hero_id, weapon_name, position, source_id),
        )
        row = cursor.fetchone()
        if row is None:
            continue
        tally["weapons"] += 1

        for config_position, config in enumerate(configs):
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
            tally["configs"] += 1
            tally["stats"] += _insert_stats(
                cursor, "weapon_stats", "config_id", config_row[0],
                config["stats"], key_ids, source_id,
            )


def _load_abilities(
        cursor: psycopg.Cursor, hero_id: int, weapon_entries: list[WeaponEntry],
        entries: list[AbilityEntry], key_ids: Mapping[str, int], kind_ids: Mapping[str, int],
        source_id: int, tally: collections.Counter[str]) -> None:
    """Classify the abilities Blizzard loaded, add the ones it omits, stat
    them, store their keywords. Weapon entries take part ONLY to classify."""
    existing = {
        ability_key(row[0]): row[1]
        for row in cursor.execute(
            "SELECT name, ability_id FROM abilities WHERE hero_id = %s",
            (hero_id,),
        ).fetchall()
    }
    next_position = psql.scalar(cursor.execute(
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
                tally["classified"] += cursor.rowcount
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
            tally["added"] += 1
        else:
            cursor.execute(
                "UPDATE abilities SET kind_id = %s, keywords = %s"
                " WHERE ability_id = %s",
                (kind_ids[entry["kind"]], entry["keywords"] or None, ability_id),
            )
            tally["classified"] += 1

        if entry["stats"]:
            tally["abilities_with_stats"] += 1
        tally["stats"] += _insert_stats(
            cursor, "ability_stats", "ability_id", ability_id,
            entry["stats"], key_ids, source_id,
        )
        tally["modifiers"] += _insert_modifiers(
            cursor, ability_id, entry, key_ids, source_id
        )


def _load_perks(
        cursor: psycopg.Cursor, hero_id: int, perks: list[PerkEntry],
        key_ids: Mapping[str, int], source_id: int, tally: collections.Counter[str]) -> None:
    """Perk stats, and the link from a perk to the ability it alters."""
    ability_names = [
        row[0] for row in cursor.execute(
            "SELECT name FROM abilities WHERE hero_id = %s", (hero_id,)
        ).fetchall()
    ]
    perk_ids = {
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
                tally["perks_announced"] += 1
    for entry in perks:
        perk_id = perk_ids.get(ability_key(entry["name"]))
        if perk_id is None:
            continue  # a perk Blizzard does not currently publish
        if entry["stats"]:
            tally["perks_with_stats"] += 1
        tally["stats"] += _insert_stats(
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
            tally["perk_links"] += cursor.rowcount


def run(
        connection: psycopg.Connection, cache_dir: str | None = None,
        session: requests.Session | None = None, supplement: bool = True,
        log: Callable[[str], None] = print) -> dict[str, int | list[str]]:
    """Pull the Cargo table (and each hero article), clean, store."""
    session = fetch.session(session)

    rows = cargo_query(session, CARGO_TABLE, CARGO_FIELDS, cache_dir)
    by_hero = parse_rows(rows)
    log("cargo rows: %d   heroes named: %d" % (len(rows), len(by_hero)))

    profiles: dict[str, HeroProfile] = {}
    supplemented = 0
    missing: list[str] = []
    if supplement:
        for hero_name, (weapons, abilities, perks) in sorted(by_hero.items()):
            try:
                extra, profile = supplement_from_wikitext(session, hero_name, cache_dir)
            except fetch.FetchError as error:
                missing.append("%s: %s" % (hero_name, error))
                continue
            if profile:
                profiles[hero_name] = profile
            for entry in weapons + abilities + perks:
                for code, value in extra.get(ability_key(entry["name"]), {}).items():
                    if code not in entry["stats"]:
                        entry["stats"][code] = value
                        supplemented += 1
        log("supplemented stats: %d  (fields Cargo does not expose)" % supplemented)

    cursor = connection.cursor()
    source_id = psql.register_source(cursor, WIKI, psql.now())
    for table in ("ability_modifiers", "perk_ability_effects", "perk_stats",
                  "weapon_stats", "ability_stats", "weapon_configs", "weapons"):
        cursor.execute(SQL("DELETE FROM {}").format(psql.identifier(table)))

    all_codes: set[str] = set()
    for weapons, abilities, perks in by_hero.values():
        for entry in weapons + abilities + perks:
            all_codes.update(entry["stats"])
    key_ids = _register_stat_keys(cursor, all_codes, source_id)
    hero_ids = psql.lookup_ids(cursor, "heroes", "name", "hero_id")
    kind_ids = psql.lookup_ids(cursor, "ability_kinds", "code", "kind_id")
    announced, unfetched = announce_heroes(cursor, session, by_hero, hero_ids, cache_dir,
                                           source_id, log)
    missing += unfetched

    tally: collections.Counter[str] = collections.Counter()
    unknown_heroes: list[str] = []
    for hero_name, profile in profiles.items():
        hero_id = hero_ids.get(hero_name.lower())
        if hero_id is None:
            continue
        cursor.execute(
            "UPDATE heroes SET health = %s, shield = %s, armor = %s"
            " WHERE hero_id = %s",
            (profile.get("health"), profile.get("shield"),
             profile.get("armor"), hero_id),
        )
        tally["health"] += cursor.rowcount

    for hero_name, (weapons, abilities, perks) in sorted(by_hero.items()):
        hero_id = hero_ids.get(hero_name.lower())
        if hero_id is None:
            unknown_heroes.append(hero_name)
            continue
        _load_weapons(cursor, hero_id, weapons, key_ids, source_id, tally)
        _load_abilities(cursor, hero_id, weapons, abilities, key_ids, kind_ids,
                        source_id, tally)
        _load_perks(cursor, hero_id, perks, key_ids, source_id, tally)
    connection.commit()

    summary: dict[str, int | list[str]] = dict(tally)
    summary.update({
        "cargo_rows": len(rows), "supplemented": supplemented, "missing": missing,
        "unknown_heroes": sorted(unknown_heroes), "announced": announced,
        "tables": ["abilities", "ability_stats", "ability_modifiers", "weapons",
                   "weapon_configs", "weapon_stats", "perk_stats",
                   "perk_ability_effects", "stat_keys", "heroes"],
    })
    return summary
