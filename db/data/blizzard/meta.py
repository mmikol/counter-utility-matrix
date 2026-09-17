"""Pull + clean + store: overwatch.blizzard.com/en-us/rates/ - win, pick and
ban rates as a dated snapshot, sliced by skill tier and by map.

Three deliberate restrictions, all recorded on the snapshot:

  queue     Competitive - Role Queue (the page offers no Open Queue). The rq
            code is read from the page's own queue filter, never hardcoded:
            Blizzard renumbered it once and the old code silently served a
            different population.
  platform  Console (the parameter is spelled input=Console).
  region    Americas, on every request including the baseline.

The page carries its rows as JSON on a blz-data-table element, and its filter
vocabularies as ordinary select options.
"""

import json

from bs4 import BeautifulSoup

from db import INPUT_DEVICE, PLATFORM, REGION, psql
from db.data import fetch
from db.data.blizzard import BLIZZARD, RATES_URL
from db.data.fetch import cache_key, cached_get
from db.psql import current_patch, current_season

# --- extract: markup -> Python ---------------------------------------------

class RatesError(Exception):
    pass


def parse_rows(html):
    """[(hero_name, win_rate, pick_rate, ban_rate)] from the data table JSON."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("blz-data-table")
    if table is None or not table.get("rows"):
        raise RatesError("no blz-data-table rows attribute - the page changed")

    stats = []
    for row in json.loads(table["rows"]):
        cells = row.get("cells", {})
        name = cells.get("name")
        if not name:
            continue
        stats.append(
            (name, cells.get("winrate"), cells.get("pickrate"), cells.get("banrate"))
        )
    if not stats:
        raise RatesError("data table held no hero rows")
    return stats


def parse_filter_options(html, select_id):
    """[(value, label)] for one filter dropdown."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id=select_id)
    if select is None:
        raise RatesError("no %s on the page" % select_id)
    return [
        (option.get("value"), option.get_text(strip=True))
        for option in select.find_all("option")
        if option.get("value")
    ]


# --- store ---------------------------------------------------------------------

# ~280 sequential pages is more load than the source will take. Slower here
# is faster overall, because being cut off costs the whole stage.
REQUEST_DELAY = 5.0
REQUEST_TIMEOUT = 90
RETRIES = 6
RETRY_BACKOFF = 5.0

QUEUE_NAME = "competitive_role_queue"
QUEUE_LABEL = "Competitive - Role Queue"
INPUT_PARAM = "Console"           # the site's spelling of PLATFORM
ALL_TIER = "All"
REGION_PARAM = "Americas"         # the site's spelling of REGION
REGION_NAME = "Americas"


def competitive_rq(session, cache_dir):
    """The rq code the page currently assigns to Competitive - Role Queue."""
    page = cached_get(
        session, RATES_URL, cache_dir,
        cache_key("rates", "queue-vocabulary",
                  "input-%s" % INPUT_PARAM, "region-%s" % REGION_PARAM),
        params={"input": INPUT_PARAM, "region": REGION_PARAM},
        timeout=REQUEST_TIMEOUT, retries=RETRIES,
        delay=REQUEST_DELAY, backoff=RETRY_BACKOFF,
    )
    options = parse_filter_options(page, "filter-rq-select")
    codes = [code for code, label in options if label == QUEUE_LABEL]
    if len(codes) != 1:
        raise RatesError(
            "queue filter no longer offers exactly one %r: %s"
            % (QUEUE_LABEL, options))
    return codes[0]


def fetch_slice(session, params, cache_dir, rq):
    """One rates page for a given filter combination."""
    query = dict(params, rq=rq, input=INPUT_PARAM, region=REGION_PARAM)
    return cached_get(
        session, RATES_URL, cache_dir,
        cache_key("rates", *("%s-%s" % kv for kv in sorted(query.items()))),
        params=query, timeout=REQUEST_TIMEOUT, retries=RETRIES,
        delay=REQUEST_DELAY, backoff=RETRY_BACKOFF,
    )


