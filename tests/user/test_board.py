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
    assert "/api/roster" in body and "/api/facts" in body and "/api/infer" in body
    assert "tab-facts" in body and "tab-inf" in body and "tab-playbook" in body
    assert "localStorage" in body


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


def test_infer_endpoint_searches_or_evaluates(db):
    data, code = board.api_infer(db, {"map": ["King's Row"], "red": ["Zarya"], "blue": ["Ana"]})
    assert code == 200 and data["kind"] == "infer" and len(data["blue"]) == 6
    assert data["cited"] and all(p["evidence"] for p in data["picks"])
    data, code = board.api_infer(db, {"blue": ["Reinhardt", "Zarya", "Widowmaker", "Bastion",
                                               "Ana", "Lúcio"]})
    assert code == 200 and data["kind"] == "evaluate" and data["rank"] >= 1
    db.rollback()


def test_heuristics_and_recs_endpoints(db):
    data = board.api_heuristics()
    assert len(data["heuristics"]) >= 30
    data = board.api_recs(db)
    assert isinstance(data["latest"], int)
    assert json.dumps(data)
    db.rollback()
