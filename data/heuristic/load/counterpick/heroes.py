"""Pull + clean + store: counterpick.gg - counters, best maps, rates.

The PLAYBOOK half of the model: who answers whom. The rates it also
publishes go into hero_meta under their own snapshot, because they are a
different population from Blizzard's. Scope is fixed to competitive on
console, Americas. Runs after wiki.maps and blizzard.meta.

    python -m data.heuristic.load.counterpick.heroes
"""

import sys

import psycopg
import requests

from data.sources import FetchError, cache_key, cached_get
from data.heuristic import pipeline
from data.common import current_patch, current_season
from data.heuristic.extract.counterpick.heroes import CounterpickError, parse_table
from data.heuristic.transform.counterpick.names import index, match_key
from data.sources.counterpick import (
    COUNTERPICK,
    BASE_URL,
    GAMEMODE,
    PLATFORM,
    REGIONS,
    USER_AGENT,
)

# The site never says which queue its competitive games were, and this
# model must not mistake an unlabelled snapshot for open queue.
QUEUE = "competitive_unspecified_queue"
PLATFORM_NAME = "console"
INPUT_DEVICE = "controller"


def run(connection, cache_dir=None, session=None, log=print):
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    cao = pipeline.now()

    pages = {}
    for their_region, our_region in REGIONS.items():
        pages[our_region] = parse_table(cached_get(
            session, BASE_URL, cache_dir,
            cache_key("heroes", GAMEMODE, PLATFORM, their_region),
            params={"platform": PLATFORM, "gamemode": GAMEMODE,
                    "region": their_region},
        ))
        log("  %-14s %d heroes" % (their_region, len(pages[our_region])))

    cursor = connection.cursor()
    source_id = pipeline.register_source(cursor, COUNTERPICK, cao)
    cursor.execute("INSERT INTO meta_snapshots (captured_at, queue, platform, input,"
                   " patch_id, season_id, source_id)"
                   " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING snapshot_id",
                   (cao, QUEUE, PLATFORM_NAME, INPUT_DEVICE,
                    current_patch(cursor), current_season(cursor), source_id))
    snapshot_id = cursor.fetchone()[0]

    hero_ids = index(pipeline.lookup_ids(cursor, "heroes", "name", "hero_id"))
    map_ids = index(pipeline.lookup_ids(cursor, "maps", "name", "map_id"))
    region_ids = pipeline.lookup_ids(cursor, "regions", "code", "region_id")
    all_tier = cursor.execute(
        "SELECT tier_id FROM competitive_tiers WHERE code = 'all'").fetchone()
    if all_tier is None:
        raise CounterpickError("no 'all' competitive tier; pull the rates first")
    tier_id = all_tier[0]

    # The playbook halves are judgements and the site's current page is the
    # whole truth about them - reloaded wholesale.
    cursor.execute("DELETE FROM counters")
    cursor.execute("DELETE FROM map_strategy")

    rates = counter_rows = best_maps = 0
    unknown_heroes, unknown_maps, missing_regions = set(), set(), set()
    for region_code, heroes in pages.items():
        region_id = region_ids.get(region_code)
        if region_id is None:
            missing_regions.add(region_code)
            continue
        for entry in heroes:
            hero_id = hero_ids.get(match_key(entry["hero"]))
            if hero_id is None:
                unknown_heroes.add(entry["hero"])
                continue
            cursor.execute(
                "INSERT INTO hero_meta (snapshot_id, hero_id, region_id,"
                " tier_id, win_rate, pick_rate, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (snapshot_id, hero_id, region_id, tier_id)"
                " DO NOTHING",
                (snapshot_id, hero_id, region_id, tier_id,
                 entry["win_rate"], entry["pick_rate"], source_id),
            )
            rates += cursor.rowcount
            # Both source columns are one claim in two directions; both
            # normalise to (hero, countered_by) and the union is kept.
            for relation in ("countered_by", "counters"):
                for name in entry[relation]:
                    other_id = hero_ids.get(match_key(name))
                    if other_id is None:
                        unknown_heroes.add(name)
                        continue
                    if other_id == hero_id:
                        continue
                    loser, winner = ((hero_id, other_id)
                                     if relation == "countered_by"
                                     else (other_id, hero_id))
                    cursor.execute(
                        "INSERT INTO counters (hero_id, countered_by_id,"
                        " source_id) VALUES (%s, %s, %s)"
                        " ON CONFLICT DO NOTHING",
                        (loser, winner, source_id),
                    )
                    counter_rows += cursor.rowcount
            for position, name in enumerate(entry["best_maps"], start=1):
                map_id = map_ids.get(match_key(name))
                if map_id is None:
                    unknown_maps.add(name)
                    continue
                cursor.execute(
                    "INSERT INTO map_strategy (hero_id, map_id, position,"
                    " source_id) VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT DO NOTHING",
                    (hero_id, map_id, position, source_id),
                )
                best_maps += cursor.rowcount
    connection.commit()
    log("rates %d   counters %d   best maps %d" % (rates, counter_rows, best_maps))
    return {"queue": QUEUE, "rates": rates, "counters": counter_rows,
            "best_maps": best_maps, "snapshot_id": snapshot_id,
            "unknown_heroes": sorted(unknown_heroes),
            "unknown_maps": sorted(unknown_maps),
            "missing_regions": sorted(missing_regions),
            "tables": ["meta_snapshots", "hero_meta", "counters", "map_strategy"]}


def main():
    parser = pipeline.build_parser(__doc__, ".cache-counterpick")
    args = parser.parse_args()
    cache = pipeline.prepare_cache(args.cache)
    with psycopg.connect(pipeline.resolve_dsn(args)) as connection:
        summary = run(connection, cache)
        pipeline.export_raw(connection, args, summary["tables"])
    if summary["unknown_heroes"]:
        print("names matched no hero: %s" % ", ".join(summary["unknown_heroes"]))


if __name__ == "__main__":
    try:
        main()
    except (CounterpickError, FetchError, psycopg.Error,
            requests.RequestException) as error:
        sys.exit("error: %s" % error)
