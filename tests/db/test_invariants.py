"""Invariants: properties the built database must hold, whoever loaded it."""

import pytest

from db.data.wiki.measurements import CANONICAL_UNITS

pytestmark = pytest.mark.invariant

STAT_TABLES = ("ability_stats", "weapon_stats", "perk_stats")


# --- roster completeness ------------------------------------------------

def test_every_hero_has_a_role_and_subrole(one):
    assert one("select count(*) from heroes where role_id is null or subrole_id is null") == 0


def test_every_hero_has_health(one):
    assert one("select count(*) from heroes where health is null") == 0


def test_every_hero_has_a_weapon_and_an_ultimate(one):
    for missing in (
        """select count(*) from heroes h where not exists
           (select 1 from weapons w where w.hero_id = h.hero_id)""",
        """select count(*) from heroes h where not exists
           (select 1 from abilities a join ability_kinds k using(kind_id)
            where a.hero_id = h.hero_id and k.code = 'ultimate')""",
    ):
        assert one(missing) == 0


def test_every_ability_is_classified(one):
    assert one("select count(*) from abilities where kind_id is null") == 0


# --- maps ---------------------------------------------------------------

def test_map_pool_is_standard_play_only(rows, one):
    assert {r[0] for r in rows("select code from game_modes")} == {
        "control", "escort", "flashpoint", "hybrid", "push"}
    assert one("""select count(*) from maps m where not exists
                  (select 1 from map_modes mm where mm.map_id = m.map_id)""") == 0


def test_each_mode_has_its_stages(rows, one):
    # Control: three stages. Flashpoint: five points. Hybrid: two phases.
    # Escort: three stretches where the article names them. Push: whole.
    allowed = {"control": {3}, "flashpoint": {5}, "hybrid": {2},
               "escort": {0, 3}, "push": {0}}
    off = [(code, name, n) for code, name, n in rows(
        """select g.code, m.name, count(s.stage_id)
           from maps m join map_modes mm using (map_id)
           join game_modes g using (mode_id) left join map_stages s using (map_id)
           group by g.code, m.name""") if n not in allowed[code]]
    assert not off, off
    # positions run 1..n in play order
    assert one("""select count(*) from (select map_id, array_agg(position order by position) p,
                  count(*) n from map_stages group by map_id) t
                  where p <> (select array_agg(i::smallint) from generate_series(1, n) i)""") == 0


def test_stage_terrain_is_whole_per_stage(one):
    # a stage with text holds all eight features, as a map does
    assert one("""select count(*) from (select stage_id from stage_terrain
                  group by stage_id having count(*) <> 8) t""") == 0


# --- the measurement model ----------------------------------------------

def test_units_are_canonical_base_quantities(rows):
    for table in STAT_TABLES:
        for column in ("unit_numerator", "unit_denominator"):
            off = {r[0] for r in rows(
                "select distinct %s from %s where %s is not null" % (column, table, column)
            )} - set(CANONICAL_UNITS)
            assert not off, "%s.%s: %s" % (table, column, off)


def test_no_unit_is_written_as_a_rate(one):
    for table in STAT_TABLES:
        assert one("select count(*) from %s where unit_numerator like '%%/%%'" % table) == 0


def test_a_denominator_always_has_a_magnitude(one):
    for table in STAT_TABLES:
        assert one("""select count(*) from %s where unit_denominator is not null
                      and denominator_value is null""" % table) == 0


def test_source_text_survives_everything(one):
    # a row with neither a number nor its source text says nothing at all
    for table in STAT_TABLES:
        assert one("select count(*) from %s where value is null and value_text is null"
                   % table) == 0


def test_no_measurement_is_stored_twice(one):
    # identical stat rows once doubled when an ability shared its weapon's
    # name; the unique constraint guards it, this states the intent
    for table, owner in (("ability_stats","ability_id"), ("weapon_stats","config_id"),
                         ("perk_stats","perk_id")):
        assert one("""select count(*) from (select %s, stat_key_id, value,
            unit_numerator, unit_denominator, denominator_value, condition,
            value_text, count(*) from %s group by 1,2,3,4,5,6,7,8
            having count(*) > 1) d""" % (owner, table)) == 0


# --- snapshots: population and delineation -------------------------------

def test_every_snapshot_is_fully_delineated(one):
    assert one("""select count(*) from meta_snapshots
                  where patch_id is null or season_id is null""") == 0


def test_delineators_predate_their_capture(one):
    assert one("""select count(*) from meta_snapshots ms
        join patches p using(patch_id) join seasons s using(season_id)
        where p.released > ms.captured_at::date
           or s.started > ms.captured_at::date""") == 0


def test_meta_records_the_queue_it_came_from(rows):
    by_source = {(c, q) for c, q in rows(
        "select s.code, m.queue from meta_snapshots m join sources s using(source_id)")}
    assert by_source
    assert all(q.startswith("competitive_") for _, q in by_source)
    # Blizzard's is the one population: its page offers Role Queue alone
    assert by_source == {("blizzard", "competitive_role_queue")}


def test_platform_is_console_and_input_follows_from_it(rows):
    # console Overwatch supports no input but a controller; a platform other
    # than console must leave input NULL rather than guess
    for platform, device in rows("select platform, input from meta_snapshots"):
        assert platform == "console" and device == "controller"


# --- the playbook: judgements, undimensioned -----------------------------

def test_a_maps_styles_are_derived_not_stored(rows):
    # the style vocabulary is the wiki's hero tags; what a map rewards is
    # computed from them and the per-map rates at load (ui.facts.model), and
    # a comp's shape is compute.EXPECTED_SHAPE - neither is a table
    tables = {r[0] for r in rows("select tablename from pg_tables where schemaname = 'public'")}
    assert not tables & {"map_playstyle", "comp_archetypes"}
    # nor are a hero's best maps: the three largest map-over-overall win rates
    assert "map_strategy" not in tables
    assert {r[0] for r in rows("select distinct style from playstyle")} >= {
        "dive", "brawl", "poke"}


