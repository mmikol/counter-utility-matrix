"""Pull + clean + store: counterpick.gg - counters, best maps, rates.

The PLAYBOOK half of the model: who answers whom. The rates it also
publishes go into hero_meta under their own snapshot, because they are a
different population from Blizzard's. Scope is fixed to competitive on
console, Americas. Runs after wiki.maps and blizzard.meta.

Reading counterpick.gg's hero ranking table.

One row per hero, with eight cells:

    0 hero      3 countered by    6 countered by (repeat)
    1 win %     4 counters        7 best maps
    2 pick %    5 counters (repeat)

Cells 5 and 6 repeat 3 and 4 for a second responsive layout, so they are
ignored.

The site's own field names invert its column labels - the key `counters` is
displayed as "Countered by" - so the tooltips are what settle the direction:
"Countered by" lists heroes to pick *against* this one, and "Counters" lists
heroes to avoid picking against it. They are read that way here, and the two
are kept separately because the site does not treat them as inverses: of 354
pairings, 114 appear in one direction only.
"""

from data import INPUT_DEVICE, PLATFORM, db, fetch
from data.db import current_patch, current_season
from data.fetch import cache_key, cached_get
from data.names import index, name_key
from data.counterpick import (
    COUNTERPICK,
    BASE_URL,
    GAMEMODE,
    REGIONS,
)
import re
from bs4 import BeautifulSoup


# --- extract: markup -> Python ---------------------------------------------

PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")

COUNTERED_BY = 3      # heroes that beat this hero
COUNTERS = 4          # heroes this hero beats
BEST_MAPS = 7


class CounterpickError(Exception):
    pass


def _percent(text):
    match = PERCENT_RE.search(text or "")
    return float(match.group(1)) if match else None


def _alts(cell):
    """The image alt texts in a cell, in order - hero or map names."""
    return [image["alt"].strip() for image in cell.find_all("img")
            if image.get("alt", "").strip()]


def parse_table(html):
    """[{hero, win_rate, pick_rate, countered_by, counters, best_maps}]."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise CounterpickError("no ranking table - the page may have changed")

    heroes = []
    for row in table.select("tbody tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) <= BEST_MAPS:
            continue
        names = _alts(cells[0])
        if not names:
            continue
        heroes.append({
            "hero": names[0],
            "win_rate": _percent(cells[1].get_text(" ", strip=True)),
            "pick_rate": _percent(cells[2].get_text(" ", strip=True)),
            "countered_by": _alts(cells[COUNTERED_BY]),
            "counters": _alts(cells[COUNTERS]),
            "best_maps": _alts(cells[BEST_MAPS]),
        })

    if not heroes:
        raise CounterpickError("ranking table held no hero rows")
    return heroes


# --- store ---------------------------------------------------------------------

# The site never says which queue its competitive games were, and this
# model must not mistake an unlabelled snapshot for open queue.
QUEUE = "competitive_unspecified_queue"
PLATFORM_NAME = PLATFORM


def run(connection, cache_dir=None, session=None, log=print):
    session = fetch.session(session)
    cao = db.now()

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
    source_id = db.register_source(cursor, COUNTERPICK, cao)
    cursor.execute("INSERT INTO meta_snapshots (captured_at, queue, platform, input,"
                   " patch_id, season_id, source_id)"
                   " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING snapshot_id",
                   (cao, QUEUE, PLATFORM_NAME, INPUT_DEVICE,
                    current_patch(cursor), current_season(cursor), source_id))
    snapshot_id = cursor.fetchone()[0]

    hero_ids = index(db.lookup_ids(cursor, "heroes", "name", "hero_id"))
    map_ids = index(db.lookup_ids(cursor, "maps", "name", "map_id"))
    region_ids = db.lookup_ids(cursor, "regions", "code", "region_id")
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
            hero_id = hero_ids.get(name_key(entry["hero"]))
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
                    other_id = hero_ids.get(name_key(name))
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
                map_id = map_ids.get(name_key(name))
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
