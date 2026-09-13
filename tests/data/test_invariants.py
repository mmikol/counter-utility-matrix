"""Invariants: properties the built database must hold, whoever loaded it."""

import pytest

from data.authoritative.transform.wiki.measurements import CANONICAL_UNITS

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


def test_stages_only_on_modes_that_have_them(one):
    # Control and Flashpoint maps have submaps; a stage on an escort map
    # means the article parser drifted.
    assert one("""select count(*) from map_stages s
        where not exists (select 1 from map_modes mm join game_modes g using(mode_id)
        where mm.map_id = s.map_id and g.code in ('control','flashpoint'))""") == 0


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
    assert {q for c, q in by_source if c == "blizzard"} <= {"competitive_role_queue"}
    assert {q for c, q in by_source if c == "counterpick"} <= {
        "competitive_unspecified_queue"}


def test_platform_is_console_and_input_follows_from_it(rows):
    # console Overwatch supports no input but a controller; a platform other
    # than console must leave input NULL rather than guess
    for platform, device in rows("select platform, input from meta_snapshots"):
        assert platform == "console" and device == "controller"


# --- the playbook: judgements, undimensioned -----------------------------

def test_playbook_styles_share_one_vocabulary(rows):
    # style is text by deliberate denormalisation (the wiki page IS the
    # vocabulary); this is the referential integrity the schema gave up
    styles = {r[0] for r in rows("select distinct style from playstyle")}
    for table in ("comp_archetypes", "map_playstyle"):
        off = {r[0] for r in rows("select distinct style from " + table)} - styles
        assert not off, "%s uses unknown styles: %s" % (table, off)


def test_archetypes_describe_a_full_six_stack(rows):
    from user.facts.compute import TEAM_SIZE
    for style, total in rows("select style, sum(slots) from comp_archetypes group by 1"):
        assert total == TEAM_SIZE, "%s describes %d slots" % (style, total)


def test_synergies_are_canonical_pairs(one):
    # bidirectional: one row per pair, lower hero_id first (schema CHECKs it;
    # this documents that both directions being present is representable
    # nowhere)
    assert one("select count(*) from synergies where hero_id >= other_id") == 0


def test_map_strategy_ranks_are_dense_per_hero(rows):
    for hero_id, positions in rows(
        "select hero_id, array_agg(position order by position) from map_strategy group by 1"):
        assert positions == list(range(1, len(positions) + 1)), hero_id


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
    from data.authoritative.transform.wiki.names import match_key
    from collections import Counter
    folds = Counter((h, match_key(a)) for h, a in rows(
        "select hero_id, name from abilities"))
    dupes = {k: v for k, v in folds.items() if v > 1}
    assert not dupes, dupes


# --- the three-layer additions ------------------------------------------------

def test_every_hero_has_a_portrait_and_every_role_an_icon(one):
    assert one("select count(*) from heroes where portrait_url is null") == 0
    assert one("select count(*) from roles where icon_url is null") == 0


def test_ability_keywords_are_stored_verbatim(one):
    # the wiki tags most abilities; the facts layer counts CC, mobility and
    # cleanses from these, so a near-empty column means the pull regressed
    assert one("select count(*) from abilities where keywords is not null") >= 200
    assert one("select count(*) from abilities where keywords like '%hitscan%'") >= 5


def test_heuristics_table_mirrors_the_files(rows):
    from inference import catalog
    files = {h.id: h.kind for h in catalog.load()}
    table = dict(rows("select heuristic_id, kind from heuristics"))
    assert table == files


def test_the_migration_ledger_matches_the_files(rows):
    import os
    from data.db import schema
    assert [r[0] for r in rows("select filename from schema_migrations order by 1")] == \
        [os.path.basename(p) for p, _ in schema.read_migrations()]
