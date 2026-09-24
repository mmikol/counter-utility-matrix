"""Pull + clean + store: overwatch.blizzard.com/en-us/rates/ - win, pick and
ban rates as a dated snapshot, sliced by skill tier and by map.

Three deliberate restrictions, all recorded on the snapshot:

    queue       Competitive - Role Queue (the page offers no Open Queue). The rq
                code is read from the page's own queue filter, never hardcoded:
                Blizzard renumbered it once and the old code silently served a
                different population.
    platform    Console (the parameter is spelled input=Console).
    region      Americas, on every request including the baseline.

The page carries its rows as JSON on a blz-data-table element, and its filter
vocabularies as ordinary select options.
"""

import json
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import NamedTuple

import psycopg
from bs4 import BeautifulSoup, Tag

from db import INPUT_DEVICE, PLATFORM, REGION, psql
from db.data import PullSummary, fetch
from db.data.blizzard import BLIZZARD, RATES_URL, BlizzardError, attr
from db.data.fetch import cache_key, cached_get
from db.data.names import index, name_key
from db.psql import current_patch, current_season

# --- extract: markup -> Python ---------------------------------------------

class RateRow(NamedTuple):
    """One hero's row of the data table; a rate the page leaves out is None."""
    name: str
    win_rate: float | None
    pick_rate: float | None
    ban_rate: float | None


def parse_rows(html: str) -> list[RateRow]:
    """[RateRow(hero_name, win_rate, pick_rate, ban_rate)] from the data table
    JSON."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("blz-data-table")
    if not isinstance(table, Tag) or not table.get("rows"):
        raise BlizzardError("no blz-data-table rows attribute - the page changed")

    stats = []
    for row in json.loads(attr(table, "rows")):
        cells = row.get("cells", {})
        name = cells.get("name")
        if not name:
            continue
        stats.append(RateRow(name=name, win_rate=cells.get("winrate"),
                             pick_rate=cells.get("pickrate"), ban_rate=cells.get("banrate")))
    if not stats:
        raise BlizzardError("data table held no hero rows")
    return stats


def parse_filter_options(html: str, select_id: str) -> list[tuple[str, str]]:
    """[(value, label)] for one filter dropdown."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id=select_id)
    if not isinstance(select, Tag):
        raise BlizzardError("no %s on the page" % select_id)
    return [
        (attr(option, "value"), option.get_text(strip=True))
        for option in select.find_all("option")
        if option.get("value")
    ]


# --- store ---------------------------------------------------------------------

# ~40 sequential pages is more load than the source will take at speed.
# Slower here is faster overall: being cut off costs the whole stage.
RATES_POLICY = fetch.RequestPolicy(attempts=6, backoff=5.0, timeout=90, delay=5.0)

QUEUE_NAME = "competitive_role_queue"
QUEUE_LABEL = "Competitive - Role Queue"
INPUT_PARAM = "Console"           # the site's spelling of PLATFORM
ALL_TIER = "All"
REGION_PARAM = "Americas"         # the site's spelling of REGION
REGION_NAME = "Americas"


def competitive_rq(pull: fetch.PullContext) -> str:
    """The rq code the page currently assigns to Competitive - Role Queue."""
    page = cached_get(
        pull, RATES_URL,
        cache_key("rates", "queue-vocabulary",
                  "input-%s" % INPUT_PARAM, "region-%s" % REGION_PARAM),
        params={"input": INPUT_PARAM, "region": REGION_PARAM},
        policy=RATES_POLICY,
    )
    options = parse_filter_options(page, "filter-rq-select")
    codes = [code for code, label in options if label == QUEUE_LABEL]
    if len(codes) != 1:
        raise BlizzardError(
            "queue filter no longer offers exactly one %r: %s"
            % (QUEUE_LABEL, options))
    return codes[0]


def fetch_slice(pull: fetch.PullContext, params: dict[str, str], rq: str) -> str:
    """One rates page for a given filter combination."""
    query = dict(params, rq=rq, input=INPUT_PARAM, region=REGION_PARAM)
    return cached_get(
        pull, RATES_URL,
        cache_key("rates", *("%s-%s" % kv for kv in sorted(query.items()))),
        params=query, policy=RATES_POLICY,
    )


class RatesSummary(PullSummary):
    """The pull's counts. A pull that read a page from the stale cache stores
    nothing: snapshot_id is None, every count 0 and tables empty."""
    queue: str
    platform: str
    region: str
    tiers: int
    maps: int
    hero_rows: int
    map_rows: int
    snapshot_id: int | None
    snapshots: int
    unmatched: list[str]
    skipped_maps: list[str]


class RatesWritten(NamedTuple):
    """What _store wrote: the snapshot it stamped, the tiers and maps under
    it, the hero rows of each and the names the roster lacks, sorted."""
    snapshot_id: int | None
    tiers: int
    maps: int
    hero_rows: int
    map_rows: int
    unmatched: list[str]


TABLES = ("regions", "competitive_tiers", "meta_snapshots", "hero_meta", "map_meta")


def _hero_rows(
        rows: list[RateRow], hero_ids: Mapping[str, int],
        unmatched: set[str]) -> Iterator[tuple[int, float | None, float | None, float | None]]:
    """(hero_id, win, pick, ban) for each row whose hero the roster holds
    (hero_ids is {name_key: hero_id}); a name it lacks is added to
    `unmatched`."""
    for name, win, pick, ban in rows:
        hero_id = hero_ids.get(name_key(name))
        if hero_id is None:
            unmatched.add(name)
            continue
        yield hero_id, win, pick, ban


