"""Pull + clean + store: overwatch.fandom.com - hero kit data, via Cargo.

The wiki stores its ability data in a Cargo table with one row per ability,
every stat as its own column, an explicit `removed` flag and a keyword list
("hitscan", "strong movement", "stun", "lesser cleanse", ...). A few template
parameters are never registered as Cargo fields - the interaction flags
among them - so those are supplemented from the article wikitext.

Loads weapons and their firing configs, classifies every ability, adds the
abilities Blizzard does not publish, stores each ability's keywords, and
attaches stat measurements to abilities, weapons and perks. Runs after
blizzard.heroes, which owns the hero, ability and perk rows this fills in.

    python -m data.load.wiki.heroes
"""

import collections
import sys

import psycopg
import requests

from data import common
from data.sources.wiki import (
    WIKI,
    USER_AGENT,
    WikiError,
    cargo_query,
    fetch_wikitext,
)
from data.extract.wiki import markup
from data.transform.wiki import modifiers
from data.transform.wiki.measurements import parse_measurements
from data.transform.wiki.weapons import (
    group_weapons,
    slot_id,
)
from data.transform.wiki.names import abilities_named_in, match_key
from data.extract.wiki.heroes import parse_hero_profile, parse_rows


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
SUPPLEMENT_FIELDS = (
    "ignores_matrix", "ignores_deflect", "ignores_window", "ignores_barrier",
    "ignores_boost", "aoe", "view_angle",
)


def supplement_from_wikitext(session, hero_name, cache_dir):
    """One hero page -> ({ability match_key: {stat: ...}}, {health/shield/armor})."""
    try:
        text = fetch_wikitext(session, hero_name.replace(" ", "_"), cache_dir)
    except (WikiError, requests.RequestException):
        return {}, {}

    extra = {}
    for block in markup.find_templates(text, r"Ability[ _]details"):
        params = markup.parse_params(block)
        name = markup.wikitext_to_text(params.get("ability_name", ""))
        if not name:
            continue
        stats = {}
        for code in SUPPLEMENT_FIELDS:
            value = markup.wikitext_to_text(params.get(code, ""))
            if value:
                stats[code] = (value, None, params[code])
        if stats:
            extra[match_key(name)] = stats
    return extra, parse_hero_profile(text)


def record_modifiers(cursor, ability_id, entry, key_ids, source_id):
    """Store the buffs and debuffs an ability applies to someone's numbers."""
    written = 0
    for code, (value_text, _, _) in entry["stats"].items():
        if code not in modifiers.MODIFIER_STATS:
            continue
        keywords = entry.get("keywords", "")
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


def stat_key_ids(cursor, codes, source_id):
    ids = {}
    for code in sorted(codes):
        cursor.execute(
            "INSERT INTO stat_keys (code, label, unit, source_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET label = EXCLUDED.label,"
            " unit = EXCLUDED.unit RETURNING stat_key_id",
            (code, code.replace("_", " "), STAT_UNITS.get(code), source_id),
        )
        ids[code] = cursor.fetchone()[0]
    return ids


def insert_stats(cursor, table, owner_column, owner_id, stats, key_ids, source_id):
    """Write one row per measurement. Returns how many rows were written."""
    written = 0
    for code, (value_text, _, raw) in stats.items():
        default_unit = STAT_UNITS.get(code)
        implied = STAT_DEFAULT_DENOMINATOR.get(code)
        for value, numerator, denominator, window, condition, text in (
            parse_measurements(value_text, default_unit)
        ):
            if denominator is None and implied and value is not None:
                denominator, window = implied, 1
            cursor.execute(
                "INSERT INTO %s (%s, stat_key_id, value, unit_numerator,"
                " unit_denominator, denominator_value, condition, value_text,"
                " raw_value, source_id)"
                " VALUES (%%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s)"
                " ON CONFLICT (%s, stat_key_id, value, unit_numerator,"
                " unit_denominator, denominator_value, condition, value_text)"
                " DO NOTHING"
                % (table, owner_column, owner_column),
                (owner_id, key_ids[code], value, numerator, denominator, window,
                 condition, text, raw, source_id),
            )
            written += cursor.rowcount
    return written


def load_weapons(cursor, hero_id, weapons, key_ids, source_id, tally):
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
                 config.get("keywords") or None, config_position, source_id),
            )
            config_row = cursor.fetchone()
            if config_row is None:
                continue
            tally["configs"] += 1
            tally["stats"] += insert_stats(
                cursor, "weapon_stats", "config_id", config_row[0],
                config["stats"], key_ids, source_id,
            )


