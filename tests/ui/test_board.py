"""The board: every JSON endpoint speaks the same facts and inference the
MCP tools serve, and the page carries the two rosters. No HTTP server is
spun up - the handler is thin routing."""

import json

import pytest

from ui import board

pytestmark = pytest.mark.invariant


def test_board_page_has_two_rosters_and_the_three_panels():
    body = board.view_board()
    assert "team red" in body and "team blue" in body
    assert "tab-comps" in body and "tab-facts" in body and "tab-playbook" in body and "tab-recorded" in body
    assert "FACTS = HEROES" not in body and "href='/recs'" not in body   # the equation moved to /math
    assert "href='/math'" in body and "id='captured'" in body
    assert "data-tab='comps'" in body
    # the two old panels were merged into comps: both seats side by side, the
    # current comp below, in one section
    assert "tab-inf" not in body and "tab-cur" not in body
    assert "data-tab='inf'" not in body and "data-tab='cur'" not in body
    comps = body[body.index("id='tab-comps'"):body.index("id='tab-facts'")]
    assert "id='inf-blue'" in comps and "id='inf-red'" in comps
    script = board.static_file("board.js")[0].decode()
    assert "/api/roster" in script and "/api/facts" in script and "/api/infer" in script
    assert "localStorage" in script
    assert "var TABS = ['comps', 'facts', 'playbook', 'recorded']" in script
    assert "normalized" in script and "/ 100" in script    # the 0-100 figure, raw score beside it
    # the playbook holds three kinds; the badge appends the form only when it differs
    assert "STRATEGIES = CONSTRAINTS &cup; HEURISTICS &cup; ASSUMPTIONS" in board.view_math()   # the equation lives on /math now
    assert "h.form !== h.kind ?" in script and "'assumption' ? 'assumption - taken as given" in script
    assert "prose -" not in script
    assert b".kind.assumption" in board.static_file("board.css")[0]


def test_the_ban_picker_is_a_roster_and_the_dropdown_is_gone():
    body = board.view_board()
    assert "bansel" not in body and "<select id='bansel'" not in body
    assert "id='banhead'" in body and "id='banslots'" in body and "id='banroster'" in body
    assert "id='banmini'" in body and "id='bancount'" in body
    script = board.static_file("board.js")[0].decode()
    assert "function buildBanPicker" in script and "rosterHTML('ban')" in script
    assert "bansOpen = false" in script                     # collapsed by default
    css = board.static_file("board.css")[0].decode()
    assert ".bans.open .banbody" in css and ".bans .tile.banned" in css
    assert ".bans select" not in css


def test_doctrine_is_a_placeholder_card_that_never_enters_state():
    script = board.static_file("board.js")[0].decode()
    assert "var DOCTRINE = {" in script and "name: 'Doctrine'" in script
    assert "role: 'announced'" in script and "'coming soon'" in script
    # rendered by its own function under its own heading, with no data-h and
    # no data-team on the card, so the click handler and the state never see it
    assert "announcedTile(DOCTRINE)" in script and ">announced</h4>" in script
    start = script.index("function announcedTile")
    card = script[start:script.index("function rosterHTML")]
    assert "class='tile soon'" in card and "data-h" not in card and "data-team" not in card
    assert "SILHOUETTE" in card and "portrait(" not in card    # a silhouette, no image
    assert 'var SILHOUETTE = "<svg' in script
    assert "Doctrine" not in script[script.index("function qs()"):script.index("function refresh")]
    css = board.static_file("board.css")[0].decode()
    assert ".tile.soon" in css and ".rolecol.announced" in css


def test_roster_endpoint_carries_portraits_and_maps(db):
    data = board.api_roster(db)
    assert {h["role"] for h in data["heroes"]} == {"tank", "damage", "support"}
    assert all(h["portrait"] for h in data["heroes"])
    assert any(m["name"] == "King's Row" for m in data["maps"])
    assert not any(h["name"] == "Doctrine" for h in data["heroes"])   # the page's placeholder only
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


def test_strategies_and_recs_endpoints(db):
    data = board.api_strategies()
    assert len(data["strategies"]) >= 30
    recorded = board.api_recorded(db)
    assert set(recorded) == {"tally", "recs", "unlinked"} and set(recorded["tally"]) >= {"win", "loss", "draw"}
    for r in recorded["recs"]:
        assert set(r) >= {"rec_id", "date", "map", "question", "playstyle", "model", "picks", "outcomes"}
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
    assert "id='momentum'" in body and "id='plan'" in body
    assert "id='bluescore'" in body and "id='redscore'" in body and "id='cur'" not in body  # scores live in the boxes
    assert "data-clear='red'" in body and "data-clear='blue'" in body
    assert body.index("id='momentum'") < body.index("id='redslots'")   # the momentum strip sits above both boxes
    assert "id='momentum'" not in body[body.index("id='tab-comps'"):]
    assert body.index("id='inf-red'") < body.index("id='inf-blue'")  # red first, then blue, like the boxes
    script = board.static_file("board.js")[0].decode()
    assert "their comp as revealed" in script and "red_current" in script and "d.momentum" in script
    assert "game plan" in script and "d.plan" in script
    assert "paintSuggestions" in script and "slot suggested" in script and "bluescore" in script
    assert "el('swapbtn').disabled = !sided" in script        # swap sides is off on maps without sides
    assert "near('[data-clear]')" in script                    # a team's clear button empties that team only
    assert "redscore" in script and "el('redslots')" not in script[script.index("function paintSuggestions"):script.index("function renderResult")]
    assert "renderFill" not in script and "el('cur')" not in script
    assert "var TEAM = 6, BANS = 5;" in body
    data, ctype = board.static_file("board.js")
    assert ctype.startswith("application/javascript") and b"function renderResult" in data
    data, ctype = board.static_file("board.css")
    assert ctype.startswith("text/css") and b".tile.banned" in data
    assert board.static_file("../board.py") is None and board.static_file("nope.js") is None


def test_the_math_page_states_the_equation_and_the_layers():
    page = board.view_math()
    for line in ("FACTS      = HEROES &cup; MAPS &cup; META",
                 "STRATEGIES = CONSTRAINTS &cup; HEURISTICS &cup; ASSUMPTIONS",
                 "COMP       = ARGMAX[ STRATEGIES( FACTS ) ]"):
        assert line in page
    assert "The data layer" in page and "The inference layer" in page and "The board" in page
    assert "never calls a language model" in page
    script = board.static_file("board.js")[0].decode()
    assert "'recorded'" in script and "/api/recorded" in script and "loadRecorded" in script