def test_synergies_are_the_wikis_scored_one_or_two_with_a_short_note(rows, one):
    from db.data.wiki.synergies import NOTE_LIMIT
    assert {r[0] for r in rows("select distinct score from synergies")} == {1, 2}
    assert one("select count(*) from synergies where note is null"
               " or length(note) >= %s", NOTE_LIMIT) == 0
    assert one("""select count(*) from synergies s
                  join heroes a on a.hero_id = s.hero_id
                  join heroes b on b.hero_id = s.other_id
                  where a.status <> 'released' or b.status <> 'released'""") == 0


def test_seasons_have_started_and_name_their_wiki_page(one):
    assert one("select count(*) from seasons") > 0
    assert one("select count(*) from seasons where started > current_date") == 0
    assert one("select count(*) from seasons where note not like 'Season/%'") == 0


def test_synergies_are_canonical_pairs(one):
    # bidirectional: one row per pair, lower hero_id first (schema CHECKs it;
    # this documents that both directions being present is representable
    # nowhere)
    assert one("select count(*) from synergies where hero_id >= other_id") == 0


def test_counters_are_directed_edges_between_released_heroes(one):
    # one row = countered_by_id answers hero_id
    assert one("select count(*) from counters") >= 100
    assert one("select count(*) from counters where hero_id = countered_by_id") == 0
    assert one("""select count(*) from counters c
                  left join heroes a on a.hero_id = c.hero_id
                  left join heroes b on b.hero_id = c.countered_by_id
                  where a.status is distinct from 'released'
                     or b.status is distinct from 'released'""") == 0


def test_no_pair_counters_both_ways(one):
    # two articles that contradict each other leave the pair without an edge
    assert one("""select count(*) from counters c join counters r
                  on r.hero_id = c.countered_by_id and r.countered_by_id = c.hero_id""") == 0


def test_most_released_heroes_answer_and_are_answered(one):
    # a hero whose article has no written Match-Up cell still gets the edges
    # other articles write about it
    released = one("select count(*) from heroes where status = 'released'")
    assert one("select count(distinct hero_id) from counters") >= 0.8 * released
    assert one("select count(distinct countered_by_id) from counters") >= 0.8 * released


# --- provenance ----------------------------------------------------------

def test_every_table_records_source_and_cao(rows):
    missing = rows("""select table_name from information_schema.columns
        where table_schema='public'
          and table_name not in ('sources', 'schema_migrations')
        group by table_name
        having count(*) filter (where column_name in ('source_id','cao')) < 2""")
    assert missing == []


def test_no_row_is_missing_its_source(rows, one):
    for (table,) in rows("""select distinct table_name from information_schema.columns
                            where table_schema='public' and column_name='source_id'"""):
        assert one("select count(*) from %s where source_id is null" % table) == 0


def test_no_media_or_links_leak_into_stored_text(one):
    assert one("select count(*) from abilities where description like '%http%'") == 0
    for table in STAT_TABLES:
        assert one("select count(*) from %s where value_text like '%%http%%'" % table) == 0


def test_weapon_numbers_live_on_configs_not_abilities(one):
    # Blizzard lists a hero's weapon among the abilities; the wiki tells us
    # its kind. Its NUMBERS belong to weapon_configs alone - statting the
    # ability row too once double-booked 1,287 measurements and made update
    # and rebuild disagree.
    assert one("""select count(*) from ability_stats s
        join abilities a using(ability_id) join ability_kinds k using(kind_id)
        where k.code = 'weapon'""") == 0


def test_no_hero_has_two_abilities_that_fold_together(rows):
    # "Biotic Rifle" and "Biotic Rifle (ADS)" fold to one key; two such rows
    # on one hero means a firing config leaked into the abilities table, and
    # every rerun then routes stats to whichever row it finds first.
    from collections import Counter

    from db.data.names import ability_key
    folds = Counter((h, ability_key(a)) for h, a in rows(
        "select hero_id, name from abilities"))
    dupes = {k: v for k, v in folds.items() if v > 1}
    assert not dupes, dupes


# --- the three-layer additions ------------------------------------------------

def test_every_hero_has_a_portrait_and_every_role_an_icon(one):
    assert one("select count(*) from heroes"
               " where portrait_url is null and status = 'released'") == 0
    assert one("select count(*) from roles where icon_url is null") == 0


def test_ability_keywords_are_stored_verbatim(one):
    # the wiki tags most abilities; the facts layer counts CC, mobility and
    # cleanses from these, so a near-empty column means the pull regressed
    assert one("select count(*) from abilities where keywords is not null") >= 200
    assert one("select count(*) from abilities where keywords like '%hitscan%'") >= 5


def test_strategies_table_mirrors_the_files(rows):
    """The table names the playbook it mirrors - the shipped one or an
    experiment - and matches that folder's files."""
    import os

    from db import ROOT
    from inference import catalog
    playbooks = [r[0] for r in rows("select distinct playbook from strategies")]
    assert len(playbooks) == 1, playbooks
    directory = os.path.join(ROOT, playbooks[0])
    files = {h.id: h.kind for h in catalog.load(directory)}
    table = dict(rows("select strategy_id, kind from strategies"))
    assert table == files


def test_the_migration_ledger_matches_the_files(rows):
    from db.psql import schema
    assert [r[0] for r in rows("select filename from schema_migrations order by 1")] == \
        [m.name for m in schema.read_migrations()]
