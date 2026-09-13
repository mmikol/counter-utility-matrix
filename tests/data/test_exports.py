"""data/raw must be an exact mirror of the database.

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
