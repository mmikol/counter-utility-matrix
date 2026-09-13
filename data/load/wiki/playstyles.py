"""Pull + clean + store: overwatch.fandom.com - team composition playstyles.

The playstyles (dive, brawl, poke) and the heroes listed under each; a hero
can appear in several, so the link table is many-to-many. The page is
reloaded wholesale - it is the whole truth about styles.

    python -m data.load.wiki.playstyles
"""

import sys

import psycopg
import requests

from data import common
from data.sources.wiki import WIKI, USER_AGENT, WikiError, fetch_wikitext
from data.extract.wiki.playstyles import COMPOSITION_PAGE, parse_playstyles


def run(connection, cache_dir=None, session=None, log=print):
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    playstyles = parse_playstyles(fetch_wikitext(session, COMPOSITION_PAGE, cache_dir))

    cursor = connection.cursor()
    source_id = common.register_source(cursor, WIKI, common.now())
    cursor.execute("DELETE FROM playstyle")
    hero_ids = common.lookup_ids(cursor, "heroes", "name", "hero_id")
    links, unmatched = 0, []
    for code, name, heroes in playstyles:
        for hero_name in heroes:
            hero_id = hero_ids.get(hero_name.lower())
            if hero_id is None:
                unmatched.append("%s: %s" % (name, hero_name))
                continue
            cursor.execute(
                "INSERT INTO playstyle (hero_id, style, source_id)"
                " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (hero_id, code, source_id),
            )
            links += 1
        log("  %-8s %2d heroes" % (name, len(heroes)))
    connection.commit()
    return {"playstyles": [name for _, name, _ in playstyles], "links": links,
            "unmatched": unmatched, "tables": ["playstyle"]}


def main():
    parser = common.build_parser(__doc__, ".cache-wiki")
    args = parser.parse_args()
    cache = common.prepare_cache(args.cache)
    with psycopg.connect(common.resolve_dsn(args)) as connection:
        summary = run(connection, cache)
        common.export_raw(connection, args, summary["tables"])
    print("playstyles: %d   hero links: %d" % (len(summary["playstyles"]),
                                              summary["links"]))


if __name__ == "__main__":
    try:
        main()
    except (WikiError, psycopg.Error, requests.RequestException) as error:
        sys.exit("error: %s" % error)
