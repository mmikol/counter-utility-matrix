"""The pulls' store paths, run whole over a recording connection: each
pull's run() reads inline pages from a page cache in tmp_path under the
names its cache uses, and writes to a RecordingConnection whose reads answer
the lookups. The database-free twin of test_sources_from_cache.py - the
parameters each pull writes, its commits and its summary, never whole SQL
text. No database, no network: the session refuses every request and
counts it."""

import datetime
import html
import json

import pytest
import requests

from db import INPUT_DEVICE, PLATFORM, REGION, psql
from db.data import fetch
from db.data.blizzard import meta
from db.data.fetch import cache_key
from db.data.wiki import WikiError, maps, patches, playstyles, seasons, terrain
from tests.db.recording import RecordingConnection
from tests.db.test_fetch import write_aged
from tests.db.test_transforms import HYBRID_PAGE
from tests.db.wiki.test_wiki_playstyles_and_patches import COMPOSITION

CAO = datetime.datetime(2026, 9, 24, 5, 0, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """Every pull's one timestamp, and the day a season is judged started by."""
    monkeypatch.setattr(psql, "now", lambda: CAO)


class Offline:
    """The network down: every request fails as a refused connection would,
    and is counted."""

    def __init__(self):
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        raise requests.ConnectionError("offline")

    def close(self):
        pass


def _pull(tmp_path, lines, **kwargs):
    return fetch.PullContext(str(tmp_path), session=Offline(), log=lines.append, **kwargs)


def _cache(tmp_path, pages, hours=0):
    """Each page written into the cache under its file name, `hours` old."""
    for name, text in pages.items():
        write_aged(tmp_path / name, text, hours=hours)


def _writes_at_fetch(monkeypatch, module, connection):
    """module.fetch_articles wrapped: at each call, it records every statement
    the pull has run by then that is not a read."""
    seen = []
    real = module.fetch_articles

    def fetch_articles(pull, titles):
        seen.append([text for cursor in connection.cursors for text, _ in cursor.statements
                     if not text.startswith("SELECT")])
        return real(pull, titles)
    monkeypatch.setattr(module, "fetch_articles", fetch_articles)
    return seen


# --- the rates: Blizzard's rates page, a snapshot per pull -------------------

def _rates_page(rows, *filters):
    """A rates page: its data table over `rows` (name, win, pick, ban), and
    each filter as (select id, [(value, label)])."""
    table = [{"cells": {"name": name, "winrate": win, "pickrate": pick, "banrate": ban}}
             for name, win, pick, ban in rows]
    selects = "".join('<select id="%s">%s</select>' % (select_id, "".join(
        '<option value="%s">%s</option>' % option for option in options))
        for select_id, options in filters)
    return '<main>%s<blz-data-table rows="%s"></blz-data-table></main>' % (
        selects, html.escape(json.dumps(table)))


RATES_PAGES = {
    # the names tests/db/blizzard/test_blizzard_rates.py pins
    "rates_queue_vocabulary_input_Console_region_Americas.html": _rates_page(
        [("Ana", 1, 1, 1)],
        ("filter-rq-select", [("0", "Quick Play - Role Queue"),
                              ("2", "Competitive - Role Queue")])),
    "rates_input_Console_region_Americas_rq_2.html": _rates_page(
        [("Ana", 48.7, 23.0, 8.2), ("Tracer", 50.1, 12.4, 1.0)],
        ("filter-tier-select", [("All", "All Tiers"), ("Gold", "Gold")]),
        ("filter-map-select", [("all-maps", "All Maps"), ("kings-row", "King's Row"),
                               ("busan", "Busan")])),
    "rates_input_Console_region_Americas_rq_2_tier_Gold.html": _rates_page(
        [("Ana", 51.0, 20.1, 7.0), ("Tracer", 49.0, 11.0, 0.5)]),
    "rates_input_Console_map_kings_row_region_Americas_rq_2.html": _rates_page(
        [("Ana", 49.5, 18.0, 6.0), ("Tracer", 47.5, 13.0, 0.9)]),
}

RATES_READS = [
    ('SELECT "name", "map_id" FROM "maps"', [("King's Row", 7)]),
    ('SELECT "name", "hero_id" FROM "heroes"', [("Ana", 1)]),
    ("SELECT patch_id FROM patches", []),
    ("SELECT season_id FROM seasons", []),
    ("SELECT count(*) FROM meta_snapshots", [(3,)]),
]


def test_the_rates_pull_stores_one_snapshot_of_every_tier_and_map_it_read(tmp_path):
    """Ana is on the roster and Tracer is not; King's Row is in the map pool
    and Busan is not, so Busan's slice is never asked for."""
    _cache(tmp_path, RATES_PAGES)
    connection, lines = RecordingConnection(RATES_READS), []
    pull = _pull(tmp_path, lines)
    summary = meta.run(connection, pull)
    [cursor] = connection.cursors
    # the ids the upserts read back, in the order they run
    source_id, region_id, all_tier, gold_tier, snapshot_id = 1, 2, 3, 4, 5
    assert cursor.written("INSERT INTO sources")[0][0] == "blizzard"
    assert cursor.written("INSERT INTO regions") == [(REGION, "Americas", source_id)]
    assert cursor.written("INSERT INTO competitive_tiers") == [
        ("all", "All Tiers", 0, source_id), ("gold", "Gold", 1, source_id)]
    assert cursor.written("INSERT INTO meta_snapshots") == [
        (CAO, "competitive_role_queue", PLATFORM, INPUT_DEVICE, None, None, source_id)]
    assert cursor.written("INSERT INTO hero_meta") == [
        (snapshot_id, 1, region_id, all_tier, 48.7, 23.0, 8.2, source_id),
        (snapshot_id, 1, region_id, gold_tier, 51.0, 20.1, 7.0, source_id)]
    assert cursor.written("INSERT INTO map_meta") == [
        (snapshot_id, 1, 7, all_tier, region_id, 49.5, 18.0, 6.0, source_id)]
    assert summary == {
        "queue": "competitive_role_queue", "platform": PLATFORM, "region": REGION,
        "tiers": 2, "maps": 1, "hero_rows": 2, "map_rows": 1, "snapshot_id": snapshot_id,
        "snapshots": 3, "unmatched": ["Tracer"], "skipped_maps": ["Busan"],
        "tables": ["regions", "competitive_tiers", "meta_snapshots", "hero_meta", "map_meta"]}
    # one commit ends the map read before the fetches, one the snapshot
    assert connection.commits == 2
    assert pull.session.calls == 0 and pull.stale == []
    assert lines == ["hero/tier rows: 2", "hero/map rows: 1   snapshots held: 3"]


def test_a_rates_pull_that_read_a_stale_page_stamps_no_snapshot(tmp_path, monkeypatch):
    """A refresh whose every refetch fails reads yesterday's pages from the
    cache; stamping them as a capture of today would be a lie, so nothing is
    written, the source's row included."""
    monkeypatch.setattr(meta, "RATES_POLICY", fetch.RequestPolicy(attempts=1, backoff=0, delay=0))
    _cache(tmp_path, RATES_PAGES, hours=48)
    connection, lines = RecordingConnection(RATES_READS), []
    pull = _pull(tmp_path, lines, max_age=0)
    summary = meta.run(connection, pull)
    [cursor] = connection.cursors
    assert cursor.written("INSERT") == [] and cursor.written("UPDATE") == []
    assert summary["snapshot_id"] is None and summary["tables"] == []
    assert (summary["tiers"], summary["maps"], summary["hero_rows"], summary["map_rows"]) == (
        0, 0, 0, 0)
    assert summary["unmatched"] == [] and summary["skipped_maps"] == ["Busan"]
    assert sorted(line.split(":")[0] for line in pull.stale) == sorted(RATES_PAGES)
    assert pull.session.calls == len(RATES_PAGES)             # each refetch asked for once
    assert connection.commits == 2
    assert "rates: 4 pages from the stale cache; no snapshot stamped" in lines


# --- the map pool: the Maps article, each map's and the Hybrid article -------

MAPS_PAGE = """== Standard Play ==
<gallery class="maps-gallery maps-gallery--control">
File:Busan.jpg|{{flag|kr}} [[Busan]]
File:Ilios.jpg|{{flag|gr}} [[Ilios]]
</gallery>
<gallery class="maps-gallery maps-gallery--hybrid">
File:Kings Row.jpg|{{flag|gb}} [[King's Row]]
</gallery>
== Former Standard Play ==
<gallery class="maps-gallery maps-gallery--assault">
File:Hanamura.jpg|{{flag|jp}} [[Hanamura]]
</gallery>
"""

BUSAN_STAGES = """== Gameplay ==
* [[Downtown]]
** A street fight.
* [[Sanctuary]]
* [[MEKA Base]]
== Trivia ==
"""


def test_the_maps_pull_stores_the_pool_and_each_map_s_stages(tmp_path):
    """Busan's article lists its three submaps, every Hybrid map plays the
    Hybrid article's two phases, and Ilios' article is not in the cache."""
    _cache(tmp_path, {
        cache_key(maps.MAPS_PAGE) + ".wikitext": MAPS_PAGE,
        cache_key(maps.HYBRID_PAGE) + ".wikitext": HYBRID_PAGE,
        cache_key("Busan") + ".wikitext": BUSAN_STAGES,
        cache_key("King's Row") + ".wikitext": "'''King's Row''' is a [[Hybrid]] map."})
    connection, lines = RecordingConnection(), []
    pull = _pull(tmp_path, lines)
    summary = maps.run(connection, pull)
    [cursor] = connection.cursors
    # the ids the upserts read back: the source, then each mode and each new map
    source_id, control, busan, ilios, hybrid, kings_row = 1, 2, 3, 4, 5, 6
    assert cursor.written("INSERT INTO game_modes") == [
        ("control", "Control", source_id), ("hybrid", "Hybrid", source_id)]
    assert cursor.written("INSERT INTO maps") == [
        ("Busan", source_id), ("Ilios", source_id), ("King's Row", source_id)]
    assert cursor.written("INSERT INTO map_modes") == [
        (busan, control, source_id), (ilios, control, source_id), (kings_row, hybrid, source_id)]
    assert cursor.written("INSERT INTO map_stages") == [
        (busan, 1, "Downtown", source_id), (busan, 2, "Sanctuary", source_id),
        (busan, 3, "MEKA Base", source_id),
        (kings_row, 1, "Assault", source_id), (kings_row, 2, "Escort", source_id)]
    [missing] = summary["missing"]
    assert missing.startswith("Ilios: ") and "offline" in missing
    assert {key: summary[key] for key in ("modes", "maps", "combinations", "stages")} == {
        "modes": 2, "maps": 3, "combinations": 3, "stages": 5}
    assert summary["maps_with_stages"] == {"control": 1, "hybrid": 1}
    assert summary["tables"] == ["game_modes", "maps", "map_modes", "map_stages"]
    assert connection.commits == 1 and pull.session.calls == 1   # Ilios, asked for once


# --- the seasons: the Season article and its era subpages --------------------

SEASON_PAGE = """The seasons, era by era.
== 2016 ==
{{main|Season/2016}}
"""

SEASON_2016 = """=== Season 1 ===
(10 August 2016 - 10 October 2016)
The first season.

=== Season 2: Far Future ===
(1 January 2099 - 1 March 2099)
"""


def test_the_seasons_pull_reloads_the_started_seasons_and_restamps_the_snapshots(tmp_path):
    _cache(tmp_path, {
        cache_key(seasons.SEASON_PAGE) + ".wikitext": SEASON_PAGE,
        cache_key("Season/2016") + ".wikitext": SEASON_2016})
    connection, lines = RecordingConnection(), []
    pull = _pull(tmp_path, lines)
    summary = seasons.run(connection, pull)
    [cursor] = connection.cursors
    source_id = 1
    assert cursor.written("UPDATE meta_snapshots SET season_id = NULL") == [()]
    assert cursor.written("DELETE FROM seasons") == [()]
    # a season that has not started is reported, not stored
    assert cursor.written("INSERT INTO seasons") == [
        ("Season 1", datetime.date(2016, 8, 10), "Season/2016", source_id)]
    assert len(cursor.written("UPDATE meta_snapshots ms SET season_id")) == 1
    assert summary == {"seasons": 1, "latest": "Season 1", "latest_started": "2016-08-10",
                       "stamped": 1, "upcoming": ["Season 2: Far Future"],
                       "tables": ["seasons", "meta_snapshots"]}
    assert connection.commits == 1 and pull.session.calls == 0


def test_a_season_page_with_no_started_season_fails_the_pull_before_it_writes(tmp_path):
    """Reloading the table from nothing would unstamp every snapshot."""
    _cache(tmp_path, {
        cache_key(seasons.SEASON_PAGE) + ".wikitext": SEASON_PAGE,
        cache_key("Season/2016") + ".wikitext": SEASON_2016.split("=== Season 2")[0].replace(
            "(10 August 2016 - 10 October 2016)", "(dates to come)")})
    connection = RecordingConnection()
    with pytest.raises(WikiError, match="no season with a start date"):
        seasons.run(connection, _pull(tmp_path, []))
    assert connection.cursors == [] and connection.commits == 0


# --- the terrain: each map's article, counted per map and per stage ----------

BUSAN_TERRAIN = """'''Busan''' is a [[Control]] map in South Korea.

== Strategy ==
Attackers who win the choke early can hold the high ground above the point for
the rest of the round. Teams that group before they commit trade their
cooldowns more evenly and lose fewer players on the way in, and a support who
stays near the tank keeps the whole team alive through the first clash of
each fight on this map.

=== Downtown ===
On Downtown the point sits between pillars that shield a patient team from
most poke, so the defenders play near them and wait for the attackers to
commit first.

== Trivia ==
The flanks of the lore are not counted here.
"""

ILIOS_TERRAIN = """== Strategy ==
Fight near the point and hold it.
"""


def _terrain_rows(key_id, words, source_id, **mentions):
    """The eight rows one map or stage is stored as, a feature the text does
    not name at 0."""
    return [(key_id, feature, mentions.get(feature, 0),
             terrain.per_thousand(mentions.get(feature, 0), words), source_id)
            for feature in terrain.FEATURES]


def test_the_terrain_pull_counts_each_map_and_stage_and_deletes_nothing_before_it_reads(
        tmp_path, monkeypatch):
    """Busan's 93 kept words name a choke, the high ground and the pillars,
    its Downtown section 30 of them the pillars, and nothing is said about
    Sanctuary; the Trivia is dropped. Ilios says too little to count, and
    Nepal's article is not in the cache."""
    _cache(tmp_path, {cache_key("Busan") + ".wikitext": BUSAN_TERRAIN,
                      cache_key("Ilios") + ".wikitext": ILIOS_TERRAIN})
    connection, lines = RecordingConnection([
        ("SELECT map_id, name FROM maps", [(1, "Busan"), (2, "Ilios"), (3, "Nepal")]),
        ("SELECT s.map_id, s.stage_id", [(1, 11, "Downtown", False),
                                         (1, 12, "Sanctuary", False)])]), []
    at_fetch = _writes_at_fetch(monkeypatch, terrain, connection)
    pull = _pull(tmp_path, lines)
    summary = terrain.run(connection, pull)
    assert at_fetch == [[]]                   # neither table emptied before the articles read
    [cursor] = connection.cursors
    source_id = 1
    assert cursor.written("DELETE FROM stage_terrain") == [()]
    assert cursor.written("DELETE FROM map_terrain") == [()]
    assert cursor.written('INSERT INTO "map_terrain"') == _terrain_rows(
        1, 93, source_id, chokes=1, high_ground=1, cover=1)
    assert cursor.written('INSERT INTO "stage_terrain"') == _terrain_rows(
        11, 30, source_id, cover=1)
    assert summary["without_text"] == ["Ilios"]
    [missing] = summary["missing"]
    assert missing.startswith("Nepal: ") and "offline" in missing
    assert {key: summary[key] for key in (
        "maps", "rows", "words", "stages", "stages_no_text", "stage_rows")} == {
        "maps": 1, "rows": 8, "words": 93, "stages": 1, "stages_no_text": 1, "stage_rows": 8}
    assert connection.commits == 1 and pull.session.calls == 1   # Nepal, asked for once


# --- the playstyles and the patches: one page each ---------------------------

def test_the_playstyles_pull_reloads_each_style_s_heroes_and_names_the_unmatched(tmp_path):
    """Reinhardt is not on the roster: the Brawl section's link to him is
    reported, and Winston sits under both styles that list him."""
    _cache(tmp_path, {cache_key(playstyles.COMPOSITION_PAGE) + ".wikitext": COMPOSITION})
    connection, lines = RecordingConnection([
        ('SELECT "name", "hero_id" FROM "heroes"', [("Winston", 1), ("D.Va", 2)])]), []
    pull = _pull(tmp_path, lines)
    summary = playstyles.run(connection, pull)
    [cursor] = connection.cursors
    source_id = 1
    assert cursor.written("DELETE FROM playstyle") == [()]
    assert cursor.written("INSERT INTO playstyle") == [
        (1, "dive", source_id), (2, "dive", source_id), (1, "brawl", source_id)]
    assert summary == {"playstyles": ["Dive", "Brawl"], "links": 3,
                       "unmatched": ["Brawl: Reinhardt"], "tables": ["playstyle"]}
    assert connection.commits == 1 and pull.session.calls == 0


def test_the_patches_pull_upserts_every_dated_patch_and_names_the_latest(tmp_path):
    """The Cargo rows as the cache holds them; the page without a date anchors
    nothing and is counted."""
    rows = [{"name": "Patch A", "date": "2026-01-10", "platform": "PC", "source": "https://a"},
            {"name": "Patch Undated", "date": ""},
            {"name": "Patch B", "date": "2026-03-01", "platform": "", "source": ""}]
    _cache(tmp_path, {cache_key("cargo", "patches") + ".json": json.dumps(rows)})
    connection, lines = RecordingConnection([
        ("SELECT name, released FROM patches", [("Patch B", "2026-03-01")])]), []
    pull = _pull(tmp_path, lines)
    summary = patches.run(connection, pull)
    [cursor] = connection.cursors
    source_id = 1
    assert cursor.written("INSERT INTO patches") == [
        ("Patch A", "2026-01-10", "PC", "https://a", source_id),
        ("Patch B", "2026-03-01", None, None, source_id)]
    assert summary == {"patches": 2, "skipped": 1, "latest": "Patch B (2026-03-01)",
                       "tables": ["patches"]}
    assert connection.commits == 1 and pull.session.calls == 0
    assert lines == ["patches: 2 loaded, 1 skipped (no date)"]