def run(connection, cache_dir=None, session=None, log=print):
    session = fetch.session(session)
    cao = psql.now()

    rq = competitive_rq(session, cache_dir)
    baseline = fetch_slice(session, {}, cache_dir, rq)
    tiers = parse_filter_options(baseline, "filter-tier-select")
    maps = [m for m in parse_filter_options(baseline, "filter-map-select")
            if m[0] != "all-maps"]

    cursor = connection.cursor()
    source_id = psql.register_source(cursor, BLIZZARD, cao)
    cursor.execute(
        "INSERT INTO regions (code, name, source_id) VALUES (%s, %s, %s)"
        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name"
        " RETURNING region_id",
        (REGION, REGION_NAME, source_id),
    )
    region_id = cursor.fetchone()[0]

    tier_ids = {}
    for order, (code, name) in enumerate(tiers):
        cursor.execute(
            "INSERT INTO competitive_tiers (code, name, rank_order, source_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
            " rank_order = EXCLUDED.rank_order RETURNING tier_id",
            (code.lower(), name, order, source_id),
        )
        tier_ids[code] = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO meta_snapshots (captured_at, queue, platform, input,"
        " patch_id, season_id, source_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING snapshot_id",
        (cao, QUEUE_NAME, PLATFORM, INPUT_DEVICE,
         current_patch(cursor), current_season(cursor), source_id),
    )
    snapshot_id = cursor.fetchone()[0]

    hero_ids = psql.lookup_ids(cursor, "heroes", "name", "hero_id")
    map_ids = psql.lookup_ids(cursor, "maps", "name", "map_id")
    unmatched = set()

    def load_hero_slice(html, tier_code):
        written = 0
        for name, win, pick, ban in parse_rows(html):
            hero_id = hero_ids.get(name.lower())
            if hero_id is None:
                unmatched.add(name)
                continue
            cursor.execute(
                "INSERT INTO hero_meta (snapshot_id, hero_id, region_id,"
                " tier_id, win_rate, pick_rate, ban_rate, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (snapshot_id, hero_id, region_id, tier_id)"
                " DO NOTHING",
                (snapshot_id, hero_id, region_id, tier_ids[tier_code],
                 win, pick, ban, source_id),
            )
            written += 1
        return written

    rows = load_hero_slice(baseline, ALL_TIER)
    for code, _ in tiers:
        if code != ALL_TIER:
            rows += load_hero_slice(fetch_slice(session, {"tier": code}, cache_dir, rq),
                                    code)
    log("hero/tier rows: %d" % rows)

    # Per map, across all ranks. Map x tier would be 270 requests against
    # 30, and the source refuses connections well before the end of a sweep
    # that size; rows carry tier_id (all ranks) so widening needs no
    # migration, only the inner loop.
    map_rows, skipped_maps = 0, []
    for slug, label in maps:
        map_id = map_ids.get(label.lower())
        if map_id is None:
            skipped_maps.append(label)
            continue
        for name, win, pick, ban in parse_rows(
            fetch_slice(session, {"map": slug}, cache_dir, rq)
        ):
            hero_id = hero_ids.get(name.lower())
            if hero_id is None:
                unmatched.add(name)
                continue
            cursor.execute(
                "INSERT INTO map_meta (snapshot_id, hero_id, map_id,"
                " tier_id, region_id, stage_id, win_rate, pick_rate,"
                " ban_rate, source_id)"
                " VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s)"
                " ON CONFLICT (snapshot_id, hero_id, map_id, tier_id,"
                " region_id, stage_id) DO NOTHING",
                (snapshot_id, hero_id, map_id, tier_ids[ALL_TIER],
                 region_id, win, pick, ban, source_id),
            )
            map_rows += 1
    connection.commit()
    snapshots = cursor.execute("SELECT count(*) FROM meta_snapshots").fetchone()[0]
    log("hero/map rows: %d   snapshots held: %d" % (map_rows, snapshots))
    return {"queue": QUEUE_NAME, "platform": PLATFORM, "region": REGION,
            "tiers": len(tier_ids), "maps": len(maps) - len(skipped_maps),
            "hero_rows": rows, "map_rows": map_rows, "snapshot_id": snapshot_id,
            "snapshots": snapshots, "unmatched": sorted(unmatched),
            "skipped_maps": skipped_maps,
            "tables": ["regions", "competitive_tiers", "meta_snapshots",
                       "hero_meta", "map_meta"]}
