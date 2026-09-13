"""data/raw must be an exact mirror of the database - the database that
exported it. Two databases share the mirror (the local cluster and the
compose one), so EXPORT.json names the exporter and these checks skip,
rather than fail, when the test database is the other one.

Counted by parsing the CSV, never by counting lines: value_text embeds
newlines, and the line-count fallacy produced nine phantom rows the first
time this check was deleted."""

import csv
import os

import pytest

pytestmark = pytest.mark.invariant

from data.common import RAW_DIR as RAW


def _tables(rows):
    return [r[0] for r in rows("select tablename from pg_tables where schemaname='public'")]


@pytest.fixture(autouse=True)
def _same_database(db):
    from data import common
    mark = common.export_mark()
    if mark and mark["system_identifier"] != common.database_identity(db):
        pytest.skip("data/raw was exported from a different database (%s); run"
                    " `python -m data.orchestrator export` against this one"
                    % mark["exported_at"])


def test_every_table_is_exported(rows):
    if not os.path.isdir(RAW):
        pytest.skip("data/raw not exported yet")
    have = {n[:-4] for n in os.listdir(RAW) if n.endswith(".csv")}
    assert set(_tables(rows)) <= have


def test_no_csv_outlives_its_table(rows):
    if not os.path.isdir(RAW):
        pytest.skip("data/raw not exported yet")
    stale = {n[:-4] for n in os.listdir(RAW) if n.endswith(".csv")} - set(_tables(rows))
    assert not stale


def test_row_counts_match_the_database(rows, one):
    if not os.path.isdir(RAW):
        pytest.skip("data/raw not exported yet")
    for table in _tables(rows):
        with open(os.path.join(RAW, table + ".csv"), newline="", encoding="utf-8") as f:
            in_csv = sum(1 for _ in csv.reader(f)) - 1
        assert in_csv == one("select count(*) from " + table), table


def test_the_mirror_names_its_database(db):
    from data import common
    mark = common.export_mark()
    if mark is None:
        pytest.skip("data/raw not exported yet")
    assert mark["system_identifier"] == common.database_identity(db)
    assert mark["tables"] == len(_tables(lambda sql: db.execute(sql).fetchall()))
