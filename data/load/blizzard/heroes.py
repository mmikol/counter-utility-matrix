"""Pull + clean + store: overwatch.blizzard.com - the roster.

Heroes, roles, subroles (with their icons and the hero portraits the user
layer draws), ability and perk text. Blizzard publishes no numbers and no
map data, so weapons, stats and maps come from the wiki.

    python -m data.load.blizzard.heroes
"""

import sys

import psycopg
import requests
from bs4 import BeautifulSoup

from data.sources import cache_key, cached_get
from data import common
from data.sources.blizzard import BASE_URL, BLIZZARD, HEROES_URL, USER_AGENT
from data.extract.blizzard.heroes import (
    ScrapeError,
    parse_abilities,
    parse_icons,
    parse_perks,
    parse_roster,
    parse_subroles,
)

ROLE_NAMES = {"tank": "Tank", "damage": "Damage", "support": "Support"}


def load(connection, subroles, heroes, abilities_by_slug, perks_by_slug, icons,
         cao):
    cursor = connection.cursor()
    source_id = common.register_source(cursor, BLIZZARD, cao)

    role_ids = {}
    for code in ("tank", "damage", "support"):
        cursor.execute(
            "INSERT INTO roles (code, name, icon_url, source_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
            " icon_url = coalesce(EXCLUDED.icon_url, roles.icon_url),"
            " source_id = EXCLUDED.source_id, cao = now()"
            " RETURNING role_id",
            (code, ROLE_NAMES[code], icons["roles"].get(code), source_id),
        )
        role_ids[code] = cursor.fetchone()[0]

    subrole_ids = {}
    for subrole in sorted(subroles.values(), key=lambda s: (s["role_code"], s["code"])):
        cursor.execute(
            "INSERT INTO subroles (role_id, code, name, passive_description,"
            " icon_url, source_id) VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET role_id = EXCLUDED.role_id,"
            " name = EXCLUDED.name,"
            " passive_description = EXCLUDED.passive_description,"
            " icon_url = coalesce(EXCLUDED.icon_url, subroles.icon_url),"
            " source_id = EXCLUDED.source_id, cao = now()"
            " RETURNING subrole_id",
            (
                role_ids[subrole["role_code"]],
                subrole["code"],
                subrole["name"],
                subrole["passive_description"],
                icons["subroles"].get(subrole["code"]),
                source_id,
            ),
        )
        subrole_ids[subrole["code"]] = cursor.fetchone()[0]

    for hero in heroes:
        cursor.execute(
            "INSERT INTO heroes (slug, name, role_id, subrole_id, portrait_url,"
            " source_id) VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name,"
            " role_id = EXCLUDED.role_id, subrole_id = EXCLUDED.subrole_id,"
            " portrait_url = coalesce(EXCLUDED.portrait_url, heroes.portrait_url),"
            " source_id = EXCLUDED.source_id, cao = now()"
            " RETURNING hero_id",
            (
                hero["slug"],
                hero["name"],
                role_ids[hero["role_code"]],
                subrole_ids[hero["subrole_code"]],
                hero.get("portrait_url"),
                source_id,
            ),
        )
        hero_id = cursor.fetchone()[0]

        for ability in abilities_by_slug[hero["slug"]]:
            cursor.execute(
                # Upserting by name means a RENAMED ability collides with its
                # own old row on (hero_id, position) and fails the stage. That
                # is deliberate: an update refreshes values, and a structural
                # change to a kit is what `rebuild` is for.
                "INSERT INTO abilities (hero_id, name, description, position,"
                " source_id) VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (hero_id, name) DO UPDATE SET"
                " description = EXCLUDED.description,"
                " position = EXCLUDED.position,"
                " source_id = EXCLUDED.source_id, cao = now()",
                (hero_id, ability["name"], ability["description"],
                 ability["position"], source_id),
            )
        for perk in perks_by_slug[hero["slug"]]:
            cursor.execute(
                "INSERT INTO perks (hero_id, tier_id, name, description, position,"
                " source_id) VALUES (%s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (hero_id, name) DO UPDATE SET"
                " tier_id = EXCLUDED.tier_id,"
                " description = EXCLUDED.description,"
                " position = EXCLUDED.position,"
                " source_id = EXCLUDED.source_id, cao = now()",
                (hero_id, perk["tier_id"], perk["name"], perk["description"],
                 perk["position"], source_id),
            )

    connection.commit()


def run(connection, cache_dir=None, session=None, log=print):
    """Pull the roster and every hero page, clean them, store them.
    Returns a summary dict."""
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    roster_soup = BeautifulSoup(cached_get(session, HEROES_URL, cache_dir,
                                           cache_key(HEROES_URL)), "html.parser")
    subroles = parse_subroles(roster_soup)
    heroes = parse_roster(roster_soup)
    icons = parse_icons(roster_soup)
    log("roster: %d heroes, %d subroles" % (len(heroes), len(subroles)))

    abilities_by_slug, perks_by_slug = {}, {}
    for index, hero in enumerate(heroes, start=1):
        slug = hero["slug"]
        page = cached_get(session, "%s/heroes/%s/" % (BASE_URL, slug),
                          cache_dir, cache_key(slug))
        soup = BeautifulSoup(page, "html.parser")
        abilities_by_slug[slug] = parse_abilities(soup, slug)
        perks_by_slug[slug] = parse_perks(soup, slug)
        log("  [%2d/%d] %-18s %d abilities, %d perks"
            % (index, len(heroes), hero["name"],
               len(abilities_by_slug[slug]), len(perks_by_slug[slug])))

    load(connection, subroles, heroes, abilities_by_slug, perks_by_slug, icons,
         common.now())
    return {
        "heroes": len(heroes),
        "subroles": len(subroles),
        "abilities": sum(len(a) for a in abilities_by_slug.values()),
        "perks": sum(len(p) for p in perks_by_slug.values()),
        "portraits": sum(1 for h in heroes if h.get("portrait_url")),
        "tables": ["roles", "subroles", "heroes", "abilities", "perks"],
    }


def main():
    parser = common.build_parser(__doc__, ".cache-blizzard")
    args = parser.parse_args()
    cache = common.prepare_cache(args.cache)
    with psycopg.connect(common.resolve_dsn(args)) as connection:
        summary = run(connection, cache)
        common.export_raw(connection, args, summary["tables"])
    print("loaded %(heroes)d heroes, %(abilities)d abilities, %(perks)d perks,"
          " %(portraits)d portraits" % summary)


if __name__ == "__main__":
    try:
        main()
    except (ScrapeError, psycopg.Error, requests.RequestException) as error:
        sys.exit("error: %s" % error)