def load_abilities(cursor, hero_id, weapon_entries, entries, key_ids,
                   source_id, tally):
    """Classify the abilities Blizzard loaded, add the ones it omits, stat
    them, store their keywords. Weapon entries take part ONLY to classify."""
    existing = {
        match_key(row[0]): row[1]
        for row in cursor.execute(
            "SELECT name, ability_id FROM abilities WHERE hero_id = %s",
            (hero_id,),
        ).fetchall()
    }
    next_position = cursor.execute(
        "SELECT coalesce(max(position), -1) + 1 FROM abilities WHERE hero_id = %s",
        (hero_id,),
    ).fetchone()[0]

    for entry in weapon_entries:
        for candidate in (entry["name"], entry.get("display_name", "")):
            ability_id = existing.get(match_key(candidate)) if candidate else None
            if ability_id is not None:
                cursor.execute(
                    "UPDATE abilities SET kind_id = %s, keywords = %s"
                    " WHERE ability_id = %s",
                    (entry["kind_id"], entry.get("keywords") or None, ability_id),
                )
                tally["classified"] += cursor.rowcount
                break

    for entry in entries:
        ability_id = existing.get(match_key(entry["name"]))
        if ability_id is None:
            cursor.execute(
                "INSERT INTO abilities (hero_id, kind_id, name, description,"
                " keywords, position, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (hero_id, name) DO NOTHING RETURNING ability_id",
                (hero_id, entry["kind_id"], entry["display_name"],
                 entry["description"], entry.get("keywords") or None,
                 next_position, source_id),
            )
            inserted = cursor.fetchone()
            if inserted is None:
                continue
            ability_id = inserted[0]
            existing[match_key(entry["display_name"])] = ability_id
            existing[match_key(entry["name"])] = ability_id
            next_position += 1
            tally["added"] += 1
        else:
            cursor.execute(
                "UPDATE abilities SET kind_id = %s, keywords = %s"
                " WHERE ability_id = %s",
                (entry["kind_id"], entry.get("keywords") or None, ability_id),
            )
            tally["classified"] += 1

        if entry["stats"]:
            tally["abilities_with_stats"] += 1
        tally["stats"] += insert_stats(
            cursor, "ability_stats", "ability_id", ability_id,
            entry["stats"], key_ids, source_id,
        )
        tally["modifiers"] += record_modifiers(
            cursor, ability_id, entry, key_ids, source_id
        )


def load_perks(cursor, hero_id, perks, key_ids, source_id, tally):
    """Perk stats, and the link from a perk to the ability it alters."""
    ability_names = [
        row[0] for row in cursor.execute(
            "SELECT name FROM abilities WHERE hero_id = %s", (hero_id,)
        ).fetchall()
    ]
    perk_ids = {
        match_key(row[0]): row[1]
        for row in cursor.execute(
            "SELECT name, perk_id FROM perks WHERE hero_id = %s", (hero_id,)
        ).fetchall()
    }
    for entry in perks:
        perk_id = perk_ids.get(match_key(entry["name"]))
        if perk_id is None:
            continue  # a perk Blizzard does not currently publish
        if entry["stats"]:
            tally["perks_with_stats"] += 1
        tally["stats"] += insert_stats(
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


def run(connection, cache_dir=None, session=None, supplement=True, log=print):
    """Pull the Cargo table (and each hero article), clean, store."""
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    rows = cargo_query(session, CARGO_TABLE, CARGO_FIELDS, cache_dir)
    by_hero = parse_rows(rows)
    log("cargo rows: %d   heroes named: %d" % (len(rows), len(by_hero)))

    profiles, supplemented = {}, 0
    if supplement:
        for hero_name, (weapons, abilities, perks) in sorted(by_hero.items()):
            extra, profile = supplement_from_wikitext(session, hero_name, cache_dir)
            if profile:
                profiles[hero_name] = profile
            for entry in weapons + abilities + perks:
                for code, value in extra.get(match_key(entry["name"]), {}).items():
                    if code not in entry["stats"]:
                        entry["stats"][code] = value
                        supplemented += 1
        log("supplemented stats: %d  (fields Cargo does not expose)" % supplemented)

    cursor = connection.cursor()
    source_id = common.register_source(cursor, WIKI, common.now())
    for table in ("ability_modifiers", "perk_ability_effects", "perk_stats",
                  "weapon_stats", "ability_stats", "weapon_configs", "weapons"):
        cursor.execute("DELETE FROM " + table)

    all_codes = set()
    for weapons, abilities, perks in by_hero.values():
        for entry in weapons + abilities + perks:
            all_codes.update(entry["stats"])
    key_ids = stat_key_ids(cursor, all_codes, source_id)
    hero_ids = common.lookup_ids(cursor, "heroes", "name", "hero_id")

    tally = collections.Counter()
    unknown_heroes = []
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
        load_weapons(cursor, hero_id, weapons, key_ids, source_id, tally)
        load_abilities(cursor, hero_id, weapons, abilities, key_ids, source_id, tally)
        load_perks(cursor, hero_id, perks, key_ids, source_id, tally)
    connection.commit()

    summary = dict(tally)
    summary.update({
        "cargo_rows": len(rows), "supplemented": supplemented,
        "unknown_heroes": sorted(unknown_heroes),
        "tables": ["abilities", "ability_stats", "ability_modifiers", "weapons",
                   "weapon_configs", "weapon_stats", "perk_stats",
                   "perk_ability_effects", "stat_keys", "heroes"],
    })
    return summary


def main():
    parser = common.build_parser(__doc__, ".cache-wiki")
    parser.add_argument("--no-supplement", action="store_true",
                        help="skip the wikitext pass for fields Cargo does not expose")
    args = parser.parse_args()
    cache = common.prepare_cache(args.cache)
    with psycopg.connect(common.resolve_dsn(args)) as connection:
        summary = run(connection, cache, supplement=not args.no_supplement)
        common.export_raw(connection, args, summary["tables"])
    for key in ("weapons", "configs", "classified", "added", "stats", "modifiers"):
        print("%-12s %d" % (key, summary.get(key, 0)))
    if summary["unknown_heroes"]:
        print("names in Cargo that are not roster heroes: %s"
              % ", ".join(summary["unknown_heroes"]))


if __name__ == "__main__":
    try:
        main()
    except (WikiError, psycopg.Error, requests.RequestException) as error:
        sys.exit("error: %s" % error)
