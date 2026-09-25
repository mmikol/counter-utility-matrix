"""The recorded matches, read: the Match record both the door and the
inference layer take, and load_matches over a scratch database holding the
synthetic roster (tests/scratch.py), oldest first."""

import datetime

import psycopg
import pytest

from db import matches as recorded
from facts.matches import Match, load_matches
from tests import scratch


def test_a_match_is_one_map_with_both_sixes_the_bans_and_blues_result():
    """The shared record: its fields, in order, are the contract the door
    writes to and the inference layer reads."""
    assert Match._fields == (
        "match_id", "played_on", "map_name", "side", "result", "blue", "red", "bans",
        "playbook_digest", "note")
    assert Match.__annotations__["played_on"] is datetime.date
    assert Match.__annotations__["blue"] == tuple[str, ...]


def _ids(cx, table, names):
    key = "hero_id" if table == "heroes" else "map_id"
    found = dict(cx.execute("select name, %s from %s" % (key, table)).fetchall())
    return tuple(found[name] for name in names)


def _store(cx, day, map_name, side, result, blue, red, bans=(), note=""):
    source = cx.execute("select source_id from sources where code = 'blizzard'").fetchone()[0]
    return recorded.store(cx.cursor(), recorded.StoredMatch(
        played_on=day, map_id=_ids(cx, "maps", [map_name])[0], side=side, result=result,
        playbook_digest="d" * 64, note=note, blue=_ids(cx, "heroes", blue),
        red=_ids(cx, "heroes", red), bans=_ids(cx, "heroes", bans)), source)


BLUE = ("Anvil", "Kite", "Rook", "Needle", "Balm", "Myrrh")
RED = ("Mortar", "Quarry", "Gale", "Flint", "Sorrel", "Tansy")


@pytest.mark.invariant
def test_load_matches_reads_every_match_oldest_first(scratch_dsn):
    """By the day played, then by id: a map recorded late for an earlier
    day sorts before the later day's. Each team keeps the order entered."""
    with psycopg.connect(scratch_dsn) as cx:
        cx.execute("delete from matches")
        later = _store(cx, datetime.date(2026, 9, 20), "Harbor Gate", "attack", "win",
                       BLUE, RED, note="held the gate")
        earlier = _store(cx, datetime.date(2026, 9, 18), "Ember Ruins", "", "loss",
                         RED, BLUE[::-1])
        cx.commit()
        matches = load_matches(cx)
    assert [m.match_id for m in matches] == [earlier, later]
    first, second = matches
    assert first == Match(
        match_id=earlier, played_on=datetime.date(2026, 9, 18), map_name="Ember Ruins",
        side="", result="loss", blue=RED, red=BLUE[::-1], bans=(), playbook_digest="d" * 64,
        note="")
    assert second.side == "attack" and second.blue == BLUE and second.note == "held the gate"


@pytest.mark.invariant
def test_a_matchs_bans_and_picks_come_back_as_named(scratch_dsn):
    with psycopg.connect(scratch_dsn) as cx:
        cx.execute("delete from matches")
        stored = _store(cx, datetime.date(2026, 9, 21), "Salt Flats", "", "draw",
                        ("Anvil", "Kite", "Gale", "Flint", "Balm", "Tansy"),
                        ("Mortar", "Quarry", "Rook", "Gale", "Myrrh", "Sorrel"),
                        ("Needle", "Wisp"))
        cx.commit()
        [match] = load_matches(cx)
    assert match.match_id == stored and match.bans == ("Needle", "Wisp")
    assert "Gale" in match.blue and "Gale" in match.red      # a hero may play for both teams


@pytest.mark.invariant
def test_a_database_before_the_matches_table_holds_none(dsn):
    with scratch.database(dsn) as bare, psycopg.connect(bare) as cx:
        assert load_matches(cx) == []
