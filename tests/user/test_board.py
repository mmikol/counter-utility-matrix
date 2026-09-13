"""The board: every JSON endpoint speaks the same facts and inference the
MCP tools serve, and the page carries the two rosters. No HTTP server is
spun up - the handler is thin routing."""

import json

import pytest

from user import board

pytestmark = pytest.mark.invariant


def test_board_page_has_two_rosters_and_the_three_panels():
    body = board.view_board()
    assert "team red" in body and "team blue" in body
    assert "tab-facts" in body and "tab-inf" in body and "tab-playbook" in body
    script = board.static_file("board.js")[0].decode()
    assert "/api/roster" in script and "/api/facts" in script and "/api/infer" in script
    assert "localStorage" in script


def test_roster_endpoint_carries_portraits_and_maps(db):
    data = board.api_roster(db)
    assert {h["role"] for h in data["heroes"]} == {"tank", "damage", "support"}
    assert all(h["portrait"] for h in data["heroes"])
    assert any(m["name"] == "King's Row" for m in data["maps"])
    db.rollback()


def test_facts_endpoint_returns_the_board(db):
    data, code = board.api_facts(db, {"map": ["King's Row"], "red": ["Zarya", "Pharah"],
                                   "blue": ["Ana"]})
    assert code == 200 and data["count"] > 300
    keys = {f["key"] for f in data["facts"]}
    assert "team.coverage" in keys and "matchup.net_edges" in keys
    data, code = board.api_facts(db, {"red": ["Saitama"]})
    assert code == 400 and "Saitama" in data["error"]
    db.rollback()


def test_infer_endpoint_serves_both_seats_and_the_current_comp(db):
    data, code = board.api_infer(db, {"map": ["King's Row"], "red": ["Zarya"], "blue": ["Ana"],
                                      "side": ["attack"]})
    assert code == 200 and data["side"] == "attack"
    assert data["blue"]["kind"] == "infer" and len(data["blue"]["blue"]) == 6
    assert data["red"]["seat"] == "red" and data["red"]["side"] == "defense"
    assert data["current"]["partial"] and data["current"]["blue"] == ["Ana"]
    assert data["blue"]["cited"] and all(p["evidence"] for p in data["blue"]["picks"])
    data, code = board.api_infer(db, {"blue": ["Reinhardt", "Zarya", "Widowmaker", "Bastion",
                                               "Ana", "Lúcio"]})
    assert code == 200 and data["current"]["kind"] == "evaluate" and data["current"]["rank"] >= 1
    db.rollback()


def test_heuristics_and_recs_endpoints(db):
    data = board.api_heuristics()
    assert len(data["heuristics"]) >= 30
    data = board.api_recs(db)
    assert isinstance(data["latest"], int)
    assert json.dumps(data)
    db.rollback()


def test_bans_ride_the_query_string(db):
    data, code = board.api_facts(db, {"map": ["King's Row"], "red": ["Zarya"],
                                      "ban": ["Widowmaker", "Sombra"]})
    assert code == 200 and data["bans"] == ["Widowmaker", "Sombra"]
    assert any(f["scope"] == "bans" for f in data["facts"])
    data, code = board.api_infer(db, {"red": ["Zarya"], "blue": ["Ana"], "ban": ["Ana"]})
    assert code == 400 and "banned" in data["error"]
    data = board.api_roster(db)
    assert any(m["name"] == "King's Row" and m["sided"] for m in data["maps"])
    assert any(m["name"] == "Ilios" and not m["sided"] for m in data["maps"])
    db.rollback()


def test_the_page_is_a_shell_over_static_files():
    body = board.view_board()
    assert "/static/board.css" in body and "/static/board.js" in body
    assert "var TEAM = 6, BANS = 5;" in body
    data, ctype = board.static_file("board.js")
    assert ctype.startswith("application/javascript") and b"function renderResult" in data
    data, ctype = board.static_file("board.css")
    assert ctype.startswith("text/css") and b".tile.banned" in data
    assert board.static_file("../board.py") is None and board.static_file("nope.js") is None