def _store(
        cursor: psycopg.Cursor, tiers: list[tuple[str, str]],
        rows_by_tier: dict[str, list[RateRow]], rows_by_map: dict[int, list[RateRow]],
        cao: datetime) -> RatesWritten:
    """Stamp one new snapshot and write its rows: the region and the tiers
    upserted, each tier's hero rows, and each map's across all ranks."""
    source_id = psql.register_source(cursor, BLIZZARD, cao)
    cursor.execute(
        "INSERT INTO regions (code, name, source_id) VALUES (%s, %s, %s)"
        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name"
        " RETURNING region_id",
        (REGION, REGION_NAME, source_id),
    )
    region_id = psql.scalar(cursor)

    tier_ids: dict[str, int] = {}
    for order, (code, name) in enumerate(tiers):
        cursor.execute(
            "INSERT INTO competitive_tiers (code, name, rank_order, source_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
            " rank_order = EXCLUDED.rank_order RETURNING tier_id",
            (code.lower(), name, order, source_id),
        )
        tier_ids[code] = psql.scalar(cursor)

    cursor.execute(
        "INSERT INTO meta_snapshots (captured_at, queue, platform, input,"
        " patch_id, season_id, source_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING snapshot_id",
        (
            cao, QUEUE_NAME, PLATFORM, INPUT_DEVICE,
            current_patch(cursor), current_season(cursor), source_id),
    )
    snapshot_id = psql.scalar(cursor)

    hero_ids = index(psql.lookup_ids(cursor, "heroes", "name", "hero_id"))
    unmatched: set[str] = set()
    hero_rows = 0
    for tier_code, rows in rows_by_tier.items():
        for hero_id, win, pick, ban in _hero_rows(rows, hero_ids, unmatched):
            cursor.execute(
                "INSERT INTO hero_meta (snapshot_id, hero_id, region_id,"
                " tier_id, win_rate, pick_rate, ban_rate, source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (snapshot_id, hero_id, region_id, tier_id)"
                " DO NOTHING",
                (snapshot_id, hero_id, region_id, tier_ids[tier_code],
                 win, pick, ban, source_id),
            )
            hero_rows += 1
    map_rows = 0
    for map_id, rows in rows_by_map.items():
        for hero_id, win, pick, ban in _hero_rows(rows, hero_ids, unmatched):
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
    return RatesWritten(snapshot_id, len(tier_ids), len(rows_by_map), hero_rows, map_rows,
                        sorted(unmatched))


def run(connection: psycopg.Connection, pull: fetch.PullContext) -> RatesSummary:
    """Fetch the rates page by tier and by map, then store it as one new
    dated snapshot in one transaction -> the rows written, the snapshots
    held, the misses. A page read from the stale cache stamps no snapshot:
    nothing is written, so the newest capture stays the last real one."""
    cao = psql.now()
    cursor = connection.cursor()
    # a map the database lacks is never fetched; the read's transaction ends
    # here, so none stays open across the ~40 fetches
    map_ids = index(psql.lookup_ids(cursor, "maps", "name", "map_id"))
    connection.commit()

    rq = competitive_rq(pull)
    baseline = fetch_slice(pull, {}, rq)
    tiers = parse_filter_options(baseline, "filter-tier-select")
    maps = [(slug, label) for slug, label in parse_filter_options(baseline, "filter-map-select")
            if slug != "all-maps"]
    rows_by_tier: dict[str, list[RateRow]] = {ALL_TIER: parse_rows(baseline)}
    for code, _ in tiers:
        if code != ALL_TIER:
            rows_by_tier[code] = parse_rows(fetch_slice(pull, {"tier": code}, rq))

    # Per map, across all ranks. Map x tier would be 270 requests against
    # 30, and the source refuses connections well before the end of a sweep
    # that size; rows carry tier_id (all ranks) so widening needs no
    # migration, only the inner loop.
    rows_by_map: dict[int, list[RateRow]] = {}
    skipped_maps: list[str] = []
    for slug, label in maps:
        map_id = map_ids.get(name_key(label))
        if map_id is None:
            skipped_maps.append(label)
            continue
        rows_by_map[map_id] = parse_rows(fetch_slice(pull, {"map": slug}, rq))

    if pull.stale:
        pull.log("rates: %d pages from the stale cache; no snapshot stamped" % len(pull.stale))
        written = RatesWritten(snapshot_id=None, tiers=0, maps=0, hero_rows=0, map_rows=0,
                               unmatched=[])
    else:
        written = _store(cursor, tiers, rows_by_tier, rows_by_map, cao)
    connection.commit()
    snapshots = psql.scalar(cursor.execute("SELECT count(*) FROM meta_snapshots"))
    pull.log("hero/tier rows: %d" % written.hero_rows)
    pull.log("hero/map rows: %d   snapshots held: %d" % (written.map_rows, snapshots))
    return RatesSummary(
        queue=QUEUE_NAME, platform=PLATFORM, region=REGION, tiers=written.tiers,
        maps=written.maps, hero_rows=written.hero_rows, map_rows=written.map_rows,
        snapshot_id=written.snapshot_id, snapshots=snapshots, unmatched=written.unmatched,
        skipped_maps=skipped_maps, tables=[] if written.snapshot_id is None else list(TABLES))
