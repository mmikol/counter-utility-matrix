"""Pull + clean + store: overwatch.fandom.com - maps, game modes, stages.

Only the wiki's "Standard Play" section is read; Former Standard Play,
Stadium, Arcade, Custom Games, Training and seasonal modes are out of scope.

    python -m data.load.wiki.maps
"""

import sys

import psycopg
import requests

from data import common
from data.sources.wiki import WIKI, USER_AGENT, WikiError, fetch_wikitext
from data.extract.wiki.maps import parse_modes_and_maps, parse_stages

MAPS_PAGE = "Maps"


def run(connection, cache_dir=None, session=None, log=print):
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    modes = parse_modes_and_maps(fetch_wikitext(session, MAPS_PAGE, cache_dir))

    cursor = connection.cursor()
    source_id = common.register_source(cursor, WIKI, common.now())
    map_ids, combinations = {}, 0
    for code, name, maps in modes:
        cursor.execute(
            # Upserted, never deleted: map_meta snapshots hang off maps, and
            # a DELETE here cascades through every older snapshot's rows.
            "INSERT INTO game_modes (code, name, source_id) VALUES (%s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
            " source_id = EXCLUDED.source_id, cao = now() RETURNING mode_id",
            (code, name, source_id),
        )
        mode_id = cursor.fetchone()[0]
        for map_name in maps:
            if map_name not in map_ids:
                cursor.execute(
                    "INSERT INTO maps (name, source_id) VALUES (%s, %s)"
                    " ON CONFLICT (name) DO UPDATE SET"
                    " source_id = EXCLUDED.source_id, cao = now()"
                    " RETURNING map_id",
                    (map_name, source_id),
                )
                map_ids[map_name] = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO map_modes (map_id, mode_id, source_id)"
                " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (map_ids[map_name], mode_id, source_id),
            )
            combinations += 1
        log("  %-11s %2d maps" % (name, len(maps)))

    stage_rows = 0
    for map_name, map_id in map_ids.items():
        for position, stage in enumerate(
            parse_stages(fetch_wikitext(session, map_name.replace(" ", "_"),
                                        cache_dir)), start=1):
            cursor.execute(
                "INSERT INTO map_stages (map_id, position, name, source_id)"
                " VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (map_id, name) DO UPDATE SET"
                " position = EXCLUDED.position,"
                " source_id = EXCLUDED.source_id, cao = now()",
                (map_id, position, stage, source_id),
            )
            stage_rows += 1
    connection.commit()
    return {"modes": len(modes), "maps": len(map_ids),
            "combinations": combinations, "stages": stage_rows,
            "tables": ["game_modes", "maps", "map_modes", "map_stages"]}


def main():
    parser = common.build_parser(__doc__, ".cache-wiki")
    args = parser.parse_args()
    cache = common.prepare_cache(args.cache)
    with psycopg.connect(common.resolve_dsn(args)) as connection:
        summary = run(connection, cache)
        common.export_raw(connection, args, summary["tables"])
    print("modes: %(modes)d   maps: %(maps)d   combinations: %(combinations)d"
          "   stages: %(stages)d" % summary)


if __name__ == "__main__":
    try:
        main()
    except (WikiError, psycopg.Error, requests.RequestException) as error:
        sys.exit("error: %s" % error)
