"""Unit tests: the rates page read into rows - the data table, the filter
vocabularies, the queue code and the cache name of each slice. No database,
no network: the pages are inline HTML and the fetch is stubbed."""

import html
import json

import pytest

from db.data import fetch
from db.data.blizzard import BlizzardError, meta


def rates_page(rows):
    """A rates page whose data table carries `rows` as its JSON attribute."""
    return '<main><blz-data-table rows="%s"></blz-data-table></main>' % html.escape(
        json.dumps(rows))


def select(select_id, options):
    """A filter dropdown: <select id=...> over (value, label) options."""
    return '<select id="%s">%s</select>' % (select_id, "".join(
        '<option value="%s">%s</option>' % option for option in options))


def stub_fetch(monkeypatch, page):
    """cached_get answering every request with `page`; the list it returns
    records each request as (url, key, params, policy)."""
    calls = []

    def fake(pull, url, key, params=None, policy=None):
        calls.append((url, key, params, policy))
        return page

    monkeypatch.setattr(meta, "cached_get", fake)
    return calls


# --- the data table ------------------------------------------------------

def test_a_rate_row_is_read_off_the_data_table_json():
    rows = [{"cells": {"name": "Ana", "winrate": 48.7, "pickrate": 23, "banrate": 8.2}},
            {"cells": {"name": "Tracer", "winrate": 50.1, "pickrate": 12.4}},
            {"cells": {"winrate": 40}}]
    # the nameless row is dropped; a rate the page leaves out is None
    assert meta.parse_rows(rates_page(rows)) == [
        ("Ana", 48.7, 23, 8.2), ("Tracer", 50.1, 12.4, None)]


@pytest.mark.parametrize("page", [
    "<main><table></table></main>",
    "<main><blz-data-table></blz-data-table></main>",
    '<main><blz-data-table rows=""></blz-data-table></main>',
], ids=["no table", "no rows attribute", "empty rows attribute"])
def test_a_page_without_the_rows_attribute_is_refused(page):
    with pytest.raises(BlizzardError, match="the page changed"):
        meta.parse_rows(page)


def test_a_table_with_no_named_hero_is_refused():
    with pytest.raises(BlizzardError, match="no hero rows"):
        meta.parse_rows(rates_page([{"cells": {}}]))


# --- the filter vocabularies ---------------------------------------------

FILTERS = "%s%s" % (
    select("filter-tier-select", [("", "Choose"), ("All", "All Tiers"),
                                  ("Grandmaster", " Grandmaster and Champion ")]),
    select("filter-map-select", [("all-maps", "All Maps"), ("kings-row", "King's Row")]))


def test_a_filter_reads_its_own_options_and_skips_the_one_without_a_value():
    assert meta.parse_filter_options(FILTERS, "filter-tier-select") == [
        ("All", "All Tiers"), ("Grandmaster", "Grandmaster and Champion")]


def test_a_missing_filter_is_refused_by_its_id():
    with pytest.raises(BlizzardError, match="filter-rq-select"):
        meta.parse_filter_options(FILTERS, "filter-rq-select")


# --- the queue code and the slices ---------------------------------------

@pytest.mark.parametrize("code", ["1", "2"])
def test_the_queue_code_is_read_from_the_page_not_hardcoded(monkeypatch, code):
    # the cache holds pages under both codes: Blizzard has renumbered the queue
    calls = stub_fetch(monkeypatch, select("filter-rq-select", [
        ("0", "Quick Play - Role Queue"), (code, "Competitive - Role Queue")]))
    assert meta.competitive_rq(fetch.PullContext("cache")) == code
    assert calls == [(meta.RATES_URL, "rates_queue_vocabulary_input_Console_region_Americas",
                      {"input": "Console", "region": "Americas"}, meta.RATES_POLICY)]


@pytest.mark.parametrize("options", [
    [("0", "Quick Play - Role Queue")],
    [("1", "Competitive - Role Queue"), ("2", "Competitive - Role Queue")],
], ids=["none", "two"])
def test_a_queue_filter_without_exactly_one_competitive_queue_is_refused(monkeypatch, options):
    stub_fetch(monkeypatch, select("filter-rq-select", options))
    with pytest.raises(BlizzardError, match="exactly one"):
        meta.competitive_rq(fetch.PullContext("cache"))


@pytest.mark.parametrize("params, key", [
    ({"tier": "Gold"}, "rates_input_Console_region_Americas_rq_2_tier_Gold"),
    ({"map": "kings-row"}, "rates_input_Console_map_kings_row_region_Americas_rq_2"),
], ids=["tier", "map"])
def test_a_slice_is_cached_under_the_name_the_cache_already_holds(monkeypatch, params, key):
    # .cache-blizzard holds both names: a changed name would refetch ~40 pages
    # at the rates page's pace of six attempts and 5 s a page
    calls = stub_fetch(monkeypatch, "<main></main>")
    assert meta.fetch_slice(fetch.PullContext("cache"), params, "2") == "<main></main>"
    query = dict(params, rq="2", input="Console", region="Americas")
    assert calls == [(meta.RATES_URL, key, query, meta.RATES_POLICY)]
    assert (meta.RATES_POLICY.attempts, meta.RATES_POLICY.delay) == (6, 5.0)
