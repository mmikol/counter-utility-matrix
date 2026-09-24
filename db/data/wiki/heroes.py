"""Pull + clean + store: overwatch.fandom.com - hero kit data, via Cargo.

The wiki stores its ability data in a Cargo table with one row per ability;
kit_rows.py reads the rows into each hero's kit. Each hero's article adds
what Cargo does not register - the interaction flags, the health pool - and
hero_articles.py reads it. A hero the Cargo table names that the roster
lacks gets a row here when its article is marked upcoming, so its kit loads
ahead of release. kit_store.py writes the kits. Runs after blizzard.heroes,
which owns the hero, ability and perk rows this fills in.
"""

import re
from collections.abc import Iterable

import psycopg

from db import psql
from db.data import ArticlePullSummary, fetch
from db.data.wiki import WIKI, cargo_query, fetch_articles, kit_store
from db.data.wiki.hero_articles import Supplement, parse_announcement, supplement_kits
from db.data.wiki.kit_rows import parse_rows
from db.data.wiki.kit_store import KitCounts

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


def _announce_heroes(
        cursor: psycopg.Cursor, pull: fetch.PullContext, names: Iterable[str],
        hero_ids: dict[str, int], source_id: int) -> tuple[list[str], list[str]]:
    """Heroes the Cargo table names that the roster lacks: those whose
    article is marked upcoming get a row - role, subrole, health, release
    day, status announced - so their kit loads and the board can show
    them; Blizzard listing them later flips the status to released. Returns
    (the names stored, the pages that would not fetch), and adds each stored
    hero's id to `hero_ids`, which the kit and ability lookups that follow
    read; the rest stay unknown."""
    stored: list[str] = []
    articles, missing = fetch_articles(
        pull.session, sorted(name for name in names if name.lower() not in hero_ids),
        pull.cache_dir, pull.log)
    for hero_name, text in articles.items():
        found = parse_announcement(text)
        if not found:
            continue
        cursor.execute("SELECT s.subrole_id, r.role_id FROM subroles s JOIN roles r USING (role_id)"
                       " WHERE r.code = %s AND s.code = %s", (found["role"], found["subrole"]))
        row = cursor.fetchone()
        if row is None:
            pull.log("announced hero %s: subrole %s/%s not on the roster yet, skipped" % (
                hero_name, found["role"], found["subrole"]))
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
        pull.log("announced hero stored: %s (%s, %s%s)" % (
            hero_name, found["role"], found["subrole"],
            ", releases %s" % found["release_date"] if found["release_date"] else ""))
    return stored, missing


class KitsSummary(KitCounts, ArticlePullSummary):
    """The store's counts, every one present, and what the pull read: the
    Cargo rows, the stats the articles added, the heroes it skipped and the
    ones it announced."""
    cargo_rows: int
    supplemented: int
    unknown_heroes: list[str]
    announced: list[str]


def run(connection: psycopg.Connection, pull: fetch.PullContext, *,
        supplement: bool = True) -> KitsSummary:
    """Store the Cargo table's kits, with what each hero article adds unless
    supplement is off, in one transaction -> every row counted, the heroes
    announced and skipped, and the articles that would not fetch."""
    rows = cargo_query(pull.session, CARGO_TABLE, CARGO_FIELDS, pull.cache_dir)
    by_hero = parse_rows(rows)
    pull.log("cargo rows: %d   heroes named: %d" % (len(rows), len(by_hero)))

    articles = Supplement({}, 0, [])
    if supplement:
        articles = supplement_kits(pull.session, by_hero, pull.cache_dir, pull.log)
        pull.log("supplemented stats: %d  (fields Cargo does not expose)" % articles.stats)

    cursor = connection.cursor()
    source_id = psql.register_source(cursor, WIKI, psql.now())
    hero_ids = psql.lookup_ids(cursor, "heroes", "name", "hero_id")
    announced, unfetched = _announce_heroes(cursor, pull, by_hero, hero_ids, source_id)
    tally, unknown_heroes = kit_store.store(cursor, by_hero, articles.profiles, hero_ids,
                                            source_id)
    connection.commit()

    return KitsSummary(
        **tally.counts(), cargo_rows=len(rows), supplemented=articles.stats,
        missing=articles.missing + unfetched, unknown_heroes=unknown_heroes,
        announced=announced,
        tables=["abilities", "ability_stats", "ability_modifiers", "weapons",
                "weapon_configs", "weapon_stats", "perk_stats",
                "perk_ability_effects", "stat_keys", "heroes"])
